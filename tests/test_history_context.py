import pytest

from backend.retriever.history_context import resolve_history_context


def test_topical_scope_prepends_the_topic_to_a_deictic_question():
    mode, scope, tokens, effective_question = resolve_history_context(
        "What changed?",
        history_mode=True,
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
def test_topical_scope_carries_the_topic_into_every_deictic_phrasing(question):
    mode, scope, tokens, effective_question = resolve_history_context(
        question,
        history_mode=True,
        history_scope="topical",
        history_topic="Quartz routing",
    )

    assert mode is True
    assert scope == "topical"
    assert {"quartz", "routing"} <= set(tokens)
    assert effective_question == f"Quartz routing {question}"


def test_global_scope_leaves_the_question_untouched():
    mode, scope, tokens, effective_question = resolve_history_context(
        "Summarize every reversal.",
        history_mode=True,
        history_scope="global",
    )

    assert (mode, scope, tokens) == (True, "global", [])
    assert effective_question == "Summarize every reversal."


def test_history_mode_never_widens_missing_scope_to_global():
    with pytest.raises(ValueError, match="explicit history_scope"):
        resolve_history_context(
            "Show earlier states.",
            history_mode=True,
        )


def test_topical_scope_requires_an_explicit_topic():
    with pytest.raises(ValueError, match="explicit topic"):
        resolve_history_context(
            "What preceded it?",
            history_mode=True,
            history_scope="topical",
        )


def test_topical_scope_rejects_empty_or_non_text_topic():
    with pytest.raises((TypeError, ValueError)):
        resolve_history_context(
            "What changed?",
            history_mode=True,
            history_scope="topical",
            history_topic=7,
        )
