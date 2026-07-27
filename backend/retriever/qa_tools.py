"""Retrieval-only tools used by the experimental tool-calling Q&A graph.

The tools in this module never write the user-facing answer. They only return
bounded evidence plus an artifact containing provenance/debug information. The
orchestrator LLM is the single component responsible for the final response.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal, Optional

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from ..graph import get_project_memory
from . import mysql_search, qa_engine
from .query_intent import _fetch_overview_context


MemoryCategory = Literal["decision", "action", "issue", "risk", "all"]
MemoryOperation = Literal["list", "count"]
CompletionStatus = Literal["open", "completed", "unknown"]
# list 응답 행 상한. "액션 아이템 전체 목록" 같은 질문이 이 도구로 라우팅되는데(e3a57da)
# 10이면 실사용 프로젝트에서 흔히 잘린다. 상한을 넘는 경우 자체를 없앨 수는 없으므로
# (그건 페이지네이션 영역) 실사용 분포를 덮는 선까지만 올리고, 잘렸다는 사실은 아래에서
# content에 노출해 모델이 "이게 전부"라고 답하지 않게 한다.
MEMORY_TOOL_MAX_ROWS = 25
_ALL_SCOPE_WORDS = frozenset({"전체", "모든", "프로젝트", "기록", "항목", "메모리"})


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
    alternate_queries: Optional[list[str]] = None,
    include_history: bool = False,
) -> tuple[str, dict]:
    """Search project records for a specific fact, metric, owner, date, reason, or change history.

    Use this for target-to-attribute questions such as "SDK 연동은 누가 담당했나?",
    for percentages and other measured values, and for comparisons across meetings.
    ``alternate_queries`` may contain at most three faithful rewrites of the user's
    question. Set ``include_history`` when the question asks how a decision changed.
    """
    context, sources, debug = qa_engine._build_context(
        project_id,
        query,
        history_mode=include_history,
        query_variants=alternate_queries or [],
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
    # 기본값을 상한과 일치시킨다 — 모델이 이 인자를 거의 지정하지 않아 기본값이 곧
    # 실질 상한이었고, MEMORY_TOOL_MAX_ROWS를 올려도 기본 경로엔 닿지 않았다.
    # 상한을 넘으면 아래에서 잘렸다는 사실을 content에 명시한다.
    limit: int = MEMORY_TOOL_MAX_ROWS,
) -> tuple[str, dict]:
    """List or count project memory using explicit structured conditions.

    Use this only for true list/count requests. ``owner`` is a condition already
    present in the question, never the person the user is asking you to discover.
    ``category`` is required; use ``all`` only when the request intentionally
    spans categories or names no category. A category name plus "전체"/"목록"/
    "개수" (e.g. "액션 아이템 전체 목록", "결정사항 목록", "리스크 전체 개수") is this
    tool, not get_project_overview, even though it says "전체".
    ``completion_status`` is ``open``, ``completed``, or ``unknown``; do not
    turn an unknown status into open.
    Put a concrete target phrase in ``text_query`` so list records can be ranked
    and count records can be restricted by that phrase. Leave it empty when the
    structured filters define the complete target set, including an all-record count.
    Raw SQL is not supported, and list output is capped. When the result is
    capped the content starts with a "(총 N건 중 상위 M건만 표시)" line — say so
    in your answer instead of presenting the listed rows as the complete set.
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
        # apply_floor=False — 이 도구의 계약은 "조건에 맞는 행 열거"라서 순서만 필요하다.
        # _build_context용 관련도 컷을 그대로 쓰면 명백히 관련 있는 행까지 잘려 목록이
        # 사실과 달라진다("알림" 질의에 "푸시 알림 연동"이 빠지는 식).
        ranked, vector_hits = qa_engine._rank_mysql_rows(
            project_id, rows, [text_query], limit, apply_floor=False
        )
    ranked = ranked[:limit]
    if ranked:
        content = "\n".join(qa_engine._format_mysql_row(row) for row in ranked)
        # 잘림은 artifact에만 있고 모델이 보는 건 content뿐이라, 상위 N건을 받은 모델이
        # 그걸 "전체"라고 답했다. 나머지가 있다는 사실을 content에 명시해 답변에
        # 반영되게 한다(F-006).
        if len(rows) > len(ranked):
            content = f"(총 {len(rows)}건 중 상위 {len(ranked)}건만 표시)\n{content}"
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

    Use only when the user explicitly asks for a briefing or overall project status
    without naming a specific category. A phrase such as "전체 정답률" is a specific
    metric and must use evidence search. The Action Plan is reference data: during
    a general briefing, select only what the question needs, and list every item
    only when the user explicitly asks for the complete list.
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
        "sources": sources,
        "category_stats": context.get("category_stats") or {},
        "total_rows": len(rows),
        "returned_rows": len(rows),
        "truncated": False,
    }


QA_TOOLS = [search_project_evidence, query_structured_memory, get_project_overview]
