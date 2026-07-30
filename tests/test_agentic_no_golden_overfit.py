"""Regression guards against evaluation-data leakage into production behavior."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable


_REPO = Path(__file__).resolve().parent.parent
_PRODUCTION_FILES = (
    _REPO / "backend" / "agentic_graph.py",
    _REPO / "backend" / "retriever" / "history_intent.py",
    _REPO / "backend" / "retriever" / "qa_engine.py",
    _REPO / "backend" / "retriever" / "qa_tools.py",
)
_QUESTION_FRAGMENT_LENGTH = 12
_RETIRED_FINAL_QUESTION_HASHES = frozenset({
    "4e8339f43f610eb42bea769716cf2fd8a4e21a5cf75312200abec19a23da8353",
    "779a65ba19aefa0af693706e3e5f46647c98b72beca4019bf8ca36014a84e2ac",
    "7a590c03cc7a6ea35694a153eede0a273700bdfe9b8dd14e5f0552896ae33b4f",
    "828986040128f26c23ac82e77b6970b8edc6faa75d03d5668af4f43014145555",
    "846a8220b74d98e2f1704a83e901ef181e2c42c635e469bcf0d9a86a94c11d27",
    "99c16e263903ec94f5a1ccc7d4008d1584ca481a86a8aa540b7499ef95043145",
    "ae23a553f055177b5441b9b1665c16df1f787eec026855a2c76250fed6328287",
    "c4147fc22ecef9b51d2e39340159bc78fccdd449490559d932bb7cf3d06768e8",
})
_RETIRED_FINAL_LITERAL_HASHES = frozenset({
    "98253ff66ed815362cffe1a5b08ea6bb4ae6835545dcdf098fa8bf17b95952ff",
})


def _normalize(value: Any) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", str(value or "")).casefold().split()
    )


def _hash(value: Any) -> str:
    return hashlib.sha256(_normalize(value).encode("utf-8")).hexdigest()


def _production_source() -> str:
    return _normalize(
        "\n".join(path.read_text(encoding="utf-8") for path in _PRODUCTION_FILES)
    )


def _walk_question_values(value: Any) -> Iterable[str]:
    if isinstance(value, list):
        for item in value:
            yield from _walk_question_values(item)
    elif isinstance(value, dict):
        question = value.get("question")
        if isinstance(question, str):
            yield question
        for item in value.values():
            yield from _walk_question_values(item)


def _question_texts() -> list[str]:
    agentic = json.loads(
        (_REPO / "evals" / "agentic_v2" / "questions.json").read_text(
            encoding="utf-8"
        )
    )
    issue17 = json.loads(
        (
            _REPO
            / "backend"
            / "test"
            / "golden"
            / "pr18_issue17_golden.json"
        ).read_text(encoding="utf-8")
    )
    return [
        *(item["user_input"] for item in agentic["questions"]),
        *_walk_question_values(issue17),
    ]


def _windows(value: str, size: int) -> Iterable[str]:
    normalized = _normalize(value)
    for start in range(max(0, len(normalized) - size + 1)):
        window = normalized[start : start + size].strip()
        if len(window) == size:
            yield window


def _golden_answer_strings() -> Iterable[str]:
    golden = json.loads(
        (_REPO / "evals" / "agentic_v2" / "golden.json").read_text(
            encoding="utf-8"
        )
    )
    for item in golden["items"]:
        reference = item.get("reference_answer")
        if reference:
            yield reference
        contract = item.get("answer_contract") or {}
        yield from contract.get("required_facts") or []
        deterministic = item.get("deterministic_answer") or {}
        yield from deterministic.get("required_items") or []
        for evidence in item.get("gold_evidence") or []:
            if evidence.get("evidence"):
                yield evidence["evidence"]


def test_production_sources_do_not_copy_evaluation_question_fragments():
    """Production instructions must not contain distinctive question excerpts."""
    source = _production_source()
    leaked = []
    for question in _question_texts():
        matches = sorted({
            window
            for window in _windows(question, _QUESTION_FRAGMENT_LENGTH)
            if window in source
        })
        if matches:
            leaked.append({"question": question, "fragments": matches})

    assert not leaked, f"evaluation question fragments leaked into production: {leaked}"


def test_production_sources_do_not_copy_golden_answers():
    """Reference answers and evidence sentences must never become runtime constants."""
    source = _production_source()
    leaked = [
        value
        for value in _golden_answer_strings()
        if len(_normalize(value)) >= _QUESTION_FRAGMENT_LENGTH
        and _normalize(value) in source
    ]

    assert not leaked, f"golden answer text leaked into production: {leaked}"


def test_committed_agentic_dataset_contains_development_questions_only():
    """A locked final holdout must be supplied outside the implementation branch."""
    questions = json.loads(
        (_REPO / "evals" / "agentic_v2" / "questions.json").read_text(
            encoding="utf-8"
        )
    )

    assert questions["splits"].get("final", 0) == 0
    assert all(item["split"] == "dev" for item in questions["questions"])


def test_retired_final_questions_and_literals_do_not_reappear_in_code():
    """The compromised final set must never be copied back into runtime or tests."""
    leaked = []
    source_files = [
        *(_REPO / "backend").rglob("*.py"),
        *(_REPO / "tests").rglob("*.py"),
    ]
    for path in source_files:
        if path == Path(__file__).resolve():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            value_hash = _hash(node.value)
            token_hashes = {
                _hash(token)
                for token in re.findall(r"[0-9A-Za-z가-힣_-]+", node.value)
            }
            if value_hash in _RETIRED_FINAL_QUESTION_HASHES or (
                token_hashes & _RETIRED_FINAL_LITERAL_HASHES
            ):
                leaked.append({
                    "file": str(path.relative_to(_REPO)),
                    "line": node.lineno,
                })

    assert not leaked, f"retired final data reappeared in code: {leaked}"
