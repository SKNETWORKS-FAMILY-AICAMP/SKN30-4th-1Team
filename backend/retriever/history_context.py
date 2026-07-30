"""Shared history-query context resolution for Agentic evidence retrieval."""

from __future__ import annotations

import unicodedata
from typing import Optional

from . import history_intent


def _last_user_question(history: Optional[list]) -> str:
    if history is not None and not isinstance(history, list):
        raise TypeError("history must be a list")
    for message in reversed(history or []):
        if not isinstance(message, dict):
            raise TypeError("history entries must be mappings")
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        if not isinstance(content, str):
            raise TypeError("history content must be a string")
        content = unicodedata.normalize("NFKC", content).strip()
        if content:
            return content
    return ""


def resolve_history_context(
    question: str,
    history: Optional[list] = None,
    history_mode: bool = False,
    *,
    inherit_previous_topic: bool = False,
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
    if type(inherit_previous_topic) is not bool:
        raise TypeError("inherit_previous_topic must be a boolean")
    if history_topic is not None:
        if not isinstance(history_topic, str):
            raise TypeError("history_topic must be a string")
        history_topic = unicodedata.normalize("NFKC", history_topic).strip()
        if not history_topic:
            raise ValueError("history_topic cannot be empty")
    if not history_mode:
        if inherit_previous_topic or history_scope is not None or history_topic is not None:
            raise ValueError("history constraints require history_mode")
        return False, None, [], question
    if history_scope not in ("topical", "global"):
        raise ValueError("history_mode requires an explicit history_scope")

    effective_question = question
    if inherit_previous_topic:
        previous = _last_user_question(history)
        if not previous:
            raise ValueError("inherited history scope requires a previous user turn")
        if history_scope != "topical" or history_topic is None:
            raise ValueError(
                "inherited history scope requires an explicit topical history_topic"
            )
        effective_question = f"{history_topic} {question}"

    if history_scope == "global":
        if history_topic is not None:
            raise ValueError("global history cannot have a topic")
        return True, "global", [], effective_question

    if history_topic is None:
        raise ValueError("topical history requires an explicit topic")
    topic_tokens = sorted(history_intent.extract_content_tokens(history_topic))
    if not topic_tokens:
        raise ValueError("topical history scope requires topic tokens")
    return True, "topical", topic_tokens, effective_question
