import json
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from backend.agentic_graph import ORCHESTRATOR_SYSTEM_PROMPT, run_agentic_qa
from backend.retriever import qa_tools
from backend.retriever.qa_tools import QA_TOOLS, query_structured_memory


class _ToolCallingFake:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.bind_calls = []
        self.invocations = []

    def bind_tools(self, tools, **kwargs):
        self.bind_calls.append(kwargs)
        return self

    def invoke(self, messages):
        self.invocations.append(list(messages))
        return next(self.responses)


def _memory_row(row_id: int, content: str, source: str = "meeting.md") -> dict:
    return {
        "id": row_id,
        "category": "action",
        "content": content,
        "reason": None,
        "topic": "연동",
        "owner": "박현우",
        "date": "2026-03-30",
        "due_date": None,
        "completed_at": None,
        "source": source,
    }


def test_tool_schemas_do_not_expose_project_id():
    for retrieval_tool in QA_TOOLS:
        assert "project_id" not in retrieval_tool.args


def test_overview_tool_returns_complete_action_plan(monkeypatch):
    rows = [
        {
            "id": index,
            "content": f"작업 {index}",
            "owner": "박현우",
            "date": "2026-07-22",
            "due_date": None,
            "completed_at": None,
            "completion_status": ("open", "completed", "unknown")[(index - 1) % 3],
            "completion_status_source": "explicit",
            "source": "meeting-a.md" if index < 20 else "meeting-b.md",
        }
        for index in range(1, 31)
    ]
    monkeypatch.setattr(
        qa_tools,
        "_fetch_overview_context",
        lambda project_id: {
            "overview_summary": "현재 프로젝트 요약",
            "category_stats": {"decision": 1, "action": 30, "issue": 0, "risk": 0},
            "action_plan": {
                "total": len(rows),
                "status_counts": {"open": 10, "completed": 10, "unknown": 10},
                "items": rows,
            },
        },
    )

    content, artifact = qa_tools.get_project_overview.func(project_id=1)
    payload = json.loads(content.removeprefix("[프로젝트 조망]\n"))

    assert payload["overview_summary"] == "현재 프로젝트 요약"
    assert payload["category_stats"]["risk"] == 0
    assert payload["action_plan"]["total"] == 30
    assert payload["action_plan"]["status_counts"]["unknown"] == 10
    assert payload["action_plan"]["items"][0]["id"] == 1
    assert payload["action_plan"]["items"][-1]["id"] == 30
    assert {row["completion_status"] for row in payload["action_plan"]["items"]} == {
        "open", "completed", "unknown",
    }
    assert artifact["sources"] == ["meeting-a.md", "meeting-b.md"]
    assert artifact["category_stats"]["issue"] == 0
    assert artifact["returned_rows"] == artifact["total_rows"] == 30
    assert artifact["truncated"] is False


def test_overview_prompt_contract_is_selective_and_preserves_unknown():
    description = qa_tools.get_project_overview.description

    assert "complete active Action Plan" in description
    assert "only when the user explicitly asks for the complete list" in description
    assert "completion_status`` as the only status evidence" in description
    assert "status_counts" in description and "authoritative aggregate" in description
    assert "필요한 핵심 액션만 선택" in ORCHESTRATOR_SYSTEM_PROMPT
    assert "현재 상태는" in ORCHESTRATOR_SYSTEM_PROMPT
    assert "completion_status만 근거" in ORCHESTRATOR_SYSTEM_PROMPT
    assert "status_counts가 현재 상태의 권위 있는 집계" in ORCHESTRATOR_SYSTEM_PROMPT
    assert "현재 상태를 증명하지 않습니다" in ORCHESTRATOR_SYSTEM_PROMPT


def test_memory_tool_requires_explicit_category_scope():
    schema = query_structured_memory.tool_call_schema.model_json_schema()

    assert "category" in schema["required"]
    assert schema["properties"]["category"]["enum"] == [
        "decision", "action", "issue", "risk", "all",
    ]
    category_description = schema["properties"]["category"]["description"]
    assert all(
        f"{category}:" in category_description
        for category in ("decision", "action", "issue", "risk", "all")
    )

    status_description = schema["properties"]["completion_status"]["description"]
    assert all(
        f"{status}:" in status_description
        for status in ("open", "completed", "unknown")
    )
    assert "Never infer open" in status_description


def test_memory_tool_rejects_completely_empty_selector(monkeypatch):
    search = MagicMock()
    monkeypatch.setattr(qa_tools.mysql_search, "search", search)

    content, artifact = query_structured_memory.func(
        operation="list",
        text_query="",
        project_id=1,
        category="all",
    )

    search.assert_not_called()
    assert artifact["status"] == "invalid_query"
    assert "전체 기록 조회를 거부" in content


def test_memory_tool_caps_rows_and_preserves_total(monkeypatch):
    cap = qa_tools.MEMORY_TOOL_MAX_ROWS
    total = cap + 5
    rows = [_memory_row(index, f"작업 {index}") for index in range(1, total + 1)]
    monkeypatch.setattr(qa_tools.mysql_search, "search", lambda *args, **kwargs: rows)
    monkeypatch.setattr(
        qa_tools.qa_engine,
        "_rank_mysql_rows",
        lambda project_id, candidates, queries, limit, **_: (candidates[:limit], []),
    )

    content, artifact = query_structured_memory.func(
        operation="list",
        text_query="SDK 연동",
        project_id=1,
        category="all",
        limit=999,
    )

    assert artifact["total_rows"] == total
    assert artifact["returned_rows"] == cap
    assert artifact["truncated"] is True
    assert content.count("[action]") == cap


def test_memory_tool_tells_the_model_when_rows_were_truncated(monkeypatch):
    """F-006: 잘림은 artifact에만 있고 모델이 보는 건 content뿐이라, 상위 N건을 받은
    모델이 그걸 "전체"라고 답했다. 나머지가 있다는 사실이 content에 있어야 한다."""
    cap = qa_tools.MEMORY_TOOL_MAX_ROWS
    total = cap + 32
    rows = [_memory_row(index, f"작업 {index}") for index in range(1, total + 1)]
    monkeypatch.setattr(qa_tools.mysql_search, "search", lambda *args, **kwargs: rows)
    monkeypatch.setattr(
        qa_tools.qa_engine,
        "_rank_mysql_rows",
        lambda project_id, candidates, queries, limit, **_: (candidates[:limit], []),
    )

    content, artifact = query_structured_memory.func(
        operation="list", text_query="작업", project_id=1, category="action", limit=999,
    )

    assert artifact["truncated"] is True
    assert f"총 {total}건 중 상위 {cap}건" in content


def test_memory_tool_does_not_claim_truncation_when_complete(monkeypatch):
    """잘리지 않았으면 안내 줄을 붙이지 않는다 — 완전한 목록을 부분 목록으로 오인하게
    만들면 F-006을 반대 방향으로 재현하는 셈이다."""
    rows = [_memory_row(index, f"작업 {index}") for index in range(1, 4)]
    monkeypatch.setattr(qa_tools.mysql_search, "search", lambda *args, **kwargs: rows)
    monkeypatch.setattr(
        qa_tools.qa_engine,
        "_rank_mysql_rows",
        lambda project_id, candidates, queries, limit, **_: (candidates[:limit], []),
    )

    content, artifact = query_structured_memory.func(
        operation="list", text_query="작업", project_id=1, category="action", limit=999,
    )

    assert artifact["truncated"] is False
    assert "상위" not in content


def test_memory_tool_all_scope_omits_sql_category(monkeypatch):
    search = MagicMock(return_value=[_memory_row(1, "SDK 연동")])
    monkeypatch.setattr(qa_tools.mysql_search, "search", search)

    content, _ = query_structured_memory.func(
        operation="count",
        text_query="전체 기록",
        project_id=1,
        category="all",
    )

    assert json.loads(content)["count"] == 1
    assert json.loads(content)["filters"]["category"] == "all"
    assert search.call_args.kwargs["category"] is None
    assert search.call_args.kwargs["text_query"] is None


def test_memory_tool_all_scope_count_accepts_empty_text_query(monkeypatch):
    search = MagicMock(return_value=[_memory_row(1, "SDK 연동")])
    monkeypatch.setattr(qa_tools.mysql_search, "search", search)

    content, artifact = query_structured_memory.func(
        operation="count",
        text_query="",
        project_id=1,
        category="all",
    )

    assert json.loads(content)["count"] == 1
    assert artifact["status"] == "ok"
    assert search.call_args.kwargs["text_query"] is None


def test_memory_count_deduplicates_join_expanded_rows(monkeypatch):
    row = _memory_row(1, "SDK 연동")
    monkeypatch.setattr(
        qa_tools.mysql_search,
        "search",
        lambda *args, **kwargs: [row, {**row, "source": "duplicate.md"}],
    )

    content, artifact = query_structured_memory.func(
        operation="count",
        text_query="",
        category="action",
        project_id=1,
    )

    assert json.loads(content)["count"] == 1
    assert artifact["total_rows"] == 1


def test_memory_count_applies_target_phrase_to_structured_search(monkeypatch):
    search = MagicMock(return_value=[_memory_row(1, "SDK 연동")])
    monkeypatch.setattr(qa_tools.mysql_search, "search", search)

    content, artifact = query_structured_memory.func(
        operation="count",
        text_query="SDK 연동",
        category="action",
        project_id=1,
    )

    assert json.loads(content)["count"] == 1
    assert artifact["total_rows"] == 1
    assert search.call_args.kwargs["text_query"] == "SDK 연동"


def test_agent_calls_evidence_tool_then_synthesizes_one_answer(monkeypatch):
    fake = _ToolCallingFake([
        AIMessage(content="", tool_calls=[{
            "name": "search_project_evidence",
            "args": {
                "query": "SDK 연동은 누가 담당했는가?",
                "alternate_queries": ["소셜 로그인 SDK 담당자"],
                "include_history": False,
            },
            "id": "call_1",
            "type": "tool_call",
        }]),
        AIMessage(content="**SDK 연동은 박현우가 담당했습니다.**"),
    ])
    monkeypatch.setattr(qa_tools, "get_project_memory", lambda project_id: "Modu 프로젝트")
    monkeypatch.setattr(
        qa_tools.qa_engine,
        "_build_context",
        lambda *args, **kwargs: (
            "[구조화 기록]\n[action] SDK 연동 (담당: 박현우)",
            ["2026-03-30.md"],
            {
                "history_mode": False,
                "filters": {},
                "multi_queries": ["SDK 연동은 누가 담당했는가?"],
                "multi_query_source": "tool_agent",
                "mysql_rows": [{"content": "SDK 연동", "owner": "박현우"}],
                "chroma_chunks": [],
            },
        ),
    )

    result = run_agentic_qa(
        1,
        "SDK 연동은 누가 담당했는가?",
        model=fake,
        max_tool_rounds=2,
    )

    assert result["answer"] == "**SDK 연동은 박현우가 담당했습니다.**"
    assert result["sources"] == ["2026-03-30.md"]
    assert result["route"] == "semantic"
    assert result["debug"]["tools_used"] == ["search_project_evidence"]
    assert result["debug"]["tool_rounds"] == 1
    assert fake.bind_calls[1]["tool_choice"] == "any"


def test_agent_can_combine_multiple_tools(monkeypatch):
    fake = _ToolCallingFake([
        AIMessage(content="", tool_calls=[
            {
                "name": "query_structured_memory",
                "args": {
                    "operation": "list",
                    "text_query": "SDK 연동",
                    "category": "action",
                    "limit": 3,
                },
                "id": "call_memory",
                "type": "tool_call",
            },
            {
                "name": "search_project_evidence",
                "args": {
                    "query": "SDK 연동 일정이 밀린 이유",
                    "include_history": False,
                },
                "id": "call_semantic",
                "type": "tool_call",
            },
        ]),
        AIMessage(content="**박현우가 담당했고, 소셜 로그인 추가로 일정이 밀렸습니다.**"),
    ])
    monkeypatch.setattr(
        qa_tools.mysql_search,
        "search",
        lambda *args, **kwargs: [_memory_row(1, "SDK 연동")],
    )
    monkeypatch.setattr(
        qa_tools.qa_engine,
        "_rank_mysql_rows",
        lambda project_id, rows, queries, limit, **_: (rows[:limit], []),
    )
    monkeypatch.setattr(qa_tools, "get_project_memory", lambda project_id: "")
    monkeypatch.setattr(
        qa_tools.qa_engine,
        "_build_context",
        lambda *args, **kwargs: ("[원문 맥락]\n소셜 로그인 추가로 1주 지연", ["delay.md"], {}),
    )

    result = run_agentic_qa(1, "SDK 연동 담당자와 지연 이유는?", model=fake)

    assert result["debug"]["tools_used"] == [
        "query_structured_memory", "search_project_evidence"
    ]
    assert "박현우" in result["answer"]
    assert result["sources"] == ["meeting.md", "delay.md"]
