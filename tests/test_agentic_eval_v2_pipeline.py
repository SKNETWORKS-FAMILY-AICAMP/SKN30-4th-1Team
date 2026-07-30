import importlib
from copy import deepcopy

from langchain_core.messages import HumanMessage

from evals.agentic_v2.pipeline import (
    _evaluation_request,
    compare_runs,
    score_contract,
)
from backend.retriever import qa_tools
from backend.retriever.qa_tools import (
    capture_retrieved_contexts_for_evaluation,
    search_project_evidence,
)


query_api = importlib.import_module("backend.api.query")


def _semantic_question() -> dict:
    """계약 검사에 필요한 최소 검색 문항을 만든다."""
    return {
        "user_input": "출시일이 왜 바뀌었어?",
        "family": "semantic",
        "required_capabilities": ["hybrid_search"],
        "allowed_capabilities": ["hybrid_search"],
        "max_tool_rounds": 1,
        "expected_arguments": {},
        "expected_history_mode": False,
        "required_evidence_kinds": ["project"],
    }


def _semantic_record() -> dict:
    """계약을 만족하는 최소 검색 실행 결과를 만든다."""
    return {
        "http_status": 200,
        "error": None,
        "answer": "QA 기간을 확보하기 위해 바뀌었습니다.",
        "sources": ["meeting.md"],
        "debug": {
            "tool_calls": [{
                "name": "search_hybrid_vector_rag",
                "args": {
                    "query": "출시일이 왜 바뀌었어?",
                    "alternate_queries": ["출시 일정 변경 이유"],
                },
            }],
            "tool_rounds": 1,
            "history_mode": False,
            "multi_queries": ["출시일이 왜 바뀌었어?", "출시 일정 변경 이유"],
            "tool_sources": ["meeting.md"],
            "attachments": [],
        },
    }


def _golden() -> dict:
    """계약 검사에 필요한 최소 골든을 만든다."""
    return {
        "expected_sources": ["meeting.md"],
        "answer_contract": {"forbidden_claims": []},
        "deterministic_answer": None,
    }


def test_score_contract_accepts_valid_search_trace_and_rejects_duplicate_query():
    """검색 계약 통과와 정규화 후 중복 검색어 실패를 함께 확인한다."""
    question = _semantic_question()
    record = _semantic_record()

    assert score_contract(question, _golden(), record)["passed"] is True

    duplicated = deepcopy(record)
    duplicated["debug"]["multi_queries"].append("  출시일이 왜 바뀌었어?  ")
    result = score_contract(question, _golden(), duplicated)

    assert result["passed"] is False
    assert next(
        check for check in result["checks"] if check["name"] == "query_deduplicated"
    )["passed"] is False


def test_score_contract_accepts_attachment_only_zero_tool_trace():
    """첨부 전용 골든은 Tool 0회와 첨부 provenance를 요구한다."""
    question = {
        "user_input": "첨부의 릴리즈명은?",
        "family": "attachment_only",
        "required_capabilities": [],
        "allowed_capabilities": [],
        "max_tool_rounds": 0,
        "expected_arguments": {},
        "expected_history_mode": None,
        "required_evidence_kinds": ["attachment"],
    }
    record = {
        "http_status": 200,
        "error": None,
        "answer": "Bluefin입니다.",
        "sources": ["note.txt"],
        "debug": {
            "tool_calls": [],
            "tool_rounds": 0,
            "tool_sources": [],
            "attachments": ["note.txt"],
        },
    }
    golden = {
        "expected_sources": ["note.txt"],
        "answer_contract": {"forbidden_claims": []},
        "deterministic_answer": None,
    }

    assert score_contract(question, golden, record)["passed"] is True


def test_score_contract_rejects_duplicate_calls_and_more_than_five_rounds():
    """평가 계약도 중복 호출과 전역 5회 상한을 독립적으로 차단한다."""
    record = _semantic_record()
    record["debug"]["tool_calls"].append(deepcopy(record["debug"]["tool_calls"][0]))
    record["debug"]["tool_rounds"] = 6
    result = score_contract(_semantic_question(), _golden(), record)

    failed = {
        check["name"] for check in result["checks"] if not check["passed"]
    }
    assert {"duplicate_tool_calls", "global_tool_rounds"} <= failed


def test_compare_runs_applies_contract_ragas_and_performance_gates():
    """동일 문항의 개선량과 성능 상한을 합쳐 최종 판정하는지 확인한다."""
    baseline_record = {
        "id": "M-SEM-01",
        "family": "semantic",
        "latency_ms": 1000.0,
        "contract": {"passed": False},
        "performance": {"tool_calls": 1, "llm_calls": 2, "llm_tokens": 100},
        "ragas_metrics": [
            "context_precision",
            "context_recall",
            "faithfulness",
            "answer_correctness",
            "response_relevancy",
        ],
        "ragas": {
            "context_precision": 0.70,
            "context_recall": 0.80,
            "faithfulness": 0.80,
            "answer_correctness": 0.80,
            "response_relevancy": 0.80,
        },
    }
    candidate_record = deepcopy(baseline_record)
    candidate_record.update({
        "latency_ms": 1050.0,
        "contract": {"passed": True},
        "ragas": {
            "context_precision": 0.74,
            "context_recall": 0.80,
            "faithfulness": 0.80,
            "answer_correctness": 0.80,
            "response_relevancy": 0.80,
        },
    })
    baseline = {
        "dataset_id": "dataset",
        "corpus": "modu",
        "split": "dev",
        "records": [baseline_record],
    }
    candidate = {**baseline, "records": [candidate_record]}

    result = compare_runs(baseline, candidate)

    assert result["passed"] is True
    assert result["ragas"]["context_precision"]["mean_delta"] == 0.04
    assert result["performance"]["semantic_p95_passed"] is True
    assert result["performance"]["llm_calls_mean_candidate"] == 2
    assert result["performance"]["llm_tokens_mean_candidate"] == 100


def test_search_tool_captures_full_context_only_for_evaluation(monkeypatch):
    """검색 Tool이 공개 debug와 분리해 평가용 전체 근거를 전달하는지 확인한다."""
    monkeypatch.setattr(
        qa_tools.qa_engine,
        "_build_context",
        lambda *args, **kwargs: (
            "[원문 맥락]\n전체 검색 본문",
            ["meeting.md"],
            {
                "history_mode": False,
                "retrieved_contexts": ["전체 검색 본문"],
            },
        ),
    )

    with capture_retrieved_contexts_for_evaluation() as contexts:
        _, artifact = search_project_evidence.func(
            query="질문",
            project_id=1,
            messages=[HumanMessage(content="질문")],
            current_question="질문",
        )

    assert contexts == ["전체 검색 본문"]
    assert "retrieved_contexts" not in artifact["debug"]


def test_evaluation_request_matches_query_endpoint():
    """로컬 실행 요청이 실제 query 경로와 클라이언트 정보를 제공하는지 확인한다."""
    request = _evaluation_request(7)

    assert request.method == "POST"
    assert request.url.path == "/api/v1/projects/7/query"
    assert request.client.host == "127.0.0.1"


def test_evaluation_request_calls_decorated_query_with_real_signature(monkeypatch):
    """평가 실행이 Request를 포함한 실제 query 시그니처를 통과하는지 확인한다."""
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, *args):
            return None

        def fetchone(self):
            return {"id": 1}

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            return None

    monkeypatch.setattr(query_api, "require_project_access", lambda project_id: None)
    monkeypatch.setattr(query_api, "get_connection", Connection)
    monkeypatch.setattr(
        query_api,
        "run_agentic_qa",
        lambda **kwargs: {"answer": "답변", "sources": [], "debug": {}},
    )

    result = query_api.query(
        _evaluation_request(1),
        1,
        query_api.QueryRequest(question="질문"),
    )

    assert result["answer"] == "답변"
    assert result["debug"]["router_stage"] == "tool_agent"
