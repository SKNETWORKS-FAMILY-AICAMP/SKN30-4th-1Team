"""Retrieval-only tools used by the Agentic Q&A graph.

The tools in this module never write the user-facing answer. They only return
bounded evidence plus an artifact containing provenance/debug information. The
orchestrator LLM is the single component responsible for the final response.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Annotated, Literal, Optional

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from . import history_context, history_intent, mysql_search, qa_engine
from .index_scope import load_project_index_scope
from .sql_project_state import fetch_project_overview_context

# Keep the private alias for test and tool-local compatibility. The old router
# module is not a runtime dependency anymore.
_fetch_overview_context = fetch_project_overview_context


MemoryCategory = Literal["decision", "action", "issue", "risk", "all"]
MemoryOperation = Literal["list", "count", "overview"]
CompletionStatus = Literal["open", "completed", "unknown"]
MEMORY_TOOL_MAX_ROWS = 10
_ALL_SCOPE_WORDS = frozenset({"전체", "모든", "프로젝트", "기록", "항목", "메모리"})
_ATTACHMENT_EVIDENCE_MARKERS = ("[첨부 자료]", "[임시 첨부 근거]")
_EVALUATION_CONTEXTS: ContextVar[Optional[list[str]]] = ContextVar(
    "qa_evaluation_contexts", default=None
)


@contextmanager
def capture_retrieved_contexts_for_evaluation():
    """현재 평가 요청에서 Tool이 사용한 전체 근거만 격리해 수집한다."""
    contexts: list[str] = []
    token = _EVALUATION_CONTEXTS.set(contexts)
    try:
        yield contexts
    finally:
        _EVALUATION_CONTEXTS.reset(token)


def _capture_evaluation_contexts(contexts: list[str]) -> None:
    """평가 수집기가 활성화된 요청에만 전체 근거를 전달한다."""
    target = _EVALUATION_CONTEXTS.get()
    if target is not None:
        target.extend(context for context in contexts if context)


def _with_latency(started: float, artifact: dict) -> dict:
    """Tool 실행 시간을 공통 trace 필드로 추가한다."""
    artifact["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return artifact


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


@tool("search_hybrid_vector_rag", response_format="content_and_artifact")
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
        Optional[bool],
        (
            "null이면 원 질문과 이전 대화로 자동 판별합니다. true는 이력 포함, "
            "false는 현재 상태만 조회하는 명시적 override입니다."
        ),
    ] = None,
) -> tuple[str, dict]:
    """현재 프로젝트에 수집된 기록에서 특정 대상의 근거를 검색합니다.

    사용자가 대상을 지목했지만 담당자·수치·날짜·상태·이유·배경 같은 속성을
    모를 때 사용합니다. 이미 주어진 구조화 조건으로 목록이나 정확한 개수를 구하는 요청,
    프로젝트 전반의 조망 요청에는 사용하지 않습니다.
    """
    started = time.perf_counter()
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
    runtime_question = current_question or query
    detected_history_mode = history_intent.detect_history_intent(
        runtime_question
    ) or (
        bool(conversation_history)
        and history_intent.is_deictic(runtime_question)
    )
    explicit_history_override = include_history
    found_override = False
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            if (
                call.get("name") == "search_hybrid_vector_rag"
                and "include_history" in (call.get("args") or {})
                and call["args"]["include_history"] is not None
            ):
                explicit_history_override = bool(call["args"]["include_history"])
                found_override = True
                break
        if found_override:
            break
    runtime_history_mode = (
        detected_history_mode
        if explicit_history_override is None
        else explicit_history_override
    )
    history_mode, history_scope, history_tokens, effective_question = (
        history_context.resolve_history_context(
            runtime_question,
            conversation_history,
            # 첫 명시적 override 또는 자동 판별 결과를 모든 Tool 호출에 재사용해
            # 한 요청 안에서 검색 범위가 흔들리지 않게 한다.
            history_mode=runtime_history_mode,
        )
    )
    retrieval_query = effective_question if history_mode else query
    # _build_context가 원 질문을 첫 검색어로 넣고, 아래 후보는 남은 3칸 안에서
    # 정규화·중복 제거한다. History 결합 질문과 모델 검색어도 같은 예산을 쓴다.
    retrieval_variants = [retrieval_query]
    if query.strip() not in {runtime_question.strip(), retrieval_query.strip()}:
        retrieval_variants.append(query)
    retrieval_variants.extend(alternate_queries or [])

    context, sources, debug = qa_engine._build_context(
        project_id,
        runtime_question,
        history_mode=history_mode,
        history_scope=history_scope,
        history_topic_tokens=history_tokens,
        query_variants=retrieval_variants,
    )
    # _build_context captures one repository-generation scope for all MySQL
    # and Chroma evidence. The unversioned project summary is intentionally not
    # mixed into this targeted tool result; query_sql_state handles overview
    # with its own summary lifecycle.
    content = context or "프로젝트 기록에서 관련 근거를 찾지 못했습니다."
    _capture_evaluation_contexts(list(debug.get("retrieved_contexts") or []))
    return content, _with_latency(started, {
        "tool": "search_hybrid_vector_rag",
        "status": "ok" if context else "empty",
        "sources": sources,
        "debug": _compact_retrieval_debug(debug),
    })


@tool("query_sql_state", response_format="content_and_artifact")
def query_structured_memory(
    operation: Annotated[
        MemoryOperation,
        (
            "사용자가 요구한 결과 형태입니다. list는 목록, count는 개수, "
            "overview는 프로젝트 전반 조망입니다."
        ),
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
    current_question: Annotated[str, InjectedState("current_question")] = "",
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
    """프로젝트의 구조화 상태를 목록·개수·전반 조망 형태로 조회합니다.

    예: "critical 버그는 몇 건"은 count·issue·text_query="critical 버그"로 조회합니다.
    프로젝트 브리핑·전반 현황·전체 위험과 다음 할 일은 overview·all·빈 text_query로 조회해
    저장된 요약과 유효한 Action Plan을 반환합니다.
    completion_status가 unknown이면 완료 여부 미확인으로 유지하고
    status_counts를 Action Plan 상태 집계의 권위 있는 값으로 사용합니다.
    1건 이상의 정상 결과를 얻으면 같은 조건을 search_hybrid_vector_rag로 다시 검색하지 않습니다.
    사용자가 모르는 담당자·상태·수치·이유를 발견하는 용도가 아닙니다.
    그 경우 search_hybrid_vector_rag를 사용합니다. 원시 SQL은 지원하지 않으며 목록 결과에는 서버 상한이 적용됩니다.
    """
    started = time.perf_counter()
    text_query = str(text_query or "").strip()
    owner = str(owner).strip() if owner else None
    limit = max(1, min(int(limit), MEMORY_TOOL_MAX_ROWS))
    requested_filters = {
        "category": category,
        "owner": owner,
        "completion_status": completion_status,
        "due_within_days": due_within_days,
        "overdue": overdue,
        "text_query": text_query,
    }
    invalid_reason = None
    if owner and current_question and owner not in current_question:
        invalid_reason = "질문에 명시되지 않은 owner는 사용할 수 없습니다."
    elif category not in {"action", "all"} and any(
        value is not None for value in (completion_status, due_within_days, overdue)
    ):
        invalid_reason = "상태·마감 필터는 action 또는 all 범위에서만 사용할 수 있습니다."
    elif due_within_days is not None and due_within_days < 0:
        invalid_reason = "due_within_days는 0 이상이어야 합니다."
    elif overdue is False:
        invalid_reason = "overdue는 기한 초과 조건을 요구할 때 true만 사용할 수 있습니다."
    if invalid_reason:
        return invalid_reason, _with_latency(started, {
            "tool": "query_sql_state",
            "status": "invalid_query",
            "operation": operation,
            "sources": [],
            "requested_filters": requested_filters,
            "applied_filters": {},
            "total_rows": 0,
            "returned_rows": 0,
        })
    if operation == "overview":
        if category != "all" or text_query or any(
            value is not None
            for value in (owner, completion_status, due_within_days, overdue)
        ):
            return "overview에는 추가 필터를 사용할 수 없습니다.", _with_latency(started, {
                "tool": "query_sql_state",
                "status": "invalid_query",
                "operation": operation,
                "sources": [],
                "requested_filters": requested_filters,
                "applied_filters": {},
                "total_rows": 0,
                "returned_rows": 0,
            })
        context = _fetch_overview_context(project_id)
        rows = list((context.get("action_plan") or {}).get("items") or [])
        sources = list(dict.fromkeys(
            row.get("source") for row in rows if row.get("source")
        ))
        content = "[프로젝트 조망]\n" + json.dumps(
            context, ensure_ascii=False, default=str
        )
        _capture_evaluation_contexts([content])
        return content, _with_latency(started, {
            "tool": "query_sql_state",
            "status": "ok" if context.get("overview_summary") or rows else "empty",
            "operation": operation,
            "sources": sources,
            "requested_filters": requested_filters,
            "applied_filters": {"category": "all"},
            "category_stats": context.get("category_stats") or {},
            "total_rows": len(rows),
            "returned_rows": len(rows),
            "truncated": False,
        })
    db_category = None if category == "all" else category
    has_filter = any(
        value is not None
        for value in (owner, db_category, completion_status, due_within_days, overdue)
    )
    if operation == "list" and not text_query and not has_filter:
        content = (
            "구조화 조건과 검색 대상이 모두 비어 있어 전체 기록 조회를 거부했습니다. "
            "구체적인 근거 검색에는 search_hybrid_vector_rag를 사용하세요."
        )
        return content, _with_latency(started, {
            "tool": "query_sql_state",
            "status": "invalid_query",
            "operation": operation,
            "sources": [],
            "requested_filters": requested_filters,
            "applied_filters": {},
            "total_rows": 0,
            "returned_rows": 0,
        })

    count_text_filter = (
        _count_text_filter(category, text_query)
        if operation == "count" else None
    )
    applied_filters = {
        "category": category,
        "owner": owner,
        "completion_status": completion_status,
        "due_within_days": due_within_days,
        "overdue": overdue,
        "text_query": count_text_filter if operation == "count" else text_query,
    }
    index_scope = load_project_index_scope(project_id)
    rows = _dedupe_rows(mysql_search.search(
        project_id,
        category=db_category,
        owner=owner,
        text_query=count_text_filter,
        completion_status=completion_status,
        due_within_days=due_within_days,
        overdue=overdue,
        index_scope=index_scope,
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
        return json.dumps(payload, ensure_ascii=False, default=str), _with_latency(started, {
            "tool": "query_sql_state",
            "status": "ok",
            "operation": operation,
            "sources": sources,
            "requested_filters": requested_filters,
            "applied_filters": applied_filters,
            "total_rows": len(rows),
            "returned_rows": 0,
        })

    ranked = rows
    vector_hits: list[dict] = []
    if text_query and rows:
        ranked, vector_hits = qa_engine._rank_mysql_rows(
            project_id, rows, [text_query], limit, index_scope
        )
    ranked = ranked[:limit]
    if ranked:
        content = "\n".join(_row_evidence(row) for row in ranked)
    else:
        content = (
            "구조화 조건으로 일치하는 행을 찾지 못했습니다. 이것만으로 기록 부재를 "
            "확정하지 말고 search_hybrid_vector_rag로 원문을 확인하세요."
        )
    return content, _with_latency(started, {
        "tool": "query_sql_state",
        "status": "ok" if ranked else "empty",
        "operation": operation,
        "sources": [
            row.get("source") for row in ranked
            if row.get("source")
        ],
        "requested_filters": requested_filters,
        "applied_filters": applied_filters,
        "total_rows": len(rows),
        "returned_rows": len(ranked),
        "truncated": len(rows) > len(ranked),
        "memory_vector_hits": vector_hits[:10],
    })


QA_TOOLS = [search_project_evidence, query_structured_memory]
