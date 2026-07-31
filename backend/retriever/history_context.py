"""Shared history-query context resolution for Agentic evidence retrieval."""

from __future__ import annotations

import unicodedata
from typing import Optional

from . import history_intent


def resolve_history_context(
    question: str,
    history_mode: bool = False,
    *,
    history_scope: Optional[str] = None,
    history_topic: Optional[str] = None,
) -> tuple[bool, Optional[str], list[str], str]:
    """Return the explicit history scope and the query sent to retrieval."""
    if not isinstance(question, str):
        raise TypeError("question must be a string")
    question = unicodedata.normalize("NFKC", question).strip()
    if not question:
        raise ValueError("question cannot be empty")
    if type(history_mode) is not bool:
        raise TypeError("history_mode must be a boolean")
    if history_topic is not None:
        if not isinstance(history_topic, str):
            raise TypeError("history_topic must be a string")
        history_topic = unicodedata.normalize("NFKC", history_topic).strip()
        if not history_topic:
            raise ValueError("history_topic cannot be empty")
    if not history_mode:
        if history_scope is not None or history_topic is not None:
            raise ValueError("history constraints require history_mode")
        return False, None, [], question
    if history_scope not in ("topical", "global"):
        raise ValueError("history_mode requires an explicit history_scope")

    if history_scope == "global":
        if history_topic is not None:
            raise ValueError("global history cannot have a topic")
        return True, "global", [], question

    if history_topic is None:
        raise ValueError("topical history requires an explicit topic")
    topic_tokens = sorted(history_intent.extract_content_tokens(history_topic))
    if not topic_tokens:
        raise ValueError("topical history scope requires topic tokens")
    # Prepending the topic keeps a pronoun-only follow-up ("what preceded it?")
    # retrievable: on its own it carries no content token to match evidence with.
    return True, "topical", topic_tokens, f"{history_topic} {question}"
