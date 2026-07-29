"""Regression checks for the immutable router-branching Q&A baseline."""

from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = REPO_ROOT / "archive" / "legacy_qa_v1"


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
        for package in ("backend", "frontend")
        for path in (REPO_ROOT / package).rglob("*.py")
        if _imports_archive(path)
    ]

    assert offenders == []


def test_archive_is_excluded_from_the_runtime_build_inputs():
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert 'packages = ["backend", "frontend"]' in pyproject
    assert "COPY archive/" not in dockerfile


def test_runtime_qna_entrypoints_are_agentic_only():
    query_api = (REPO_ROOT / "backend" / "api" / "query.py").read_text(encoding="utf-8")
    streamlit_chat = (REPO_ROOT / "frontend" / "views" / "chat.py").read_text(
        encoding="utf-8"
    )
    ingest_graph = (REPO_ROOT / "backend" / "graph.py").read_text(encoding="utf-8")
    retrieval_engine = (REPO_ROOT / "backend" / "retriever" / "qa_engine.py").read_text(
        encoding="utf-8"
    )

    assert "run_agentic_qa" in query_api
    assert "run_qa(" not in query_api
    assert "query_intent" not in query_api
    assert "run_agentic_qa" in streamlit_chat
    assert "qa_engine import answer" not in streamlit_chat
    assert "def run_qa(" not in ingest_graph
    assert "def answer(" not in retrieval_engine
    assert not (REPO_ROOT / "backend" / "retriever" / "query_intent.py").exists()
