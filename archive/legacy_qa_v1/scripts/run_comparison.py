#!/usr/bin/env python3
"""Run the frozen Legacy and current Q&A evaluations as isolated candidates.

This script is an archive-side orchestration tool.  It never imports Legacy
code into the production process.  Each selected ref is materialized in a
detached worktree and executes that ref's own golden evaluation CLI.
"""

from __future__ import annotations

import argparse
import csv
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Iterator


ARCHIVE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ARCHIVE_ROOT.parents[1]
MANIFEST_PATH = ARCHIVE_ROOT / "manifest.json"
VERIFY_SCRIPT = ARCHIVE_ROOT / "scripts" / "verify_snapshot.py"
GLOBAL_LOCK = Path(tempfile.gettempdir()) / "paim-legacy-current-eval.lock"
EVAL_CONTAINER = "paim-eval-db"
EVAL_PORT = "127.0.0.1:3316"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class ComparisonError(RuntimeError):
    """A comparison precondition failed without starting live evaluation."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_manifest() -> dict:
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ComparisonError(f"cannot read archive manifest: {exc}") from exc


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ComparisonError(f"git {' '.join(args)} failed: {detail}")
    return completed


def _resolve_commit(ref: str, label: str) -> str:
    completed = _git("rev-parse", "--verify", f"{ref}^{{commit}}", check=False)
    if completed.returncode:
        hint = ""
        if label == "legacy baseline":
            hint = (
                " This clone does not contain the frozen baseline object. "
                "If it is shallow, fetch history first (for example: "
                "`git fetch --unshallow <remote>`), or fetch the exact baseline "
                f"commit `{ref}` from a trusted remote."
            )
        raise ComparisonError(
            f"{label} ref `{ref}` is unavailable as a commit.{hint}"
        )
    return completed.stdout.strip()


def _object_id(commit: str, path: str) -> str:
    completed = _git("rev-parse", "--verify", f"{commit}:{path}", check=False)
    if completed.returncode:
        raise ComparisonError(f"evaluation dataset path missing at {commit}: {path}")
    return completed.stdout.strip()


def _dataset_contract(
    manifest: dict, baseline_sha: str, candidate_sha: str
) -> list[dict[str, str]]:
    paths = manifest.get("comparison_evaluation", {}).get("dataset_paths", [])
    if not paths:
        raise ComparisonError("manifest has no comparison_evaluation.dataset_paths")

    records: list[dict[str, str]] = []
    mismatches: list[str] = []
    for path in paths:
        baseline_object = _object_id(baseline_sha, path)
        candidate_object = _object_id(candidate_sha, path)
        records.append(
            {
                "path": path,
                "baseline_object": baseline_object,
                "candidate_object": candidate_object,
            }
        )
        if baseline_object != candidate_object:
            mismatches.append(path)
    if mismatches:
        joined = ", ".join(mismatches)
        raise ComparisonError(
            "baseline and candidate do not contain the same evaluation dataset "
            f"objects: {joined}. Curate one immutable dataset for both refs before "
            "claiming a comparison."
        )
    return records


def _verify_archive() -> None:
    completed = subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ComparisonError(f"frozen archive verification failed: {detail}")


def _selected_labels(target: str) -> list[str]:
    if target == "both":
        return ["legacy", "candidate"]
    return ["candidate" if target == "current" else "legacy"]


def _command_template(corpus: str, phase: str, run_id: str) -> list[str]:
    return [
        "uv",
        "run",
        "--directory",
        "{detached_worktree}",
        "--locked",
        "--group",
        "eval",
        "python",
        "backend/test/golden/run_eval.py",
        "all",
        "--corpus",
        corpus,
        "--phase",
        phase,
        "--runid",
        run_id,
        "--no-langsmith",
    ]


def build_plan(args: argparse.Namespace) -> dict:
    manifest = _load_manifest()
    baseline_ref = manifest["baseline"]["commit"]
    baseline_sha = _resolve_commit(baseline_ref, "legacy baseline")
    candidate_sha = _resolve_commit(args.candidate_ref, "candidate")
    _verify_archive()
    dataset = _dataset_contract(manifest, baseline_sha, candidate_sha)
    runner_path = manifest["comparison_evaluation"]["runner"]
    baseline_runner_object = _object_id(baseline_sha, runner_path)
    candidate_runner_object = _object_id(candidate_sha, runner_path)
    same_harness = baseline_runner_object == candidate_runner_object

    refs = {
        "legacy": {
            "label": "frozen router-branching baseline",
            "requested_ref": baseline_ref,
            "commit": baseline_sha,
            "runner_object": baseline_runner_object,
        },
        "candidate": {
            "label": "current Agentic candidate",
            "requested_ref": args.candidate_ref,
            "commit": candidate_sha,
            "runner_object": candidate_runner_object,
        },
    }
    command = _command_template(args.corpus, args.phase, args.run_id)
    executions = [
        {
            "label": label,
            "commit": refs[label]["commit"],
            "status": "planned",
            "command": command,
        }
        for label in _selected_labels(args.target)
    ]
    return {
        "schema_version": 1,
        "created_at_utc": _utc_now(),
        "status": "planned",
        "mode": args.mode,
        "target": args.target,
        "run": {
            "id": args.run_id,
            "corpus": args.corpus,
            "phase": args.phase,
            "llm_provider": "openai",
            "generation_model": "gpt-4.1-mini",
            "judge_model": "gpt-4.1-mini",
            "langsmith_enabled": False,
        },
        "refs": refs,
        "dataset_objects": dataset,
        "comparison_contract": {
            "same_dataset_required": True,
            "runner_path": runner_path,
            "same_harness": same_harness,
            "harness_note": (
                "Each ref executes its own architecture-specific adapter and audit. "
                "Review shared metric outputs together with raw per-question artifacts."
            ),
            "cross_version_route_is_scored": False,
            "route_note": (
                "Legacy router labels are historical diagnostics. The Agentic "
                "candidate selects tools dynamically, so compatibility field "
                "route=semantic is not a quality or routing verdict."
            ),
        },
        "isolation": {
            "execution_order": "sequential",
            "source_checkout": "detached temporary worktree per ref",
            "result_layout": "legacy/ and candidate/ under this output directory",
            "shared_docker_container": EVAL_CONTAINER,
            "shared_host_port": EVAL_PORT,
            "cleanup": "container removed after each selected ref",
            "production_runtime_imported": False,
        },
        "executions": executions,
        "host": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
    }


def _prepare_output(path: Path) -> Path:
    output = path.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ComparisonError(f"output directory must be absent or empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    return output


def _write_metadata(output: Path, metadata: dict) -> None:
    target = output / "comparison.json"
    temporary = output / ".comparison.json.tmp"
    temporary.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def _acquire_lock() -> int:
    try:
        descriptor = os.open(GLOBAL_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        owner = GLOBAL_LOCK.read_text(encoding="utf-8", errors="replace").strip()
        raise ComparisonError(
            f"another archived evaluation may be active ({GLOBAL_LOCK}, {owner})"
        ) from exc
    os.write(descriptor, f"pid={os.getpid()} started={_utc_now()}\n".encode())
    return descriptor


def _release_lock(descriptor: int) -> None:
    os.close(descriptor)
    GLOBAL_LOCK.unlink(missing_ok=True)


def _container_exists() -> bool:
    completed = subprocess.run(
        ["docker", "ps", "-aq", "-f", f"name=^{EVAL_CONTAINER}$"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or "docker command failed"
        raise ComparisonError(f"cannot inspect evaluation container: {detail}")
    return bool(completed.stdout.strip())


def _cleanup_container() -> None:
    subprocess.run(
        ["docker", "rm", "-f", EVAL_CONTAINER],
        capture_output=True,
        text=True,
        check=False,
    )


@contextmanager
def _materialized_worktree(commit: str, label: str) -> Iterator[Path]:
    temporary = Path(tempfile.mkdtemp(prefix=f"paim-{label}-eval-"))
    worktree = temporary / "repo"
    added = False
    try:
        _git("worktree", "add", "--detach", "--quiet", str(worktree), commit)
        added = True
        yield worktree
    finally:
        if added:
            _git("worktree", "remove", "--force", str(worktree), check=False)
        shutil.rmtree(temporary, ignore_errors=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_selected_artifacts(worktree: Path, output: Path, run_id: str) -> list[dict]:
    source_results = worktree / "backend" / "test" / "golden" / "results"
    destination = output / "results"
    copied: list[dict] = []
    if not source_results.exists():
        return copied

    for source in sorted(source_results.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(source_results)
        if source.name == "summary.csv":
            destination.mkdir(parents=True, exist_ok=True)
            target = destination / "summary.csv"
            with source.open(newline="", encoding="utf-8-sig") as src:
                rows = [row for row in csv.DictReader(src) if row.get("run_id") == run_id]
            if not rows:
                continue
            with target.open("w", newline="", encoding="utf-8-sig") as dst:
                writer = csv.DictWriter(dst, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        elif run_id in source.name:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        else:
            continue
        copied.append(
            {
                "path": str(target.relative_to(output)),
                "sha256": _sha256(target),
                "bytes": target.stat().st_size,
            }
        )
    return copied


def _live_environment() -> dict[str, str]:
    if not os.getenv("OPENAI_API_KEY"):
        raise ComparisonError(
            "run mode requires OPENAI_API_KEY; plan mode intentionally works without it"
        )
    if not shutil.which("uv"):
        raise ComparisonError("run mode requires uv on PATH")
    environment = os.environ.copy()
    environment["LLM_PROVIDER"] = "openai"
    environment["OPENAI_MODEL"] = "gpt-4.1-mini"
    # Compare only against the official OpenAI endpoint.  Never persist the key.
    environment.pop("OPENAI_BASE_URL", None)
    environment.pop("OPENAI_API_BASE", None)
    environment["LANGSMITH_TRACING"] = "false"
    environment["LANGCHAIN_TRACING_V2"] = "false"
    environment.pop("LANGSMITH_API_KEY", None)
    environment.pop("LANGCHAIN_API_KEY", None)
    return environment


def _run_logged(command: list[str], worktree: Path, log_path: Path, env: dict) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=worktree,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.write(line)
            log.write(line)
        return process.wait()


def _execute_side(
    label: str,
    entry: dict,
    args: argparse.Namespace,
    output: Path,
    env: dict,
) -> None:
    if _container_exists():
        raise ComparisonError(
            f"Docker container `{EVAL_CONTAINER}` already exists. The wrapper will "
            "not adopt or delete pre-existing state; stop it explicitly before retrying."
        )

    side_output = output / label
    side_output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    entry["status"] = "running"
    entry["started_at_utc"] = _utc_now()
    try:
        with _materialized_worktree(entry["commit"], label) as worktree:
            command = [
                part.replace("{detached_worktree}", str(worktree))
                for part in entry["command"]
            ]
            entry["resolved_command"] = command
            returncode = _run_logged(
                command, worktree, side_output / "runner.log", env
            )
            entry["returncode"] = returncode
            entry["artifacts"] = _copy_selected_artifacts(
                worktree, side_output, args.run_id
            )
            if returncode:
                raise ComparisonError(f"{label} evaluation exited with {returncode}")
            entry["status"] = "passed"
    except Exception:
        entry["status"] = "failed"
        raise
    finally:
        _cleanup_container()
        entry["finished_at_utc"] = _utc_now()
        entry["duration_seconds"] = round(time.monotonic() - started, 3)


def execute(metadata: dict, args: argparse.Namespace, output: Path) -> None:
    if not args.acknowledge_live_eval_state:
        raise ComparisonError(
            "run mode mutates and removes the dedicated Docker container "
            f"`{EVAL_CONTAINER}` on {EVAL_PORT} and spends OpenAI quota. Re-run with "
            "--acknowledge-live-eval-state after confirming that state is disposable."
        )
    env = _live_environment()
    descriptor = _acquire_lock()
    metadata["status"] = "running"
    _write_metadata(output, metadata)
    try:
        for entry in metadata["executions"]:
            _execute_side(entry["label"], entry, args, output, env)
            _write_metadata(output, metadata)
    except Exception:
        metadata["status"] = "failed"
        _write_metadata(output, metadata)
        raise
    finally:
        _release_lock(descriptor)
    metadata["status"] = "passed"
    metadata["finished_at_utc"] = _utc_now()
    _write_metadata(output, metadata)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plan or run frozen Legacy vs current Agentic golden evaluation in "
            "independent detached worktrees."
        )
    )
    parser.add_argument("mode", choices=("plan", "run"))
    parser.add_argument("target", choices=("legacy", "current", "both"))
    parser.add_argument(
        "--candidate-ref",
        required=True,
        help="Exact commit/ref for the current Agentic candidate.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--corpus", choices=("modu", "csbot"), required=True)
    parser.add_argument("--phase", choices=("dev", "final"), default="dev")
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--acknowledge-live-eval-state",
        action="store_true",
        help=(
            "Acknowledge Docker state replacement and OpenAI usage; required only "
            "for run mode."
        ),
    )
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if not RUN_ID_PATTERN.fullmatch(args.run_id):
        parser.error("--run-id must use 1-64 ASCII letters, digits, '.', '_' or '-'")
    try:
        metadata = build_plan(args)
        output = _prepare_output(args.output_dir)
        _write_metadata(output, metadata)
        if args.mode == "run":
            execute(metadata, args, output)
        print(f"comparison {metadata['status']}: {output / 'comparison.json'}")
        return 0
    except ComparisonError as exc:
        print(f"comparison refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
