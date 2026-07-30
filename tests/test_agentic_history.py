from unittest.mock import MagicMock

from langchain_core.messages import AIMessage

from backend.agentic_graph import run_agentic_qa
from backend.retriever import qa_tools


class _ToolCallingFake:
    def __init__(self, responses):
        self.responses = iter(responses)

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages):
        return next(self.responses)


def _evidence_call(query: str, call_id: str = "call_evidence", **args) -> AIMessage:
    return AIMessage(content="", tool_calls=[{
        "name": "search_hybrid_vector_rag",
        "args": {"query": query, **args},
        "id": call_id,
        "type": "tool_call",
    }])


def test_orchestrator_topic_makes_a_pronoun_follow_up_retrievable(monkeypatch):
    fake = _ToolCallingFake([
        _evidence_call(
            "Nimbus42 authentication 이전 상태",
            include_history=True,
            history_topic="Nimbus42 authentication",
        ),
        AIMessage(content="An earlier state was found."),
    ])
    build_context = MagicMock(
        return_value=("history evidence", ["repo#1:notes.md"], {})
    )
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    result = run_agentic_qa(
        1,
        "What preceded it?",
        history=[
            {"role": "user", "content": "Explain Nimbus42 authentication."},
            {"role": "assistant", "content": "An unsupported prior answer."},
        ],
        model=fake,
    )

    assert result["answer"] == "An earlier state was found."
    args, kwargs = build_context.call_args
    assert args == (1, "What preceded it?")
    assert kwargs["history_mode"] is True
    assert kwargs["history_scope"] == "topical"
    assert {"nimbus", "42"} <= set(kwargs["history_topic_tokens"])
    # The topic is prepended to the authoritative variant, so a question that
    # carries no content token of its own can still admit evidence.
    assert kwargs["query_variants"][0] == (
        "Nimbus42 authentication What preceded it?"
    )


def test_current_state_search_never_widens_into_history(monkeypatch):
    fake = _ToolCallingFake([
        _evidence_call("current Nimbus42 state"),
        AIMessage(content="The current state was found."),
    ])
    build_context = MagicMock(
        return_value=("current evidence", ["repo#1:notes.md"], {})
    )
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    run_agentic_qa(
        1,
        "What changed in Nimbus42?",
        history=[{"role": "user", "content": "Discuss an unrelated release."}],
        model=fake,
    )

    kwargs = build_context.call_args.kwargs
    assert kwargs["history_mode"] is False
    assert kwargs["history_scope"] is None
    assert kwargs["history_topic_tokens"] == []
    assert kwargs["query_variants"] == [
        "What changed in Nimbus42?",
        "current Nimbus42 state",
    ]


def test_history_without_a_topic_is_a_global_scope(monkeypatch):
    fake = _ToolCallingFake([
        _evidence_call("project chronology", include_history=True),
        AIMessage(content="The chronology was found."),
    ])
    build_context = MagicMock(
        return_value=("history evidence", ["repo#1:notes.md"], {})
    )
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    run_agentic_qa(1, "Summarize the project chronology.", model=fake)

    kwargs = build_context.call_args.kwargs
    assert kwargs["history_mode"] is True
    assert kwargs["history_scope"] == "global"
    assert kwargs["history_topic_tokens"] == []


def test_history_choice_is_per_call_not_sticky(monkeypatch):
    fake = _ToolCallingFake([
        _evidence_call(
            "Nimbus42 origin",
            "call_1",
            include_history=True,
            history_topic="Nimbus42",
        ),
        _evidence_call("Nimbus42 current outcome", "call_2"),
        AIMessage(content="Both evidence slices were found."),
    ])
    build_context = MagicMock(
        return_value=("evidence", ["repo#1:notes.md"], {})
    )
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    run_agentic_qa(1, "Compare the origin and outcome of Nimbus42.", model=fake)

    assert build_context.call_count == 2
    assert [
        call.kwargs["history_mode"]
        for call in build_context.call_args_list
    ] == [True, False]
    assert [
        call.kwargs["history_scope"]
        for call in build_context.call_args_list
    ] == ["topical", None]


def test_runtime_fields_stay_hidden_from_the_tool_schema():
    properties = qa_tools.search_project_evidence.tool_call_schema.model_json_schema()[
        "properties"
    ]

    assert set(properties) == {
        "query",
        "alternate_queries",
        "include_history",
        "history_topic",
    }
    for name in ("messages", "current_question", "project_id", "question_scope"):
        assert name not in properties
