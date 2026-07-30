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


def _evidence_call(
    query: str,
    *,
    include_history: bool | None = None,
    call_id: str = "call_evidence",
) -> AIMessage:
    args = {"query": query}
    if include_history is not None:
        args["include_history"] = include_history
    return AIMessage(content="", tool_calls=[{
        "name": "search_hybrid_vector_rag",
        "args": args,
        "id": call_id,
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
    assert args == (1, question)
    assert kwargs["history_mode"] is True
    assert kwargs["history_scope"] == "topical"
    assert "인증" in kwargs["history_topic_tokens"]
    assert kwargs["query_variants"] == [
        f"인증 방식을 어떻게 결정했어? {question}"
    ]


def test_non_history_question_keeps_tool_query_as_variant(monkeypatch):
    fake = _ToolCallingFake([
        _evidence_call("현재 인증 담당자"),
        AIMessage(content="현재 담당자는 민지입니다."),
    ])
    build_context = MagicMock(return_value=("현재 근거", ["action.md"], {}))
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    run_agentic_qa(
        1,
        "지금 누가 담당해?",
        history=[{"role": "user", "content": "예전 인증 결정은?"}],
        model=fake,
    )

    args, kwargs = build_context.call_args
    assert args == (1, "지금 누가 담당해?")
    assert kwargs["query_variants"] == ["현재 인증 담당자"]
    assert kwargs["history_mode"] is False
    assert kwargs["history_scope"] is None
    assert kwargs["history_topic_tokens"] == []


def test_explicit_history_override_can_enable_history(monkeypatch):
    """명시적 true override는 자동 판별보다 우선해 이력 범위를 사용한다."""
    fake = _ToolCallingFake([
        _evidence_call("모임 알림 지연 원인", include_history=True),
        AIMessage(content="알림 지연 원인을 답했습니다."),
    ])
    build_context = MagicMock(return_value=("현재 근거", ["issue.md"], {}))
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    run_agentic_qa(
        1,
        "모임 알림 지연의 원인은 무엇이었고 개선 후 얼마나 줄었어?",
        history=[{"role": "user", "content": "출시 일정은?"}],
        model=fake,
    )

    args, kwargs = build_context.call_args
    assert args == (
        1,
        "모임 알림 지연의 원인은 무엇이었고 개선 후 얼마나 줄었어?",
    )
    assert kwargs["query_variants"] == [
        "모임 알림 지연의 원인은 무엇이었고 개선 후 얼마나 줄었어?",
        "모임 알림 지연 원인",
    ]
    assert kwargs["history_mode"] is True


def test_explicit_change_question_enables_history_without_model_hint(monkeypatch):
    """독립적인 결정 변경 질문은 모델 힌트가 없어도 이력 검색을 사용한다."""
    question = "소셜 로그인을 출시 후가 아니라 MVP에 넣기로 바꾼 이유는 무엇이야?"
    fake = _ToolCallingFake([
        _evidence_call(question),
        AIMessage(content="결정 변경 이유를 답했습니다."),
    ])
    build_context = MagicMock(return_value=("이력 근거", ["decision.md"], {}))
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    run_agentic_qa(1, question, model=fake)

    _, kwargs = build_context.call_args
    assert kwargs["history_mode"] is True


def test_explicit_false_override_disables_detected_history(monkeypatch):
    """명시적 false override는 변화 질문도 현재 상태 범위로 제한한다."""
    question = "소셜 로그인 계획이 바뀐 이유는 무엇이야?"
    fake = _ToolCallingFake([
        _evidence_call(question, include_history=False),
        AIMessage(content="현재 기록만 확인했습니다."),
    ])
    build_context = MagicMock(return_value=("현재 근거", ["decision.md"], {}))
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    run_agentic_qa(1, question, model=fake)

    assert build_context.call_args.kwargs["history_mode"] is False


def test_null_history_hint_keeps_automatic_detection(monkeypatch):
    """null은 false override가 아니라 원 질문 기반 자동 판별을 유지한다."""
    question = "이전 결정에서 뭐가 바뀌었어?"
    fake = _ToolCallingFake([
        AIMessage(content="", tool_calls=[{
            "name": "search_hybrid_vector_rag",
            "args": {"query": question, "include_history": None},
            "id": "call_evidence",
            "type": "tool_call",
        }]),
        AIMessage(content="변경 내용을 답했습니다."),
    ])
    build_context = MagicMock(return_value=("이력 근거", ["decision.md"], {}))
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    run_agentic_qa(
        1,
        question,
        history=[{"role": "user", "content": "이전 결정은 A였습니다."}],
        model=fake,
    )

    assert build_context.call_args.kwargs["history_mode"] is True


def test_history_mode_is_stable_across_repeated_tool_calls(monkeypatch):
    """한 요청의 반복 Tool 호출에서 모델 힌트가 달라도 판별은 같아야 한다."""
    fake = _ToolCallingFake([
        _evidence_call(
            "모임 알림 지연 원인",
            include_history=True,
            call_id="call_evidence_1",
        ),
        _evidence_call(
            "알림 지연 개선 수치",
            include_history=False,
            call_id="call_evidence_2",
        ),
        AIMessage(content="알림 지연 원인과 개선 수치를 답했습니다."),
    ])
    build_context = MagicMock(return_value=("현재 근거", ["issue.md"], {}))
    monkeypatch.setattr(qa_tools.qa_engine, "_build_context", build_context)

    run_agentic_qa(
        1,
        "모임 알림 지연의 원인은 무엇이었고 개선 후 얼마나 줄었어?",
        model=fake,
    )

    assert build_context.call_count == 2
    assert [
        call.kwargs["history_mode"]
        for call in build_context.call_args_list
    ] == [True, True]


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

    run_agentic_qa(
        1,
        "그 전에는?",
        history=[{"role": "user", "content": "인증 방식을 어떻게 결정했어?"}],
        attachment_context=f"{attachment_marker}\n릴리즈명은 Nebula",
        model=fake,
    )

    assert build_context.call_args.args == (
        1,
        "그 전에는?",
    )
    assert build_context.call_args.kwargs["query_variants"] == [
        "인증 방식을 어떻게 결정했어? 그 전에는?",
    ]


def test_history_runtime_fields_are_not_exposed_to_the_model():
    assert "messages" not in qa_tools.search_project_evidence.args
    assert "current_question" not in qa_tools.search_project_evidence.args
