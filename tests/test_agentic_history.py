from unittest.mock import MagicMock

import pytest
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


def _evidence_call(query: str, *, include_history: bool = False) -> AIMessage:
    return AIMessage(content="", tool_calls=[{
        "name": "search_project_evidence",
        "args": {"query": query, "include_history": include_history},
        "id": "call_evidence",
        "type": "tool_call",
    }])


@pytest.mark.parametrize("question", ["그 전에는?", "이전 결정은?"])
def test_history_followup_reaches_retrieval_with_previous_topic(monkeypatch, question):
    fake = _ToolCallingFake([
        _evidence_call(question),
        AIMessage(content="기존에는 세션 인증을 사용했습니다."),
    ])
    build_context = MagicMock(return_value=("이력 근거", ["decision.md"], {}))
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)
    monkeypatch.setattr(qa_tools, "get_project_memory", lambda project_id: "")

    result = run_agentic_qa(
        1,
        question,
        history=[
            {"role": "user", "content": "인증 방식을 어떻게 결정했어?"},
            {"role": "assistant", "content": "OAuth로 결정했습니다."},
        ],
        model=fake,
    )

    assert result["answer"] == "기존에는 세션 인증을 사용했습니다."
    args, kwargs = build_context.call_args
    assert args == (1, f"인증 방식을 어떻게 결정했어? {question}")
    assert kwargs["history_mode"] is True
    assert kwargs["history_scope"] == "topical"
    assert "인증" in kwargs["history_topic_tokens"]
    assert kwargs["query_variants"] == [question]


def test_non_history_question_keeps_tool_query_unchanged(monkeypatch):
    fake = _ToolCallingFake([
        _evidence_call("현재 인증 담당자"),
        AIMessage(content="현재 담당자는 민지입니다."),
    ])
    build_context = MagicMock(return_value=("현재 근거", ["action.md"], {}))
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)
    monkeypatch.setattr(qa_tools, "get_project_memory", lambda project_id: "")

    run_agentic_qa(
        1,
        "지금 누가 담당해?",
        history=[{"role": "user", "content": "예전 인증 결정은?"}],
        model=fake,
    )

    args, kwargs = build_context.call_args
    assert args == (1, "현재 인증 담당자")
    assert kwargs["history_mode"] is False
    assert kwargs["history_scope"] is None
    assert kwargs["history_topic_tokens"] == []


@pytest.mark.parametrize("attachment_marker", ["[첨부 자료]", "[임시 첨부 근거]"])
def test_attachment_evidence_is_not_used_as_the_followup_topic(
    monkeypatch, attachment_marker
):
    fake = _ToolCallingFake([
        _evidence_call("그 전에는?"),
        AIMessage(content="기존 인증 결정을 답했습니다."),
    ])
    build_context = MagicMock(return_value=("이력 근거", ["decision.md"], {}))
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)
    monkeypatch.setattr(qa_tools, "get_project_memory", lambda project_id: "")

    run_agentic_qa(
        1,
        "그 전에는?",
        history=[{"role": "user", "content": "인증 방식을 어떻게 결정했어?"}],
        attachment_context=f"{attachment_marker}\n릴리즈명은 Bluefin",
        model=fake,
    )

    assert build_context.call_args.args == (
        1,
        "인증 방식을 어떻게 결정했어? 그 전에는?",
    )


def test_history_runtime_fields_are_not_exposed_to_the_model():
    assert "messages" not in qa_tools.search_project_evidence.args
    assert "current_question" not in qa_tools.search_project_evidence.args
