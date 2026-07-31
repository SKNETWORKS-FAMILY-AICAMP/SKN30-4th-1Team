"""Regression checks for the immutable router-branching Q&A baseline."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = REPO_ROOT / "archive" / "legacy_qa_v1"
COMPARISON_SCRIPT = ARCHIVE_ROOT / "scripts" / "run_comparison.py"


def _load_comparison_module():
    spec = importlib.util.spec_from_file_location(
        "legacy_qa_comparison", COMPARISON_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _imports_archive(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        if any(name == "archive" or name.startswith("archive.") for name in names):
            return True
    return False


def test_legacy_snapshot_manifest_matches_the_tagged_source():
    result = subprocess.run(
        [sys.executable, str(ARCHIVE_ROOT / "scripts" / "verify_snapshot.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "Legacy snapshot verified" in result.stdout


def test_production_packages_do_not_import_the_archive():
    offenders = [
        path.relative_to(REPO_ROOT)
        for package in ("backend",)
        for path in (REPO_ROOT / package).rglob("*.py")
        if _imports_archive(path)
    ]

    assert offenders == []


def test_archive_is_excluded_from_the_runtime_build_inputs():
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert 'packages = ["backend"]' in pyproject
    assert "COPY frontend/" not in dockerfile
    assert "COPY archive/" not in dockerfile


def test_comparison_plan_is_key_free_sha_pinned_and_route_neutral(tmp_path):
    candidate = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    output = tmp_path / "comparison"
    environment = {
        key: value
        for key, value in os.environ.items()
        if key != "OPENAI_API_KEY"
    }

    result = subprocess.run(
        [
            sys.executable,
            str(COMPARISON_SCRIPT),
            "plan",
            "both",
            "--candidate-ref",
            candidate,
            "--output-dir",
            str(output),
            "--corpus",
            "modu",
            "--phase",
            "dev",
            "--run-id",
            "unit-plan-01",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    metadata = json.loads((output / "comparison.json").read_text(encoding="utf-8"))
    manifest = json.loads((ARCHIVE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert metadata["refs"]["legacy"]["commit"] == manifest["baseline"]["commit"]
    assert metadata["refs"]["candidate"]["commit"] == candidate
    assert {item["label"] for item in metadata["executions"]} == {
        "legacy",
        "candidate",
    }
    assert all(
        item["baseline_object"] == item["candidate_object"]
        for item in metadata["dataset_objects"]
    )
    assert metadata["comparison_contract"]["cross_version_route_is_scored"] is False
    assert metadata["comparison_contract"]["same_harness"] is False
    assert metadata["refs"]["legacy"]["runner_object"]
    assert metadata["refs"]["candidate"]["runner_object"]
    assert (
        metadata["refs"]["legacy"]["runner_object"]
        != metadata["refs"]["candidate"]["runner_object"]
    )
    assert "OPENAI_API_KEY" not in json.dumps(metadata)


def test_comparison_run_requires_explicit_live_state_acknowledgement(tmp_path):
    candidate = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    result = subprocess.run(
        [
            sys.executable,
            str(COMPARISON_SCRIPT),
            "run",
            "legacy",
            "--candidate-ref",
            candidate,
            "--output-dir",
            str(tmp_path / "live-refused"),
            "--corpus",
            "modu",
            "--run-id",
            "unit-live-refused",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "--acknowledge-live-eval-state" in result.stderr


def test_missing_legacy_object_has_shallow_clone_recovery_hint(monkeypatch):
    comparison = _load_comparison_module()
    failed = subprocess.CompletedProcess(
        args=["git"], returncode=128, stdout="", stderr="bad object"
    )
    monkeypatch.setattr(comparison, "_git", lambda *args, **kwargs: failed)

    with pytest.raises(comparison.ComparisonError, match="fetch --unshallow"):
        comparison._resolve_commit("missing", "legacy baseline")


def test_runtime_qna_entrypoints_are_agentic_only():
    query_api = (REPO_ROOT / "backend" / "api" / "query.py").read_text(encoding="utf-8")
    session_router = (REPO_ROOT / "backend" / "chat" / "router.py").read_text(
        encoding="utf-8"
    )
    project_memory = (REPO_ROOT / "backend" / "project_memory.py").read_text(
        encoding="utf-8"
    )
    retrieval_engine = (REPO_ROOT / "backend" / "retriever" / "qa_engine.py").read_text(
        encoding="utf-8"
    )

    assert "run_agentic_qa" in query_api
    assert "run_qa(" not in query_api
    assert "query_intent" not in query_api
    assert "run_agentic_qa" in session_router
    assert "get_chat_model" not in session_router
    assert "_to_langchain_messages" not in session_router
    assert not (REPO_ROOT / "frontend").exists()
    assert "def run_ingest(" not in project_memory
    assert "def answer(" not in retrieval_engine
    assert not (REPO_ROOT / "backend" / "graph.py").exists()
    assert not (REPO_ROOT / "backend" / "retriever" / "query_intent.py").exists()
    assert not (REPO_ROOT / "backend" / "retriever" / "classifier.py").exists()
    assert not (REPO_ROOT / "backend" / "retriever" / "chroma_search.py").exists()
