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
    query: Annotated[
        str,
        (
            "질문이 지목한 대상과 요구 속성을 모두 보존한 기본 검색어입니다. "
            "주변 작업·상위 개념으로 임의 확장하지 않습니다."
        ),
    ],
    project_id: Annotated[int, InjectedState("project_id")],
    messages: Annotated[list, InjectedState("messages")],
    current_question: Annotated[str, InjectedState("current_question")],
    alternate_queries: Annotated[
        Optional[list[str]],
        (
            "기본 검색어와 같은 의미의 표기 변형을 최대 3개 전달합니다. "
            "대상·역할·시점·수치 단위를 바꾸지 않습니다."
        ),
    ] = None,
    include_history: Annotated[
        bool,
        (
            "변화 과정, 이전 상태, 번복·대체 관계를 묻는 경우에 true입니다. "
            "단순 이유·현재 상태 질문만으로 true를 추측하지 않습니다."
        ),
    ] = False,
) -> tuple[str, dict]:
    """현재 프로젝트에 수집된 기록에서 특정 대상의 근거를 검색합니다.

    사용자가 대상을 지목했지만 담당자·수치·날짜·상태·이유·배경 같은 속성을
    모를 때 사용합니다. 이미 주어진 구조화 조건으로 목록이나 정확한 개수를 구하는 요청,
    프로젝트 전반의 조망 요청에는 사용하지 않습니다.
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
    operation: Annotated[
        MemoryOperation,
        "사용자가 요구한 결과 형태입니다. list는 목록, count는 개수입니다.",
    ],
    text_query: Annotated[
        str,
        (
            "목록의 관련도 정렬에 쓸 구체 대상 문구입니다. 구조화 필터만으로 "
            "대상 집합이 완전히 정의되면 빈 문자열입니다."
        ),
    ],
    project_id: Annotated[int, InjectedState("project_id")],
    category: Annotated[
        MemoryCategory,
        (
            "질문에 명시된 분류 범위입니다. decision: 합의·확정된 선택이나 방침, "
            "action: 수행할 구체 작업, issue: 해결이 필요한 현재 문제, "
            "risk: 미래의 위협·불확실성, all: 여러 분류를 함께 묻거나 분류 조건이 없을 때만 사용."
        ),
    ],
    owner: Annotated[
        Optional[str],
        "질문에 조건으로 이미 주어진 담당자만 넣습니다. 사용자가 묻는 미지의 담당자를 추측하지 않습니다.",
    ] = None,
    completion_status: Annotated[
        Optional[CompletionStatus],
        (
            "action 전용 상태 필터입니다. open: 배정·대기·진행 중이거나 끝나지 않음, "
            "completed: 완료·전달이 명시됨, unknown: 완료 여부를 근거로 확정할 수 없음. "
            "completed_at이 비었다는 이유로 open으로 간주하지 않습니다."
        ),
    ] = None,
    due_within_days: Annotated[
        Optional[int],
        "사용자가 명시한 N일 이내 마감 조건입니다.",
    ] = None,
    overdue: Annotated[
        Optional[bool],
        "사용자가 기한 초과 조건을 요구할 때만 true입니다.",
    ] = None,
    limit: Annotated[
        int,
        "목록 표시 희망 상한이며 서버 최대값을 넘을 수 없습니다.",
    ] = 8,
) -> tuple[str, dict]:
    """질문에 이미 명시된 구조화 조건으로 프로젝트 기록을 목록 조회하거나 개수 집계합니다.

    사용자가 모르는 담당자·상태·수치·이유를 발견하는 용도가 아닙니다.
    그 경우 search_project_evidence를 사용합니다. 원시 SQL은 지원하지 않으며 목록 결과에는 서버 상한이 적용됩니다.
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
    """현재 프로젝트 전체를 폭넓게 조망할 때 저장된 요약, 분류별 집계와 유효한 Action Plan을 반환합니다.

    프로젝트 브리핑·전반 현황·전체 위험과 다음 할 일을 묻는 요청에만 사용합니다.
    "전체 정답률"처럼 범위 단어가 있어도 결과가 하나의 지표·수치·대상 속성이면
    search_project_evidence를 사용합니다. completion_status가 unknown이면 완료 여부 미확인으로 유지하고,
    status_counts를 Action Plan 상태 집계의 권위 있는 값으로 사용합니다.
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
