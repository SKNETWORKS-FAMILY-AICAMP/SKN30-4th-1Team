"""Shared history-query context resolution for Agentic evidence retrieval."""

from __future__ import annotations

from typing import Optional

from . import history_intent


def _last_user_question(history: Optional[list]) -> str:
    for message in reversed(history or []):
        if message.get("role") != "user":
            continue
        content = str(message.get("content", "")).strip()
        if content:
            return content
    return ""


def resolve_history_context(
    question: str,
    history: Optional[list] = None,
    history_mode: Optional[bool] = None,
) -> tuple[bool, Optional[str], list[str], str]:
    """Return stable history-search scope and the query sent to retrieval.

    The orchestrator can explicitly request history evidence with
    history_mode=True. If it does not, this helper only auto-detects when the
    caller passes None.
    """
    if history_mode is None:
        history_mode = history_intent.detect_history_intent(question)
    if not history_mode:
        return False, None, [], question

    effective_question = question
    current_topic_tokens = history_intent.extract_content_tokens(question)
    # Topic-less history questions ("이전 결정은?", "왜 바뀌었어?") are
    # conversational follow-ups even when they do not contain an explicit
    # pronoun.  Resolve them against the previous user turn before retrieval;
    # otherwise they degrade to a project-global supersede search.
    if history_intent.is_deictic(question) or not current_topic_tokens:
        previous = _last_user_question(history)
        if previous and not history_intent.is_deictic(previous):
            effective_question = f"{previous} {question}"

    topic_tokens = sorted(history_intent.extract_content_tokens(effective_question))
    scope = "topical" if topic_tokens else "global"
    return True, scope, topic_tokens, effective_question
