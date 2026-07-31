#!/usr/bin/env python3
"""Run one corpus of the 160-question set against the current PaiM graph."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


CORPORA = ("modu", "csbot")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", required=True, type=Path)
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--corpus", required=True, choices=CORPORA)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--db-host", default="127.0.0.1")
    parser.add_argument("--db-port", type=int, default=3316)
    parser.add_argument("--db-user", default="root")
    parser.add_argument("--db-password", default="eval")
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--model", default=None)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def evaluate_tools(expected: list[str], debug: dict, status: int, error: str | None) -> dict:
    expected_set = set(expected)
    actual_calls = debug.get("tool_calls") or []
    actual_sequence = [call.get("name") for call in actual_calls if call.get("name")]
    actual_set = set(debug.get("tools_used") or actual_sequence)
    return {
        "api_success": status == 200 and not error,
        "expected_tools": sorted(expected_set),
        "actual_tools": sorted(actual_set),
        "actual_tool_sequence": actual_sequence,
        "required_coverage_pass": expected_set.issubset(actual_set),
        "exact_set_pass": expected_set == actual_set,
        "missing_tools": sorted(expected_set - actual_set),
        "extra_tools": sorted(actual_set - expected_set),
        # The source question set does not specify argument or call-count gold.
        "args_scored": False,
        "call_count_scored": False,
    }


def load_completed(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            result[row["id"]] = row
    return result


def main() -> int:
    args = parse_args()
    if args.db_port == 3306:
        raise RuntimeError("refusing to run evaluation against development MySQL port 3306")

    repo = Path(__file__).resolve().parents[1]
    state_dir = args.state_root.resolve() / args.corpus
    manifest_path = state_dir / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(f"prepared state not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    load_dotenv(repo / ".env")
    os.environ.update({
        "DB_HOST": args.db_host,
        "DB_PORT": str(args.db_port),
        "DB_USER": args.db_user,
        "DB_PASSWORD": args.db_password,
        "DB_NAME": manifest["database"],
        "PAIM_AUTH_MODE": "dev",
        "CHROMA_PERSIST_DIR": str(state_dir / "chroma"),
        "CHROMA_COLLECTION_NAME": manifest.get("chroma_collection_name", "paiM_openai_v1"),
    })
    if args.model:
        os.environ["OPENAI_MODEL"] = args.model
    os.environ.pop("DEV_USER_ID", None)
    sys.path.insert(0, str(repo))

    from fastapi import HTTPException
    from backend.api.query import QueryRequest, query

    golden = json.loads(args.golden.read_text(encoding="utf-8"))
    questions = [row for row in golden["items"] if row["corpus"] == args.corpus]
    if len(questions) != 80:
        raise RuntimeError(f"expected 80 {args.corpus} questions, got {len(questions)}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    partial = args.output.with_suffix(args.output.suffix + ".partial")
    if args.resume:
        completed = load_completed(partial if partial.exists() else args.output)
    else:
        completed = {}
        if partial.exists():
            raise RuntimeError(f"partial output already exists; use --resume or remove it: {partial}")

    # If resuming from a completed output, materialize it as the partial log first.
    if completed and not partial.exists():
        with partial.open("w", encoding="utf-8") as handle:
            for question in questions:
                if question["id"] in completed:
                    handle.write(json.dumps(completed[question["id"]], ensure_ascii=False) + "\n")

    mode = "a" if partial.exists() else "w"
    with partial.open(mode, encoding="utf-8") as handle:
        for index, item in enumerate(questions, start=1):
            if item["id"] in completed:
                print(f"[{args.corpus} {index:02d}/80] {item['id']} resume-skip", flush=True)
                continue

            started = time.perf_counter()
            payload: dict[str, Any] = {}
            status = 500
            error = None
            attempts = 0
            while attempts < max(1, args.max_attempts):
                attempts += 1
                try:
                    payload = query(
                        1,
                        QueryRequest(question=item["question"], history=[], attachments=[]),
                    )
                    status = 200
                    error = None
                    break
                except HTTPException as exc:
                    status = exc.status_code
                    error = str(exc.detail)
                except Exception as exc:  # pragma: no cover - external runtime path
                    status = 500
                    error = f"{type(exc).__name__}: {exc}"
                if attempts < args.max_attempts:
                    time.sleep(min(2 ** attempts, 5))

            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            debug = payload.get("debug") or {}
            record = {
                "id": item["id"],
                "corpus": item["corpus"],
                "family": item["family"],
                "question": item["question"],
                "run_at": datetime.now(timezone.utc).isoformat(),
                "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                "http_status": status,
                "attempts": attempts,
                "latency_ms": elapsed_ms,
                "error": error,
                "answer": payload.get("answer") or "",
                "sources": payload.get("sources") or [],
                "route": payload.get("route") or debug.get("route"),
                "debug": debug,
                "tool_eval": evaluate_tools(item["expected_tools"], debug, status, error),
            }
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            handle.flush()
            tools = "+".join(debug.get("tools_used") or []) or "none"
            print(
                f"[{args.corpus} {index:02d}/80] {item['id']} status={status} "
                f"tools={tools} rounds={debug.get('tool_rounds')} latency={elapsed_ms:.0f}ms",
                flush=True,
            )

    final_rows = load_completed(partial)
    missing = [row["id"] for row in questions if row["id"] not in final_rows]
    if missing:
        raise RuntimeError(f"run incomplete; missing {len(missing)} ids: {missing[:5]}")
    with args.output.with_suffix(args.output.suffix + ".tmp").open("w", encoding="utf-8") as handle:
        for question in questions:
            handle.write(json.dumps(final_rows[question["id"]], ensure_ascii=False) + "\n")
    args.output.with_suffix(args.output.suffix + ".tmp").replace(args.output)
    partial.unlink()
    print(f"[완료] {args.corpus}: 80문항 → {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
