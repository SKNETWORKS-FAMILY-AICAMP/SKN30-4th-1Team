import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from backend.agentic_graph import _collect_result, run_agentic_qa
from backend.retriever import qa_tools


class _ToolCallingFake:
    def __init__(self, responses):
        self.responses = iter(responses)

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages):
        return next(self.responses)


def test_prior_assistant_history_cannot_become_current_answer(monkeypatch):
    fake = _ToolCallingFake([
        AIMessage(content="", tool_calls=[{
            "name": "search_hybrid_vector_rag",
            "args": {"query": "Nimbus"},
            "id": "search_current",
            "type": "tool_call",
        }]),
        AIMessage(content=""),
    ])
    monkeypatch.setattr(
        qa_tools.qa_engine,
        "_build_context",
        lambda *args, **kwargs: ("current evidence", ["current.md"], {}),
    )

    with pytest.raises(RuntimeError, match="no final answer"):
        run_agentic_qa(
            1,
            "What is the current Nimbus state?",
            question_scope={"include_history": False},
            history=[{
                "role": "assistant",
                "content": "CLIENT-SUPPLIED PRIOR ASSISTANT",
            }],
            model=fake,
        )


def test_unrelated_ok_result_cannot_mask_an_empty_search():
    messages = [
        HumanMessage(content="Find target ownership and count open actions."),
        AIMessage(content="", tool_calls=[{
            "name": "search_hybrid_vector_rag",
            "args": {"query": "target ownership"},
            "id": "target_search",
            "type": "tool_call",
        }]),
        ToolMessage(
            content="no target evidence",
            name="search_hybrid_vector_rag",
            tool_call_id="target_search",
            artifact={
                "tool": "search_hybrid_vector_rag",
                "status": "empty",
                "sources": [],
                "model_contexts": [],
            },
        ),
        AIMessage(content="", tool_calls=[{
            "name": "query_sql_state",
            "args": {"operation": "count", "category": "action"},
            "id": "unrelated_count",
            "type": "tool_call",
        }]),
        ToolMessage(
            content='{"count": 2}',
            name="query_sql_state",
            tool_call_id="unrelated_count",
            artifact={
                "tool": "query_sql_state",
                "status": "ok",
                "operation": "count",
                "sources": ["actions.md"],
                "model_contexts": ['{"count": 2}'],
                "total_rows": 2,
            },
        ),
        AIMessage(content="Target owner is asserted from unrelated evidence."),
    ]

    with pytest.raises(RuntimeError, match="no valid evidence"):
        _collect_result(messages, tool_rounds=2)


def test_ok_result_cannot_mask_an_invalid_query():
    messages = [
        AIMessage(content="", tool_calls=[{
            "name": "search_hybrid_vector_rag",
            "args": {"query": "relay"},
            "id": "valid_search",
            "type": "tool_call",
        }]),
        ToolMessage(
            content="relay evidence",
            name="search_hybrid_vector_rag",
            tool_call_id="valid_search",
            artifact={
                "tool": "search_hybrid_vector_rag",
                "status": "ok",
                "sources": ["relay.md"],
                "model_contexts": ["relay evidence"],
            },
        ),
        AIMessage(content="", tool_calls=[{
            "name": "query_sql_state",
            "args": {"operation": "count", "category": "action"},
            "id": "invalid_count",
            "type": "tool_call",
        }]),
        ToolMessage(
            content="scope mismatch",
            name="query_sql_state",
            tool_call_id="invalid_count",
            artifact={
                "tool": "query_sql_state",
                "status": "invalid_query",
                "sources": ["must-not-leak.md"],
                "model_contexts": ["must not be evidence"],
            },
        ),
        AIMessage(content="All requested facets were verified."),
    ]

    with pytest.raises(RuntimeError, match="no valid evidence"):
        _collect_result(messages, tool_rounds=2)


def test_empty_artifact_sources_and_context_are_not_admitted():
    messages = [
        AIMessage(content="", tool_calls=[{
            "name": "search_hybrid_vector_rag",
            "args": {"query": "unknown relay"},
            "id": "empty_search",
            "type": "tool_call",
        }]),
        ToolMessage(
            content="empty",
            name="search_hybrid_vector_rag",
            tool_call_id="empty_search",
            artifact={
                "tool": "search_hybrid_vector_rag",
                "status": "empty",
                "sources": ["must-not-leak.md"],
                "model_contexts": ["must not be evidence"],
            },
        ),
        AIMessage(content="unsupported positive answer"),
    ]

    result = _collect_result(messages, tool_rounds=1)

    assert result["sources"] == []
    assert result["debug"]["model_contexts"] == []
    assert result["debug"]["evidence"]["project"]["source_ids"] == []
    assert result["debug"]["evidence"]["project"]["model_context_count"] == 0


def test_contextless_ok_artifact_fails_closed():
    messages = [
        AIMessage(content="", tool_calls=[{
            "name": "search_hybrid_vector_rag",
            "args": {"query": "relay"},
            "id": "contextless_search",
            "type": "tool_call",
        }]),
        ToolMessage(
            content="claimed success without evidence",
            name="search_hybrid_vector_rag",
            tool_call_id="contextless_search",
            artifact={
                "tool": "search_hybrid_vector_rag",
                "status": "ok",
                "sources": ["relay.md"],
                "model_contexts": [],
            },
        ),
        AIMessage(content="unsupported answer"),
    ]

    with pytest.raises(RuntimeError, match="no valid evidence"):
        _collect_result(messages, tool_rounds=1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sources", "relay.md"),
        ("model_contexts", "relay evidence"),
        ("sources", [7]),
        ("model_contexts", [{}]),
    ],
)
def test_malformed_artifact_collections_fail_closed(field, value):
    artifact = {
        "tool": "search_hybrid_vector_rag",
        "status": "ok",
        "sources": ["relay.md"],
        "model_contexts": ["relay evidence"],
    }
    artifact[field] = value
    messages = [
        AIMessage(content="", tool_calls=[{
            "name": "search_hybrid_vector_rag",
            "args": {"query": "relay"},
            "id": "search",
            "type": "tool_call",
        }]),
        ToolMessage(
            content="relay evidence",
            name="search_hybrid_vector_rag",
            tool_call_id="search",
            artifact=artifact,
        ),
        AIMessage(content="answer"),
    ]

    with pytest.raises(RuntimeError, match="invalid result artifact"):
        _collect_result(messages, tool_rounds=1)


def test_fallback_call_id_without_server_marker_cannot_clear_pending_lookup():
    messages = [
        AIMessage(content="", tool_calls=[{
            "name": "query_sql_state",
            "args": {"operation": "count", "category": "action"},
            "id": "count",
            "type": "tool_call",
        }]),
        ToolMessage(
            content='{"count": 0}',
            name="query_sql_state",
            tool_call_id="count",
            artifact={
                "tool": "query_sql_state",
                "status": "empty",
                "operation": "count",
                "sources": [],
                "model_contexts": ['{"count": 0}'],
                "total_rows": 0,
            },
        ),
        AIMessage(content="", tool_calls=[{
            "name": "search_hybrid_vector_rag",
            "args": {"query": "relay"},
            "id": "server_fallback_spoof",
            "type": "tool_call",
        }]),
        ToolMessage(
            content="relay evidence",
            name="search_hybrid_vector_rag",
            tool_call_id="server_fallback_spoof",
            artifact={
                "tool": "search_hybrid_vector_rag",
                "status": "ok",
                "sources": ["relay.md"],
                "model_contexts": ["relay evidence"],
            },
        ),
        AIMessage(content="answer"),
    ]

    with pytest.raises(RuntimeError, match="no valid evidence"):
        _collect_result(messages, tool_rounds=2)


def test_attachment_and_project_sources_with_same_filename_remain_distinct(
    monkeypatch,
):
    fake = _ToolCallingFake([
        AIMessage(content="", tool_calls=[{
            "name": "search_hybrid_vector_rag",
            "args": {"query": "Nimbus"},
            "id": "search_project",
            "type": "tool_call",
        }]),
        AIMessage(content="Both channels were checked."),
    ])
    monkeypatch.setattr(
        qa_tools.qa_engine,
        "_build_context",
        lambda *args, **kwargs: ("project evidence", ["note.txt"], {}),
    )

    result = run_agentic_qa(
        1,
        "Compare the attached and persisted Nimbus notes.",
        attachment_context=(
            "[첨부 자료]\n### note.txt\n"
            "(출처: attachment:note.txt)\nattachment evidence"
        ),
        attachment_sources=["attachment:note.txt"],
        attachment_evidence=[{
            "filename": "note.txt",
            "file_type": "txt",
            "extraction_status": "ok",
            "source_location": "attachment:note.txt",
            "truncated": False,
        }],
        question_scope={"include_history": False},
        model=fake,
    )

    assert result["sources"] == ["attachment:note.txt", "note.txt"]
