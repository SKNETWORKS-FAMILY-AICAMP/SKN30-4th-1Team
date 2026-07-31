import base64
import importlib
import json
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest

from evals.agentic_v2 import pipeline
from evals.agentic_v2.pipeline import (
    _attachment_models,
    _resolve_run_questions_path,
    _resolve_score_dataset_paths,
    _verify_raw_run,
    compare_runs,
    parse_args,
    run_questions,
    score_contract,
    score_ragas,
)


SEARCH_TOOL = "search_hybrid_vector_rag"
SQL_TOOL = "query_sql_state"
ALL_RAGAS_METRICS = [
    "context_precision",
    "context_recall",
    "faithfulness",
    "answer_correctness",
    "response_relevancy",
]


def _check(result: dict, name: str) -> dict:
    return next(item for item in result["checks"] if item["name"] == name)


def _question(
    *,
    family: str = "semantic",
    required_capabilities: list[str] | None = None,
    allowed_capabilities: list[str] | None = None,
    required_evidence_kinds: list[str] | None = None,
    attachments: list[dict] | None = None,
) -> dict:
    return {
        "id": "synthetic-1",
        "corpus": "modu",
        "split": "dev",
        "family": family,
        "user_input": "Alpha 상태를 알려줘",
        "required_capabilities": required_capabilities or [],
        "allowed_capabilities": allowed_capabilities or [],
        "max_tool_rounds": 2,
        "required_evidence_kinds": required_evidence_kinds or [],
        "attachments": attachments or [],
        "ragas_metrics": list(ALL_RAGAS_METRICS),
    }


def _golden(
    *,
    sources: list[str] | None = None,
    required_facts: list[str] | None = None,
    unsupported_claims: list[str] | None = None,
    deterministic: dict | None = None,
) -> dict:
    return {
        "id": "synthetic-1",
        "expected_sources": sources or [],
        "reference_answer": "Alpha",
        "answer_contract": {
            "required_facts": required_facts or [],
            "unsupported_claims": unsupported_claims or [],
            "forbidden_claims": [],
        },
        "deterministic_answer": deterministic or {},
    }


def _record(
    *,
    answer: str = "Alpha가 확인됩니다.",
    calls: list[dict] | None = None,
    tool_results: list[dict] | None = None,
    model_contexts: list[str] | None = None,
    sources: list[str] | None = None,
    multi_queries: list[str] | None = None,
    attachment_evidence: list[dict] | None = None,
    answer_verdicts: dict | None = None,
    project_source_ids: list[str] | None = None,
    project_lookup_completed: bool | None = None,
) -> dict:
    calls = calls or []
    tool_results = tool_results or []
    model_contexts = model_contexts or []
    sources = sources or []
    project_substantive = any(
        item.get("status") == "ok" for item in tool_results
    )
    if project_source_ids is None:
        project_source_ids = list(sources) if project_substantive else []
    return {
        "id": "synthetic-1",
        "family": "semantic",
        "http_status": 200,
        "error": None,
        "answer": answer,
        "sources": sources,
        "latency_ms": 10.0,
        "answer_verdicts": answer_verdicts or {
            "schema_version": 1,
            "targets": [],
        },
        "debug": {
            "tool_calls": calls,
            "tool_results": tool_results,
            "tool_rounds": len(calls),
            "multi_queries": multi_queries or [],
            "model_contexts": model_contexts,
            "attachment_evidence": attachment_evidence or [],
            "evidence": {
                "project": {
                    "lookup_completed": (
                        bool(calls)
                        if project_lookup_completed is None
                        else project_lookup_completed
                    ),
                    "has_substantive_evidence": project_substantive,
                    "model_context_count": (
                        len(model_contexts) if project_substantive else 0
                    ),
                    "source_ids": project_source_ids,
                },
            },
        },
    }


def _passing_verdicts(
    question: dict,
    golden: dict,
    overrides: dict[str, str] | None = None,
) -> dict:
    overrides = overrides or {}
    return {
        "schema_version": 1,
        "targets": [{
            "target_id": target["target_id"],
            "verdict": overrides.get(
                target["target_id"],
                (
                    "absent"
                    if target["kind"] in {
                        "forbidden_claim",
                        "unsupported_claim",
                    }
                    else "affirmed"
                ),
            ),
        } for target in pipeline._answer_verdict_targets(question, golden)],
    }


def _valid_search_case() -> tuple[dict, dict, dict]:
    question = _question(
        required_capabilities=["hybrid_search"],
        allowed_capabilities=["hybrid_search"],
        required_evidence_kinds=["project"],
    )
    question["expected_arguments"] = {
        "hybrid_search": {"query": question["user_input"]}
    }
    question["expected_history_mode"] = False
    record = _record(
        calls=[{
            "name": SEARCH_TOOL,
            "args": {"query": question["user_input"]},
        }],
        tool_results=[{"tool": SEARCH_TOOL, "status": "ok"}],
        model_contexts=["(출처: repo/docs/meeting.md) Alpha"],
        sources=["repo/docs/meeting.md"],
        multi_queries=[question["user_input"]],
    )
    record["debug"]["history_mode"] = False
    golden = _golden(
        sources=["repo/docs/meeting.md"],
        required_facts=["Alpha"],
    )
    record["answer_verdicts"] = _passing_verdicts(question, golden)
    return question, golden, record


def test_contract_accepts_valid_search_trace_and_rejects_duplicate_queries():
    question, golden, record = _valid_search_case()
    assert score_contract(question, golden, record)["passed"]

    duplicate = deepcopy(record)
    duplicate["debug"]["multi_queries"] = [
        question["user_input"],
        f"  {question['user_input'].lower()}  ",
    ]
    result = score_contract(question, golden, duplicate)
    assert not result["passed"]
    assert not _check(result, "query_deduplicated")["passed"]


def test_contract_verdict_schema_rejects_free_form_or_wrong_types():
    question, golden, record = _valid_search_case()
    with_rationale = deepcopy(record)
    with_rationale["answer_verdicts"]["targets"][0]["rationale"] = "free form"
    result = score_contract(question, golden, with_rationale)
    assert not _check(result, "answer_verdict_schema")["passed"]

    wrong_version_type = deepcopy(record)
    wrong_version_type["answer_verdicts"]["schema_version"] = True
    result = score_contract(question, golden, wrong_version_type)
    assert not _check(result, "answer_verdict_schema")["passed"]


@pytest.mark.parametrize("status", ["empty", "error"])
def test_project_evidence_requires_success_and_nonempty_model_context(status):
    question, golden, record = _valid_search_case()
    record["debug"]["tool_results"] = [{"tool": SEARCH_TOOL, "status": status}]
    record["debug"]["model_contexts"] = []
    record["debug"]["evidence"]["project"]["has_substantive_evidence"] = False

    result = score_contract(question, golden, record)
    assert not _check(result, "required_evidence")["passed"]


def test_attachment_evidence_requires_a_project_lookup_and_matching_source():
    attachments = [{"filename": "notes.txt", "content_text": "Alpha 근거"}]
    question = _question(
        family="attachment",
        required_capabilities=["hybrid_search"],
        allowed_capabilities=["hybrid_search"],
        required_evidence_kinds=["attachment"],
        attachments=attachments,
    )
    golden = _golden(
        sources=["attachment:notes.txt"],
        required_facts=["Alpha"],
    )
    record = _record(
        calls=[{
            "name": SEARCH_TOOL,
            "args": {"query": question["user_input"]},
        }],
        tool_results=[{"tool": SEARCH_TOOL, "status": "empty"}],
        sources=["attachment:notes.txt"],
        multi_queries=[question["user_input"]],
        attachment_evidence=[{
            "filename": "display-name.txt",
            "source_location": "attachment:notes.txt",
            "extraction_status": "ok",
        }],
        project_lookup_completed=True,
    )
    record["answer_verdicts"] = _passing_verdicts(question, golden)
    assert score_contract(question, golden, record)["passed"]

    zero_tool_question = deepcopy(question)
    zero_tool_question["required_capabilities"] = []
    zero_tool_question["allowed_capabilities"] = []
    zero_tool_question["max_tool_rounds"] = 0
    zero_tool_record = deepcopy(record)
    zero_tool_record["debug"]["tool_calls"] = []
    zero_tool_record["debug"]["tool_results"] = []
    zero_tool_record["debug"]["tool_rounds"] = 0
    zero_tool_record["debug"]["multi_queries"] = []
    zero_tool_record["debug"]["evidence"]["project"]["lookup_completed"] = False
    result = score_contract(zero_tool_question, golden, zero_tool_record)
    assert not result["passed"]
    assert not _check(result, "attachment_project_lookup")["passed"]

    for status in ("empty", "failed"):
        unsuccessful = deepcopy(record)
        unsuccessful["debug"]["attachment_evidence"][0][
            "extraction_status"
        ] = status
        assert not _check(
            score_contract(question, golden, unsuccessful),
            "required_evidence",
        )["passed"]


@pytest.mark.parametrize("invalid_rounds", [True, 1.0, "1", -1])
def test_performance_metrics_rejects_noncanonical_tool_rounds(invalid_rounds):
    record = _record()
    record["debug"]["tool_rounds"] = invalid_rounds

    with pytest.raises(RuntimeError, match="tool_rounds"):
        pipeline.performance_metrics(record)


def test_source_boundary_uses_canonical_full_source_ids():
    question, golden, record = _valid_search_case()
    record["sources"] = [r".\repo\docs\meeting.md"]
    assert _check(
        score_contract(question, golden, record),
        "source_boundary",
    )["passed"]

    record["sources"] = ["archive/meeting.md"]
    assert not _check(
        score_contract(question, golden, record),
        "source_boundary",
    )["passed"]

    record["sources"] = []
    assert not _check(
        score_contract(question, golden, record),
        "source_boundary",
    )["passed"]


def test_project_sources_must_come_from_the_server_owned_project_trace():
    question, golden, record = _valid_search_case()
    record["debug"]["model_contexts"] = ["unrelated project context"]
    record["debug"]["evidence"]["project"]["source_ids"] = [
        "repo/docs/other.md"
    ]

    result = score_contract(question, golden, record)

    assert not result["passed"]
    assert not _check(result, "source_boundary")["passed"]


def test_project_sources_cannot_cover_a_missing_attachment_source():
    attachments = [
        {"filename": "first.txt", "content_text": "first"},
        {"filename": "second.txt", "content_text": "second"},
    ]
    question = _question(
        required_capabilities=["hybrid_search"],
        allowed_capabilities=["hybrid_search"],
        required_evidence_kinds=["project", "attachment"],
        attachments=attachments,
    )
    expected_sources = [
        "repo/docs/project.md",
        "attachment:first.txt",
        "attachment:second.txt",
    ]
    golden = _golden(sources=expected_sources)
    record = _record(
        calls=[{
            "name": SEARCH_TOOL,
            "args": {"query": question["user_input"]},
        }],
        tool_results=[{"tool": SEARCH_TOOL, "status": "ok"}],
        model_contexts=["project context"],
        sources=expected_sources,
        multi_queries=[question["user_input"]],
        attachment_evidence=[{
            "source_location": "attachment:first.txt",
            "extraction_status": "ok",
        }],
        project_source_ids=["repo/docs/project.md"],
        project_lookup_completed=True,
    )

    result = score_contract(question, golden, record)

    assert not result["passed"]
    assert not _check(result, "source_boundary")["passed"]


@pytest.mark.parametrize(
    ("required", "operation"),
    [
        ("overview", "count"),
        ("structured_state", "overview"),
    ],
)
def test_capabilities_are_tool_and_operation_predicates(required, operation):
    question = _question(
        family="semantic",
        required_capabilities=[required],
        allowed_capabilities=[required],
        required_evidence_kinds=["project"],
    )
    record = _record(
        calls=[{
            "name": SQL_TOOL,
            "args": {"operation": operation, "category": "all"},
        }],
        tool_results=[{"tool": SQL_TOOL, "status": "ok"}],
        model_contexts=["구조화 결과"],
    )
    result = score_contract(question, _golden(), record)
    assert not _check(result, "required_capabilities")["passed"]
    assert not _check(result, "allowed_capabilities")["passed"]


def test_expected_arguments_bind_to_explicit_capabilities():
    question = _question(
        required_capabilities=["hybrid_search", "structured_state"],
        allowed_capabilities=["hybrid_search", "structured_state"],
        required_evidence_kinds=["project"],
    )
    question["expected_arguments"] = {
        "hybrid_search": {"query": question["user_input"]},
        "structured_state": {"operation": "list", "category": "action"},
    }
    calls = [
        {"name": SEARCH_TOOL, "args": {"query": question["user_input"]}},
        {
            "name": SQL_TOOL,
            "args": {"operation": "list", "category": "action"},
        },
    ]
    record = _record(
        calls=calls,
        tool_results=[{"tool": SQL_TOOL, "status": "ok"}],
        model_contexts=["근거"],
        sources=["structured/source.md"],
        multi_queries=[question["user_input"]],
    )
    golden = _golden(sources=["structured/source.md"])
    result = score_contract(question, golden, record)
    assert result["passed"]
    assert _check(result, "expected_arguments:hybrid_search")["passed"]
    assert _check(result, "expected_arguments:structured_state")["passed"]

    ambiguous = deepcopy(question)
    ambiguous["expected_arguments"] = {"query": question["user_input"]}
    result = score_contract(ambiguous, golden, record)
    assert not result["passed"]
    assert not _check(result, "expected_arguments_binding")["passed"]


def test_duplicate_calls_are_normalized_after_public_tool_defaults():
    question = _question(
        family="semantic",
        required_capabilities=["structured_state"],
        allowed_capabilities=["structured_state"],
        required_evidence_kinds=["project"],
    )
    record = _record(
        calls=[
            {
                "name": SQL_TOOL,
                "args": {"operation": "list", "category": "action"},
            },
            {
                "name": SQL_TOOL,
                "args": {
                    "operation": "list",
                    "category": "action",
                    "owner": None,
                    "completion_status": None,
                    "due_within_days": None,
                    "overdue": None,
                    "limit": 8,
                },
            },
        ],
        tool_results=[{"tool": SQL_TOOL, "status": "ok"}],
        model_contexts=["구조화 결과"],
    )
    result = score_contract(question, _golden(), record)
    assert not result["passed"]
    assert not _check(result, "duplicate_tool_calls")["passed"]


@pytest.mark.parametrize(
    ("answer", "verdict", "expected_pass"),
    [
        ("현재 조건에 맞는 항목은 총 7건입니다.", "affirmed", True),
        ("7건은 아니고 실제로 2건입니다.", "denied", False),
        ("7건 또는 8건일 수 있습니다.", "uncertain", False),
        ("앞서 7건이라 했지만 정정합니다. 실제로 2건입니다.", "denied", False),
    ],
)
def test_count_contract_uses_prejudged_structured_verdict(
    answer,
    verdict,
    expected_pass,
):
    question = _question(
        family="structured_count",
        required_capabilities=["structured_state"],
        allowed_capabilities=["structured_state"],
        required_evidence_kinds=["project"],
    )
    record = _record(
        answer=answer,
        calls=[{
            "name": SQL_TOOL,
            "args": {"operation": "count", "category": "action"},
        }],
        tool_results=[{"tool": SQL_TOOL, "status": "ok"}],
        model_contexts=["구조화 count 결과"],
        sources=["structured/count.md"],
    )
    golden = _golden(
        sources=["structured/count.md"],
        deterministic={"exact_count": 7},
    )
    record["answer_verdicts"] = _passing_verdicts(
        question,
        golden,
        {"exact_count:0": verdict},
    )
    result = score_contract(
        question,
        golden,
        record,
    )
    assert _check(result, "exact_count")["passed"] is expected_pass


@pytest.mark.parametrize(
    ("answer", "item_verdict", "unsupported_verdict", "expected_pass"),
    [
        ("Alpha가 목록에 포함됩니다.", "affirmed", "absent", True),
        ("Alpha는 목록에 포함되지 않습니다.", "denied", "absent", False),
        ("Alpha가 아니라 Beta입니다.", "denied", "absent", False),
        ("Alpha와 Secret이 목록에 포함됩니다.", "affirmed", "affirmed", False),
    ],
)
def test_list_contract_uses_prejudged_structured_verdicts(
    answer,
    item_verdict,
    unsupported_verdict,
    expected_pass,
):
    question = _question(
        family="structured_list",
        required_capabilities=["structured_state"],
        allowed_capabilities=["structured_state"],
        required_evidence_kinds=["project"],
    )
    record = _record(
        answer=answer,
        calls=[{
            "name": SQL_TOOL,
            "args": {"operation": "list", "category": "action"},
        }],
        tool_results=[{"tool": SQL_TOOL, "status": "ok"}],
        model_contexts=["구조화 list 결과"],
        sources=["structured/list.md"],
    )
    golden = _golden(
        sources=["structured/list.md"],
        unsupported_claims=["Secret"],
        deterministic={"required_items": ["Alpha"]},
    )
    record["answer_verdicts"] = _passing_verdicts(
        question,
        golden,
        {
            "unsupported_claim:0": unsupported_verdict,
            "required_item:0": item_verdict,
        },
    )
    result = score_contract(
        question,
        golden,
        record,
    )
    assert result["passed"] is expected_pass


@pytest.mark.parametrize(
    ("answer", "abstention_verdict", "claim_verdict", "expected_pass"),
    [
        ("현재 근거로는 확인할 수 없습니다.", "affirmed", "absent", True),
        (
            "확인할 수 없다는 설명은 틀렸고 Alpha가 확정됐습니다.",
            "denied",
            "affirmed",
            False,
        ),
        (
            "확인할 수 없지는 않습니다. Alpha가 확정됐습니다.",
            "denied",
            "affirmed",
            False,
        ),
    ],
)
def test_abstention_contract_uses_prejudged_structured_verdicts(
    answer,
    abstention_verdict,
    claim_verdict,
    expected_pass,
):
    question = _question(family="abstention")
    question["must_abstain"] = True
    record = _record(answer=answer)
    golden = _golden(unsupported_claims=["Alpha"])
    record["answer_verdicts"] = _passing_verdicts(
        question,
        golden,
        {
            "unsupported_claim:0": claim_verdict,
            "abstention:0": abstention_verdict,
        },
    )
    result = score_contract(
        question,
        golden,
        record,
    )
    assert result["passed"] is expected_pass


def test_inline_attachment_builder_accepts_only_text_with_inline_body():
    attachment = _attachment_models([{
        "filename": "notes.txt",
        "content_text": "안전한 텍스트",
    }])[0]
    assert base64.b64decode(attachment.content_base64).decode() == "안전한 텍스트"

    with pytest.raises(ValueError, match="must be text"):
        _attachment_models([{
            "filename": "notes.pdf",
            "content_text": "not really a PDF",
        }])
    with pytest.raises(ValueError, match="requires content_text"):
        _attachment_models([{"filename": "notes.txt"}])


def _compared_run() -> dict:
    return {
        "schema_version": 2,
        "phase": "scored",
        "dataset_id": "synthetic-v1",
        "corpus": "modu",
        "split": "final",
        "questions_sha256": "q" * 64,
        "golden_sha256": "g" * 64,
        "manifest": {"snapshot": "frozen"},
        "run_config": {"model": "synthetic-model", "max_attempts": 1},
        "ragas_config": {
            "judge": "synthetic-judge",
            "embedding_model": "synthetic-embedding",
            "workers": 1,
        },
        "records": [{
            "id": "synthetic-1",
            "family": "semantic",
            "user_input": "synthetic question",
            "question_sha256": "r" * 64,
            "input_sha256": "i" * 64,
            "model": "synthetic-model",
            "latency_ms": 100.0,
            "contract": {"passed": True},
            "performance": {
                "tool_calls": 1,
                "llm_calls": 2,
                "llm_tokens": 50,
            },
            "ragas_metrics": list(ALL_RAGAS_METRICS),
            "ragas": {metric: 0.8 for metric in ALL_RAGAS_METRICS},
        }],
    }


def test_compare_requires_identical_nonempty_complete_metric_coverage():
    baseline = _compared_run()
    candidate = _compared_run()
    assert compare_runs(baseline, candidate)["passed"]

    empty = _compared_run()
    empty["records"][0]["ragas_metrics"] = []
    empty["records"][0]["ragas"] = {}
    with pytest.raises(RuntimeError, match="nonempty"):
        compare_runs(empty, deepcopy(empty))

    incomplete_coverage = _compared_run()
    incomplete_coverage["records"][0]["ragas_metrics"].remove(
        "response_relevancy"
    )
    incomplete_coverage["records"][0]["ragas"].pop("response_relevancy")
    with pytest.raises(RuntimeError, match="all RAGAS metrics"):
        compare_runs(baseline, incomplete_coverage)

    incomplete = _compared_run()
    incomplete["records"][0]["ragas"] = {}
    with pytest.raises(RuntimeError, match="fully RAGAS-scored"):
        compare_runs(incomplete, candidate)

    unknown = _compared_run()
    unknown["records"][0]["ragas_metrics"].append("synthetic_unknown")
    unknown["records"][0]["ragas"]["synthetic_unknown"] = 0.8
    with pytest.raises(RuntimeError, match="unknown RAGAS"):
        compare_runs(unknown, deepcopy(unknown))


@pytest.mark.parametrize("field", pipeline.COMPARISON_INVARIANT_FIELDS)
def test_compare_rejects_mismatched_run_and_score_invariants(field):
    baseline = _compared_run()
    candidate = deepcopy(baseline)
    candidate[field] = {"different": True}

    with pytest.raises(RuntimeError, match=field):
        compare_runs(baseline, candidate)


def test_compare_rejects_a_different_model_or_request_identity():
    baseline = _compared_run()
    candidate = deepcopy(baseline)
    candidate["records"][0]["model"] = "other-model"
    with pytest.raises(RuntimeError, match="model"):
        compare_runs(baseline, candidate)

    candidate = deepcopy(baseline)
    candidate["records"][0]["input_sha256"] = "other-input"
    with pytest.raises(RuntimeError, match="input_sha256"):
        compare_runs(baseline, candidate)


def test_final_dataset_paths_are_separated_between_run_and_score(tmp_path):
    questions = tmp_path / "questions.json"
    golden = tmp_path / "golden.json"
    assert _resolve_run_questions_path("final", questions) == questions
    assert _resolve_score_dataset_paths(
        "final",
        questions,
        golden,
    ) == (questions, golden)

    with pytest.raises(RuntimeError, match="external --questions"):
        _resolve_run_questions_path("final", None)
    with pytest.raises(RuntimeError, match="--questions and --golden"):
        _resolve_score_dataset_paths("final", questions, None)
    with pytest.raises(RuntimeError, match="separate files"):
        _resolve_score_dataset_paths("final", questions, questions)


def test_duplicate_question_or_golden_ids_are_rejected():
    items = [{"id": "same"}, {"id": "same"}]

    with pytest.raises(RuntimeError, match="duplicate question id"):
        pipeline._validated_unique_items(items, "question")
    with pytest.raises(RuntimeError, match="duplicate golden id"):
        pipeline._validated_unique_items(items, "golden")


def test_raw_verifier_rejects_duplicate_question_ids_before_scoring():
    first = _question()
    second = deepcopy(first)
    second["user_input"] = "different synthetic question"
    questions_data = {
        "dataset_id": "synthetic-v1",
        "questions": [first, second],
    }
    records = []
    for item in questions_data["questions"]:
        record = {
            "id": item["id"],
            "corpus": item["corpus"],
            "split": item["split"],
            "family": item["family"],
            "user_input": item["user_input"],
            "ragas_metrics": item["ragas_metrics"],
        }
        record["question_sha256"] = pipeline._sha256_json(item)
        record["input_sha256"] = pipeline._sha256_json(
            pipeline._request_payload(item, 1)
        )
        record["output_sha256"] = pipeline._sha256_json(
            pipeline._raw_output_payload(record)
        )
        records.append(record)
    run = pipeline._seal_raw_run({
        "schema_version": 2,
        "phase": "run",
        "dataset_id": "synthetic-v1",
        "questions_sha256": pipeline._sha256_json(questions_data),
        "label": "synthetic",
        "corpus": "modu",
        "split": "dev",
        "manifest": {"project_id": 1},
        "run_config": {"model": "synthetic", "max_attempts": 1},
        "created_at": "synthetic",
        "records": records,
    })

    with pytest.raises(RuntimeError, match="duplicate question id"):
        _verify_raw_run(run, questions_data)


def test_run_cli_does_not_accept_golden(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", [
        "pipeline",
        "run",
        "--state-root",
        str(tmp_path),
        "--corpus",
        "modu",
        "--label",
        "candidate",
        "--output",
        str(tmp_path / "raw.json"),
        "--golden",
        str(tmp_path / "golden.json"),
    ])
    with pytest.raises(SystemExit):
        parse_args()


def test_raw_run_is_sealed_then_scored_in_a_separate_phase(
    monkeypatch,
    tmp_path,
):
    question, golden_item, _ = _valid_search_case()
    questions_data = {
        "dataset_id": "synthetic-v1",
        "questions": [question],
    }
    golden_data = {
        "dataset_id": "synthetic-v1",
        "items": [golden_item],
    }
    questions_path = tmp_path / "questions.json"
    golden_path = tmp_path / "golden.json"
    raw_path = tmp_path / "raw.json"
    questions_path.write_text(
        json.dumps(questions_data, ensure_ascii=False),
        encoding="utf-8",
    )
    golden_path.write_text(
        json.dumps(golden_data, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        pipeline,
        "_configure_runtime",
        lambda _args: {"project_id": 9, "snapshot": "frozen"},
    )
    query_module = importlib.import_module("backend.api.query")

    def service_query(project_id, body):
        assert project_id == 9
        assert body.question == question["user_input"]
        return {
            "answer": "Alpha가 확인됩니다.",
            "plan": [],
            "sources": ["repo/docs/meeting.md"],
            "route": "agentic",
            "debug": {
                "tool_calls": [{
                    "name": SEARCH_TOOL,
                    "args": {"query": question["user_input"]},
                }],
                "tool_results": [{"tool": SEARCH_TOOL, "status": "ok"}],
                "tool_rounds": 1,
                "multi_queries": [question["user_input"]],
                "history_mode": False,
                "model_contexts": ["project context"],
                "attachment_evidence": [],
                "evidence": {
                    "project": {
                        "lookup_completed": True,
                        "has_substantive_evidence": True,
                        "model_context_count": 1,
                        "source_ids": ["repo/docs/meeting.md"],
                    },
                },
            },
        }

    def production_rate_limiter(*_args, **_kwargs):
        raise AssertionError("the transport rate limiter must not run")

    monkeypatch.setattr(query_module, "query", production_rate_limiter)
    monkeypatch.setattr(
        query_module,
        "execute_project_query",
        service_query,
    )

    raw = run_questions(SimpleNamespace(
        split="dev",
        questions=questions_path,
        corpus="modu",
        label="candidate",
        max_attempts=1,
    ))
    assert raw["phase"] == "run"
    assert raw["raw_run_sha256"]
    assert "contract_summary" not in raw
    assert raw["records"][0]["retrieved_contexts"] == ["project context"]
    assert {
        "question_sha256",
        "input_sha256",
        "output_sha256",
    } <= raw["records"][0].keys()
    assert not {
        "answer_verdicts",
        "contract",
        "performance",
        "ragas",
    } & raw["records"][0].keys()
    _verify_raw_run(raw, questions_data)

    tampered = deepcopy(raw)
    tampered["records"][0]["answer"] = "바뀐 답변"
    with pytest.raises(RuntimeError, match="seal"):
        _verify_raw_run(tampered, questions_data)

    leaked_feedback = deepcopy(raw)
    leaked_feedback["records"][0]["answer_verdicts"] = {
        "schema_version": 1,
        "targets": [],
    }
    with pytest.raises(RuntimeError, match="score-phase feedback"):
        _verify_raw_run(leaked_feedback, questions_data)

    raw_path.write_text(
        json.dumps(raw, ensure_ascii=False),
        encoding="utf-8",
    )

    async def fake_ragas(records, _golden_by_id, *_args):
        for record in records:
            record["ragas"] = {
                metric: 0.9 for metric in record["ragas_metrics"]
            }

    async def fake_contract_judge(
        records,
        question_by_id,
        golden_by_id,
        *_args,
    ):
        for record in records:
            record["answer_verdicts"] = _passing_verdicts(
                question_by_id[record["id"]],
                golden_by_id[record["id"]],
            )

    monkeypatch.setattr(pipeline, "_score_ragas_records", fake_ragas)
    monkeypatch.setattr(
        pipeline,
        "_judge_answer_contracts",
        fake_contract_judge,
    )
    monkeypatch.setattr(
        pipeline.importlib.metadata,
        "version",
        lambda _package: "synthetic",
    )
    scored = score_ragas(SimpleNamespace(
        input=raw_path,
        questions=questions_path,
        golden=golden_path,
        judge="synthetic-judge",
        embedding_model="synthetic-embedding",
        workers=1,
    ))
    assert scored["phase"] == "scored"
    assert scored["contract_summary"]["all_passed"]
    assert scored["records"][0]["contract"]["passed"]
    assert scored["records"][0]["performance"]["tool_calls"] == 1
    assert scored["records"][0]["ragas"] == {
        metric: 0.9 for metric in ALL_RAGAS_METRICS
    }
