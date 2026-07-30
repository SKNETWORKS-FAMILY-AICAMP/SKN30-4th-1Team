import pytest

from backend.retriever.history_context import resolve_history_context


def test_history_context_inherits_the_previous_topic_for_deictic_question():
    mode, scope, tokens, effective_question = resolve_history_context(
        "What changed?",
        history=[
            {"role": "user", "content": "Explain Nimbus cadence."},
            {"role": "assistant", "content": "Untrusted answer."},
        ],
        history_mode=True,
        inherit_previous_topic=True,
        history_scope="topical",
        history_topic="Nimbus cadence",
    )

    assert mode is True
    assert scope == "topical"
    assert {"nimbus", "cadence"} <= set(tokens)
    assert effective_question == "Nimbus cadence What changed?"


def test_history_context_keeps_non_history_queries_unchanged():
    assert resolve_history_context("현재 상태는?", history_mode=False) == (
        False,
        None,
        [],
        "현재 상태는?",
    )


@pytest.mark.parametrize("question", ["What preceded it?", "Show the prior state."])
def test_explicit_topical_history_scope_inherits_previous_topic(question):
    mode, scope, tokens, effective_question = resolve_history_context(
        question,
        history=[
            {"role": "user", "content": "Explain Quartz routing."},
            {"role": "assistant", "content": "Untrusted answer."},
        ],
        history_mode=True,
        inherit_previous_topic=True,
        history_scope="topical",
        history_topic="Quartz routing",
    )

    assert mode is True
    assert scope == "topical"
    assert {"quartz", "routing"} <= set(tokens)
    assert effective_question == f"Quartz routing {question}"


def test_inherited_query_uses_explicit_topic_not_an_unrelated_last_turn():
    _, _, _, effective_question = resolve_history_context(
        "What preceded it?",
        history=[
            {"role": "user", "content": "Explain Nimbus cadence."},
            {"role": "user", "content": "Discuss an unrelated budget."},
        ],
        history_mode=True,
        inherit_previous_topic=True,
        history_scope="topical",
        history_topic="Nimbus cadence",
    )

    assert effective_question == "Nimbus cadence What preceded it?"
    assert "budget" not in effective_question


def test_history_mode_never_widens_missing_scope_to_global():
    with pytest.raises(ValueError, match="explicit history_scope"):
        resolve_history_context(
            "Show earlier states.",
            history_mode=True,
        )


def test_inherited_history_requires_an_actual_previous_user_turn():
    with pytest.raises(ValueError, match="previous user turn"):
        resolve_history_context(
            "What preceded it?",
            history=[],
            history_mode=True,
            inherit_previous_topic=True,
            history_scope="topical",
            history_topic="Quartz relay",
        )


def test_topical_scope_rejects_empty_or_non_text_topic():
    with pytest.raises((TypeError, ValueError)):
        resolve_history_context(
            "What changed?",
            history_mode=True,
            history_scope="topical",
            history_topic=7,
        )
