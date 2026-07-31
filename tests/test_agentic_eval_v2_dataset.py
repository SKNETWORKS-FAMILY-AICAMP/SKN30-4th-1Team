import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
EVAL_DIR = ROOT / "evals" / "agentic_v2"


def _load_json(filename: str) -> dict:
    """평가 데이터 JSON을 UTF-8로 읽는다."""
    return json.loads((EVAL_DIR / filename).read_text(encoding="utf-8"))


def test_questions_have_frozen_small_set_and_valid_sources():
    """공개 질문셋에는 반복 개발용 dev 문항만 있는지 확인한다."""
    data = _load_json("questions.json")
    questions = data["questions"]

    assert data["dataset_id"] == "paim-agentic-v2-dev-20260730"
    assert len(questions) == 16
    assert data["splits"] == {"dev": 16}
    assert all(item["split"] == "dev" for item in questions)
    assert len({item["id"] for item in questions}) == len(questions)
    assert sum(item["corpus"] == "modu" for item in questions) == 8
    assert sum(item["corpus"] == "csbot" for item in questions) == 8
    ragas_questions = [item for item in questions if item["ragas_metrics"]]
    assert len(ragas_questions) == 11
    assert all(
        "answer_correctness" in item["ragas_metrics"]
        for item in ragas_questions
    )
    assert all(
        capability in item["allowed_capabilities"]
        for item in questions
        for capability in item["required_capabilities"]
    )
    assert all(
        (ROOT / source).is_file()
        for item in questions
        for source in item["source_scope"]
    )


def test_explicit_change_reason_question_expects_history_mode():
    """명시적인 결정 변경 이유 질문은 대화 이력 없이도 변경 이력 검색을 요구한다."""
    questions = _load_json("questions.json")["questions"]
    question = next(item for item in questions if item["id"] == "M-SEM-01")

    assert question["expected_history_mode"] is True


def test_golden_matches_questions_and_uses_only_allowed_sources():
    """공개 dev 골든이 질문과 일대일 대응하고 허용된 근거만 쓰는지 확인한다."""
    questions = _load_json("questions.json")
    golden = _load_json("golden.json")
    question_by_id = {item["id"]: item for item in questions["questions"]}
    golden_by_id = {item["id"]: item for item in golden["items"]}

    assert golden["dataset_id"] == questions["dataset_id"]
    assert golden["authoring_policy"] == {"allowed_sources_only": True}
    assert "independent_from_question_author" not in golden["authoring_policy"]
    assert list(golden_by_id) == list(question_by_id)

    for item_id, answer in golden_by_id.items():
        question = question_by_id[item_id]
        allowed_sources = {
            Path(source).name for source in question["source_scope"]
        } | {
            attachment["filename"] for attachment in question["attachments"]
        }
        evidence_sources = {evidence["source"] for evidence in answer["gold_evidence"]}

        assert evidence_sources <= allowed_sources
        assert set(answer["expected_sources"]) <= allowed_sources
        assert answer["answer_contract"]["must_abstain"] == question["must_abstain"]
        assert bool(answer["reference_answer"].strip())
        if "answer_correctness" in question["ragas_metrics"]:
            assert answer["answer_contract"]["required_facts"]
        assert set(question["required_evidence_kinds"]) <= {
            evidence["kind"] for evidence in answer["gold_evidence"]
        }

        deterministic = answer["deterministic_answer"]
        if question["family"] == "structured_count":
            assert set(deterministic) == {"exact_count"}
            assert isinstance(deterministic["exact_count"], int)
        elif question["family"] == "structured_list":
            assert set(deterministic) == {"required_items"}
            assert isinstance(deterministic["required_items"], list)
        elif question["family"] == "abstention":
            assert set(deterministic) == {"reason"}
            assert bool(deterministic["reason"].strip())
        else:
            assert deterministic is None
