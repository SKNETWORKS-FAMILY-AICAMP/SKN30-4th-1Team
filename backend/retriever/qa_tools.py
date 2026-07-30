"""Retrieval-only tools used by the Agentic Q&A graph.

The tools in this module never write the user-facing answer. They only return
bounded evidence plus an artifact containing provenance/debug information. The
orchestrator LLM is the single component responsible for the final response.
"""

from __future__ import annotations

import json
import time
import unicodedata
from typing import Annotated, Literal, Optional

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from . import history_context, mysql_search, qa_engine
from .index_scope import load_project_index_scope
from .question_scope import QuestionScope
from .sql_project_state import fetch_project_overview_context

# Keep the private alias for test and tool-local compatibility. The old router
# module is not a runtime dependency anymore.
_fetch_overview_context = fetch_project_overview_context


MemoryCategory = Literal["decision", "action", "issue", "risk", "all"]
MemoryOperation = Literal["list", "count", "overview"]
CompletionStatus = Literal["open", "completed", "unknown"]
MEMORY_TOOL_MAX_ROWS = 10
_ATTACHMENT_EVIDENCE_MARKERS = ("[첨부 자료]", "[임시 첨부 근거]")
_SERVER_FALLBACK_MARKER = "paim_server_fallback"


def _with_latency(started: float, artifact: dict) -> dict:
    """Tool 실행 시간을 공통 trace 필드로 추가한다."""
    artifact["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return artifact


def _question_scope(value: Optional[dict]) -> QuestionScope:
    """Validate a non-empty server-created scope injected into a Tool call."""
    if not isinstance(value, dict) or not value:
        raise ValueError("a non-empty server question scope is required")
    return QuestionScope.model_validate(value)


def _strict_text(value, field: str, *, optional: bool = False) -> Optional[str]:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized:
        raise ValueError(f"{field} cannot be empty")
    return normalized


def _strict_project_id(value) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("project_id must be a positive integer")
    return value


def _is_server_owned_fallback(messages: list, current_question: str) -> bool:
    """Accept the one raw-search call created by the graph, never a model call."""
    if not messages:
        return False
    last = messages[-1]
    if getattr(last, "type", None) != "ai":
        return False
    marker = getattr(last, "additional_kwargs", None) or {}
    calls = list(getattr(last, "tool_calls", None) or [])
    if marker.get(_SERVER_FALLBACK_MARKER) is not True or len(calls) != 1:
        return False
    call = calls[0]
    call_id = call.get("id")
    args = call.get("args")
    if (
        call.get("name") != "search_hybrid_vector_rag"
        or not isinstance(call_id, str)
        or not call_id.startswith("server_fallback_")
        or not isinstance(args, dict)
        or set(args) != {"query"}
    ):
        return False
    fallback_query = args.get("query")
    if not isinstance(fallback_query, str):
        return False
    return (
        unicodedata.normalize("NFKC", fallback_query).strip()
        == current_question
    )


def _row_source_labels(row: dict) -> list[str]:
    """Return every canonical source label attached to one memory row."""
    labels = list(row.get("_source_labels") or [])
    raw_infos = row.get("source_infos") or []
    infos = list(raw_infos) if isinstance(raw_infos, list) else []
    primary = row.get("source_info")
    if isinstance(primary, dict) and primary and primary not in infos:
        infos.append(primary)
    if infos:
        for info in infos:
            label = qa_engine._row_source_label({**row, "source_info": info})
            if label != "?":
                labels.append(label)
    else:
        label = qa_engine._row_source_label(row)
        if label != "?":
            labels.append(label)
    return sorted(set(labels))


def _dedupe_rows(rows: list[dict]) -> list[dict]:
    """Deduplicate memory rows while preserving every canonical source."""
    by_key: dict[object, dict] = {}
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
        labels = _row_source_labels(row)
        if key in by_key:
            existing = by_key[key]
            existing["_source_labels"] = sorted(set(
                list(existing.get("_source_labels") or []) + labels
            ))
            continue
        kept = dict(row)
        kept["_source_labels"] = labels
        by_key[key] = kept
        result.append(kept)
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
    question_scope: Annotated[
        Optional[dict],
        InjectedState("question_scope"),
    ] = None,
    alternate_queries: Annotated[
        Optional[list[str]],
        (
            "기본 검색어와 같은 의미의 표기 변형을 최대 3개 전달합니다. "
            "대상·역할·시점·수치 단위를 바꾸지 않습니다."
        ),
    ] = None,
) -> tuple[str, dict]:
    """현재 프로젝트에 수집된 기록에서 특정 대상의 근거를 검색합니다.

    사용자가 대상을 지목했지만 담당자·수치·날짜·상태·이유·배경 같은 속성을
    모를 때 사용합니다. 이미 주어진 구조화 조건으로 목록이나 정확한 개수를 구하는 요청,
    프로젝트 전반의 조망 요청에는 사용하지 않습니다.
    """
    started = time.perf_counter()
    try:
        project_id = _strict_project_id(project_id)
        _strict_text(query, "query")
        runtime_question = _strict_text(current_question, "current_question")
        if not isinstance(messages, list):
            raise ValueError("messages must be a list")
        if alternate_queries is not None:
            if not isinstance(alternate_queries, list):
                raise ValueError("alternate_queries must be a list")
            if len(alternate_queries) > 3:
                raise ValueError("alternate_queries accepts at most 3 values")
            for alternate in alternate_queries:
                _strict_text(alternate, "alternate_queries item")
        scope = _question_scope(question_scope)
        server_fallback = _is_server_owned_fallback(messages, runtime_question)
    except (TypeError, ValueError) as exc:
        content = f"요청 범위를 검증할 수 없어 검색을 거부했습니다: {exc}"
        return content, _with_latency(started, {
            "tool": "search_hybrid_vector_rag",
            "status": "invalid_query",
            "sources": [],
            "model_contexts": [],
            "debug": {},
        })

    unsupported_constraints = any((
        scope.operation is not None,
        scope.category is not None,
        bool(scope.categories),
        scope.owner is not None,
        bool(scope.owners),
        bool(scope.excluded_owners),
        scope.completion_status is not None,
        bool(scope.completion_statuses),
        scope.due_within_days is not None,
        scope.overdue,
    ))
    if unsupported_constraints and not server_fallback:
        content = (
            "하이브리드 검색으로 정확히 집행할 수 없는 구조화 범위가 포함되어 "
            "검색을 거부했습니다."
        )
        return content, _with_latency(started, {
            "tool": "search_hybrid_vector_rag",
            "status": "invalid_query",
            "sources": [],
            "model_contexts": [],
            "debug": {},
        })

    # ``messages`` is the same bounded sequence shown to the orchestrator.  Its
    # last human turn is the current question, so only earlier human turns are
    # eligible as the topic of a conversational history follow-up.  Attachment
    # blocks are evidence, not conversation turns.
    user_turns = []
    for message in messages:
        if getattr(message, "type", None) != "human":
            continue
        content = getattr(message, "content", "")
        if not isinstance(content, str):
            invalid = (
                "요청 범위를 검증할 수 없어 검색을 거부했습니다: "
                "human message content must be a string"
            )
            return invalid, _with_latency(started, {
                "tool": "search_hybrid_vector_rag",
                "status": "invalid_query",
                "sources": [],
                "model_contexts": [],
                "debug": {},
            })
        normalized = unicodedata.normalize("NFKC", content).strip()
        if normalized:
            user_turns.append(normalized)
    if user_turns:
        user_turns.pop()
    conversation_history = [
        {"role": "user", "content": content}
        for content in user_turns
        if not content.startswith(_ATTACHMENT_EVIDENCE_MARKERS)
    ]
    runtime_history_mode = scope.include_history
    try:
        history_mode, history_scope, history_tokens, effective_question = (
            history_context.resolve_history_context(
                runtime_question,
                conversation_history,
                history_mode=runtime_history_mode,
                inherit_previous_topic=scope.inherit_previous_topic,
                history_scope=scope.history_scope,
                history_topic=scope.history_topic,
            )
        )
    except (TypeError, ValueError) as exc:
        content = f"이력 범위를 검증할 수 없어 검색을 거부했습니다: {exc}"
        return content, _with_latency(started, {
            "tool": "search_hybrid_vector_rag",
            "status": "invalid_query",
            "sources": [],
            "model_contexts": [],
            "debug": {},
        })
    # Model-authored query variants are advisory and cannot prove that they
    # preserve the immutable request scope. Search only the authoritative user
    # question (plus the server-approved inherited user topic).
    retrieval_variants = [effective_question]

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
    return content, _with_latency(started, {
        "tool": "search_hybrid_vector_rag",
        "status": "ok" if context else "empty",
        "sources": sources,
        "model_contexts": [content] if context else [],
        "server_fallback": server_fallback,
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
    project_id: Annotated[int, InjectedState("project_id")],
    category: Annotated[
        MemoryCategory,
        (
            "질문에 명시된 분류 범위입니다. decision: 합의·확정된 선택이나 방침, "
            "action: 수행할 구체 작업, issue: 해결이 필요한 현재 문제, "
            "risk: 미래의 위협·불확실성, all: 여러 분류를 함께 묻거나 분류 조건이 없을 때만 사용."
        ),
    ],
    question_scope: Annotated[
        Optional[dict],
        InjectedState("question_scope"),
    ] = None,
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

    목록·개수는 category, owner, completion_status, due_within_days, overdue처럼
    스키마로 표현되는 조건만 정확하게 조회합니다. 작업명이나 자연어 대상 문구처럼
    스키마 밖 조건이 필요하면 search_hybrid_vector_rag를 사용합니다.
    프로젝트 브리핑·전반 현황 요청은 overview·all로 조회해 저장된 요약과
    유효한 Action Plan을 반환합니다.
    completion_status가 unknown이면 완료 여부 미확인으로 유지하고
    status_counts를 Action Plan 상태 집계의 권위 있는 값으로 사용합니다.
    1건 이상의 정상 결과를 얻으면 같은 조건을 search_hybrid_vector_rag로 다시 검색하지 않습니다.
    사용자가 모르는 담당자·상태·수치·이유를 발견하는 용도가 아닙니다.
    그 경우 search_hybrid_vector_rag를 사용합니다. 원시 SQL은 지원하지 않으며 목록 결과에는 서버 상한이 적용됩니다.
    """
    started = time.perf_counter()
    requested_filters = {
        "category": category,
        "owner": owner,
        "completion_status": completion_status,
        "due_within_days": due_within_days,
        "overdue": overdue,
    }
    invalid_reason = None
    try:
        project_id = _strict_project_id(project_id)
        if type(operation) is not str or operation not in (
            "list", "count", "overview"
        ):
            raise ValueError("operation is invalid")
        if type(category) is not str or category not in (
            "decision", "action", "issue", "risk", "all"
        ):
            raise ValueError("category is invalid")
        owner = _strict_text(owner, "owner", optional=True)
        if completion_status is not None and (
            type(completion_status) is not str
            or completion_status not in ("open", "completed", "unknown")
        ):
            raise ValueError("completion_status is invalid")
        if due_within_days is not None and type(due_within_days) is not int:
            raise ValueError("due_within_days must be an integer")
        if overdue is not None and type(overdue) is not bool:
            raise ValueError("overdue must be a boolean")
        if type(limit) is not int or limit <= 0:
            raise ValueError("limit must be a positive integer")
        limit = min(limit, MEMORY_TOOL_MAX_ROWS)
        scope = _question_scope(question_scope)
    except (TypeError, ValueError) as exc:
        invalid_reason = f"요청 범위를 검증할 수 없습니다: {exc}"
        scope = None

    include_superseded = False
    if invalid_reason is None:
        scoped_categories = (
            [scope.category]
            if scope.category is not None
            else list(scope.categories)
        )
        scoped_owners = (
            [scope.owner] if scope.owner is not None else list(scope.owners)
        )
        scoped_statuses = (
            [scope.completion_status]
            if scope.completion_status is not None
            else list(scope.completion_statuses)
        )
        if any(
            len(values) > 1
            for values in (scoped_categories, scoped_owners, scoped_statuses)
        ):
            invalid_reason = (
                "복수 분류·담당자·상태 조건은 단일값 구조화 조회로 "
                "정확히 표현할 수 없습니다."
            )
        elif scope.include_history and scope.history_scope != "global":
            invalid_reason = (
                "주제별 이력 범위는 구조화 조회로 정확히 표현할 수 없습니다. "
                "원문 근거 검색을 사용하세요."
            )
        elif scope.include_history and operation == "overview":
            invalid_reason = (
                "프로젝트 이력 전체의 조망은 현재 구조화 조회가 지원하지 않습니다."
            )
        elif scope.include_history and scope.inherit_previous_topic:
            invalid_reason = (
                "이전 대화 주제를 상속한 이력 범위는 구조화 조회로 "
                "정확히 표현할 수 없습니다."
            )
        elif scope.subject is not None:
            invalid_reason = (
                "자연어 대상 조건은 구조화 조회로 정확히 표현할 수 없습니다. "
                "원문 근거 검색을 사용하세요."
            )
        elif scope.operation is None:
            invalid_reason = (
                "질문 범위에 구조화 목록·개수·조망 요청이 명시되지 않았습니다. "
                "원문 근거 검색을 사용하세요."
            )
        elif operation != scope.operation:
            invalid_reason = "요청한 결과 형태와 operation이 일치하지 않습니다."
        elif category != (scoped_categories[0] if scoped_categories else "all"):
            invalid_reason = "요청한 분류 범위와 category가 일치하지 않습니다."
        elif owner != (scoped_owners[0] if scoped_owners else None):
            invalid_reason = "요청한 담당자 범위와 owner가 일치하지 않습니다."
        elif scope.excluded_owners:
            invalid_reason = (
                "제외 담당자 조건은 구조화 조회가 지원하지 않습니다. "
                "원문 근거 검색을 사용하세요."
            )
        elif completion_status != (
            scoped_statuses[0] if scoped_statuses else None
        ):
            invalid_reason = "요청한 완료 상태와 completion_status가 일치하지 않습니다."
        elif due_within_days != scope.due_within_days:
            invalid_reason = "요청한 마감 범위와 due_within_days가 일치하지 않습니다."
        elif overdue is not (True if scope.overdue else None):
            invalid_reason = "요청한 기한 초과 범위와 overdue가 일치하지 않습니다."
        else:
            include_superseded = scope.include_history

    if invalid_reason is None and category != "action" and any(
        value is not None for value in (completion_status, due_within_days, overdue)
    ):
        invalid_reason = "상태·마감 필터는 action 범위에서만 사용할 수 있습니다."
    elif invalid_reason is None and due_within_days is not None and not (
        0 <= due_within_days <= 365
    ):
        invalid_reason = "due_within_days는 0 이상 365 이하여야 합니다."
    elif invalid_reason is None and overdue is False:
        invalid_reason = "overdue는 기한 초과 조건을 요구할 때 true만 사용할 수 있습니다."
    elif (
        invalid_reason is None
        and overdue is True
        and due_within_days is not None
    ):
        invalid_reason = "overdue와 due_within_days는 함께 사용할 수 없습니다."
    elif (
        invalid_reason is None
        and overdue is True
        and completion_status not in (None, "open")
    ):
        invalid_reason = "overdue는 open action에만 사용할 수 있습니다."
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
            "model_contexts": [],
        })
    if operation == "overview":
        if category != "all" or any(
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
                "model_contexts": [],
            })
        context = _fetch_overview_context(project_id)
        rows = list((context.get("action_plan") or {}).get("items") or [])
        sources = list(dict.fromkeys(
            source
            for row in rows
            for source in _row_source_labels(row)
        ))
        content = "[프로젝트 조망]\n" + json.dumps(
            context, ensure_ascii=False, default=str
        )
        has_evidence = bool(context.get("overview_summary") or rows)
        return content, _with_latency(started, {
            "tool": "query_sql_state",
            "status": "ok" if has_evidence else "empty",
            "operation": operation,
            "sources": sources,
            "model_contexts": [content] if has_evidence else [],
            "requested_filters": requested_filters,
            "applied_filters": {
                "category": "all",
                "include_superseded": False,
            },
            "category_stats": context.get("category_stats") or {},
            "total_rows": len(rows),
            "returned_rows": len(rows),
            "truncated": False,
        })
    db_category = None if category == "all" else category
    has_filter = include_superseded or any(
        value is not None
        for value in (owner, db_category, completion_status, due_within_days, overdue)
    )
    if operation == "list" and not has_filter:
        content = (
            "구조화 조건이 비어 있어 전체 기록 조회를 거부했습니다. "
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
            "model_contexts": [],
        })

    applied_filters = {
        "category": category,
        "owner": owner,
        "completion_status": completion_status,
        "due_within_days": due_within_days,
        "overdue": overdue,
        "include_superseded": include_superseded,
    }
    index_scope = load_project_index_scope(project_id)
    rows = _dedupe_rows(mysql_search.search(
        project_id,
        category=db_category,
        owner=owner,
        text_query=None,
        completion_status=completion_status,
        due_within_days=due_within_days,
        overdue=overdue,
        include_superseded=include_superseded,
        index_scope=index_scope,
    ))
    sources = []
    for row in rows:
        for source in _row_source_labels(row):
            if source not in sources:
                sources.append(source)

    if operation == "count":
        payload = {"count": len(rows), "filters": {
            "owner": owner,
            "category": category,
            "completion_status": completion_status,
            "due_within_days": due_within_days,
            "overdue": overdue,
        }}
        content = json.dumps(payload, ensure_ascii=False, default=str)
        return content, _with_latency(started, {
            "tool": "query_sql_state",
            "status": "ok" if rows else "empty",
            "operation": operation,
            "sources": sources,
            "model_contexts": [content],
            "requested_filters": requested_filters,
            "applied_filters": applied_filters,
            "total_rows": len(rows),
            "returned_rows": 0,
        })

    ranked = rows[:limit]
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
        "sources": list(dict.fromkeys(
            source
            for row in ranked
            for source in _row_source_labels(row)
        )),
        "model_contexts": [content] if ranked else [],
        "requested_filters": requested_filters,
        "applied_filters": applied_filters,
        "total_rows": len(rows),
        "returned_rows": len(ranked),
        "truncated": len(rows) > len(ranked),
    })


QA_TOOLS = [search_project_evidence, query_structured_memory]
