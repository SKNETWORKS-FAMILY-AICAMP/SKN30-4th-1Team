"""Structural guards against coupling production behavior to evaluation data."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from backend.retriever import qa_engine, qa_tools
from evals.agentic_v2 import context_answer, pipeline


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


def test_production_retriever_has_no_legacy_answer_generation_chain():
    for name in (
        "SYSTEM_QA",
        "MULTI_QUERY_PROMPT",
        "MultiQueryResult",
        "_generate_multi_queries",
        "_prompt",
        "_chain",
        "_get_chain",
    ):
        assert not hasattr(qa_engine, name)


def test_fixed_evidence_eval_uses_current_agentic_prompt(monkeypatch):
    model = type("FakeModel", (), {
        "invocations": [],
        "invoke": lambda self, messages: (
            self.invocations.append(messages)
            or AIMessage(content="평가 답변")
        ),
    })()
    monkeypatch.setattr(context_answer, "_model", model)

    answer = context_answer.answer_from_context(
        "[구조화 기록]\n[action] 테스트",
        "현재 상태는?",
    )

    assert answer == "평가 답변"
    assert isinstance(model.invocations[0][0], SystemMessage)
    assert model.invocations[0][0].content == context_answer.ORCHESTRATOR_SYSTEM_PROMPT
    assert isinstance(model.invocations[0][1], HumanMessage)
    assert "[action] 테스트" in model.invocations[0][1].content


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


def test_runtime_state_is_server_injected_not_model_controlled():
    """The orchestrator picks the query; the server still owns request identity."""
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

    for name in ("project_id", "current_question", "messages", "question_scope"):
        assert name not in search_properties
        assert name not in structured_properties
    assert "text_query" not in structured_properties
    # Retrieval scope is now an explicit, model-authored argument.
    assert "include_history" in search_properties
    assert "include_history" in structured_properties
