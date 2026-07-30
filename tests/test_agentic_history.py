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


def _evidence_call(query: str, call_id: str = "call_evidence") -> AIMessage:
    return AIMessage(content="", tool_calls=[{
        "name": "search_hybrid_vector_rag",
        "args": {"query": query},
        "id": call_id,
        "type": "tool_call",
    }])


def _topical_scope(*, inherit_previous_topic: bool) -> dict:
    return {
        "include_history": True,
        "inherit_previous_topic": inherit_previous_topic,
        "history_scope": "topical",
        "history_topic": "Nimbus42 authentication",
    }


def test_request_scope_can_inherit_the_previous_user_topic(monkeypatch):
    fake = _ToolCallingFake([
        _evidence_call("earlier state"),
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
        question_scope=_topical_scope(inherit_previous_topic=True),
        model=fake,
    )

    assert result["answer"] == "An earlier state was found."
    args, kwargs = build_context.call_args
    assert args == (1, "What preceded it?")
    assert kwargs["history_mode"] is True
    assert kwargs["history_scope"] == "topical"
    assert {"nimbus", "42"} <= set(kwargs["history_topic_tokens"])
    assert kwargs["query_variants"] == [
        "Nimbus42 authentication What preceded it?",
    ]


def test_self_contained_history_scope_does_not_prepend_prior_turn(monkeypatch):
    fake = _ToolCallingFake([
        _evidence_call("Nimbus42 changes"),
        AIMessage(content="The change history was found."),
    ])
    build_context = MagicMock(
        return_value=("history evidence", ["repo#1:notes.md"], {})
    )
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    run_agentic_qa(
        1,
        "How did Nimbus42 authentication change?",
        history=[{"role": "user", "content": "Discuss an unrelated release."}],
        question_scope=_topical_scope(inherit_previous_topic=False),
        model=fake,
    )

    assert build_context.call_args.kwargs["query_variants"] == [
        "How did Nimbus42 authentication change?",
    ]


def test_current_scope_never_infers_history_from_question_phrasing(monkeypatch):
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
        question_scope={"include_history": False},
        model=fake,
    )

    kwargs = build_context.call_args.kwargs
    assert kwargs["history_mode"] is False
    assert kwargs["history_scope"] is None
    assert kwargs["history_topic_tokens"] == []
    assert kwargs["query_variants"] == ["What changed in Nimbus42?"]


def test_global_history_scope_uses_no_topic_predicate(monkeypatch):
    fake = _ToolCallingFake([
        _evidence_call("project chronology"),
        AIMessage(content="The chronology was found."),
    ])
    build_context = MagicMock(
        return_value=("history evidence", ["repo#1:notes.md"], {})
    )
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    run_agentic_qa(
        1,
        "Summarize the project chronology.",
        question_scope={
            "include_history": True,
            "history_scope": "global",
        },
        model=fake,
    )

    kwargs = build_context.call_args.kwargs
    assert kwargs["history_mode"] is True
    assert kwargs["history_scope"] == "global"
    assert kwargs["history_topic_tokens"] == []


def test_one_injected_scope_is_stable_across_repeated_searches(monkeypatch):
    fake = _ToolCallingFake([
        _evidence_call("Nimbus42 origin", "call_1"),
        _evidence_call("Nimbus42 outcome", "call_2"),
        AIMessage(content="Both evidence slices were found."),
    ])
    build_context = MagicMock(
        return_value=("history evidence", ["repo#1:notes.md"], {})
    )
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    run_agentic_qa(
        1,
        "Compare the origin and outcome of Nimbus42.",
        question_scope=_topical_scope(inherit_previous_topic=False),
        model=fake,
    )

    assert build_context.call_count == 2
    assert [
        call.kwargs["history_mode"]
        for call in build_context.call_args_list
    ] == [True, True]
    assert [
        call.kwargs["history_scope"]
        for call in build_context.call_args_list
    ] == ["topical", "topical"]


def test_attachment_evidence_is_not_used_as_inherited_topic(monkeypatch):
    fake = _ToolCallingFake([
        _evidence_call("earlier state"),
        AIMessage(content="The prior state was found."),
    ])
    build_context = MagicMock(
        return_value=("history evidence", ["repo#1:notes.md"], {})
    )
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    run_agentic_qa(
        1,
        "What preceded it?",
        history=[{"role": "user", "content": "Explain Nimbus42 authentication."}],
        attachment_context="[첨부 자료]\nUnrelated attachment content",
        question_scope=_topical_scope(inherit_previous_topic=True),
        model=fake,
    )

    assert build_context.call_args.kwargs["query_variants"] == [
        "Nimbus42 authentication What preceded it?",
    ]


def test_request_scope_and_runtime_fields_are_hidden_from_tool_schema():
    properties = qa_tools.search_project_evidence.tool_call_schema.model_json_schema()[
        "properties"
    ]

    assert set(properties) == {"query", "alternate_queries"}
    for name in (
        "messages",
        "current_question",
        "question_scope",
        "include_history",
        "inherit_previous_topic",
    ):
        assert name not in properties
