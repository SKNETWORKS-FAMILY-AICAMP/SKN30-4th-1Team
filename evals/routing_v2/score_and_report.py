#!/usr/bin/env python3
"""Score routing_v2 outputs and write JSON, CSV, and Markdown reports."""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import subprocess
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field


HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
CAPABILITIES = {
    "hybrid_search": ("search_hybrid_vector_rag", None),
    "structured_state": ("query_sql_state", {"list", "count"}),
    "overview": ("query_sql_state", {"overview"}),
}


class Judgment(BaseModel):
    verdict: Literal["PASS", "PARTIAL", "FAIL"]
    confidence: float = Field(ge=0, le=1)
    matched_facts: list[str]
    missing_facts: list[str]
    contradictions: list[str]
    rationale: str


JUDGE_INSTRUCTIONS = """당신은 프로젝트 Q&A의 독립 채점자입니다.
질문, 기준 답변, 필수 사실, 금지 주장과 실제 답변만 비교하세요.
- PASS: 필수 사실을 모두 충족하고 질문에 직접 답하며 중대한 오류가 없음.
- PARTIAL: 핵심 방향은 맞지만 필수 사실 일부가 빠졌거나 표현이 불완전함.
- FAIL: 핵심 수치·담당자·인과관계가 틀림, 금지 주장을 함, 답할 수 있는데 기권함.
표현이 달라도 의미가 같으면 인정하세요. 기준 답변 밖의 스타일은 채점하지 마세요.
Tool 선택은 별도로 채점하므로 답변 판정에 섞지 마세요. 한국어로 짧고 구체적으로 쓰세요."""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reuse-judgments",
        action="store_true",
        help="Reuse judgments from results/current_scored.json.",
    )
    return parser.parse_args()


def _call_matches(call: dict, capability: str) -> bool:
    tool, operations = CAPABILITIES[capability]
    if call.get("name") != tool:
        return False
    if operations is None:
        return True
    return (call.get("args") or {}).get("operation") in operations


def _tool_contract(question: dict, record: dict) -> dict:
    calls = record.get("tool_calls") or []
    required = question["required_capabilities"]
    allowed = question["allowed_capabilities"]
    expected = question.get("expected_arguments") or {}
    checks = {
        "api_success": record.get("http_status") == 200 and not record.get("error"),
        "required_capabilities": all(
            any(_call_matches(call, capability) for call in calls)
            for capability in required
        ),
        "allowed_capabilities": all(
            any(_call_matches(call, capability) for capability in allowed)
            for call in calls
        ),
        "tool_rounds": (
            type((record.get("debug") or {}).get("tool_rounds")) is int
            and (record.get("debug") or {}).get("tool_rounds")
            <= question["max_tool_rounds"]
        ),
    }
    argument_checks = {}
    for capability, expected_args in expected.items():
        argument_checks[capability] = any(
            _call_matches(call, capability)
            and all(
                (call.get("args") or {}).get(key) == value
                for key, value in expected_args.items()
            )
            for call in calls
        )
    checks["expected_arguments"] = all(argument_checks.values())
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "argument_checks": argument_checks,
    }


def _judge_one(client: OpenAI, question: dict, golden: dict, record: dict) -> dict:
    prompt = json.dumps(
        {
            "question": question["user_input"],
            "reference_answer": golden["reference_answer"],
            "required_facts": golden["required_facts"],
            "forbidden_claims": golden["forbidden_claims"],
            "actual_answer": record["answer"],
        },
        ensure_ascii=False,
    )
    parsed = client.responses.parse(
        model=os.getenv("ROUTING_V2_JUDGE_MODEL", "gpt-4.1"),
        instructions=JUDGE_INSTRUCTIONS,
        input=prompt,
        text_format=Judgment,
        temperature=0,
        store=False,
    ).output_parsed
    if parsed is None:
        raise RuntimeError("judge returned no parsed output")
    return parsed.model_dump()


def _percentile_95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * 0.95 + 0.9999)))
    return ordered[index]


def _clean_markdown_text(value: object) -> str:
    """Remove source trailing spaces without changing report line structure."""
    return "\n".join(line.rstrip() for line in str(value or "").splitlines())


def main() -> int:
    args = _parse_args()
    load_dotenv(HERE.parents[1] / ".env")
    questions = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))[
        "questions"
    ]
    golden = json.loads((HERE / "golden.json").read_text(encoding="utf-8"))["items"]
    question_by_id = {item["id"]: item for item in questions}
    golden_by_id = {item["id"]: item for item in golden}

    records = []
    for corpus in ("csbot", "modu"):
        payload = json.loads(
            (RESULTS / f"current_{corpus}.json").read_text(encoding="utf-8")
        )
        records.extend(payload["records"])
    record_by_id = {item["id"]: item for item in records}
    if set(record_by_id) != set(question_by_id) or set(record_by_id) != set(golden_by_id):
        raise RuntimeError("questions, golden, and actual output IDs do not match")

    judgments: dict[str, dict]
    if args.reuse_judgments:
        previous = json.loads(
            (RESULTS / "current_scored.json").read_text(encoding="utf-8")
        )
        judgments = {
            item["id"]: item["judgment"] for item in previous["records"]
        }
        if set(judgments) != set(record_by_id):
            raise RuntimeError("saved judgment IDs do not match current outputs")
        print(f"[judge] reused {len(judgments)} saved judgments", flush=True)
    else:
        client = OpenAI(timeout=120, max_retries=3)
        judgments = {}
        with ThreadPoolExecutor(max_workers=6) as executor:
            pending = {
                executor.submit(
                    _judge_one,
                    client,
                    question_by_id[item_id],
                    golden_by_id[item_id],
                    record_by_id[item_id],
                ): item_id
                for item_id in sorted(record_by_id)
            }
            for completed, future in enumerate(as_completed(pending), 1):
                item_id = pending[future]
                try:
                    judgments[item_id] = future.result()
                except Exception as exc:
                    judgments[item_id] = {
                        "verdict": "FAIL",
                        "confidence": 0.0,
                        "matched_facts": [],
                        "missing_facts": golden_by_id[item_id]["required_facts"],
                        "contradictions": [],
                        "rationale": f"Judge error: {type(exc).__name__}: {exc}",
                    }
                print(
                    f"[judge {completed:02d}/{len(pending)}] {item_id} "
                    f"{judgments[item_id]['verdict']}",
                    flush=True,
                )

    state_validation_path = RESULTS / "current_state_validation.json"
    state_validation = (
        json.loads(state_validation_path.read_text(encoding="utf-8"))
        if state_validation_path.exists()
        else None
    )
    drift_by_id: dict[str, list[dict]] = defaultdict(list)
    if state_validation:
        for drift in state_validation.get("golden_count_drift") or []:
            for item_id in drift.get("affected_ids") or []:
                drift_by_id[item_id].append(drift)

    scored = []
    for item_id in [item["id"] for item in questions]:
        record = record_by_id[item_id]
        scored.append({
            **record,
            "reference_answer": golden_by_id[item_id]["reference_answer"],
            "required_facts": golden_by_id[item_id]["required_facts"],
            "tool_contract": _tool_contract(question_by_id[item_id], record),
            "judgment": judgments[item_id],
            "golden_state_drift": drift_by_id.get(item_id, []),
        })

    verdicts = Counter(item["judgment"]["verdict"] for item in scored)
    latencies = [float(item["latency_ms"]) for item in scored]
    summary = {
        "dataset_id": "routing_v2",
        "branch": "feat/이동욱-프롬프트_수정",
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=HERE.parents[1],
            text=True,
        ).strip(),
        "working_tree_dirty": bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"],
                cwd=HERE.parents[1],
                text=True,
            ).strip()
        ),
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "total": len(scored),
        "api_success": sum(item["http_status"] == 200 for item in scored),
        "tool_contract_pass": sum(
            item["tool_contract"]["passed"] for item in scored
        ),
        "answer_verdicts": dict(verdicts),
        "strict_answer_accuracy": verdicts["PASS"] / len(scored),
        "pass_or_partial": (verdicts["PASS"] + verdicts["PARTIAL"]) / len(scored),
        "latency_ms": {
            "average": round(statistics.mean(latencies), 1),
            "median": round(statistics.median(latencies), 1),
            "p95": round(_percentile_95(latencies), 1),
            "maximum": round(max(latencies), 1),
        },
    }
    adjusted_verdicts = verdicts.copy()
    state_aligned_failures = []
    if state_validation:
        for item_id in state_validation.get(
            "strict_failures_matching_current_state"
        ) or []:
            if judgments.get(item_id, {}).get("verdict") == "FAIL":
                adjusted_verdicts["FAIL"] -= 1
                adjusted_verdicts["PASS"] += 1
                state_aligned_failures.append(item_id)
        summary["state_validation"] = state_validation
        summary["current_state_adjusted_diagnostic"] = {
            "answer_verdicts": {
                verdict: adjusted_verdicts[verdict]
                for verdict in ("PASS", "PARTIAL", "FAIL")
            },
            "strict_answer_accuracy": adjusted_verdicts["PASS"] / len(scored),
            "pass_or_partial": (
                adjusted_verdicts["PASS"] + adjusted_verdicts["PARTIAL"]
            ) / len(scored),
            "reclassified_ids": state_aligned_failures,
            "official_score": False,
        }

    family_rows = defaultdict(list)
    corpus_rows = defaultdict(list)
    for item in scored:
        family_rows[item["family"]].append(item)
        corpus_rows[item["corpus"]].append(item)

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "current_scored.json").write_text(
        json.dumps(
            {"summary": summary, "records": scored},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (RESULTS / "current_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (RESULTS / "current_per_question.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "id", "corpus", "family", "question", "http_status", "latency_ms",
            "tools", "tool_contract", "answer_verdict", "answer",
            "reference_answer", "rationale", "golden_state_drift",
        ])
        for item in scored:
            writer.writerow([
                item["id"],
                item["corpus"],
                item["family"],
                item["question"],
                item["http_status"],
                item["latency_ms"],
                "+".join(item["actual_tools"]),
                "PASS" if item["tool_contract"]["passed"] else "FAIL",
                item["judgment"]["verdict"],
                item["answer"],
                item["reference_answer"],
                item["judgment"]["rationale"],
                "; ".join(
                    f"{drift['field']}: {drift['golden']}->{drift['current_state']}"
                    for drift in item["golden_state_drift"]
                ),
            ])

    lines = [
        "# routing_v2 현재 브랜치 평가 보고서",
        "",
        f"- 브랜치: `{summary['branch']}`",
        f"- 커밋: `{summary['commit']}`",
        f"- 문항: {summary['total']}개",
        f"- API 성공: {summary['api_success']}/{summary['total']}",
        (
            f"- Tool 계약: {summary['tool_contract_pass']}/{summary['total']} "
            f"({summary['tool_contract_pass'] / summary['total']:.1%})"
        ),
        (
            f"- 답변: PASS {verdicts['PASS']} / PARTIAL {verdicts['PARTIAL']} / "
            f"FAIL {verdicts['FAIL']}"
        ),
        f"- 엄격 정확도(PASS): {summary['strict_answer_accuracy']:.1%}",
        f"- 핵심 방향 포함(PASS+PARTIAL): {summary['pass_or_partial']:.1%}",
        (
            "- 지연시간: 평균 {average:.1f}ms / 중앙 {median:.1f}ms / "
            "p95 {p95:.1f}ms / 최대 {maximum:.1f}ms"
        ).format(**summary["latency_ms"]),
    ]
    adjusted = summary.get("current_state_adjusted_diagnostic")
    if adjusted:
        adjusted_counts = adjusted["answer_verdicts"]
        lines.extend([
            (
                "- 현재 상태 보정 진단(공식 점수 아님): "
                f"PASS {adjusted_counts['PASS']} / "
                f"PARTIAL {adjusted_counts['PARTIAL']} / "
                f"FAIL {adjusted_counts['FAIL']}"
            ),
            "",
            "## 판정 해석",
            "",
            (
                "엄격 점수는 `golden.json`을 그대로 기준으로 유지했다. 다만 현재 "
                "격리 DB의 활성 레코드 수와 golden 사이에 아래 드리프트가 확인됐다."
            ),
            "",
            "| 필드 | golden | 현재 DB | 관련 문항 |",
            "|---|---:|---:|---|",
        ])
        for drift in state_validation["golden_count_drift"]:
            lines.append(
                f"| {drift['field']} | {drift['golden']} | "
                f"{drift['current_state']} | "
                f"{', '.join(drift['affected_ids'])} |"
            )
        lines.extend([
            "",
            (
                f"{', '.join(f'`{item_id}`' for item_id in adjusted['reclassified_ids'])}"
                "의 답변은 현재 count 도구 결과와 일치한다. 따라서 해당 엄격 FAIL은 라우팅/생성 "
                "실패가 아니라 golden과 실행 상태의 불일치다."
            ),
            (
                "해당 문항만 현재 상태에 맞춰 재분류하면 "
                f"PASS {adjusted_counts['PASS']} / "
                f"PARTIAL {adjusted_counts['PARTIAL']} / "
                f"FAIL {adjusted_counts['FAIL']}"
                f"({adjusted['strict_answer_accuracy']:.1%}, "
                f"PASS+PARTIAL {adjusted['pass_or_partial']:.1%})이다. "
                "이 값은 데이터 드리프트 해석용이며 공식 golden 점수는 아니다."
            ),
        ])
    lines.extend([
        "",
        "## 유형별",
        "",
        "| 유형 | 문항 | API 성공 | Tool PASS | 답변 P/P/F | 평균 지연 |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for family in ("hybrid_search", "structured_state", "overview"):
        rows = family_rows[family]
        counts = Counter(item["judgment"]["verdict"] for item in rows)
        lines.append(
            f"| {family} | {len(rows)} | "
            f"{sum(item['http_status'] == 200 for item in rows)}/{len(rows)} | "
            f"{sum(item['tool_contract']['passed'] for item in rows)}/{len(rows)} | "
            f"{counts['PASS']}/{counts['PARTIAL']}/{counts['FAIL']} | "
            f"{statistics.mean(float(item['latency_ms']) for item in rows):.1f}ms |"
        )

    lines.extend([
        "",
        "## 코퍼스별",
        "",
        "| 코퍼스 | 문항 | Tool PASS | 답변 P/P/F | 평균 지연 |",
        "|---|---:|---:|---:|---:|",
    ])
    for corpus in ("csbot", "modu"):
        rows = corpus_rows[corpus]
        counts = Counter(item["judgment"]["verdict"] for item in rows)
        lines.append(
            f"| {corpus} | {len(rows)} | "
            f"{sum(item['tool_contract']['passed'] for item in rows)}/{len(rows)} | "
            f"{counts['PASS']}/{counts['PARTIAL']}/{counts['FAIL']} | "
            f"{statistics.mean(float(item['latency_ms']) for item in rows):.1f}ms |"
        )

    non_pass = [
        item
        for item in scored
        if not item["tool_contract"]["passed"]
        or item["judgment"]["verdict"] != "PASS"
    ]
    lines.extend(["", "## PASS가 아닌 문항", ""])
    if not non_pass:
        lines.append("- 없음")
    for item in non_pass:
        lines.extend([
            (
                f"### {item['id']} · Tool "
                f"{'PASS' if item['tool_contract']['passed'] else 'FAIL'} · "
                f"답변 {item['judgment']['verdict']}"
            ),
            "",
            f"- 질문: {_clean_markdown_text(item['question'])}",
            f"- 실제 답변: {_clean_markdown_text(item['answer'])}",
            f"- 기준 답변: {_clean_markdown_text(item['reference_answer'])}",
            f"- 판정: {_clean_markdown_text(item['judgment']['rationale'])}",
        ])
        for drift in item["golden_state_drift"]:
            lines.append(
                f"- 상태 확인: `{drift['field']}`는 golden "
                f"{drift['golden']}건, 현재 DB {drift['current_state']}건"
            )
        lines.append("")

    lines.extend([
        "## 산출물",
        "",
        "- `CURRENT_BRANCH_REPORT.html`: 실제 답변과 golden이 포함된 자체 완결 비교 화면",
        "- `CURRENT_BRANCH_REPORT.md`: 요약·문항별 판정 보고서",
        "- `results/`: runner 재실행 시 생성되는 로컬 원시 응답·채점 중간 산출물",
        "",
        "답변 평가는 `gpt-4.1` 구조화 Judge를 temperature 0으로 실행했다.",
    ])
    (HERE / "CURRENT_BRANCH_REPORT.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
