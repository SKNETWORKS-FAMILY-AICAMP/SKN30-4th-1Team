#!/usr/bin/env python3
"""Run the routing_v2 questions through the current PaiM Agentic Q&A path."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True, choices=("csbot", "modu"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--db-port", default="3316")
    parser.add_argument("--db-password", default="eval")
    parser.add_argument("--max-attempts", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    here = Path(__file__).resolve().parent
    repo = here.parents[1]
    golden_root = repo / "backend/test/golden"
    state_dir = golden_root / ".eval_state" / args.corpus

    load_dotenv(repo / ".env")
    os.environ.update({
        "DB_HOST": "127.0.0.1",
        "DB_PORT": str(args.db_port),
        "DB_USER": "root",
        "DB_PASSWORD": args.db_password,
        "DB_NAME": f"paim_{args.corpus}",
        "PAIM_AUTH_MODE": "dev",
        "CHROMA_PERSIST_DIR": str(state_dir / "chroma"),
    })
    os.environ.pop("DEV_USER_ID", None)
    sys.path.insert(0, str(repo))

    from fastapi import HTTPException
    from backend.api.query import QueryRequest, execute_project_query

    project_id = int((state_dir / "project_id").read_text(encoding="utf-8"))
    questions = json.loads(
        (here / "questions.json").read_text(encoding="utf-8")
    )["questions"]
    selected = [item for item in questions if item["corpus"] == args.corpus]

    records: list[dict[str, Any]] = []
    for index, item in enumerate(selected, 1):
        payload: dict[str, Any] = {}
        status, error, attempts = 500, None, 0
        started = time.perf_counter()
        while attempts < max(1, args.max_attempts):
            attempts += 1
            try:
                payload = execute_project_query(
                    project_id,
                    QueryRequest(
                        question=item["user_input"],
                        history=item.get("history") or [],
                        attachments=[],
                    ),
                )
                status, error = 200, None
                break
            except HTTPException as exc:
                status, error = exc.status_code, str(exc.detail)
            except Exception as exc:
                status, error = 500, f"{type(exc).__name__}: {exc}"
            if attempts < args.max_attempts:
                time.sleep(min(2**attempts, 5))

        debug = payload.get("debug") or {}
        records.append({
            "id": item["id"],
            "corpus": item["corpus"],
            "family": item["family"],
            "question": item["user_input"],
            "project_id": project_id,
            "run_at": datetime.now(timezone.utc).isoformat(),
            "http_status": status,
            "attempts": attempts,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "error": error,
            "answer": payload.get("answer") or "",
            "sources": payload.get("sources") or [],
            "route": payload.get("route") or debug.get("route"),
            "actual_tools": debug.get("tools_used") or [],
            "tool_calls": debug.get("tool_calls") or [],
            "debug": debug,
        })
        print(
            f"[{args.corpus} {index:02d}/{len(selected)}] {item['id']} "
            f"status={status} tools={'+'.join(records[-1]['actual_tools']) or 'none'} "
            f"latency={records[-1]['latency_ms']:.0f}ms",
            flush=True,
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        text=True,
    ).strip()
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"],
        cwd=repo,
        text=True,
    ).strip()
    working_tree_dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=repo,
            text=True,
        ).strip()
    )
    args.output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dataset_id": "routing_v2",
                "corpus": args.corpus,
                "branch": branch,
                "commit": commit,
                "working_tree_dirty": working_tree_dirty,
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
