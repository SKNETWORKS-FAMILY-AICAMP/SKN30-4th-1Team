"""Structural guards against coupling production behavior to evaluation data."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from backend.retriever import qa_tools
from evals.agentic_v2 import pipeline


_REPO = Path(__file__).resolve().parent.parent


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_production_modules_do_not_import_evaluation_packages():
    violations = []
    for path in (_REPO / "backend").rglob("*.py"):
        if "test" in path.relative_to(_REPO / "backend").parts:
            continue
        forbidden = {
            module
            for module in _imports(path)
            if module == "evals"
            or module.startswith("evals.")
            or module == "backend.test"
            or module.startswith("backend.test.")
        }
        if forbidden:
            violations.append((str(path.relative_to(_REPO)), sorted(forbidden)))

    assert violations == []


def test_run_command_accepts_questions_but_never_a_golden(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", [
        "pipeline",
        "run",
        "--state-root",
        str(tmp_path),
        "--corpus",
        "modu",
        "--label",
        "blind-run",
        "--output",
        str(tmp_path / "raw.json"),
        "--questions",
        str(tmp_path / "questions.json"),
    ])

    args = pipeline.parse_args()

    assert args.command == "run"
    assert args.questions == tmp_path / "questions.json"
    assert not hasattr(args, "golden")


def test_runtime_tools_expose_standard_trace_not_evaluation_state():
    source = Path(qa_tools.__file__).read_text(encoding="utf-8")

    assert "ContextVar" not in source
    assert "capture_retrieved_contexts_for_evaluation" not in source
    assert "model_contexts" in source


def test_request_scope_is_server_injected_not_model_controlled():
    search_properties = (
        qa_tools.search_project_evidence.tool_call_schema.model_json_schema()[
            "properties"
        ]
    )
    structured_properties = (
        qa_tools.query_structured_memory.tool_call_schema.model_json_schema()[
            "properties"
        ]
    )

    assert "question_scope" not in search_properties
    assert "question_scope" not in structured_properties
    assert "include_history" not in search_properties
    assert "text_query" not in structured_properties
