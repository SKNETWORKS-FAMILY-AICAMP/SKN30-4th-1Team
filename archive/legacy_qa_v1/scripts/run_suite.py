#!/usr/bin/env python3
"""Run frozen router-branching and current Agentic Q&A suites independently."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ARCHIVE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ARCHIVE_ROOT.parents[1]
VERIFY_SCRIPT = ARCHIVE_ROOT / "scripts" / "verify_snapshot.py"


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _manifest() -> dict:
    return json.loads((ARCHIVE_ROOT / "manifest.json").read_text(encoding="utf-8"))


def _targets(filename: str) -> list[str]:
    target_file = ARCHIVE_ROOT / "tests" / filename
    return [
        line.strip()
        for line in target_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _pytest_command(worktree: Path, targets: list[str]) -> list[str]:
    if shutil.which("uv"):
        return [
            "uv",
            "run",
            "--directory",
            str(worktree),
            "--locked",
            "--group",
            "dev",
            "pytest",
            "-q",
            *targets,
        ]
    return [sys.executable, "-m", "pytest", "-q", *targets]


def _run_pytest(label: str, worktree: Path, targets: list[str]) -> int:
    command = _pytest_command(worktree, targets)
    print(f"\n== {label} ==")
    print("$ " + " ".join(command))
    return subprocess.run(command, cwd=worktree, check=False).returncode


def _with_detached_worktree(ref: str, label: str, targets: list[str]) -> int:
    with tempfile.TemporaryDirectory(prefix="paim-qa-version-") as temporary:
        worktree = Path(temporary) / label
        subprocess.run(
            [
                "git",
                "-C",
                str(REPO_ROOT),
                "worktree",
                "add",
                "--detach",
                "--quiet",
                str(worktree),
                ref,
            ],
            check=True,
        )
        try:
            return _run_pytest(label, worktree, targets)
        finally:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(REPO_ROOT),
                    "worktree",
                    "remove",
                    "--force",
                    str(worktree),
                ],
                check=False,
            )


def _verify_snapshot() -> int:
    return subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT)],
        cwd=REPO_ROOT,
        check=False,
    ).returncode


def _current_is_dirty() -> bool:
    return bool(_git("status", "--porcelain"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run frozen router-branching and current Agentic Q&A unit suites."
    )
    parser.add_argument(
        "suite",
        choices=("legacy", "current", "both"),
        nargs="?",
        default="both",
    )
    parser.add_argument(
        "--current-ref",
        help="Run current tests from this committed ref in another detached worktree.",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow current tests against this uncommitted worktree (not a release comparison).",
    )
    args = parser.parse_args()

    if _verify_snapshot():
        return 2

    manifest = _manifest()
    statuses: list[int] = []
    if args.suite in ("legacy", "both"):
        statuses.append(
            _with_detached_worktree(
                manifest["baseline"]["commit"],
                "legacy",
                _targets(Path(manifest["legacy_test_targets"]).name),
            )
        )

    if args.suite in ("current", "both"):
        current_targets = _targets(Path(manifest["current_test_targets"]).name)
        if args.current_ref:
            statuses.append(
                _with_detached_worktree(args.current_ref, "current", current_targets)
            )
        else:
            if _current_is_dirty() and not args.allow_dirty:
                print(
                    "Current worktree has uncommitted changes. Commit it, use "
                    "--current-ref, or pass --allow-dirty for a local-only check.",
                    file=sys.stderr,
                )
                return 2
            label = "current (dirty)" if _current_is_dirty() else "current"
            statuses.append(_run_pytest(label, REPO_ROOT, current_targets))

    return 0 if statuses and all(status == 0 for status in statuses) else 1


if __name__ == "__main__":
    raise SystemExit(main())
