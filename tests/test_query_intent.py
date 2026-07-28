from unittest.mock import MagicMock, patch

from langchain_core.runnables import RunnableLambda

from backend.retriever import query_intent
from backend.retriever.index_scope import ProjectIndexScope
from backend.retriever.mysql_search import search


class _FakeStructuredLLM:
    """with_structured_output()만 흉내 내는 라우터/필터 테스트용 LLM."""

    def __init__(self, values):
        self.values = values

    def with_structured_output(self, schema):
        return RunnableLambda(lambda _: schema(**self.values))


def _make_conn(rows=None):
    cursor = MagicMock()
    cursor.fetchall.return_value = rows or []
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    return conn, cursor


def test_rule_router_classifies_filter_lookup_and_overview():
    """명백한 조회형/조망형 질문은 LLM 없이 규칙으로 분기한다."""
    lookup = query_intent.classify_question("박제섭이 담당인 미완료 액션은?")
    completed_count = query_intent.classify_question("완료된 액션 몇 개야?")
    overdue = query_intent.classify_question("마감 지난 거 있어?")
    overview = query_intent.classify_question("프로젝트 전체 상황 정리해줘")

    assert lookup.route == "filter_lookup"
    assert lookup.router_stage == "rule"
    assert completed_count.route == "filter_lookup"
    assert completed_count.router_stage == "rule"
    assert overdue.route == "filter_lookup"
    assert overdue.router_stage == "rule"
    assert overview.route == "overview"
    assert overview.router_stage == "rule"
    # 비이력 질문의 history_mode 기본값은 False — 현행 라우팅 불변
    assert lookup.history_mode is False
    assert overview.history_mode is False


def test_history_question_routes_semantic_with_history_mode():
    """TASK-004: 이력 질문은 LLM 없이 semantic + history_mode=True로 확정된다."""
    result = query_intent.classify_question("배포 주기가 왜 바뀌었어?")

    assert result.route == "semantic"
    assert result.router_stage == "history_rule"
    assert result.history_mode is True


def test_history_rule_overrides_overview_and_filter_rules():
    """이력 판정이 기존 규칙보다 우선한다 — "변경 이력 정리해줘"는 정리(overview 규칙),
    "이전 결정 목록"은 목록(filter 규칙)에 걸리지만 체인 없는 경로로 새면 안 된다."""
    summary_style = query_intent.classify_question("변경 이력 정리해줘")
    list_style = query_intent.classify_question("이전 결정 목록 보여줘")

    assert summary_style.route == "semantic"
    assert summary_style.history_mode is True
    assert list_style.route == "semantic"
    assert list_style.history_mode is True


def test_security_filter_question_not_hijacked_by_history_rule():
    """round-2 R-005: '보안' 내부의 '안'이 이력 트리거로 오매칭되어 결정론적
    filter_lookup 조회를 잃으면 안 된다."""
    result = query_intent.classify_question("기존 보안 이슈 목록 보여줘")

    assert result.route == "filter_lookup"
    assert result.router_stage == "rule"
    assert result.history_mode is False


def test_specific_work_completion_question_uses_llm_semantic(monkeypatch):
    """특정 작업의 완료 여부 질문은 filter_lookup 규칙으로 확정하지 않는다."""
    monkeypatch.setattr(
        query_intent,
        "get_chat_model",
        lambda **kwargs: _FakeStructuredLLM({"label": "semantic"}),
    )

    result = query_intent.classify_question("데스크탑 앱 FastAPI 연동 작업 상태는 실제로 완료됐어?")

    assert result.route == "semantic"
    assert result.router_stage == "llm"


def test_llm_router_classifies_semantic_when_rule_is_unclear(monkeypatch):
    """규칙이 애매하면 structured-output LLM 분류 결과를 사용한다."""
    monkeypatch.setattr(
        query_intent,
        "get_chat_model",
        lambda **kwargs: _FakeStructuredLLM({"label": "semantic"}),
    )

    result = query_intent.classify_question("왜 PR AUC를 평가 지표로 선택했어?")

    assert result.route == "semantic"
    assert result.router_stage == "llm"


def test_filter_lookup_formats_rows_without_llm_generation(monkeypatch):
    """filter_lookup은 MySQL 결과를 템플릿으로 포맷하고 sources/debug를 유지한다."""
    monkeypatch.setattr(
        query_intent,
        "extract_filters",
        lambda question, history: query_intent.QueryFilters(
            owner="박제섭",
            category="action",
            completion_status="open",
        ),
    )
    monkeypatch.setattr(
        query_intent.mysql_search,
        "search",
        lambda *args, **kwargs: [
            {
                "id": 1,
                "category": "action",
                "content": "FastAPI 연동",
                "owner": "박제섭",
                "due_date": "2026-07-04",
                "completed_at": None,
                "completion_status": "open",
                "source": "repo.md",
            }
        ],
    )

    result = query_intent.answer_filter_lookup(1, "박제섭이 담당인 미완료 액션은?", [], "rule")

    assert result["route"] == "filter_lookup"
    assert "조건에 맞는 기록 1건" in result["answer"]
    assert "FastAPI 연동" in result["answer"]
    assert result["sources"] == ["repo.md"]
    assert result["debug"]["filters"]["owner"] == "박제섭"
    assert result["debug"]["filters"]["completion_status"] == "open"


def test_memory_search_completion_status_filter_sql():
    """mysql_search.search()가 3상태 완료 필터를 SQL 조건으로 반영한다."""
    conn, cursor = _make_conn()

    with patch("backend.retriever.mysql_search.get_connection", return_value=conn):
        search(
            project_id=1,
            category="action",
            completion_status="unknown",
            index_scope=ProjectIndexScope(1),
        )

    sql, params = cursor.execute.call_args.args
    assert "m.category = %s" in sql
    assert "m.completion_status = %s" in sql
    assert params == [1, "action", "unknown"]


def test_unknown_action_is_not_formatted_as_open():
    text = query_intent._format_lookup_row({
        "category": "action",
        "content": "상태 불명 작업",
        "completed_at": None,
        "completion_status": "unknown",
    })

    assert "완료 여부 미확인" in text
    assert "**미완료**" not in text


def test_fetch_overview_context_reads_active_memory():
    """Overview는 active action 전체를 잘라내지 않고 새 계약으로 반환한다."""
    rows = [
        {
            "id": index,
            "content": f"작업 {index}",
            "owner": f"담당자 {index}",
            "date": f"2026-07-{index:02d}",
            "due_date": None,
            "completed_at": None,
            "completion_status": ("open", "completed", "unknown")[(index - 1) % 3],
            "completion_status_source": "explicit",
            "source": f"meeting-{index}.md",
        }
        for index in range(1, 21)
    ]
    conn, cursor = _make_conn(rows)
    cursor.fetchone.return_value = {"summary": "요약"}
    cursor.fetchall.side_effect = [
        [{"category": "action", "count": 20}],
        rows,
    ]

    with patch("backend.retriever.query_intent.get_connection", return_value=conn):
        ctx = query_intent._fetch_overview_context(1)

    assert ctx["overview_summary"] == "요약"
    assert ctx["category_stats"] == {
        "decision": 0,
        "action": 20,
        "issue": 0,
        "risk": 0,
    }
    assert ctx["action_plan"]["total"] == 20
    assert ctx["action_plan"]["status_counts"] == {
        "open": 7,
        "completed": 7,
        "unknown": 6,
    }
    assert ctx["action_plan"]["items"][0] == rows[0]
    assert ctx["action_plan"]["items"][-1] == rows[-1]
    assert {
        row["completion_status"] for row in ctx["action_plan"]["items"]
    } == {"open", "completed", "unknown"}

    memory_sqls = [
        c.args[0] for c in cursor.execute.call_args_list
        if "FROM memory" in c.args[0] or "FROM active_memory" in c.args[0]
    ]
    assert len(memory_sqls) == 2
    assert "GROUP BY category" in memory_sqls[0]
    action_sql = memory_sqls[1]
    assert "FROM active_memory" in action_sql
    assert "category = 'action'" in action_sql
    assert " date," in action_sql
    assert "completion_status =" not in action_sql
    assert "LIMIT" not in action_sql


def test_answer_overview_uses_new_context_and_collects_all_sources(monkeypatch):
    captured = {}
    context = {
        "overview_summary": "현재 프로젝트 요약",
        "category_stats": {"decision": 1, "action": 2, "issue": 0, "risk": 0},
        "action_plan": {
            "total": 2,
            "status_counts": {"open": 0, "completed": 0, "unknown": 2},
            "items": [
                {"id": 1, "content": "첫 작업", "source": "a.md"},
                {"id": 2, "content": "마지막 작업", "source": "b.md"},
            ],
        },
    }
    monkeypatch.setattr(query_intent, "_fetch_overview_context", lambda project_id: context)

    def answer(prompt):
        captured["prompt"] = prompt.to_string()
        return "핵심 액션만 고른 답변"

    monkeypatch.setattr(query_intent, "get_chat_model", lambda: RunnableLambda(answer))

    result = query_intent.answer_overview(1, "프로젝트 현황 알려줘", "rule")

    assert result["answer"] == "핵심 액션만 고른 답변"
    assert result["sources"] == ["a.md", "b.md"]
    assert result["debug"]["overview"]["category_stats"]["issue"] == 0
    assert result["debug"]["overview"]["action_plan_total"] == 2
    assert "마지막 작업" in captured["prompt"]
