"""Agentic Q&A v2 실행, 계약 검사, RAGAS 채점과 비교 파이프라인."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import importlib.machinery
import importlib.metadata
import json
import math
import os
import statistics
import sys
import time
import types
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PUBLIC_DEV_QUESTIONS = HERE / "questions.json"
PUBLIC_DEV_GOLDEN = HERE / "golden.json"
CAPABILITY_PREDICATES = {
    "hybrid_search": {
        "tool": "search_hybrid_vector_rag",
        "operations": None,
    },
    "structured_state": {
        "tool": "query_sql_state",
        "operations": frozenset({"list", "count"}),
    },
    "overview": {
        "tool": "query_sql_state",
        "operations": frozenset({"overview"}),
    },
}
INLINE_TEXT_ATTACHMENT_SUFFIXES = frozenset({
    ".csv", ".json", ".log", ".md", ".txt", ".xml", ".yaml", ".yml",
})
RAGAS_METRICS = {
    "context_precision",
    "context_recall",
    "faithfulness",
    "answer_correctness",
    "response_relevancy",
}
COMPARISON_INVARIANT_FIELDS = (
    "schema_version",
    "questions_sha256",
    "golden_sha256",
    "manifest",
    "run_config",
    "ragas_config",
)
ANSWER_VERDICTS = frozenset({"affirmed", "denied", "absent", "uncertain"})
RAW_OUTPUT_FIELDS = (
    "run_at",
    "model",
    "http_status",
    "attempts",
    "latency_ms",
    "error",
    "answer",
    "plan",
    "sources",
    "route",
    "debug",
    "retrieved_contexts",
)


class _JudgeVerdictItem(BaseModel):
    """Judge가 반환할 단일 의미 판정."""

    model_config = ConfigDict(extra="forbid", strict=True)

    target_id: str
    verdict: Literal["affirmed", "denied", "absent", "uncertain"]


class _JudgeVerdictSet(BaseModel):
    """문항 하나의 모든 의미 판정."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    targets: list[_JudgeVerdictItem]


def _is_repository_path(path: Path) -> bool:
    """경로가 공개 저장소 내부를 가리키는지 확인한다."""
    try:
        path.resolve().relative_to(REPO.resolve())
    except ValueError:
        return False
    return True


def _paths_refer_to_same_file(left: Path, right: Path) -> bool:
    """존재 여부와 무관하게 alias를 잡고, 존재하면 hard link도 잡는다."""
    if left.resolve() == right.resolve():
        return True
    try:
        return left.samefile(right)
    except OSError:
        return False


def _resolve_run_questions_path(
    split: str,
    questions: Path | None,
) -> Path:
    """개발 질문 기본값을 적용하고 final 질문은 외부 잠금 파일만 허용한다."""
    questions_path = questions or PUBLIC_DEV_QUESTIONS
    if split == "final":
        if questions is None:
            raise RuntimeError("final split requires explicit external --questions")
        if _is_repository_path(questions_path):
            raise RuntimeError("final questions must be locked outside the repository")
    return questions_path


def _resolve_score_dataset_paths(
    split: str,
    questions: Path | None,
    golden: Path | None,
) -> tuple[Path, Path]:
    """채점은 질문 계약과 골든을 함께 읽고 final에서는 둘 다 외부 잠금한다."""
    questions_path = questions or PUBLIC_DEV_QUESTIONS
    golden_path = golden or PUBLIC_DEV_GOLDEN
    if _paths_refer_to_same_file(questions_path, golden_path):
        raise RuntimeError("questions and golden must be separate files")
    if split == "final":
        if questions is None or golden is None:
            raise RuntimeError(
                "final score requires explicit external --questions and --golden"
            )
        if _is_repository_path(questions_path) or _is_repository_path(golden_path):
            raise RuntimeError(
                "final questions and golden must be locked outside the repository"
            )
    return questions_path, golden_path


def _read_json(path: Path) -> dict:
    """UTF-8 JSON 객체를 읽는다."""
    return json.loads(path.read_text(encoding="utf-8"))


def _validated_unique_items(value: Any, label: str) -> list[dict]:
    """ID가 있는 JSON 객체 목록만 받고 중복 ID를 fail-closed로 거부한다."""
    if type(value) is not list:
        raise RuntimeError(f"{label} must be a list")
    seen: set[str] = set()
    result: list[dict] = []
    for index, item in enumerate(value):
        if type(item) is not dict:
            raise RuntimeError(f"{label}[{index}] must be an object")
        item_id = item.get("id")
        if type(item_id) is not str or not item_id.strip():
            raise RuntimeError(f"{label}[{index}] must have a nonempty string id")
        if item_id in seen:
            raise RuntimeError(f"duplicate {label} id: {item_id}")
        seen.add(item_id)
        result.append(item)
    return result


def _write_json(path: Path, value: dict) -> None:
    """평가 결과를 임시 파일을 거쳐 원자적으로 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256_json(value: Any) -> str:
    """형식과 키 순서에 무관한 canonical JSON SHA-256을 계산한다."""
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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


def _canonical_source_id(value: Any) -> str:
    """경로 정보를 버리지 않고 출처 ID의 구분자와 유니코드만 정규화한다."""
    if type(value) is not str:
        return ""
    normalized = unicodedata.normalize("NFKC", value.strip()).replace(
        "\\", "/"
    )
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _validated_source_ids(
    value: Any,
    field: str,
) -> tuple[set[str], list[str]]:
    """출처 목록의 타입과 canonical identity 충돌을 엄격히 검증한다."""
    if type(value) is not list:
        return set(), [f"{field} must be a list"]
    result: set[str] = set()
    errors: list[str] = []
    for index, item in enumerate(value):
        canonical = _canonical_source_id(item)
        if not canonical:
            errors.append(f"{field}[{index}] must be a nonempty string")
            continue
        if canonical in result:
            errors.append(
                f"{field}[{index}] duplicates canonical source {canonical}"
            )
            continue
        result.add(canonical)
    return result, errors


def _call_matches_capability(call: dict, capability: str) -> bool:
    """Tool 이름과 operation을 함께 사용해 역할 충족 여부를 판정한다."""
    try:
        predicate = CAPABILITY_PREDICATES[capability]
    except KeyError as exc:
        raise RuntimeError(f"unknown capability: {capability}") from exc
    if call.get("name") != predicate["tool"]:
        return False
    operations = predicate["operations"]
    if operations is None:
        return True
    return (call.get("args") or {}).get("operation") in operations


def _canonical_tool_call(call: dict) -> str:
    """실제 공개 Tool schema로 검증·기본값 적용 후 호출을 canonicalize한다."""
    name = call.get("name")
    from backend.agentic_graph import QA_TOOLS

    tool = {item.name: item for item in QA_TOOLS}.get(name)
    if tool is None:
        raise ValueError(f"unknown Tool schema: {name}")
    validated = tool.tool_call_schema.model_validate(call.get("args") or {})
    args = validated.model_dump(mode="json", exclude_none=False)
    return json.dumps(
        {"name": name, "args": _normalize_value(args)},
        ensure_ascii=False,
        sort_keys=True,
    )


def _expected_argument_contracts(
    question: dict,
) -> tuple[list[tuple[str, dict]], str | None]:
    """명시적 capability에 Tool 인자 계약을 결합한다."""
    expected = question.get("expected_arguments") or {}
    if not expected:
        return [], None
    if all(
        key in CAPABILITY_PREDICATES and isinstance(value, dict)
        for key, value in expected.items()
    ):
        return list(expected.items()), None

    capability = question.get("expected_arguments_capability")
    if capability is None:
        required = list(dict.fromkeys(question.get("required_capabilities") or []))
        if len(required) != 1:
            return [], (
                "flat expected_arguments requires expected_arguments_capability "
                "when more than one capability is required"
            )
        capability = required[0]
    if capability not in CAPABILITY_PREDICATES:
        return [], f"unknown expected_arguments_capability: {capability}"
    return [(capability, expected)], None


def _answer_verdict_targets(question: dict, golden: dict) -> list[dict]:
    """골든 계약을 언어와 무관한 judge target 목록으로 변환한다."""
    answer_contract = golden.get("answer_contract") or {}
    deterministic = golden.get("deterministic_answer") or {}
    targets = []
    for index, fact in enumerate(answer_contract.get("required_facts") or []):
        targets.append({
            "target_id": f"required_fact:{index}",
            "kind": "required_fact",
            "value": fact,
        })
    for index, fact in enumerate(answer_contract.get("forbidden_claims") or []):
        targets.append({
            "target_id": f"forbidden_claim:{index}",
            "kind": "forbidden_claim",
            "value": fact,
        })
    for index, fact in enumerate(answer_contract.get("unsupported_claims") or []):
        targets.append({
            "target_id": f"unsupported_claim:{index}",
            "kind": "unsupported_claim",
            "value": fact,
        })
    if question["family"] == "structured_count":
        targets.append({
            "target_id": "exact_count:0",
            "kind": "exact_count",
            "value": deterministic["exact_count"],
        })
    elif question["family"] == "structured_list":
        for index, item in enumerate(deterministic["required_items"]):
            targets.append({
                "target_id": f"required_item:{index}",
                "kind": "required_item",
                "value": item,
            })
    if question["family"] == "abstention" or question.get("must_abstain"):
        targets.append({
            "target_id": "abstention:0",
            "kind": "abstention",
            "value": True,
        })
    return targets


def _accepted_verdicts(kind: str) -> frozenset[str]:
    """계약 target 종류별 통과 가능한 정확한 verdict 집합을 반환한다."""
    if kind in {"forbidden_claim", "unsupported_claim"}:
        return frozenset({"denied", "absent"})
    return frozenset({"affirmed"})


def _validated_answer_verdicts(
    value: Any,
    targets: list[dict],
) -> tuple[dict[str, str], str | None]:
    """주입된 judge 결과의 타입·키·순서·enum을 정확히 검증한다."""
    if type(value) is not dict or set(value) != {"schema_version", "targets"}:
        return {}, "answer verdict must contain exactly schema_version and targets"
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        return {}, "answer verdict schema_version must be integer 1"
    items = value["targets"]
    if type(items) is not list:
        return {}, "answer verdict targets must be a list"
    expected_ids = [target["target_id"] for target in targets]
    actual_ids = []
    verdicts = {}
    for item in items:
        if type(item) is not dict or set(item) != {"target_id", "verdict"}:
            return {}, "each answer verdict must contain exactly target_id and verdict"
        target_id = item["target_id"]
        verdict = item["verdict"]
        if type(target_id) is not str or type(verdict) is not str:
            return {}, "answer verdict target_id and verdict must be strings"
        if verdict not in ANSWER_VERDICTS:
            return {}, f"invalid answer verdict: {verdict}"
        actual_ids.append(target_id)
        verdicts[target_id] = verdict
    if actual_ids != expected_ids:
        return {}, (
            "answer verdict target IDs/order do not match contract: "
            f"expected={expected_ids}, actual={actual_ids}"
        )
    return verdicts, None


def _question_attachment_source_ids(question: dict) -> set[str]:
    """요청 첨부의 중복 occurrence까지 반영한 canonical source ID를 만든다."""
    result = set()
    occurrences: dict[str, int] = {}
    attachments = question.get("attachments") or []
    if type(attachments) is not list:
        return result
    for item in attachments:
        if type(item) is not dict or type(item.get("filename")) is not str:
            continue
        filename = Path(item["filename"].replace("\\", "/")).name
        if not filename:
            continue
        occurrence_key = filename.casefold()
        occurrence = occurrences.get(occurrence_key, 0) + 1
        occurrences[occurrence_key] = occurrence
        occurrence_label = (
            filename if occurrence == 1 else f"{filename}#{occurrence}"
        )
        source_location = f"attachment:{occurrence_label}"
        canonical = _canonical_source_id(source_location)
        if canonical:
            result.add(canonical)
    return result


def _successful_attachment_source_ids(debug: dict, question: dict) -> set[str]:
    """추출 성공 debug source_location을 요청 첨부 source와 정확히 결합한다."""
    requested = _question_attachment_source_ids(question)
    successful = {
        _canonical_source_id(item.get("source_location"))
        for item in debug.get("attachment_evidence") or []
        if type(item) is dict
        and item.get("extraction_status") == "ok"
        and type(item.get("source_location")) is str
    }
    return requested & successful


def _has_successful_project_evidence(debug: dict) -> bool:
    """서버가 센 project 문맥과 실제 모델 문맥을 함께 요구한다."""
    project = ((debug.get("evidence") or {}).get("project") or {})
    model_context_count = project.get("model_context_count")
    return (
        project.get("has_substantive_evidence") is True
        and type(model_context_count) is int
        and model_context_count > 0
        and len(_model_contexts(debug)) >= model_context_count
    )


def _check(name: str, passed: bool, detail: Any = None) -> dict:
    """계약 검사 한 건을 공통 형식으로 만든다."""
    return {"name": name, "passed": bool(passed), "detail": detail}


def score_contract(question: dict, golden: dict, record: dict) -> dict:
    """한 실행 결과가 이슈의 결정론 계약을 만족하는지 검사한다."""
    debug = record.get("debug") or {}
    calls = debug.get("tool_calls") or []
    required_capabilities = list(dict.fromkeys(
        question.get("required_capabilities") or []
    ))
    allowed_capabilities = list(dict.fromkeys(
        question.get("allowed_capabilities") or []
    ))
    missing_capabilities = [
        capability
        for capability in required_capabilities
        if not any(_call_matches_capability(call, capability) for call in calls)
    ]
    disallowed_calls = [
        {
            "name": call.get("name"),
            "operation": (call.get("args") or {}).get("operation"),
        }
        for call in calls
        if not any(
            _call_matches_capability(call, capability)
            for capability in allowed_capabilities
        )
    ]
    checks = [
        _check("api_success", record.get("http_status") == 200 and not record.get("error")),
        _check(
            "required_capabilities",
            not missing_capabilities,
            {"required": required_capabilities, "missing": missing_capabilities},
        ),
        _check(
            "allowed_capabilities",
            not disallowed_calls,
            {"allowed": allowed_capabilities, "disallowed": disallowed_calls},
        ),
    ]

    raw_rounds = debug.get("tool_rounds", 0)
    rounds_valid = type(raw_rounds) is int and raw_rounds >= 0
    rounds = raw_rounds if rounds_valid else 0
    checks.extend([
        _check("tool_rounds_schema", rounds_valid, raw_rounds),
        _check(
            "question_tool_rounds",
            rounds_valid and rounds <= question["max_tool_rounds"],
            raw_rounds,
        ),
        _check("global_tool_rounds", rounds_valid and rounds <= 5, raw_rounds),
    ])

    canonical_calls = []
    tool_schema_errors = []
    for index, call in enumerate(calls):
        try:
            canonical_calls.append(_canonical_tool_call(call))
        except (TypeError, ValueError) as exc:
            tool_schema_errors.append({
                "index": index,
                "name": call.get("name"),
                "error": str(exc),
            })
            canonical_calls.append(json.dumps(
                {
                    "name": call.get("name"),
                    "args": _normalize_value(call.get("args") or {}),
                },
                ensure_ascii=False,
                sort_keys=True,
            ))
    checks.append(_check(
        "tool_call_schema",
        not tool_schema_errors,
        tool_schema_errors,
    ))
    checks.append(_check(
        "duplicate_tool_calls",
        len(canonical_calls) == len(set(canonical_calls)),
        canonical_calls,
    ))
    project_evidence = ((debug.get("evidence") or {}).get("project") or {})
    project_tool_called = any(
        _call_matches_capability(call, capability)
        for call in calls
        for capability in CAPABILITY_PREDICATES
    )
    has_attachments = bool(question.get("attachments"))
    checks.append(_check(
        "attachment_project_lookup",
        not has_attachments or (
            not tool_schema_errors
            and project_tool_called
            and project_evidence.get("lookup_completed") is True
        ),
        {
            "has_attachments": has_attachments,
            "project_tool_called": project_tool_called,
            "lookup_completed": project_evidence.get("lookup_completed"),
        },
    ))

    argument_contracts, argument_error = _expected_argument_contracts(question)
    if argument_error:
        checks.append(_check(
            "expected_arguments_binding",
            False,
            argument_error,
        ))
    for capability, expected_args in argument_contracts:
        args_match = any(
            _call_matches_capability(call, capability)
            and all(
                _normalize_value((call.get("args") or {}).get(key))
                == _normalize_value(value)
                for key, value in expected_args.items()
            )
            for call in calls
        )
        checks.append(_check(
            f"expected_arguments:{capability}",
            args_match,
            expected_args,
        ))

    expected_history = question.get("expected_history_mode")
    if expected_history is not None:
        checks.append(_check(
            "history_mode",
            debug.get("history_mode") is expected_history,
            {"expected": expected_history, "actual": debug.get("history_mode")},
        ))

    if any(
        _call_matches_capability(call, "hybrid_search") for call in calls
    ):
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

    expected_sources, expected_source_errors = _validated_source_ids(
        golden.get("expected_sources"),
        "golden.expected_sources",
    )
    actual_sources, actual_source_errors = _validated_source_ids(
        record.get("sources"),
        "record.sources",
    )
    project_source_ids, project_source_errors = _validated_source_ids(
        project_evidence.get("source_ids", []),
        "debug.evidence.project.source_ids",
    )
    project_source_errors.extend(
        f"project source uses reserved attachment namespace: {source_id}"
        for source_id in project_source_ids
        if source_id.startswith("attachment:")
    )
    source_identity_errors = (
        expected_source_errors
        + actual_source_errors
        + project_source_errors
    )
    checks.append(_check(
        "source_identity_schema",
        not source_identity_errors,
        source_identity_errors,
    ))
    required_evidence = set(question["required_evidence_kinds"])
    attachment_source_ids = _successful_attachment_source_ids(debug, question)
    project_evidence_succeeded = (
        not project_source_errors
        and bool(project_source_ids)
        and _has_successful_project_evidence(debug)
    )
    actual_evidence = set()
    if project_evidence_succeeded:
        actual_evidence.add("project")
    if attachment_source_ids:
        actual_evidence.add("attachment")
    successful_source_ids = set(attachment_source_ids)
    if project_evidence_succeeded:
        successful_source_ids |= project_source_ids
    checks.append(_check(
        "source_boundary",
        not source_identity_errors
        and actual_sources == expected_sources
        and expected_sources <= successful_source_ids
        and (not required_evidence or bool(actual_sources)),
        {
            "expected": sorted(expected_sources),
            "actual": sorted(actual_sources),
            "successful_evidence": sorted(actual_evidence),
            "successful_sources": sorted(successful_source_ids),
        },
    ))

    checks.append(_check(
        "required_evidence",
        required_evidence <= actual_evidence,
        {"required": sorted(required_evidence), "actual": sorted(actual_evidence)},
    ))

    verdict_targets = _answer_verdict_targets(question, golden)
    verdicts, verdict_error = _validated_answer_verdicts(
        record.get("answer_verdicts"),
        verdict_targets,
    )
    checks.append(_check(
        "answer_verdict_schema",
        verdict_error is None,
        verdict_error,
    ))

    def add_verdict_check(name: str, kinds: set[str], *, always: bool = False) -> None:
        selected = [
            target for target in verdict_targets if target["kind"] in kinds
        ]
        if not selected and not always:
            return
        detail = [{
            "target_id": target["target_id"],
            "expected": sorted(_accepted_verdicts(target["kind"])),
            "actual": verdicts.get(target["target_id"]),
        } for target in selected]
        checks.append(_check(
            name,
            verdict_error is None and all(
                verdicts[target["target_id"]]
                in _accepted_verdicts(target["kind"])
                for target in selected
            ),
            detail,
        ))

    add_verdict_check("required_facts", {"required_fact"})
    add_verdict_check(
        "unsupported_claims",
        {"forbidden_claim", "unsupported_claim"},
        always=True,
    )
    add_verdict_check("exact_count", {"exact_count"})
    add_verdict_check("required_items", {"required_item"})
    add_verdict_check("must_abstain", {"abstention"})

    return {"passed": all(item["passed"] for item in checks), "checks": checks}


def performance_metrics(record: dict) -> dict:
    """실행 결과에서 비용 비교용 호출 수와 지연 시간을 계산한다."""
    debug = record.get("debug") or {}
    calls = debug.get("tool_calls") or []
    rounds = debug.get("tool_rounds", 0)
    if type(rounds) is not int or rounds < 0:
        raise RuntimeError("tool_rounds must be a nonnegative integer")
    limited = any(
        result.get("status") == "tool_limit"
        for result in debug.get("tool_results") or []
    )
    return {
        "latency_ms": record.get("latency_ms"),
        "tool_calls": len(calls),
        "tool_rounds": rounds,
        "llm_calls": debug.get("llm_calls", rounds + 1 + int(limited)),
        "llm_tokens": (debug.get("llm_usage") or {}).get("total_tokens", 0),
    }


def _request_payload(item: dict, project_id: int) -> dict:
    """실제 서비스 호출 입력을 해시 가능한 형태로 고정한다."""
    return {
        "project_id": project_id,
        "question": item["user_input"],
        "history": item.get("history") or [],
        "attachments": item.get("attachments") or [],
    }


def _raw_output_payload(record: dict) -> dict:
    """계약·RAGAS 필드를 제외한 원시 실행 출력만 반환한다."""
    return {field: record.get(field) for field in RAW_OUTPUT_FIELDS}


def _raw_run_fingerprint(run: dict) -> dict:
    """seal 자체를 제외한 원시 실행 전체를 fingerprint 입력으로 반환한다."""
    return {
        key: value
        for key, value in run.items()
        if key != "raw_run_sha256"
    }


def _seal_raw_run(run: dict) -> dict:
    """원시 실행을 후속 채점 전에 변조 감지 가능하게 봉인한다."""
    run["raw_run_sha256"] = _sha256_json(_raw_run_fingerprint(run))
    return run


def _verify_raw_run(run: dict, questions_data: dict) -> list[dict]:
    """질문 입력과 원시 출력 hash를 모두 재계산해 봉인을 검증한다."""
    if type(run.get("schema_version")) is not int or run["schema_version"] != 2:
        raise RuntimeError("score requires raw run schema_version 2")
    if run.get("phase") != "run":
        raise RuntimeError("score requires an unscored raw run")
    if any(
        key in run
        for key in (
            "contract_summary",
            "golden_sha256",
            "ragas_config",
            "ragas_summary",
            "scored_at",
        )
    ):
        raise RuntimeError("raw run contains score-phase feedback")
    if any(
        key in record
        for record in run.get("records") or []
        for key in ("answer_verdicts", "contract", "performance", "ragas")
    ):
        raise RuntimeError("raw run contains score-phase feedback")
    if run.get("dataset_id") != questions_data.get("dataset_id"):
        raise RuntimeError("run and questions dataset_id do not match")
    if run.get("questions_sha256") != _sha256_json(questions_data):
        raise RuntimeError("questions input hash does not match raw run")
    if run.get("raw_run_sha256") != _sha256_json(_raw_run_fingerprint(run)):
        raise RuntimeError("raw run seal does not match")

    all_questions = _validated_unique_items(
        questions_data.get("questions"),
        "question",
    )
    questions = [
        item for item in all_questions
        if item["corpus"] == run["corpus"] and item["split"] == run["split"]
    ]
    records = _validated_unique_items(run.get("records"), "raw record")
    if [record.get("id") for record in records] != [
        item.get("id") for item in questions
    ]:
        raise RuntimeError("raw run record IDs do not match questions")
    project_id = (run.get("manifest") or {}).get("project_id", 1)
    for item, record in zip(questions, records):
        expected_identity = {
            "id": item["id"],
            "corpus": item["corpus"],
            "split": item["split"],
            "family": item["family"],
            "user_input": item["user_input"],
            "ragas_metrics": item["ragas_metrics"],
        }
        actual_identity = {
            key: record.get(key) for key in expected_identity
        }
        if actual_identity != expected_identity:
            raise RuntimeError(f"{item['id']}: raw record identity changed")
        if record.get("question_sha256") != _sha256_json(item):
            raise RuntimeError(f"{item['id']}: question hash does not match")
        if record.get("input_sha256") != _sha256_json(
            _request_payload(item, project_id)
        ):
            raise RuntimeError(f"{item['id']}: request input hash does not match")
        if record.get("output_sha256") != _sha256_json(
            _raw_output_payload(record)
        ):
            raise RuntimeError(f"{item['id']}: raw output hash does not match")
    return questions


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

    attachments = []
    for item in items:
        filename = str(item["filename"])
        suffix = Path(filename).suffix.lower()
        if suffix not in INLINE_TEXT_ATTACHMENT_SUFFIXES:
            raise ValueError(
                f"inline evaluation attachment must be text: {filename}"
            )
        content = item.get("content_text")
        if not isinstance(content, str):
            raise ValueError(
                f"inline evaluation attachment requires content_text: {filename}"
            )
        attachments.append(QueryAttachment(
            filename=filename,
            content_base64=base64.b64encode(content.encode("utf-8")).decode(
                "ascii"
            ),
        ))
    return attachments


def _model_contexts(debug: dict) -> list[str]:
    """표준 debug.model_contexts에서 비어 있지 않은 문자열 문맥만 읽는다."""
    return [
        context
        for context in debug.get("model_contexts") or []
        if isinstance(context, str) and context.strip()
    ]


def run_questions(args: argparse.Namespace) -> dict:
    """질문만 읽어 서비스 함수를 실행하고 채점 없는 원시 결과를 봉인한다."""
    questions_path = _resolve_run_questions_path(args.split, args.questions)
    questions_data = _read_json(questions_path)
    all_questions = _validated_unique_items(
        questions_data.get("questions"),
        "question",
    )
    questions = [
        item for item in all_questions
        if item["corpus"] == args.corpus and item["split"] == args.split
    ]
    if not questions:
        raise RuntimeError("selected question set is empty")

    manifest = _configure_runtime(args)

    from fastapi import HTTPException
    from backend.api.query import QueryRequest, execute_project_query

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
                payload = execute_project_query(
                    project_id,
                    QueryRequest(
                        question=item["user_input"],
                        history=item.get("history") or [],
                        attachments=_attachment_models(
                            item.get("attachments") or []
                        ),
                    ),
                )
                debug = payload.get("debug") or {}
                contexts = _model_contexts(debug)
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
            "question_sha256": _sha256_json(item),
            "input_sha256": _sha256_json(_request_payload(item, project_id)),
        }
        record["output_sha256"] = _sha256_json(_raw_output_payload(record))
        records.append(record)
        print(
            f"[{index:02d}/{len(questions):02d}] {item['id']} "
            f"status={status}",
            flush=True,
        )

    return _seal_raw_run({
        "schema_version": 2,
        "phase": "run",
        "dataset_id": questions_data["dataset_id"],
        "questions_sha256": _sha256_json(questions_data),
        "label": args.label,
        "corpus": args.corpus,
        "split": args.split,
        "manifest": manifest,
        "run_config": {
            "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            "max_attempts": max(1, args.max_attempts),
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "records": records,
    })


async def _judge_answer_contracts(
    records: list[dict],
    question_by_id: dict[str, dict],
    golden_by_id: dict[str, dict],
    judge: str,
    workers: int,
) -> None:
    """같은 score judge로 답변의 최종 의미 입장을 structured verdict로 판정한다."""
    from openai import AsyncOpenAI

    instructions = """
You are a multilingual semantic adjudicator. Evaluate the final meaning of an
answer in whatever language it uses. For every target, return exactly one:
affirmed, denied, absent, or uncertain.

affirmed: the answer's final stance clearly endorses the target.
denied: the final stance rejects, retracts, replaces, or contradicts the target.
absent: the answer takes no stance on the target.
uncertain: the answer is ambiguous, hedged, merely quotes the target, or leaves
conflicting final claims.

Target kinds:
- required_fact, forbidden_claim, unsupported_claim: classify the proposition
  in value, considering its final semantic stance rather than word occurrence.
- exact_count: affirmed only when the single unambiguous final count equals
  value and no incompatible count remains; a replacement count is denied.
- required_item: affirmed only when value is included in the final result;
  explicit exclusion is denied.
- abstention: affirmed only when the final answer actually abstains because the
  evidence is insufficient; a negated or reversed abstention is denied.

Return the target IDs once, in the supplied order, with no rationale.
""".strip()
    client = AsyncOpenAI(max_retries=10)
    semaphore = asyncio.Semaphore(max(1, workers))

    async def judge_one(record: dict) -> None:
        item_id = record["id"]
        targets = _answer_verdict_targets(
            question_by_id[item_id],
            golden_by_id[item_id],
        )
        if not targets:
            record["answer_verdicts"] = {
                "schema_version": 1,
                "targets": [],
            }
            return
        async with semaphore:
            response = await client.responses.parse(
                model=judge,
                instructions=instructions,
                input=json.dumps(
                    {
                        "question": record["user_input"],
                        "answer": record["answer"],
                        "targets": targets,
                    },
                    ensure_ascii=False,
                ),
                text_format=_JudgeVerdictSet,
                temperature=0,
                max_output_tokens=2048,
                store=False,
            )
        parsed = response.output_parsed
        if parsed is None:
            raise RuntimeError(f"{item_id}: contract judge returned no verdict")
        value = parsed.model_dump(mode="json")
        _, error = _validated_answer_verdicts(value, targets)
        if error:
            raise RuntimeError(f"{item_id}: invalid contract judge verdict: {error}")
        record["answer_verdicts"] = value
        print(f"[CONTRACT JUDGE] {item_id}", flush=True)

    await asyncio.gather(*(judge_one(record) for record in records))


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
    """봉인된 원시 실행을 검증한 뒤 계약과 RAGAS를 한 번 채점한다."""
    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
    run = _read_json(args.input)
    questions_path, golden_path = _resolve_score_dataset_paths(
        run["split"],
        args.questions,
        args.golden,
    )
    questions_data = _read_json(questions_path)
    golden = _read_json(golden_path)
    questions = _verify_raw_run(run, questions_data)
    if run["dataset_id"] != golden.get("dataset_id"):
        raise RuntimeError("run and golden dataset_id do not match")
    golden_items = _validated_unique_items(golden.get("items"), "golden")
    golden_by_id = {item["id"]: item for item in golden_items}
    missing_golden = [
        item["id"] for item in questions if item["id"] not in golden_by_id
    ]
    if missing_golden:
        raise RuntimeError(f"golden entries missing: {missing_golden}")
    question_by_id = {item["id"]: item for item in questions}
    asyncio.run(_judge_answer_contracts(
        run["records"],
        question_by_id,
        golden_by_id,
        args.judge,
        args.workers,
    ))
    for record in run["records"]:
        item_id = record["id"]
        record["contract"] = score_contract(
            question_by_id[item_id],
            golden_by_id[item_id],
            record,
        )
        record["performance"] = performance_metrics(record)

    asyncio.run(_score_ragas_records(
        run["records"],
        golden_by_id,
        args.judge,
        args.embedding_model,
        args.workers,
    ))
    _metric_coverage(run)
    run["ragas_config"] = {
        "ragas_version": importlib.metadata.version("ragas"),
        "judge": args.judge,
        "embedding_model": args.embedding_model,
        "workers": args.workers,
    }
    run["phase"] = "scored"
    run["golden_sha256"] = _sha256_json(golden)
    run["scored_at"] = datetime.now(timezone.utc).isoformat()
    run["contract_summary"] = {
        "passed": sum(
            record["contract"]["passed"] for record in run["records"]
        ),
        "total": len(run["records"]),
        "all_passed": all(
            record["contract"]["passed"] for record in run["records"]
        ),
    }
    run["ragas_summary"] = _metric_summary(run["records"])
    return run


def _p95(values: list[float]) -> float:
    """표본이 작아도 정의되는 nearest-rank 방식으로 p95를 계산한다."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def _metric_coverage(run: dict) -> set[tuple[str, str]]:
    """알려진 다섯 지표가 완전 채점된 coverage만 허용한다."""
    coverage: set[tuple[str, str]] = set()
    for record in run.get("records") or []:
        metrics = record.get("ragas_metrics")
        if (
            type(metrics) is not list
            or any(type(metric) is not str for metric in metrics)
            or len(metrics) != len(set(metrics))
        ):
            raise RuntimeError(
                f"{record.get('id')}: RAGAS metrics must be unique strings"
            )
        scores = record.get("ragas")
        if type(scores) is not dict:
            raise RuntimeError(f"{record.get('id')}: RAGAS scores must be an object")
        expected = set(metrics)
        actual = set(scores)
        unknown = (expected | actual) - RAGAS_METRICS
        if unknown:
            raise RuntimeError(
                f"{record.get('id')}: unknown RAGAS metrics: {sorted(unknown)}"
            )
        if expected != actual:
            raise RuntimeError(
                f"{record['id']}: run must be fully RAGAS-scored before compare"
            )
        invalid_values = [
            metric
            for metric, value in scores.items()
            if type(value) not in (int, float) or not math.isfinite(value)
        ]
        if invalid_values:
            raise RuntimeError(
                f"{record['id']}: RAGAS scores must be finite numbers: "
                f"{sorted(invalid_values)}"
            )
        coverage.update((record["id"], metric) for metric in actual)
    if not coverage:
        raise RuntimeError("compare requires nonempty RAGAS metric coverage")
    covered_metrics = {metric for _, metric in coverage}
    if covered_metrics != RAGAS_METRICS:
        missing = sorted(RAGAS_METRICS - covered_metrics)
        raise RuntimeError(
            f"compare requires coverage for all RAGAS metrics; missing={missing}"
        )
    return coverage


def compare_runs(baseline: dict, candidate: dict) -> dict:
    """동일 문항 baseline과 candidate의 계약·품질·성능을 paired 비교한다."""
    if baseline.get("phase") != "scored" or candidate.get("phase") != "scored":
        raise RuntimeError("compare requires two scored runs")
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
    for field in COMPARISON_INVARIANT_FIELDS:
        if field not in baseline or field not in candidate:
            raise RuntimeError(f"comparison invariant is missing: {field}")
        if baseline[field] != candidate[field]:
            raise RuntimeError(f"comparison invariant does not match: {field}")
    if not baseline.get("records") or not candidate.get("records"):
        raise RuntimeError("baseline and candidate records must be nonempty")
    baseline_by_id = {record["id"]: record for record in baseline["records"]}
    candidate_by_id = {record["id"]: record for record in candidate["records"]}
    if len(baseline_by_id) != len(baseline["records"]) or len(
        candidate_by_id
    ) != len(candidate["records"]):
        raise RuntimeError("duplicate question IDs are not allowed")
    if list(baseline_by_id) != list(candidate_by_id):
        raise RuntimeError("baseline and candidate question IDs do not match")
    for item_id, before in baseline_by_id.items():
        after = candidate_by_id[item_id]
        for field in (
            "family",
            "user_input",
            "question_sha256",
            "input_sha256",
            "model",
        ):
            if not before.get(field) or not after.get(field):
                raise RuntimeError(
                    f"{item_id}: comparison record identity is missing: {field}"
                )
            if before[field] != after[field]:
                raise RuntimeError(
                    f"{item_id}: comparison record identity does not match: {field}"
                )
    baseline_coverage = _metric_coverage(baseline)
    candidate_coverage = _metric_coverage(candidate)
    if baseline_coverage != candidate_coverage:
        raise RuntimeError(
            "baseline and candidate RAGAS metric coverage must be identical"
        )

    pairs = []
    for item_id, before in baseline_by_id.items():
        after = candidate_by_id[item_id]
        metrics = sorted({
            metric for covered_id, metric in baseline_coverage
            if covered_id == item_id
        })
        metric_deltas = {
            metric: round(after["ragas"][metric] - before["ragas"][metric], 6)
            for metric in metrics
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
    if not semantic_before or not semantic_after:
        raise RuntimeError("compare requires semantic latency coverage")
    before_tool_mean = statistics.mean(
        record["performance"]["tool_calls"] for record in baseline["records"]
    )
    after_tool_mean = statistics.mean(
        record["performance"]["tool_calls"] for record in candidate["records"]
    )
    before_llm_mean = statistics.mean(
        record["performance"].get("llm_calls", 0) for record in baseline["records"]
    )
    after_llm_mean = statistics.mean(
        record["performance"].get("llm_calls", 0) for record in candidate["records"]
    )
    before_token_mean = statistics.mean(
        record["performance"].get("llm_tokens", 0) for record in baseline["records"]
    )
    after_token_mean = statistics.mean(
        record["performance"].get("llm_tokens", 0) for record in candidate["records"]
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
        "llm_calls_mean_baseline": round(before_llm_mean, 6),
        "llm_calls_mean_candidate": round(after_llm_mean, 6),
        "llm_tokens_mean_baseline": round(before_token_mean, 6),
        "llm_tokens_mean_candidate": round(after_token_mean, 6),
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

    run = subcommands.add_parser("run", help="질문 실행과 원시 결과 봉인")
    run.add_argument("--state-root", required=True, type=Path)
    run.add_argument("--corpus", required=True, choices=("modu", "csbot"))
    run.add_argument("--split", default="dev", choices=("dev", "final"))
    run.add_argument("--label", required=True)
    run.add_argument("--output", required=True, type=Path)
    run.add_argument(
        "--questions",
        type=Path,
        help="질문셋 경로. dev는 공개 기본값, final은 저장소 밖 잠금 파일 필수",
    )
    run.add_argument("--db-host", default="127.0.0.1")
    run.add_argument("--db-port", type=int, default=3316)
    run.add_argument("--db-user", default="root")
    run.add_argument("--db-password", default="eval")
    run.add_argument("--model")
    run.add_argument("--max-attempts", type=int, default=2)

    score = subcommands.add_parser(
        "score",
        help="봉인된 실행 결과의 결정론 계약과 RAGAS 채점",
    )
    score.add_argument("--input", required=True, type=Path)
    score.add_argument("--output", required=True, type=Path)
    score.add_argument(
        "--questions",
        type=Path,
        help="질문·계약 경로. dev는 공개 기본값, final은 저장소 밖 잠금 파일 필수",
    )
    score.add_argument(
        "--golden",
        type=Path,
        help="골든셋 경로. dev는 공개 기본값, final은 저장소 밖 잠금 파일 필수",
    )
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
