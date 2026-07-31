import json
from unittest.mock import MagicMock

import pytest

from backend.retriever import qa_tools


def _invoke_count(monkeypatch, *, rows=None, **overrides):
    search = MagicMock(return_value=list(rows or []))
    monkeypatch.setattr(qa_tools.mysql_search, "search", search)
    monkeypatch.setattr(qa_tools, "load_project_index_scope", lambda project_id: None)
    args = {
        "operation": "count",
        "project_id": 1,
        "category": "action",
    }
    args.update(overrides)
    content, artifact = qa_tools.query_structured_memory.func(**args)
    return content, artifact, search


def test_action_only_filter_rejects_all_category(monkeypatch):
    _, artifact, search = _invoke_count(
        monkeypatch,
        category="all",
        completion_status="open",
    )

    search.assert_not_called()
    assert artifact["status"] == "invalid_query"
    assert artifact["applied_filters"] == {}


def test_out_of_range_due_filter_is_rejected_not_clamped(monkeypatch):
    _, artifact, search = _invoke_count(monkeypatch, due_within_days=366)

    search.assert_not_called()
    assert artifact["status"] == "invalid_query"
    assert artifact["requested_filters"]["due_within_days"] == 366


def test_conflicting_due_filters_are_rejected(monkeypatch):
    _, artifact, search = _invoke_count(
        monkeypatch,
        due_within_days=3,
        overdue=True,
    )

    search.assert_not_called()
    assert artifact["status"] == "invalid_query"


def test_zero_count_is_reported_as_valid_evidence(monkeypatch):
    content, artifact, search = _invoke_count(monkeypatch)

    search.assert_called_once()
    assert json.loads(content)["count"] == 0
    assert artifact["status"] == "ok"
    assert artifact["model_contexts"] == [content]
    assert artifact["sources"] == []


def test_structured_tool_schema_has_no_natural_language_sql_filter():
    properties = (
        qa_tools.query_structured_memory.tool_call_schema.model_json_schema()[
            "properties"
        ]
    )

    assert "text_query" not in properties


def test_bare_list_without_any_filter_is_rejected(monkeypatch):
    _, artifact, search = _invoke_count(
        monkeypatch,
        operation="list",
        category="all",
    )

    search.assert_not_called()
    assert artifact["status"] == "invalid_query"


def test_model_query_variants_reach_retrieval_behind_the_user_question(monkeypatch):
    build_context = MagicMock(return_value=("evidence", ["repo#1:a.md"], {}))
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    _, artifact = qa_tools.search_project_evidence.func(
        query="Quartz relay owner",
        alternate_queries=["Quartz relay 담당", "relay 담당자"],
        project_id=1,
        current_question="Explain the Quartz relay.",
    )

    assert artifact["status"] == "ok"
    # The user question must stay first: _authoritative_query_tokens trusts only
    # that entry to admit evidence, so the model's variants can rerank but never
    # widen what counts as relevant.
    assert build_context.call_args.kwargs["query_variants"] == [
        "Explain the Quartz relay.",
        "Quartz relay owner",
        "Quartz relay 담당",
        "relay 담당자",
    ]


def test_more_than_three_alternate_queries_are_rejected(monkeypatch):
    build_context = MagicMock()
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    _, artifact = qa_tools.search_project_evidence.func(
        query="relay",
        alternate_queries=["a", "b", "c", "d"],
        project_id=1,
        current_question="Explain the relay.",
    )

    build_context.assert_not_called()
    assert artifact["status"] == "invalid_query"


def test_search_without_history_stays_on_the_current_state(monkeypatch):
    build_context = MagicMock(return_value=("evidence", [], {}))
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    qa_tools.search_project_evidence.func(
        query="relay owner",
        project_id=1,
        current_question="Who owns the relay?",
    )

    assert build_context.call_args.kwargs["history_mode"] is False
    assert build_context.call_args.kwargs["history_scope"] is None


def test_history_topic_narrows_the_search_to_that_topic(monkeypatch):
    build_context = MagicMock(return_value=("evidence", [], {}))
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    qa_tools.search_project_evidence.func(
        query="relay owner history",
        project_id=1,
        current_question="Who owned it before?",
        include_history=True,
        history_topic="Quartz relay",
    )

    assert build_context.call_args.kwargs["history_mode"] is True
    assert build_context.call_args.kwargs["history_scope"] == "topical"
    assert build_context.call_args.kwargs["history_topic_tokens"]


def test_history_without_a_topic_searches_the_whole_project_history(monkeypatch):
    build_context = MagicMock(return_value=("evidence", [], {}))
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    qa_tools.search_project_evidence.func(
        query="every reversed decision",
        project_id=1,
        current_question="What decisions were reversed?",
        include_history=True,
    )

    assert build_context.call_args.kwargs["history_mode"] is True
    assert build_context.call_args.kwargs["history_scope"] == "global"
    assert build_context.call_args.kwargs["history_topic_tokens"] == []


def test_history_topic_without_history_mode_is_rejected(monkeypatch):
    build_context = MagicMock()
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    _, artifact = qa_tools.search_project_evidence.func(
        query="relay",
        project_id=1,
        current_question="Who owns the relay?",
        include_history=False,
        history_topic="Quartz relay",
    )

    build_context.assert_not_called()
    assert artifact["status"] == "invalid_query"


@pytest.mark.parametrize("operation", ["list", "count"])
def test_structured_history_includes_superseded_rows(monkeypatch, operation):
    _, artifact, search = _invoke_count(
        monkeypatch,
        operation=operation,
        include_history=True,
    )

    assert search.call_args.kwargs["include_superseded"] is True
    assert artifact["applied_filters"]["include_superseded"] is True


def test_structured_history_overview_is_rejected(monkeypatch):
    overview = MagicMock()
    monkeypatch.setattr(qa_tools, "_fetch_overview_context", overview)

    _, artifact = qa_tools.query_structured_memory.func(
        operation="overview",
        project_id=1,
        category="all",
        include_history=True,
    )

    overview.assert_not_called()
    assert artifact["status"] == "invalid_query"


def test_structured_tool_rejects_coercible_scalar_shapes(monkeypatch):
    for overrides in (
        {"due_within_days": 1.9},
        {"overdue": 1},
        {"owner": 7},
        {"limit": True},
        {"include_history": 1},
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
