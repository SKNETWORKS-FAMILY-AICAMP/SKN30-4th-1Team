"""Retrieval-only tools used by the Agentic Q&A graph.

The tools in this module never write the user-facing answer. They only return
bounded evidence plus an artifact containing provenance/debug information. The
orchestrator LLM is the single component responsible for the final response.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal, Optional

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from ..project_memory import get_project_memory
from . import history_context, mysql_search, qa_engine
from .sql_project_state import fetch_project_overview_context


# Keep the private alias for test and tool-local compatibility. The old router
# module is not a runtime dependency anymore.
_fetch_overview_context = fetch_project_overview_context


MemoryCategory = Literal["decision", "action", "issue", "risk", "all"]
MemoryOperation = Literal["list", "count"]
CompletionStatus = Literal["open", "completed", "unknown"]
MEMORY_TOOL_MAX_ROWS = 10
_ALL_SCOPE_WORDS = frozenset({"전체", "모든", "프로젝트", "기록", "항목", "메모리"})
_ATTACHMENT_EVIDENCE_MARKERS = ("[첨부 자료]", "[임시 첨부 근거]")


def _count_text_filter(category: MemoryCategory, text_query: str) -> Optional[str]:
    """Return a real count target, excluding phrases that only mean all rows."""
    normalized = " ".join(text_query.split())
    if not normalized:
        return None
    if category == "all" and set(normalized.split()) <= _ALL_SCOPE_WORDS:
        return None
    return normalized


def _dedupe_rows(rows: list[dict]) -> list[dict]:
    """Deduplicate JOIN-expanded memory rows without losing their DB order."""
    seen: set[object] = set()
    result: list[dict] = []
    for row in rows:
        key = row.get("id")
        if key is None:
            key = (
                row.get("category"),
                row.get("content"),
                row.get("owner"),
                row.get("source"),
            )
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _row_evidence(row: dict) -> str:
    # reason 은 _format_mysql_row -> _row_line_body 가 이미 붙인다.
    # 여기서 또 붙이면 structured tool 출력에만 "이유: X 이유: X" 가 생긴다.
    return qa_engine._format_mysql_row(row)


def _compact_retrieval_debug(debug: dict) -> dict:
    """Keep useful retrieval diagnostics without duplicating full chunk text."""
    chunks = []
    for chunk in debug.get("chroma_chunks") or []:
        chunks.append({key: value for key, value in chunk.items() if key != "text_full"})
    return {
        "filters": debug.get("filters") or {},
        "history_mode": bool(debug.get("history_mode")),
        "history_scope": debug.get("history_scope"),
        "multi_queries": debug.get("multi_queries") or [],
        "multi_query_source": debug.get("multi_query_source"),
        "mysql_rows": debug.get("mysql_rows") or [],
        "chroma_chunks": chunks,
    }


@tool(response_format="content_and_artifact")
def search_project_evidence(
    query: str,
    project_id: Annotated[int, InjectedState("project_id")],
    messages: Annotated[list, InjectedState("messages")],
    current_question: Annotated[str, InjectedState("current_question")],
    alternate_queries: Optional[list[str]] = None,
    include_history: bool = False,
) -> tuple[str, dict]:
    """Search project records for a specific fact, metric, owner, date, reason, or change history.

    Use this for target-to-attribute questions such as "SDK 연동은 누가 담당했나?",
    for percentages and other measured values, and for comparisons across meetings.
    ``alternate_queries`` may contain at most three faithful rewrites of the user's
    question. Set ``include_history`` when the question asks how a decision changed.
    """
    # ``messages`` is the same bounded sequence shown to the orchestrator.  Its
    # last human turn is the current question, so only earlier human turns are
    # eligible as the topic of a conversational history follow-up.  Attachment
    # blocks are evidence, not conversation turns.
    user_turns = [
        str(message.content).strip()
        for message in messages
        if getattr(message, "type", None) == "human"
        and str(getattr(message, "content", "")).strip()
    ]
    if user_turns:
        user_turns.pop()
    conversation_history = [
        {"role": "user", "content": content}
        for content in user_turns
        if not content.startswith(_ATTACHMENT_EVIDENCE_MARKERS)
    ]
    history_mode, history_scope, history_tokens, effective_question = (
        history_context.resolve_history_context(
            current_question or query,
            conversation_history,
            # An explicit true from the model is authoritative.  False (the
            # schema default) still permits deterministic intent detection so
            # a missed flag cannot disconnect a conversational follow-up.
            history_mode=True if include_history else None,
        )
    )
    retrieval_query = effective_question if history_mode else query
    retrieval_variants = []
    if history_mode and query.strip() != retrieval_query.strip():
        retrieval_variants.append(query)
    retrieval_variants.extend(alternate_queries or [])

    context, sources, debug = qa_engine._build_context(
        project_id,
        retrieval_query,
        history_mode=history_mode,
        history_scope=history_scope,
        history_topic_tokens=history_tokens,
        query_variants=retrieval_variants[:3],
    )
    project_memory = get_project_memory(project_id)
    parts = []
    if project_memory:
        parts.append(f"[프로젝트 메모리]\n{project_memory}")
    if context:
        parts.append(context)
    content = "\n\n".join(parts) or "프로젝트 기록에서 관련 근거를 찾지 못했습니다."
    return content, {
        "tool": "search_project_evidence",
        "status": "ok" if parts else "empty",
        "sources": sources,
        "debug": _compact_retrieval_debug(debug),
    }


@tool(response_format="content_and_artifact")
def query_structured_memory(
    operation: MemoryOperation,
    text_query: str,
    project_id: Annotated[int, InjectedState("project_id")],
    category: Annotated[
        MemoryCategory,
        (
            "Required category scope. decision: an explicitly agreed or confirmed "
            "choice, policy, or direction; action: concrete work to be performed; "
            "issue: a current problem or blocker that needs resolution; risk: a "
            "potential future problem or uncertainty; all: use only when the request "
            "intentionally spans categories or names no category."
        ),
    ],
    owner: Optional[str] = None,
    completion_status: Annotated[
        Optional[CompletionStatus],
        (
            "Optional action-only status filter. open: explicitly assigned, pending, "
            "in progress, or not done; completed: explicitly done, finished, or "
            "delivered; unknown: the evidence does not establish whether the action "
            "is complete. Never infer open from a missing completed_at value."
        ),
    ] = None,
    due_within_days: Optional[int] = None,
    overdue: Optional[bool] = None,
    limit: int = 8,
) -> tuple[str, dict]:
    """List or count project memory using explicit structured conditions.

    Use this only for true list/count requests. ``owner`` is a condition already
    present in the question, never the person the user is asking you to discover.
    ``category`` is required; use ``all`` only when the request intentionally
    spans categories or names no category.
    ``completion_status`` is ``open``, ``completed``, or ``unknown``; do not
    turn an unknown status into open.
    Put a concrete target phrase in ``text_query`` so list records can be ranked
    and count records can be restricted by that phrase. Leave it empty when the
    structured filters define the complete target set, including an all-record count.
    Raw SQL is not supported, and list output is always capped at ten rows.
    """
    text_query = str(text_query or "").strip()
    limit = max(1, min(int(limit), MEMORY_TOOL_MAX_ROWS))
    db_category = None if category == "all" else category
    has_filter = any(
        value is not None
        for value in (owner, db_category, completion_status, due_within_days, overdue)
    )
    if operation == "list" and not text_query and not has_filter:
        content = (
            "구조화 조건과 검색 대상이 모두 비어 있어 전체 기록 조회를 거부했습니다. "
            "구체적인 근거 검색에는 search_project_evidence를 사용하세요."
        )
        return content, {
            "tool": "query_structured_memory",
            "status": "invalid_query",
            "sources": [],
            "total_rows": 0,
            "returned_rows": 0,
        }

    count_text_filter = (
        _count_text_filter(category, text_query)
        if operation == "count" else None
    )
    rows = _dedupe_rows(mysql_search.search(
        project_id,
        category=db_category,
        owner=owner,
        text_query=count_text_filter,
        completion_status=completion_status,
        due_within_days=due_within_days,
        overdue=overdue,
    ))
    sources = []
    for row in rows:
        source = row.get("source")
        if source and source not in sources:
            sources.append(source)

    if operation == "count":
        payload = {"count": len(rows), "filters": {
            "owner": owner,
            "category": category,
            "completion_status": completion_status,
            "due_within_days": due_within_days,
            "overdue": overdue,
        }}
        return json.dumps(payload, ensure_ascii=False, default=str), {
            "tool": "query_structured_memory",
            "status": "ok",
            "operation": operation,
            "sources": sources,
            "total_rows": len(rows),
            "returned_rows": 0,
        }

    ranked = rows
    vector_hits: list[dict] = []
    if text_query and rows:
        ranked, vector_hits = qa_engine._rank_mysql_rows(
            project_id, rows, [text_query], limit
        )
    ranked = ranked[:limit]
    if ranked:
        content = "\n".join(_row_evidence(row) for row in ranked)
    else:
        content = (
            "구조화 조건으로 일치하는 행을 찾지 못했습니다. 이것만으로 기록 부재를 "
            "확정하지 말고 search_project_evidence로 원문을 확인하세요."
        )
    return content, {
        "tool": "query_structured_memory",
        "status": "ok" if ranked else "empty",
        "operation": operation,
        "sources": [
            row.get("source") for row in ranked
            if row.get("source")
        ],
        "total_rows": len(rows),
        "returned_rows": len(ranked),
        "truncated": len(rows) > len(ranked),
        "memory_vector_hits": vector_hits[:10],
    }


@tool(response_format="content_and_artifact")
def get_project_overview(
    project_id: Annotated[int, InjectedState("project_id")],
) -> tuple[str, dict]:
    """Return the current project overview summary and complete active Action Plan.

    Use only when the user explicitly asks for a briefing or overall project status.
    A phrase such as "전체 정답률" is a specific metric and must use evidence search.
    The Action Plan is reference data: select only what the question needs, and list
    every item only when the user explicitly asks for the complete list.
    Treat ``completion_status`` as the only status evidence. ``unknown`` means the
    status is unconfirmed, never open, unfinished, or in progress. ``status_counts``
    is the authoritative aggregate when summary wording conflicts with action rows.
    """
    context = _fetch_overview_context(project_id)
    rows = list((context.get("action_plan") or {}).get("items") or [])
    sources = []
    for row in rows:
        source = row.get("source")
        if source and source not in sources:
            sources.append(source)
    return "[프로젝트 조망]\n" + json.dumps(
        context, ensure_ascii=False, default=str
    ), {
        "tool": "get_project_overview",
        "status": "ok" if context.get("overview_summary") or rows else "empty",
        "sources": sources,
        "category_stats": context.get("category_stats") or {},
        "total_rows": len(rows),
        "returned_rows": len(rows),
        "truncated": False,
    }


QA_TOOLS = [search_project_evidence, query_structured_memory, get_project_overview]
