import pytest

from backend.retriever.history_context import resolve_history_context


def test_history_context_inherits_the_previous_topic_for_deictic_question():
    mode, scope, tokens, effective_question = resolve_history_context(
        "그건 왜 바뀌었어?",
        history=[
            {"role": "user", "content": "배포 주기 어떻게 하기로 했어?"},
            {"role": "assistant", "content": "2주로 결정했습니다."},
        ],
        history_mode=True,
    )

    assert mode is True
    assert scope == "topical"
    assert {"배포", "주기"} <= set(tokens)
    assert effective_question == "배포 주기 어떻게 하기로 했어? 그건 왜 바뀌었어?"


def test_history_context_keeps_non_history_queries_unchanged():
    assert resolve_history_context("현재 상태는?", history_mode=False) == (
        False,
        None,
        [],
        "현재 상태는?",
    )


@pytest.mark.parametrize("question", ["그 전에는?", "이전 결정은?"])
def test_topicless_history_followup_inherits_previous_topic(question):
    mode, scope, tokens, effective_question = resolve_history_context(
        question,
        history=[
            {"role": "user", "content": "인증 방식을 어떻게 결정했어?"},
            {"role": "assistant", "content": "OAuth로 결정했습니다."},
        ],
    )

    assert mode is True
    assert scope == "topical"
    assert "인증" in tokens
    assert effective_question == f"인증 방식을 어떻게 결정했어? {question}"
