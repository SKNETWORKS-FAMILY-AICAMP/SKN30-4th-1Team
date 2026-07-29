#!/usr/bin/env python3
"""Verify that the Legacy archive still points to the exact frozen baseline."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ARCHIVE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ARCHIVE_ROOT.parents[1]


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _git_tag_exists(tag: str) -> bool:
    try:
        _git("rev-parse", f"{tag}^{{}}")
    except subprocess.CalledProcessError:
        return False
    return True


def _load_manifest() -> dict:
    return json.loads((ARCHIVE_ROOT / "manifest.json").read_text(encoding="utf-8"))


def _tracked_files(path: Path) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        source_path, blob = line.split("\t", maxsplit=1)
        records.append((source_path, blob))
    return records


def verify() -> list[str]:
    manifest = _load_manifest()
    baseline = manifest["baseline"]
    expected_commit = baseline["commit"]
    errors: list[str] = []

    try:
        actual_commit = _git("rev-parse", f"{baseline['tag']}^{{}}")
    except subprocess.CalledProcessError:
        actual_commit = ""
    if actual_commit and actual_commit != expected_commit:
        errors.append(f"tag {baseline['tag']} resolves to {actual_commit}, expected {expected_commit}")

    _git("rev-parse", f"{expected_commit}^{{commit}}")

    lock = manifest["reproducibility"]["lockfile"]
    lock_blob = _git("rev-parse", f"{expected_commit}:{lock['path']}")
    if lock_blob != lock["git_blob"]:
        errors.append(f"lockfile blob is {lock_blob}, expected {lock['git_blob']}")

    project = manifest["reproducibility"]["project_file"]
    project_blob = _git("rev-parse", f"{expected_commit}:{project['path']}")
    if project_blob != project["git_blob"]:
        errors.append(
            f"project file blob is {project_blob}, expected {project['git_blob']}"
        )

    file_list = ARCHIVE_ROOT / manifest["tracked_files"]
    for source_path, expected_blob in _tracked_files(file_list):
        actual_blob = _git("rev-parse", f"{expected_commit}:{source_path}")
        if actual_blob != expected_blob:
            errors.append(
                f"{source_path} blob is {actual_blob}, expected {expected_blob}"
            )
    return errors


def main() -> int:
    try:
        errors = verify()
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError, ValueError) as exc:
        print(f"Legacy snapshot verification could not run: {exc}", file=sys.stderr)
        return 2

    if errors:
        print("Legacy snapshot verification failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    manifest = _load_manifest()
    baseline = manifest["baseline"]
    tag_note = f" ({baseline['tag']})" if _git_tag_exists(baseline["tag"]) else ""
    print(f"Legacy snapshot verified: {baseline['commit']}{tag_note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
