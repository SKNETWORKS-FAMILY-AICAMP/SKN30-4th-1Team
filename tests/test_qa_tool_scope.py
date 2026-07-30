import json
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from backend.retriever import qa_tools


def _invoke_count(monkeypatch, *, rows=None, scope=None, **overrides):
    search = MagicMock(return_value=list(rows or []))
    monkeypatch.setattr(qa_tools.mysql_search, "search", search)
    monkeypatch.setattr(qa_tools, "load_project_index_scope", lambda project_id: None)
    if scope is None:
        scope = {
            "operation": "count",
            "category": "action",
        }
    args = {
        "operation": "count",
        "project_id": 1,
        "category": "action",
        "question_scope": scope,
    }
    args.update(overrides)
    content, artifact = qa_tools.query_structured_memory.func(**args)
    return content, artifact, search


def test_injected_scope_rejects_a_guessed_positive_owner(monkeypatch):
    content, artifact, search = _invoke_count(
        monkeypatch,
        scope={
            "operation": "count",
            "category": "action",
            "excluded_owners": ["Beta"],
        },
        owner="Beta",
    )

    search.assert_not_called()
    assert artifact["status"] == "invalid_query"
    assert artifact["applied_filters"] == {}
    assert "owner" in content


def test_injected_scope_rejects_category_widening(monkeypatch):
    _, artifact, search = _invoke_count(
        monkeypatch,
        scope={
            "operation": "count",
            "category": "decision",
        },
        category="all",
    )

    search.assert_not_called()
    assert artifact["status"] == "invalid_query"


def test_action_only_filter_rejects_all_category_without_query_scope(monkeypatch):
    _, artifact, search = _invoke_count(
        monkeypatch,
        category="all",
        completion_status="open",
        scope={
            "operation": "count",
            "category": "all",
            "completion_status": "open",
        },
    )

    search.assert_not_called()
    assert artifact["status"] == "invalid_query"
    assert artifact["applied_filters"] == {}


def test_out_of_range_due_filter_is_rejected_not_clamped(monkeypatch):
    _, artifact, search = _invoke_count(
        monkeypatch,
        due_within_days=366,
        scope={
            "operation": "count",
            "category": "action",
            "due_within_days": 366,
        },
    )

    search.assert_not_called()
    assert artifact["status"] == "invalid_query"
    assert artifact["requested_filters"]["due_within_days"] == 366


def test_conflicting_due_filters_are_rejected(monkeypatch):
    _, artifact, search = _invoke_count(
        monkeypatch,
        due_within_days=3,
        overdue=True,
        scope={
            "operation": "count",
            "category": "action",
        },
    )

    search.assert_not_called()
    assert artifact["status"] == "invalid_query"


def test_zero_count_requires_graph_fallback(monkeypatch):
    content, artifact, search = _invoke_count(monkeypatch)

    search.assert_called_once()
    assert json.loads(content)["count"] == 0
    assert artifact["status"] == "empty"
    assert artifact["model_contexts"] == [content]
    assert artifact["sources"] == []


def test_structured_tool_schema_has_no_natural_language_sql_filter():
    properties = (
        qa_tools.query_structured_memory.tool_call_schema.model_json_schema()[
            "properties"
        ]
    )

    assert "text_query" not in properties


def test_missing_scope_fails_closed_before_structured_query(monkeypatch):
    _, artifact, search = _invoke_count(monkeypatch, scope={})

    search.assert_not_called()
    assert artifact["status"] == "invalid_query"
    assert artifact["applied_filters"] == {}


def test_multi_value_scope_is_rejected_instead_of_widened(monkeypatch):
    _, artifact, search = _invoke_count(
        monkeypatch,
        category="all",
        scope={
            "operation": "count",
            "categories": ["action", "issue"],
        },
    )

    search.assert_not_called()
    assert artifact["status"] == "invalid_query"
    assert "복수" in artifact.get("error", "") or "복수" in _


def test_named_subject_cannot_be_counted_as_the_whole_category(monkeypatch):
    content, artifact, search = _invoke_count(
        monkeypatch,
        scope={
            "operation": "count",
            "category": "action",
            "subject": "Quartz relay",
        },
    )

    search.assert_not_called()
    assert artifact["status"] == "invalid_query"
    assert "자연어 대상" in content


def test_hybrid_search_uses_only_authoritative_current_question(monkeypatch):
    build_context = MagicMock(return_value=("evidence", ["repo#1:a.md"], {}))
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    _, artifact = qa_tools.search_project_evidence.func(
        query="widened model query",
        alternate_queries=["different owner", "different category"],
        project_id=1,
        messages=[],
        current_question="Explain the Quartz relay.",
        question_scope={"subject": "Quartz relay"},
    )

    assert artifact["status"] == "ok"
    assert build_context.call_args.kwargs["query_variants"] == [
        "Explain the Quartz relay.",
    ]


def test_hybrid_search_rejects_unenforceable_structured_scope(monkeypatch):
    build_context = MagicMock()
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    _, artifact = qa_tools.search_project_evidence.func(
        query="actions",
        project_id=1,
        messages=[],
        current_question="List Alpha's actions.",
        question_scope={
            "operation": "list",
            "category": "action",
            "owner": "Alpha",
        },
    )

    build_context.assert_not_called()
    assert artifact["status"] == "invalid_query"


def test_server_owned_fallback_can_raw_search_structured_scope(monkeypatch):
    build_context = MagicMock(return_value=("raw evidence", ["repo#4:note.md"], {}))
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)
    question = "Count open relay actions."
    fallback_message = AIMessage(
        content="",
        additional_kwargs={"paim_server_fallback": True},
        tool_calls=[{
            "name": "search_hybrid_vector_rag",
            "args": {"query": question},
            "id": "server_fallback_1",
            "type": "tool_call",
        }],
    )

    _, artifact = qa_tools.search_project_evidence.func(
        query=question,
        project_id=1,
        messages=[fallback_message],
        current_question=question,
        question_scope={
            "operation": "count",
            "category": "action",
            "completion_status": "open",
        },
    )

    assert artifact["status"] == "ok"
    assert artifact["server_fallback"] is True
    build_context.assert_called_once()


def test_hybrid_search_rejects_missing_scope(monkeypatch):
    build_context = MagicMock()
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    _, artifact = qa_tools.search_project_evidence.func(
        query="anything",
        project_id=1,
        messages=[],
        current_question="Anything?",
        question_scope={},
    )

    build_context.assert_not_called()
    assert artifact["status"] == "invalid_query"


@pytest.mark.parametrize("operation", ["list", "count"])
def test_structured_global_history_includes_superseded_rows(
    monkeypatch,
    operation,
):
    search = MagicMock(return_value=[])
    monkeypatch.setattr(qa_tools.mysql_search, "search", search)
    monkeypatch.setattr(qa_tools, "load_project_index_scope", lambda project_id: None)

    _, artifact = qa_tools.query_structured_memory.func(
        operation=operation,
        project_id=1,
        category="action",
        question_scope={
            "operation": operation,
            "category": "action",
            "include_history": True,
            "history_scope": "global",
        },
    )

    assert search.call_args.kwargs["include_superseded"] is True
    assert artifact["applied_filters"]["include_superseded"] is True


def test_global_history_is_an_explicit_scope_for_bounded_all_category_list(
    monkeypatch,
):
    search = MagicMock(return_value=[])
    monkeypatch.setattr(qa_tools.mysql_search, "search", search)
    monkeypatch.setattr(qa_tools, "load_project_index_scope", lambda project_id: None)

    _, artifact = qa_tools.query_structured_memory.func(
        operation="list",
        project_id=1,
        category="all",
        question_scope={
            "operation": "list",
            "include_history": True,
            "history_scope": "global",
        },
    )

    search.assert_called_once()
    assert search.call_args.kwargs["include_superseded"] is True
    assert artifact["status"] == "empty"


def test_structured_topical_history_is_rejected(monkeypatch):
    content, artifact, search = _invoke_count(
        monkeypatch,
        scope={
            "operation": "count",
            "category": "action",
            "include_history": True,
            "history_scope": "topical",
            "history_topic": "Quartz relay",
        },
    )

    search.assert_not_called()
    assert artifact["status"] == "invalid_query"
    assert "주제별 이력" in content


def test_structured_history_overview_is_rejected(monkeypatch):
    overview = MagicMock()
    monkeypatch.setattr(qa_tools, "_fetch_overview_context", overview)

    _, artifact = qa_tools.query_structured_memory.func(
        operation="overview",
        project_id=1,
        category="all",
        question_scope={
            "operation": "overview",
            "include_history": True,
            "history_scope": "global",
        },
    )

    overview.assert_not_called()
    assert artifact["status"] == "invalid_query"


def test_structured_tool_rejects_coercible_scalar_shapes(monkeypatch):
    for overrides in (
        {"due_within_days": 1.9},
        {"overdue": 1},
        {"owner": 7},
        {"limit": True},
    ):
        _, artifact, search = _invoke_count(monkeypatch, **overrides)
        search.assert_not_called()
        assert artifact["status"] == "invalid_query"


def test_deduped_structured_row_preserves_all_canonical_sources(monkeypatch):
    first = {
        "id": 11,
        "category": "action",
        "content": "Ship relay",
        "source": "fallback.md",
        "source_info": {"repo_id": 8, "path": "relay.md"},
    }
    second = {
        **first,
        "source_info": {"repo_id": 3, "path": "relay.md"},
    }

    _, artifact, _ = _invoke_count(
        monkeypatch,
        rows=[first, second],
    )

    assert artifact["total_rows"] == 1
    assert artifact["sources"] == [
        "relay.md (repo#3)",
        "relay.md (repo#8)",
    ]
