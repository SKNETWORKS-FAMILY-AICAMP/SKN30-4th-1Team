"""Language-agnostic topic tokenization for explicit history retrieval.

History intent and conversational references are not inferred here.  The
request-level structured scope decides whether history is needed and whether
the previous user topic must be inherited.  This module only puts questions
and stored components in the same canonical token space for topical ranking.
"""

from __future__ import annotations

import unicodedata
from typing import Set


_kiwi = None


def _with_east_asian_ngrams(tokens: Set[str]) -> Set[str]:
    """Add generic local overlap for unsegmented wide/fullwidth text."""
    expanded = set(tokens)
    for token in tokens:
        if not any(
            unicodedata.east_asian_width(character) in {"W", "F"}
            for character in token
        ):
            continue
        for size in (2, 3):
            expanded.update(
                token[index:index + size]
                for index in range(len(token) - size + 1)
            )
    return expanded


def _unicode_tokens(text: str) -> Set[str]:
    """Split NFKC text on Unicode categories without script assumptions."""
    result: set[str] = set()
    current: list[str] = []
    for character in unicodedata.normalize("NFKC", text):
        group = unicodedata.category(character)[0]
        if group in ("L", "N") or (group == "M" and current):
            current.append(character)
            continue
        if current:
            result.add("".join(current).casefold())
            current = []
    if current:
        result.add("".join(current).casefold())
    return {token for token in result if token}


def _tokenize_with_kiwi(text: str, *, nouns_only: bool) -> Set[str] | None:
    """Return ``None`` only when Kiwi is unavailable or fails."""
    global _kiwi
    if _kiwi is False:
        return None
    if _kiwi is None:
        try:
            from kiwipiepy import Kiwi

            _kiwi = Kiwi()
        except (ImportError, RuntimeError):
            _kiwi = False
            return None
    try:
        tokens = _kiwi.tokenize(text)
    except (RuntimeError, TypeError, ValueError):
        return None
    if nouns_only:
        selected = [
            token.form
            for token in tokens
            if token.tag[0] == "N" or token.tag in ("SL", "SN")
        ]
    else:
        selected = [
            token.form
            for token in tokens
            if token.tag[0] in ("N", "V", "X") or token.tag in ("SL", "SN")
        ]
    return {
        normalized
        for token in selected
        for normalized in _unicode_tokens(token)
    }


def content_tokens(text: str, *, nouns_only: bool = False) -> Set[str]:
    """Return normalized content tokens without regex or phrase blacklists."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if type(nouns_only) is not bool:
        raise TypeError("nouns_only must be a boolean")
    normalized_text = unicodedata.normalize("NFKC", text).strip()
    if not normalized_text:
        return set()
    kiwi_tokens = _tokenize_with_kiwi(
        normalized_text,
        nouns_only=nouns_only,
    )
    if kiwi_tokens:
        return _with_east_asian_ngrams(kiwi_tokens)
    return _with_east_asian_ngrams(_unicode_tokens(normalized_text))


def extract_content_tokens(text: str) -> Set[str]:
    """Return noun-like topic tokens for a caller-selected topical scope."""
    return content_tokens(text, nouns_only=True)
