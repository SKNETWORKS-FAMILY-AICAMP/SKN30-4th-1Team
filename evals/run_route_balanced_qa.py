#!/usr/bin/env python3
"""Run the current PaiM agentic Q&A path on one route-balanced corpus."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from prepare_route_balanced_eval import CORPORA, database_name


CATEGORY_LABELS = {
    "decision": "결정",
    "action": "액션",
    "issue": "이슈",
    "risk": "리스크",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", required=True, type=Path)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--corpus", required=True, choices=CORPORA)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--db-host", default="127.0.0.1")
    parser.add_argument("--db-port", default="3316")
    parser.add_argument("--db-user", default="root")
    parser.add_argument("--db-password", default="eval")
    parser.add_argument("--max-attempts", type=int, default=2)
    return parser.parse_args()


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[^0-9a-z가-힣%]+", "", text)


def score_tooling(item: dict, debug: dict) -> dict:
    expected = item["expected"]
    required = set(expected["required_tools"])
    allowed = set(expected["allowed_tools"])
    actual_tools = set(debug.get("tools_used") or [])
    actual_calls = debug.get("tool_calls") or []
    call_checks = []

    for expected_call in expected.get("tool_calls") or []:
        name = expected_call["name"]
        required_args = expected_call.get("args_required") or {}
        candidates = [call for call in actual_calls if call.get("name") == name]
        matched = next((
            call for call in candidates
            if all((call.get("args") or {}).get(key) == value for key, value in required_args.items())
        ), None)
        call_checks.append({
            "name": name,
            "required_args": required_args,
            "args_semantics": expected_call.get("args_semantics"),
            "matched_required_args": matched is not None,
            "actual_candidates": candidates,
        })

    rounds = int(debug.get("tool_rounds") or 0)
    max_rounds = int(expected.get("max_tool_rounds") or 0)
    tool_selection_pass = required.issubset(actual_tools) and actual_tools.issubset(allowed)
    exact_args_pass = all(
        check["matched_required_args"]
        for check in call_checks
        if check["required_args"]
    )
    return {
        "required_tools": sorted(required),
        "allowed_tools": sorted(allowed),
        "actual_tools": sorted(actual_tools),
        "tool_selection_pass": tool_selection_pass,
        "tool_call_checks": call_checks,
        "exact_args_pass": exact_args_pass,
        "semantic_args_need_review": any(check["args_semantics"] for check in call_checks),
        "tool_rounds": rounds,
        "max_tool_rounds": max_rounds,
        "rounds_pass": rounds <= max_rounds,
        "extra_tool_calls": max(0, len(actual_calls) - len(expected.get("tool_calls") or [])),
    }


def score_answer_contract(item: dict, answer: str) -> dict:
    contract = item["expected"]["answer_contract"]
    answer_norm = normalize(answer)
    contract_type = contract["type"]
    required = (
        contract.get("required_items")
        or contract.get("required_facts")
        or contract.get("required_terms")
        or []
    )
    matched = [term for term in required if normalize(term) in answer_norm]
    missing = [term for term in required if term not in matched]

    if contract_type == "exact_count":
        expected_count = int(contract["exact_count"])
        numeric_tokens = [int(value) for value in re.findall(r"(?<![\d.])\d+(?![\d.])", answer)]
        passed = expected_count in numeric_tokens
    elif contract_type == "overview_facts":
        passed = len(matched) >= int(contract.get("min_required_facts", len(required)))
    else:
        passed = not missing

    count_checks = []
    for category, count in (contract.get("category_counts") or {}).items():
        label = CATEGORY_LABELS[category]
        ok = normalize(f"{label} {count}") in answer_norm
        count_checks.append({"category": category, "count": count, "matched": ok})

    return {
        "type": contract_type,
        "strict_text_pass": passed,
        "matched": matched,
        "missing": missing,
        "category_count_checks": count_checks,
        "must_abstain": bool(contract.get("must_abstain")),
    }


def main() -> int:
    args = parse_args()
    repo = Path(__file__).resolve().parents[1]
    dataset_dir = args.dataset_dir.resolve()
    state_dir = args.state_dir.resolve() / args.corpus
    if not (state_dir / "manifest.json").exists():
        raise RuntimeError(f"prepared state not found: {state_dir}")

    load_dotenv(repo / ".env")
    os.environ.update({
        "DB_HOST": args.db_host,
        "DB_PORT": str(args.db_port),
        "DB_USER": args.db_user,
        "DB_PASSWORD": args.db_password,
        "DB_NAME": database_name(args.corpus),
        "PAIM_AUTH_MODE": "dev",
        "CHROMA_PERSIST_DIR": str(state_dir / "chroma"),
    })
    os.environ.pop("DEV_USER_ID", None)
    sys.path.insert(0, str(repo))

    from fastapi import HTTPException
    from backend.api.query import QueryRequest, query

    golden = json.loads((dataset_dir / "route_balanced_golden.json").read_text(encoding="utf-8"))
    questions = [item for item in golden["items"] if item["corpus"] == args.corpus]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")

    with temporary.open("w", encoding="utf-8") as handle:
        for index, item in enumerate(questions, start=1):
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
                except Exception as exc:
                    status = 500
                    error = f"{type(exc).__name__}: {exc}"
                if attempts < args.max_attempts:
                    time.sleep(min(2 ** attempts, 5))

            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            debug = payload.get("debug") or {}
            answer = payload.get("answer") or ""
            record = {
                "id": item["id"],
                "corpus": item["corpus"],
                "family": item["family"],
                "question": item["question"],
                "reference_answer": item["reference_answer"],
                "gold_sources": item.get("gold_sources") or [],
                "expected": item["expected"],
                "run_at": datetime.now(timezone.utc).isoformat(),
                "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                "http_status": status,
                "attempts": attempts,
                "latency_ms": elapsed_ms,
                "error": error,
                "answer": answer,
                "sources": payload.get("sources") or [],
                "route": payload.get("route") or debug.get("route"),
                "debug": debug,
                "tool_score": score_tooling(item, debug),
                "answer_contract_score": score_answer_contract(item, answer),
            }
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            handle.flush()
            tools = "+".join(debug.get("tools_used") or []) or "none"
            print(
                f"[{args.corpus} {index:02d}/{len(questions)}] {item['id']} "
                f"status={status} tools={tools} rounds={debug.get('tool_rounds')} "
                f"latency={elapsed_ms:.0f}ms",
                flush=True,
            )

    temporary.replace(args.output)
    print(f"[완료] {args.corpus}: {len(questions)}문항 → {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
