"""Agentic Q&A v2 실행, 계약 검사, RAGAS 채점과 비교 파이프라인."""

from __future__ import annotations

import argparse
import asyncio
import base64
import importlib.machinery
import importlib.metadata
import json
import math
import os
import re
import statistics
import sys
import time
import types
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CAPABILITY_TO_TOOL = {
    "hybrid_search": "search_project_evidence",
    "structured_state": "query_structured_memory",
    "overview": "get_project_overview",
}
RAGAS_METRICS = {
    "context_precision",
    "context_recall",
    "faithfulness",
    "answer_correctness",
    "response_relevancy",
}
ABSTENTION_MARKERS = ("확인할 수 없", "확인되지 않", "알 수 없", "근거가 없")


def _read_json(path: Path) -> dict:
    """UTF-8 JSON 객체를 읽는다."""
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict) -> None:
    """평가 결과를 임시 파일을 거쳐 원자적으로 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


def _normalize_text(value: Any) -> str:
    """검색어와 비교 문자열을 유니코드·공백·대소문자 기준으로 정규화한다."""
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).split()).casefold()


def _normalize_value(value: Any) -> Any:
    """중복 Tool 인자 비교를 위해 중첩 값을 결정론적으로 정규화한다."""
    if isinstance(value, str):
        return _normalize_text(value)
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_value(value[key]) for key in sorted(value)}
    return value


def _source_name(value: Any) -> str:
    """운영체제 경로 구분자와 무관하게 출처 파일명만 반환한다."""
    return str(value or "").replace("\\", "/").rsplit("/", 1)[-1]


def _check(name: str, passed: bool, detail: Any = None) -> dict:
    """계약 검사 한 건을 공통 형식으로 만든다."""
    return {"name": name, "passed": bool(passed), "detail": detail}


def score_contract(question: dict, golden: dict, record: dict) -> dict:
    """한 실행 결과가 이슈의 결정론 계약을 만족하는지 검사한다."""
    debug = record.get("debug") or {}
    calls = debug.get("tool_calls") or []
    actual_tools = {call.get("name") for call in calls if call.get("name")}
    required_tools = {
        CAPABILITY_TO_TOOL[name] for name in question["required_capabilities"]
    }
    allowed_tools = {
        CAPABILITY_TO_TOOL[name] for name in question["allowed_capabilities"]
    }
    checks = [
        _check("api_success", record.get("http_status") == 200 and not record.get("error")),
        _check("required_tools", required_tools <= actual_tools, {
            "required": sorted(required_tools), "actual": sorted(actual_tools)
        }),
        _check("allowed_tools", actual_tools <= allowed_tools, {
            "allowed": sorted(allowed_tools), "actual": sorted(actual_tools)
        }),
    ]

    rounds = int(debug.get("tool_rounds") or 0)
    checks.extend([
        _check("question_tool_rounds", rounds <= question["max_tool_rounds"], rounds),
        _check("global_tool_rounds", rounds <= 5, rounds),
    ])

    canonical_calls = [
        json.dumps(
            {"name": call.get("name"), "args": _normalize_value(call.get("args") or {})},
            ensure_ascii=False,
            sort_keys=True,
        )
        for call in calls
    ]
    checks.append(_check(
        "duplicate_tool_calls",
        len(canonical_calls) == len(set(canonical_calls)),
        canonical_calls,
    ))

    expected_args = question.get("expected_arguments") or {}
    if expected_args:
        expected_tool = next(iter(required_tools), None)
        args_match = any(
            call.get("name") == expected_tool
            and all((call.get("args") or {}).get(key) == value for key, value in expected_args.items())
            for call in calls
        )
        checks.append(_check("expected_arguments", args_match, expected_args))

    expected_history = question.get("expected_history_mode")
    if expected_history is not None:
        checks.append(_check(
            "history_mode",
            debug.get("history_mode") is expected_history,
            {"expected": expected_history, "actual": debug.get("history_mode")},
        ))

    if CAPABILITY_TO_TOOL["hybrid_search"] in actual_tools:
        queries = debug.get("multi_queries") or []
        normalized = [_normalize_text(query) for query in queries]
        checks.extend([
            _check("query_count", 1 <= len(queries) <= 4, len(queries)),
            _check("query_nonempty", all(normalized), queries),
            _check("query_deduplicated", len(normalized) == len(set(normalized)), queries),
            _check(
                "original_question_preserved",
                _normalize_text(question["user_input"]) in normalized,
                queries,
            ),
        ])

    expected_sources = {_source_name(value) for value in golden["expected_sources"]}
    actual_sources = {_source_name(value) for value in record.get("sources") or []}
    checks.append(_check(
        "source_boundary",
        actual_sources <= expected_sources,
        {"expected": sorted(expected_sources), "actual": sorted(actual_sources)},
    ))

    required_evidence = set(question["required_evidence_kinds"])
    actual_evidence = set()
    if debug.get("tool_sources"):
        actual_evidence.add("project")
    if debug.get("attachments"):
        actual_evidence.add("attachment")
    checks.append(_check(
        "required_evidence",
        required_evidence <= actual_evidence,
        {"required": sorted(required_evidence), "actual": sorted(actual_evidence)},
    ))

    answer = str(record.get("answer") or "")
    deterministic = golden.get("deterministic_answer")
    if question["family"] == "structured_count":
        expected = deterministic["exact_count"]
        numbers = [int(value) for value in re.findall(r"(?<![\d.])\d+(?![\d.])", answer)]
        checks.append(_check("exact_count", expected in numbers, expected))
    elif question["family"] == "structured_list":
        required_items = deterministic["required_items"]
        missing = [item for item in required_items if _normalize_text(item) not in _normalize_text(answer)]
        checks.append(_check("required_items", not missing, missing))
    elif question["family"] == "abstention":
        normalized_answer = _normalize_text(answer)
        forbidden = [
            claim for claim in golden["answer_contract"]["forbidden_claims"]
            if _normalize_text(claim) and _normalize_text(claim) in normalized_answer
        ]
        checks.extend([
            _check("must_abstain", any(marker in answer for marker in ABSTENTION_MARKERS)),
            _check("forbidden_claims", not forbidden, forbidden),
        ])

    return {"passed": all(item["passed"] for item in checks), "checks": checks}


def performance_metrics(record: dict) -> dict:
    """실행 결과에서 비용 비교용 호출 수와 지연 시간을 계산한다."""
    debug = record.get("debug") or {}
    calls = debug.get("tool_calls") or []
    rounds = int(debug.get("tool_rounds") or 0)
    limited = any(
        result.get("status") == "tool_limit"
        for result in debug.get("tool_results") or []
    )
    return {
        "latency_ms": record.get("latency_ms"),
        "tool_calls": len(calls),
        "tool_rounds": rounds,
        "llm_calls": rounds + 1 + int(limited),
    }


def _configure_runtime(args: argparse.Namespace) -> dict:
    """동결된 한 코퍼스 상태를 현재 평가 프로세스에 연결한다."""
    state_dir = args.state_root.resolve() / args.corpus
    manifest_path = state_dir / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"prepared state not found: {manifest_path}")
    manifest = _read_json(manifest_path)
    if args.db_port == 3306:
        raise RuntimeError("development MySQL port 3306 cannot be used for evaluation")

    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
    os.environ.update({
        "DB_HOST": args.db_host,
        "DB_PORT": str(args.db_port),
        "DB_USER": args.db_user,
        "DB_PASSWORD": args.db_password,
        "DB_NAME": manifest["database"],
        "PAIM_AUTH_MODE": "dev",
        "PAIM_QUERY_ROUTING_MODE": "agentic",
        "CHROMA_PERSIST_DIR": str(state_dir / "chroma"),
        "CHROMA_COLLECTION_NAME": manifest["chroma_collection_name"],
    })
    if args.model:
        os.environ["OPENAI_MODEL"] = args.model
    os.environ.pop("DEV_USER_ID", None)
    return manifest


def _attachment_models(items: list[dict]) -> list[Any]:
    """질문셋의 inline 텍스트 첨부를 실제 API 첨부 모델로 변환한다."""
    from backend.api.query import QueryAttachment

    return [
        QueryAttachment(
            filename=item["filename"],
            content_base64=base64.b64encode(
                item["content_text"].encode("utf-8")
            ).decode("ascii"),
        )
        for item in items
    ]


def _evaluation_request(project_id: int):
    """실제 query 데코레이터가 요구하는 로컬 HTTP 요청 객체를 만든다."""
    from starlette.requests import Request

    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": f"/api/v1/projects/{project_id}/query",
        "raw_path": f"/api/v1/projects/{project_id}/query".encode("ascii"),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 0),
        "server": ("127.0.0.1", 80),
        "root_path": "",
    })


def run_questions(args: argparse.Namespace) -> dict:
    """동결 상태에서 실제 query 엔드포인트 함수를 문항당 한 번 성공시킨다."""
    manifest = _configure_runtime(args)
    questions_data = _read_json(args.questions)
    golden_data = _read_json(args.golden)
    golden_by_id = {item["id"]: item for item in golden_data["items"]}
    questions = [
        item for item in questions_data["questions"]
        if item["corpus"] == args.corpus and item["split"] == args.split
    ]
    if not questions:
        raise RuntimeError("selected question set is empty")

    from fastapi import HTTPException
    from backend.api.query import QueryRequest, query
    from backend.retriever.qa_tools import capture_retrieved_contexts_for_evaluation

    records = []
    project_id = manifest.get("project_id", 1)
    for index, item in enumerate(questions, 1):
        payload: dict[str, Any] = {}
        contexts: list[str] = []
        error = None
        status = 500
        attempts = 0
        started = time.perf_counter()
        while attempts < max(1, args.max_attempts):
            attempts += 1
            try:
                with capture_retrieved_contexts_for_evaluation() as captured:
                    payload = query(
                        _evaluation_request(project_id),
                        project_id,
                        QueryRequest(
                            question=item["user_input"],
                            history=item["history"],
                            attachments=_attachment_models(item["attachments"]),
                        ),
                    )
                contexts = list(captured) + [
                    attachment["content_text"] for attachment in item["attachments"]
                ]
                status = 200
                error = None
                break
            except HTTPException as exc:
                status = exc.status_code
                error = str(exc.detail)
            except Exception as exc:  # pragma: no cover - 외부 LLM/DB 실행 경계
                error = f"{type(exc).__name__}: {exc}"
            if attempts < args.max_attempts:
                time.sleep(min(2 ** attempts, 5))

        debug = payload.get("debug") or {}
        record = {
            "id": item["id"],
            "corpus": item["corpus"],
            "split": item["split"],
            "family": item["family"],
            "user_input": item["user_input"],
            "ragas_metrics": item["ragas_metrics"],
            "run_at": datetime.now(timezone.utc).isoformat(),
            "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            "http_status": status,
            "attempts": attempts,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "error": error,
            "answer": payload.get("answer") or "",
            "plan": payload.get("plan") or [],
            "sources": payload.get("sources") or [],
            "route": payload.get("route") or debug.get("route"),
            "debug": debug,
            "retrieved_contexts": contexts,
        }
        record["contract"] = score_contract(item, golden_by_id[item["id"]], record)
        record["performance"] = performance_metrics(record)
        records.append(record)
        print(
            f"[{index:02d}/{len(questions):02d}] {item['id']} "
            f"status={status} contract={record['contract']['passed']}",
            flush=True,
        )

    return {
        "schema_version": 1,
        "dataset_id": questions_data["dataset_id"],
        "label": args.label,
        "corpus": args.corpus,
        "split": args.split,
        "manifest": manifest,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "contract_summary": {
            "passed": sum(record["contract"]["passed"] for record in records),
            "total": len(records),
            "all_passed": all(record["contract"]["passed"] for record in records),
        },
        "records": records,
    }


def _install_ragas_vertexai_shim() -> None:
    """RAGAS 0.4.3이 제거된 VertexAI 모듈을 import하는 호환 문제만 우회한다."""
    name = "langchain_community.chat_models.vertexai"
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__spec__ = importlib.machinery.ModuleSpec(name, None)
    module.ChatVertexAI = type("ChatVertexAI", (), {})
    sys.modules[name] = module


async def _score_ragas_records(
    records: list[dict],
    golden_by_id: dict[str, dict],
    judge: str,
    embedding_model: str,
    workers: int,
) -> None:
    """RAGAS 다섯 지표를 문항별 적용 목록에 따라 한 번씩 채점한다."""
    _install_ragas_vertexai_shim()
    os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")

    from openai import AsyncOpenAI
    from ragas.embeddings.base import embedding_factory
    from ragas.llms import llm_factory
    from ragas.metrics.collections import (
        AnswerCorrectness,
        AnswerRelevancy,
        ContextPrecision,
        ContextRecall,
        Faithfulness,
    )

    client = AsyncOpenAI(max_retries=10)
    llm = llm_factory(judge, client=client, max_tokens=4096)
    embeddings = embedding_factory(
        "openai", model=embedding_model, client=client
    )
    scorers = {
        "context_precision": ContextPrecision(llm=llm),
        "context_recall": ContextRecall(llm=llm),
        "faithfulness": Faithfulness(llm=llm),
        "answer_correctness": AnswerCorrectness(llm=llm, embeddings=embeddings),
        "response_relevancy": AnswerRelevancy(llm=llm, embeddings=embeddings),
    }
    semaphore = asyncio.Semaphore(max(1, workers))

    async def score_one(record: dict, metric_name: str) -> tuple[str, float]:
        golden = golden_by_id[record["id"]]
        common = {
            "user_input": record["user_input"],
            "response": record["answer"],
            "reference": golden["reference_answer"],
            "retrieved_contexts": record["retrieved_contexts"],
        }
        required = {
            "context_precision": ("user_input", "reference", "retrieved_contexts"),
            "context_recall": ("user_input", "reference", "retrieved_contexts"),
            "faithfulness": ("user_input", "response", "retrieved_contexts"),
            "answer_correctness": ("user_input", "response", "reference"),
            "response_relevancy": ("user_input", "response"),
        }[metric_name]
        if "retrieved_contexts" in required and not common["retrieved_contexts"]:
            raise RuntimeError(f"{record['id']}: {metric_name} requires retrieved contexts")
        async with semaphore:
            result = await scorers[metric_name].ascore(
                **{key: common[key] for key in required}
            )
        value = float(result.value)
        if not math.isfinite(value):
            raise RuntimeError(f"{record['id']}: {metric_name} returned {value}")
        return metric_name, round(value, 6)

    for record in records:
        unknown = set(record["ragas_metrics"]) - RAGAS_METRICS
        if unknown:
            raise RuntimeError(f"{record['id']}: unknown RAGAS metrics: {sorted(unknown)}")
        results = await asyncio.gather(*[
            score_one(record, metric_name)
            for metric_name in record["ragas_metrics"]
        ])
        record["ragas"] = dict(results)
        print(f"[RAGAS] {record['id']} {record['ragas']}", flush=True)


def _metric_summary(records: list[dict]) -> dict:
    """문항별 RAGAS 결과를 지표별 평균과 중앙값으로 요약한다."""
    summary = {}
    for metric in sorted(RAGAS_METRICS):
        values = [
            record["ragas"][metric]
            for record in records
            if metric in record.get("ragas", {})
        ]
        if values:
            summary[metric] = {
                "count": len(values),
                "mean": round(statistics.mean(values), 6),
                "median": round(statistics.median(values), 6),
            }
    return summary


def score_ragas(args: argparse.Namespace) -> dict:
    """저장된 실행 결과를 재호출하지 않고 RAGAS로 채점한다."""
    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
    run = _read_json(args.input)
    golden = _read_json(args.golden)
    if run["dataset_id"] != golden["dataset_id"]:
        raise RuntimeError("run and golden dataset_id do not match")
    golden_by_id = {item["id"]: item for item in golden["items"]}
    asyncio.run(_score_ragas_records(
        run["records"],
        golden_by_id,
        args.judge,
        args.embedding_model,
        args.workers,
    ))
    run["ragas_config"] = {
        "ragas_version": importlib.metadata.version("ragas"),
        "judge": args.judge,
        "embedding_model": args.embedding_model,
        "workers": args.workers,
    }
    run["ragas_summary"] = _metric_summary(run["records"])
    return run


def _p95(values: list[float]) -> float:
    """표본이 작아도 정의되는 nearest-rank 방식으로 p95를 계산한다."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def compare_runs(baseline: dict, candidate: dict) -> dict:
    """동일 문항 baseline과 candidate의 계약·품질·성능을 paired 비교한다."""
    if (
        baseline["dataset_id"],
        baseline["corpus"],
        baseline["split"],
    ) != (
        candidate["dataset_id"],
        candidate["corpus"],
        candidate["split"],
    ):
        raise RuntimeError("baseline and candidate scopes do not match")
    baseline_by_id = {record["id"]: record for record in baseline["records"]}
    candidate_by_id = {record["id"]: record for record in candidate["records"]}
    if list(baseline_by_id) != list(candidate_by_id):
        raise RuntimeError("baseline and candidate question IDs do not match")
    for record in baseline["records"] + candidate["records"]:
        expected = set(record.get("ragas_metrics") or [])
        if expected != set(record.get("ragas") or {}):
            raise RuntimeError(f"{record['id']}: run must be fully RAGAS-scored before compare")

    pairs = []
    for item_id, before in baseline_by_id.items():
        after = candidate_by_id[item_id]
        metric_deltas = {
            metric: round(after["ragas"][metric] - before["ragas"][metric], 6)
            for metric in sorted(set(before.get("ragas", {})) & set(after.get("ragas", {})))
        }
        pairs.append({
            "id": item_id,
            "contract_passed": after["contract"]["passed"],
            "ragas_delta": metric_deltas,
            "latency_delta_ms": round(after["latency_ms"] - before["latency_ms"], 1),
            "tool_calls_delta": (
                after["performance"]["tool_calls"] - before["performance"]["tool_calls"]
            ),
        })

    ragas = {}
    for metric in sorted(RAGAS_METRICS):
        values = [
            pair["ragas_delta"][metric] for pair in pairs
            if metric in pair["ragas_delta"]
        ]
        if values:
            ragas[metric] = {
                "count": len(values),
                "mean_delta": round(statistics.mean(values), 6),
                "improved": sum(value > 0 for value in values),
                "tied": sum(value == 0 for value in values),
                "regressed": sum(value < 0 for value in values),
            }

    semantic_before = [
        record["latency_ms"] for record in baseline["records"]
        if record["family"] == "semantic"
    ]
    semantic_after = [
        record["latency_ms"] for record in candidate["records"]
        if record["family"] == "semantic"
    ]
    before_tool_mean = statistics.mean(
        record["performance"]["tool_calls"] for record in baseline["records"]
    )
    after_tool_mean = statistics.mean(
        record["performance"]["tool_calls"] for record in candidate["records"]
    )
    split = candidate["split"]
    ragas_pass = all(
        value["mean_delta"] >= (
            0.03 if split == "dev" and metric == "context_precision"
            else (-0.02 if split == "dev" else 0.0)
        )
        for metric, value in ragas.items()
    )
    performance = {
        "semantic_p95_baseline_ms": _p95(semantic_before),
        "semantic_p95_candidate_ms": _p95(semantic_after),
        "semantic_p95_passed": _p95(semantic_after) <= _p95(semantic_before) * 1.10,
        "tool_calls_mean_baseline": round(before_tool_mean, 6),
        "tool_calls_mean_candidate": round(after_tool_mean, 6),
        "tool_calls_passed": after_tool_mean <= before_tool_mean + 0.25,
    }
    contract_pass = all(pair["contract_passed"] for pair in pairs)
    return {
        "schema_version": 1,
        "dataset_id": baseline["dataset_id"],
        "corpus": baseline["corpus"],
        "split": split,
        "passed": (
            contract_pass
            and ragas_pass
            and performance["semantic_p95_passed"]
            and performance["tool_calls_passed"]
        ),
        "contract_passed": contract_pass,
        "ragas_passed": ragas_pass,
        "ragas": ragas,
        "performance": performance,
        "pairs": pairs,
    }


def parse_args() -> argparse.Namespace:
    """평가 파이프라인 서브커맨드 인자를 구성한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    run = subcommands.add_parser("run", help="질문 실행과 계약 평가")
    run.add_argument("--state-root", required=True, type=Path)
    run.add_argument("--corpus", required=True, choices=("modu", "csbot"))
    run.add_argument("--split", default="dev", choices=("dev", "final"))
    run.add_argument("--label", required=True)
    run.add_argument("--output", required=True, type=Path)
    run.add_argument("--questions", type=Path, default=HERE / "questions.json")
    run.add_argument("--golden", type=Path, default=HERE / "golden.json")
    run.add_argument("--db-host", default="127.0.0.1")
    run.add_argument("--db-port", type=int, default=3316)
    run.add_argument("--db-user", default="root")
    run.add_argument("--db-password", default="eval")
    run.add_argument("--model")
    run.add_argument("--max-attempts", type=int, default=2)

    score = subcommands.add_parser("score", help="저장된 실행 결과 RAGAS 채점")
    score.add_argument("--input", required=True, type=Path)
    score.add_argument("--output", required=True, type=Path)
    score.add_argument("--golden", type=Path, default=HERE / "golden.json")
    score.add_argument("--judge", default="gpt-4.1-mini")
    score.add_argument("--embedding-model", default="text-embedding-3-small")
    score.add_argument("--workers", type=int, default=4)

    compare = subcommands.add_parser("compare", help="baseline/candidate 비교")
    compare.add_argument("--baseline", required=True, type=Path)
    compare.add_argument("--candidate", required=True, type=Path)
    compare.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    """선택한 평가 단계를 실행하고 결과를 저장한다."""
    args = parse_args()
    if args.command == "run":
        result = run_questions(args)
    elif args.command == "score":
        result = score_ragas(args)
    else:
        result = compare_runs(_read_json(args.baseline), _read_json(args.candidate))
    _write_json(args.output, result)
    print(f"[완료] {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
