"""이슈 #17(Tool·첨부 리팩터링) 완료 조건 회귀 테스트.

목적은 "현재 브랜치가 이슈의 완료 조건을 만족하는가"를 기계적으로 판정하는 것이다.
따라서 **실패하는 테스트가 곧 미해결 항목**이며, 통과하는 테스트가 해결 항목이다.

두 층으로 나눈다.
- 계약 검증: LLM·DB 없이 관찰 가능한 런타임 동작을 본다. CI에서 항상 돌아간다.
- 골든 실행: 실제 모델의 도구 선택·인자를 본다. 명시적으로
  `RUN_PR18_LIVE_GOLDEN=1`을 설정한 경우에만 실행한다.

fixture 정본: `backend/test/golden/pr18_issue17_golden.json`
"""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

_GOLDEN = Path(__file__).resolve().parent.parent / "backend" / "test" / "golden" / "pr18_issue17_golden.json"


def _golden() -> dict:
    return json.loads(_GOLDEN.read_text(encoding="utf-8"))


def _case(section: str, case_id: str) -> dict:
    for row in _golden()[section]:
        if row["id"] == case_id:
            return row
    raise AssertionError(f"golden fixture 없음: {section}/{case_id}")


class _ToolCallingFake:
    """정해진 모델 응답으로 실제 Agentic Tool 루프만 검증한다."""

    def __init__(self, responses):
        self.responses = iter(responses)
        self.invocations = []

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages):
        self.invocations.append(list(messages))
        return next(self.responses)


# ─── 골든셋 자체의 무결성 ───────────────────────────────────────────────────

def test_golden_fixture_is_wellformed():
    """골든셋이 깨지면 아래 판정 전부가 무의미해진다."""
    data = _golden()
    assert data["issue"] == 17
    required = {
        "tool_selection", "category_args", "count_scope",
        "attachment_provenance", "loop_control", "query_variants",
        "history_scope", "observability", "tool_naming",
    }
    assert required <= set(data), sorted(required - set(data))
    seen = set()
    for section in required:
        for row in data[section]:
            assert "rationale" in row, f"{section}/{row.get('id')} 근거 누락"
            assert row["id"] not in seen, f"중복 id: {row['id']}"
            seen.add(row["id"])


# ─── LC: Tool 루프 통제 ─────────────────────────────────────────────────────

def test_lc01_tool_loop_cannot_exceed_hard_cap():
    """LC-01~03 — 큰 설정값에서도 실행·trace·응답 계약이 5회에서 닫힌다."""
    from backend.agentic_graph import run_agentic_qa
    from backend.retriever import qa_tools

    expected_max = _case("loop_control", "LC-01")["expected_max"]
    _case("loop_control", "LC-02")
    _case("loop_control", "LC-03")
    responses = [
        AIMessage(content="", tool_calls=[{
            "name": "search_hybrid_vector_rag",
            "args": {"query": f"검색 {index}", "include_history": False},
            "id": f"call_{index}",
            "type": "tool_call",
        }])
        for index in range(expected_max + 1)
    ]
    responses.append(AIMessage(content="확인한 근거 범위에서 답합니다."))

    with patch.object(
        qa_tools.qa_engine,
        "_build_context",
        return_value=("근거", ["source.md"], {}),
    ):
        result = run_agentic_qa(
            1,
            "여러 근거를 확인해줘",
            model=_ToolCallingFake(responses),
            max_tool_rounds=99,
        )

    assert result["debug"]["tool_rounds"] == expected_max
    assert len(result["debug"]["tool_calls"]) == expected_max
    assert all(
        call["args"]["query"] != f"검색 {expected_max}"
        for call in result["debug"]["tool_calls"]
    )
    assert result["debug"]["tool_results"][-1]["status"] == "tool_limit"
    assert "도구 호출 상한" in result["answer"]


def test_lc04_sufficient_evidence_stops_after_one_round():
    """LC-04 — 근거가 충분하면 추가 Tool 호출 없이 한 라운드에서 끝난다."""
    from backend.agentic_graph import run_agentic_qa
    from backend.retriever import qa_tools

    _case("loop_control", "LC-04")
    fake = _ToolCallingFake([
        AIMessage(content="", tool_calls=[{
            "name": "search_hybrid_vector_rag",
            "args": {"query": "SDK 담당자"},
            "id": "call_search",
            "type": "tool_call",
        }]),
        AIMessage(content="SDK 담당자는 박현우입니다."),
    ])
    with patch.object(
        qa_tools.qa_engine,
        "_build_context",
        return_value=("SDK 담당자는 박현우", ["meeting.md"], {}),
    ):
        result = run_agentic_qa(1, "SDK 담당자는?", model=fake)

    assert result["debug"]["tool_rounds"] == 1
    assert [call["name"] for call in result["debug"]["tool_calls"]] == [
        "search_hybrid_vector_rag"
    ]


def test_lc05_search_then_sql_state_chaining():
    """LC-05 — 검색 근거를 본 뒤 SQL 상태 조회를 다음 라운드에서 실행한다."""
    from backend.agentic_graph import run_agentic_qa
    from backend.retriever import qa_tools

    _case("loop_control", "LC-05")
    fake = _ToolCallingFake([
        AIMessage(content="", tool_calls=[{
            "name": "search_hybrid_vector_rag",
            "args": {"query": "SDK 지연 이유"},
            "id": "call_search",
            "type": "tool_call",
        }]),
        AIMessage(content="", tool_calls=[{
            "name": "query_sql_state",
            "args": {
                "operation": "count",
                "text_query": "SDK 작업",
                "category": "action",
            },
            "id": "call_sql",
            "type": "tool_call",
        }]),
        AIMessage(content="지연 이유와 남은 작업 수를 확인했습니다."),
    ])
    with patch.object(
        qa_tools.qa_engine,
        "_build_context",
        return_value=("지연 근거", ["delay.md"], {}),
    ), patch.object(
        qa_tools.mysql_search,
        "search",
        return_value=[],
    ), patch.object(
        qa_tools,
        "load_project_index_scope",
        return_value=None,
    ):
        result = run_agentic_qa(1, "SDK가 왜 지연됐고 남은 작업은?", model=fake)

    assert [call["name"] for call in result["debug"]["tool_calls"]] == [
        "search_hybrid_vector_rag",
        "query_sql_state",
    ]


# ─── QV: 질의 변형 런타임 강제 ──────────────────────────────────────────────

def _searched_queries(question, variants):
    """실제 _build_context를 돌려 코어가 진짜로 검색한 문장 목록을 얻는다.

    변형 병합 규칙을 테스트가 다시 구현하면 코드가 아니라 테스트 자신을
    검증하게 된다. DB·벡터스토어만 막고 코어 경로를 그대로 태운다.
    """
    from backend.retriever import qa_engine
    from backend.retriever.index_scope import ProjectIndexScope

    scope = ProjectIndexScope(project_id=1)
    with patch.object(qa_engine, "load_project_index_scope", return_value=scope), \
         patch.object(qa_engine.mysql_search, "search", return_value=[]), \
         patch.object(qa_engine, "_get_vectorstore") as vs:
        vs.return_value.similarity_search_with_score.return_value = []
        _, _, debug = qa_engine._build_context(
            1, question, history_mode=False, query_variants=list(variants),
        )
    return list(debug["multi_queries"])


def test_qv01_original_question_is_first_search_term():
    """QV-01 — 원 질문이 첫 검색어로 보존돼야 한다."""
    _case("query_variants", "QV-01")
    searched = _searched_queries("배포 절차가 뭐야?", ["배포 방법"])
    assert searched[0] == "배포 절차가 뭐야?", f"원본이 첫 검색어가 아니다: {searched}"


def test_qv02_search_core_caps_total_terms():
    """QV-02 — 내부 계층과 무관하게 실제 검색어가 원본 포함 4개 이하다."""
    expected_total = _case("query_variants", "QV-02")["expected_total_max"]
    searched = _searched_queries("원 질문", ["a", "b", "c", "d", "e"])
    assert searched[0] == "원 질문", f"원본이 첫 검색어가 아니다: {searched}"
    assert len(searched) <= expected_total, (
        f"런타임에서 변형 수가 {expected_total}개로 제한되지 않는다: {searched}"
    )


def test_qv03_duplicate_variants_are_removed():
    """QV-03 — 정규화 중복은 제거하고 뒤의 고유 후보는 보존한다."""
    _case("query_variants", "QV-03")
    searched = _searched_queries(
        "원 질문", ["중복", "중복", " 중복 ", "고유변형"]
    )
    assert len(set(searched)) == len(searched), (
        f"실제 검색이 중복 문장을 반복 조회한다: {searched}"
    )
    assert "고유변형" in searched


# ─── HS: 이력 범위 자동 판별과 override ─────────────────────────────────────

@pytest.mark.parametrize("case", _golden()["history_scope"], ids=lambda c: c["id"])
def test_history_scope_auto_detection_and_explicit_override(case):
    """HS — null은 자동 판별, bool 값은 명시적 override로 적용한다."""
    from backend.retriever import qa_tools

    captured = {}

    def fake_build_context(project_id, question, **kwargs):
        captured.update(kwargs)
        return ("근거", ["history.md"], {})

    with patch.object(
        qa_tools.qa_engine,
        "_build_context",
        side_effect=fake_build_context,
    ), patch.object(
        qa_tools,
        "load_project_index_scope",
        return_value=None,
    ):
        qa_tools.search_project_evidence.func(
            project_id=1,
            query=case["question"],
            alternate_queries=[],
            include_history=case["include_history"],
            messages=[HumanMessage(content=case["question"])],
            current_question=case["question"],
        )

    assert captured["history_mode"] is case["expected_history_mode"]


# ─── CA: Tool 경계에서의 인자 검증 ──────────────────────────────────────────

def test_ca_boundary_rejects_out_of_range_arguments():
    """완료 조건: category/status/count 범위를 프롬프트가 아니라 Tool 경계에서 거부한다.

    검증 함수의 존재가 아니라 거부 동작을 본다. 타입 주석(Literal)으로 강제되든
    별도 검증 함수로 강제되든, 범위 밖 값이 DB까지 내려가지 않으면 충족이다.
    """
    from backend.retriever import qa_tools

    # limit은 서버 상한으로 클램프된다(기존 계약).
    assert qa_tools.MEMORY_TOOL_MAX_ROWS >= 1

    for field, bogus in [
        ("category", "BOGUS"),
        ("completion_status", "BOGUS"),
        ("operation", "BOGUS"),
    ]:
        args = {"operation": "list", "text_query": "", "category": "action", "project_id": 1}
        args[field] = bogus
        with pytest.raises(Exception) as exc:
            qa_tools.query_structured_memory.invoke(args)
        # DB까지 내려간 뒤 터진 것이면 경계에서 막지 못했다는 뜻이다.
        assert "validation" in type(exc.value).__name__.lower(), (
            f"{field}={bogus}가 Tool 경계를 통과했다: {type(exc.value).__name__}"
        )


def test_ca03_completion_status_is_action_only_at_boundary():
    """CA-03 — 잘못된 조합은 DB 호출 없이 일관된 Tool 오류로 반환한다."""
    from backend.retriever import qa_tools

    case = _case("category_args", "CA-03")
    assert case["forbidden"]["completion_status"] == "open"
    with patch.object(qa_tools.mysql_search, "search") as search:
        _, artifact = qa_tools.query_structured_memory.func(
            operation="list",
            text_query="",
            category="decision",
            completion_status="open",
            project_id=1,
        )

    search.assert_not_called()
    assert artifact["status"] == "invalid_query"
    assert artifact["applied_filters"] == {}


# ─── CS: count 범위 일치 ───────────────────────────────────────────────────

@pytest.mark.parametrize("case", _golden()["count_scope"], ids=lambda c: c["id"])
def test_count_matches_the_applied_filter_scope(case):
    """CS — count 값과 실제 적용된 구조화 필터가 같은 집합을 가리킨다."""
    from backend.retriever import qa_tools

    expected = case["expected"]
    rows = [
        {"id": 1, "source": "a.md"},
        {"id": 2, "source": "b.md"},
        {"id": 2, "source": "duplicate.md"},
    ]
    with patch.object(
        qa_tools.mysql_search,
        "search",
        return_value=rows,
    ) as search, patch.object(
        qa_tools,
        "load_project_index_scope",
        return_value=None,
    ):
        content, artifact = qa_tools.query_structured_memory.func(
            project_id=1,
            operation=expected["operation"],
            category=expected["category"],
            text_query=expected.get("text_query", ""),
        )

    assert json.loads(content)["count"] == 2
    assert artifact["total_rows"] == 2
    assert artifact["applied_filters"]["category"] == expected["category"]
    assert search.call_args.kwargs["category"] == (
        None if expected["category"] == "all" else expected["category"]
    )
    assert search.call_args.kwargs["text_query"] is None


# ─── AP: 첨부 근거 ──────────────────────────────────────────────────────────

def test_ap01_valid_attachment_is_cited_and_not_persisted():
    """AP-01 — 정상 첨부는 임시 근거로 인용되고 영속 색인에 저장되지 않는다."""
    from backend.agentic_graph import run_agentic_qa

    case = _case("attachment_provenance", "AP-01")
    fake = _ToolCallingFake([AIMessage(content="백엔드는 FastAPI로 확정됐습니다.")])
    with patch(
        "backend.retriever.memory_vector.upsert_memory_vectors",
    ) as vector_upsert, patch(
        "backend.project_memory.upsert_project_memory",
    ) as summary_upsert:
        result = run_agentic_qa(
            1,
            "첨부에 뭐라고 적혀 있어?",
            attachment_context=f"[첨부 자료]\n### {case['filename']}\n"
                               f"(출처: {case['filename']})\n{case['content']}",
            attachment_sources=[case["filename"]],
            attachment_evidence=[{"extraction_status": "ok"}],
            model=fake,
        )

    joined = "\n".join(
        str(getattr(message, "content", ""))
        for message in fake.invocations[0]
    )
    for needle in case["expect_in_context"]:
        assert needle in joined, f"첨부 근거에 {needle} 없음"
    assert result["sources"] == [case["filename"]]
    assert result["debug"]["tool_calls"] == []
    vector_upsert.assert_not_called()
    summary_upsert.assert_not_called()


def test_ap02_failed_extraction_is_visible_and_does_not_block_search(monkeypatch):
    """AP-02 — 추출 실패 provenance를 남기고 프로젝트 검색은 계속한다."""
    import base64

    from backend.agentic_graph import run_agentic_qa
    from backend.api import query as query_api
    from backend.pipeline.converters import ConversionError, ErrorCode
    from backend.retriever import qa_tools

    case = _case("attachment_provenance", "AP-02")
    monkeypatch.setattr(
        query_api,
        "convert",
        lambda *args: (_ for _ in ()).throw(
            ConversionError(ErrorCode.EMPTY_DOCUMENT, "추출 실패")
        ),
    )
    evidence = query_api._prepare_attachment_evidence([
        query_api.QueryAttachment(
            filename=case["filename"],
            content_base64=base64.b64encode(b"%PDF-1.4\n").decode(),
        )
    ])
    attachment_context, sources = query_api._render_attachment_evidence(evidence)
    fake = _ToolCallingFake([
        AIMessage(content="", tool_calls=[{
            "name": "search_hybrid_vector_rag",
            "args": {"query": "프로젝트 기록 확인"},
            "id": "call_search",
            "type": "tool_call",
        }]),
        AIMessage(content="첨부 추출은 실패했고 프로젝트 기록을 확인했습니다."),
    ])
    with patch.object(
        qa_tools.qa_engine,
        "_build_context",
        return_value=("프로젝트 근거", ["project.md"], {}),
    ):
        result = run_agentic_qa(
            1,
            "첨부와 프로젝트 기록을 확인해줘",
            attachment_context=attachment_context,
            attachment_sources=sources,
            attachment_evidence=[item.debug() for item in evidence],
            model=fake,
        )

    assert evidence[0].extraction_status == "failed"
    assert all(needle in attachment_context for needle in case["expect_in_context"])
    assert result["debug"]["tool_rounds"] == 1
    assert result["debug"]["attachment_evidence"][0]["extraction_status"] == "failed"


def test_ap03_attachment_sources_do_not_evict_project_sources():
    """AP-03 — 첨부와 프로젝트 출처는 독립 상한으로 함께 반환한다."""
    from backend.agentic_graph import run_agentic_qa
    from backend.retriever import qa_tools

    case = _case("attachment_provenance", "AP-03")
    attachment_sources = [
        f"attachment-{index}.txt"
        for index in range(case["attachment_count"])
    ]
    project_sources = case["project_sources"]
    fake = _ToolCallingFake([
        AIMessage(content="", tool_calls=[{
            "name": "search_hybrid_vector_rag",
            "args": {"query": "프로젝트 근거"},
            "id": "call_search",
            "type": "tool_call",
        }]),
        AIMessage(content="첨부와 프로젝트 기록을 함께 확인했습니다."),
    ])
    with patch.object(
        qa_tools.qa_engine,
        "_build_context",
        return_value=("프로젝트 근거", project_sources, {}),
    ):
        result = run_agentic_qa(
            1,
            "첨부와 프로젝트 근거를 확인해줘",
            attachment_context="[첨부 자료]\n첨부 근거",
            attachment_sources=attachment_sources,
            model=fake,
        )

    assert result["sources"] == attachment_sources + project_sources
    assert result["debug"]["tool_sources"] == project_sources


def test_ap04_truncation_is_exposed_in_context(monkeypatch):
    """AP-04 — 잘림 여부를 provenance와 컨텍스트 양쪽에 남긴다."""
    import base64
    from types import SimpleNamespace

    from backend.api import query as query_api

    case = _case("attachment_provenance", "AP-04")
    monkeypatch.setattr(query_api, "_ATTACHMENT_MAX_CHARS_PER_FILE", 5)
    monkeypatch.setattr(query_api, "_ATTACHMENT_MAX_CHARS_TOTAL", 20)
    monkeypatch.setattr(
        query_api,
        "convert",
        lambda *args: SimpleNamespace(text="1234567890"),
    )
    evidence = query_api._prepare_attachment_evidence([
        query_api.QueryAttachment(
            filename=case["filename"],
            content_base64=base64.b64encode(b"1234567890").decode(),
        )
    ])
    context, _ = query_api._render_attachment_evidence(evidence)

    assert evidence[0].truncated is case["expect_truncated"]
    assert all(needle in context for needle in case["expect_in_context"])


def test_ap05_unsupported_format_is_rejected_before_conversion():
    """AP-05 — 미지원 형식은 변환·질의 전에 입력 경계에서 거부한다."""
    import base64

    from fastapi import HTTPException

    from backend.api import query as query_api

    case = _case("attachment_provenance", "AP-05")
    with patch.object(query_api, "convert") as convert, pytest.raises(
        HTTPException
    ) as exc:
        query_api._prepare_attachment_evidence([
            query_api.QueryAttachment(
                filename=case["filename"],
                content_base64=base64.b64encode(b"binary").decode(),
            )
        ])

    assert exc.value.status_code == case["expected_status_code"]
    convert.assert_not_called()


# ─── OB: 관측성 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("case_id", ["OB-01", "OB-02", "OB-03", "OB-04", "OB-05", "OB-06"])
def test_observability_fields_present_in_debug(case_id):
    """완료 조건: tools_used·호출 순서·도구별 지연·적용 필터·상태·절단을 기록한다.

    p95 지연 비교와 집계 대상 일치 사후 검증이 완료 조건에 포함되므로,
    기록되지 않는 필드는 그 조건을 충족할 수 없다는 뜻이다.
    """
    from backend import agentic_graph

    case = _case("observability", case_id)
    # 이름이 달라도 같은 정보를 담으면 충족으로 본다. 판정 대상은 이름이 아니라
    # 완료 조건이 요구하는 관측 정보의 존재다.
    accepts = case.get("accepts") or [case["field"]]

    debug = _agentic_debug()
    per_tool = [
        entry
        for key in ("tool_results", "tool_calls", "tools")
        for entry in (debug.get(key) or [])
        if isinstance(entry, dict)
    ]

    if case.get("per_tool"):
        present = any(f in entry for entry in per_tool for f in accepts)
    else:
        present = any(f in debug for f in accepts)
    assert present, (
        f"debug에 {'/'.join(accepts)} 없음 — 완료 조건의 관측 항목 미기록. "
        f"현재 최상위 키: {sorted(debug)}"
    )


def _agentic_debug(tool_debugs=None):
    """_collect_result를 실제로 태워 최종 debug dict를 얻는다."""
    from backend import agentic_graph
    from langchain_core.messages import AIMessage, ToolMessage

    if tool_debugs is None:
        # qa_engine._build_context가 실제로 내보내는 모양. 빈 dict를 넣으면
        # 코드가 기록하는 필드까지 없다고 잘못 판정한다.
        tool_debugs = [{
            "filters": {"category": "action"},
            "multi_queries": ["원 질문"],
            "mysql_rows": [], "chroma_chunks": [],
        }]
    messages = []
    for idx, tool_debug in enumerate(tool_debugs, start=1):
        messages.append(AIMessage(
            content="",
            tool_calls=[{
                "name": "search_hybrid_vector_rag",
                "args": {"query": f"q{idx}"},
                "id": f"call_{idx}",
            }],
        ))
        messages.append(ToolMessage(
            content="[구조화 기록] - 근거",
            name="search_hybrid_vector_rag",
            tool_call_id=f"call_{idx}",
            artifact={
                "tool": "search_hybrid_vector_rag", "status": "ok",
                "sources": [f"s{idx}.md"], "debug": tool_debug,
                "latency_ms": 1.0, "truncated": False,
                "total_rows": 1, "returned_rows": 1,
            },
        ))
    messages.append(AIMessage(content="답변입니다."))
    return agentic_graph._collect_result(messages, tool_rounds=len(tool_debugs)).get("debug") or {}


def test_ob07_per_tool_debug_is_not_clobbered():
    """OB-07 — 도구가 2개 호출되면 앞선 도구의 근거가 남아야 한다.

    _collect_result가 retrieval_debug에 덮어쓰기로 대입하면 마지막 도구만 살아남고,
    첫 도구의 filters·multi_queries는 사라진다. 그러면 '집계 대상 일치'를
    사후 검증할 수 없다.
    """
    debug = _agentic_debug([
        {"filters": {"category": "action"}, "multi_queries": ["첫 도구"]},
        {"filters": {"category": "risk"}, "multi_queries": ["둘째 도구"]},
    ])
    blob = repr(debug)
    assert "첫 도구" in blob and "action" in blob, (
        f"첫 도구의 debug가 둘째 도구에 덮여 사라졌다: {sorted(debug)} / {debug.get('filters')}"
    )


# ─── TN: Tool 재명명 ────────────────────────────────────────────────────────

@pytest.mark.parametrize("case_id", ["TN-01", "TN-02"])
def test_tool_renamed_to_role_based_name(case_id):
    """이슈 구현 범위: 내부 Tool 이름을 역할 기준으로 재명명한다."""
    from backend.retriever import qa_tools

    case = _case("tool_naming", case_id)
    proposed = case["proposed"]
    names = {t.name for t in qa_tools.QA_TOOLS} if hasattr(qa_tools, "QA_TOOLS") else set()
    if not names:
        from backend.agentic_graph import QA_TOOLS
        names = {t.name for t in QA_TOOLS}
    assert proposed in names, (
        f"{case['current']} → {proposed} 재명명 미적용 (현재: {sorted(names)})"
    )
    assert case["current"] not in names, (
        f"이전 Tool 이름이 함께 노출된다: {case['current']} / {sorted(names)}"
    )


def test_overview_is_query_sql_state_operation_not_a_third_tool():
    """프로젝트 조망은 별도 Tool이 아니라 SQL 상태 Tool의 operation이다."""
    from typing import get_args

    from backend.retriever import qa_tools

    names = {tool.name for tool in qa_tools.QA_TOOLS}
    assert names == {"query_sql_state", "search_hybrid_vector_rag"}
    operation = qa_tools.query_structured_memory.args_schema.model_fields[
        "operation"
    ].annotation
    assert "overview" in get_args(operation)


# ─── 골든 실행 (실제 모델 필요) ─────────────────────────────────────────────

_NEEDS_KEY = pytest.mark.skipif(
    os.getenv("RUN_PR18_LIVE_GOLDEN") != "1" or not os.getenv("OPENAI_API_KEY"),
    reason=(
        "실제 모델 골든은 RUN_PR18_LIVE_GOLDEN=1과 "
        "OPENAI_API_KEY를 함께 설정해야 실행한다"
    ),
)


def _observed_tools(question: str) -> tuple[list[str], list[dict]]:
    """오케스트레이터가 첫 라운드에서 고른 도구와 인자를 관찰한다(도구 미실행)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from backend.agentic_graph import ORCHESTRATOR_SYSTEM_PROMPT, QA_TOOLS
    from backend.llm.chat_model_factory import get_chat_model

    model = get_chat_model().bind_tools(QA_TOOLS, tool_choice="any")
    response = model.invoke([
        SystemMessage(content=ORCHESTRATOR_SYSTEM_PROMPT),
        HumanMessage(content=question),
    ])
    calls = getattr(response, "tool_calls", None) or []
    return [c["name"] for c in calls], [c.get("args") or {} for c in calls]


@_NEEDS_KEY
@pytest.mark.parametrize("case", _golden()["tool_selection"], ids=lambda c: c["id"])
def test_golden_tool_selection(case):
    """골든 도구 선택 회귀 — 완료 조건의 'Tool 선택 골든 회귀'."""
    names, args_list = _observed_tools(case["question"])

    for banned in case.get("forbidden_tools") or []:
        assert banned not in names, (
            f"{case['id']} 금지 도구 사용: {banned} (선택: {names}) — {case['rationale']}"
        )

    expected = case.get("expected_tools") or []
    mode = case.get("expected_tools_mode", "all_of")
    if mode == "any_of":
        assert set(names) & set(expected), (
            f"{case['id']} 기대 도구 중 하나도 안 씀: {expected} (선택: {names})"
        )
    else:
        for tool in expected:
            assert tool in names, (
                f"{case['id']} 기대 도구 미사용: {tool} (선택: {names}) — {case['rationale']}"
            )

    expected_args = case.get("expected_args") or {}
    if expected_args:
        assert any(
            name in expected
            and all(args.get(key) == value for key, value in expected_args.items())
            for name, args in zip(names, args_list)
        ), f"{case['id']} 기대 인자 {expected_args}가 호출에 없음: {list(zip(names, args_list))}"

    for forbidden in case.get("forbidden_calls") or []:
        assert not any(
            name == forbidden["name"]
            and all(
                args.get(key) == value
                for key, value in (forbidden.get("args") or {}).items()
            )
            for name, args in zip(names, args_list)
        ), f"{case['id']} 금지 호출 발생: {forbidden} / {list(zip(names, args_list))}"


@_NEEDS_KEY
@pytest.mark.parametrize("case", _golden()["category_args"], ids=lambda c: c["id"])
def test_golden_category_arguments(case):
    """골든 category 인자 회귀 — 완료 조건의 'category 인자 골든 회귀'."""
    names, args_list = _observed_tools(case["question"])
    memory_args = [
        a for name, a in zip(names, args_list) if name == "query_sql_state"
    ]

    if case.get("forbidden_owner_guess"):
        for args in memory_args:
            assert not args.get("owner"), (
                f"{case['id']} 미지의 담당자를 owner로 추측: {args.get('owner')}"
            )
        return

    if not memory_args:
        # 구조화 필터가 명시된 목록·개수 요청은 도구 선택 자체가 판정 대상이다.
        # 여기서 skip하면 도구 선택 실패가 통계에서 사라진다.
        if case.get("requires_memory_tool"):
            pytest.fail(
                f"{case['id']} 구조화 도구를 고르지 않았다: {names} — {case['rationale']}"
            )
        pytest.skip(f"{case['id']}: 구조화 도구를 쓰지 않아 인자 검증 대상이 아니다")

    args = memory_args[0]
    for key, want in (case.get("expected") or {}).items():
        assert args.get(key) == want, (
            f"{case['id']} {key}={args.get(key)!r}, 기대 {want!r} — {case['rationale']}"
        )
    for key, banned in (case.get("forbidden") or {}).items():
        assert args.get(key) != banned, (
            f"{case['id']} {key}에 금지값 {banned!r} — {case['rationale']}"
        )


@_NEEDS_KEY
@pytest.mark.parametrize("case", _golden()["count_scope"], ids=lambda c: c["id"])
def test_golden_count_scope_arguments(case):
    """골든 count 질문이 집계 대상과 같은 구조화 인자를 생성한다."""
    names, args_list = _observed_tools(case["question"])
    sql_args = [
        args for name, args in zip(names, args_list) if name == "query_sql_state"
    ]
    assert sql_args, f"{case['id']} query_sql_state를 고르지 않았다: {names}"
    for key, expected in case["expected"].items():
        assert sql_args[0].get(key) == expected, (
            f"{case['id']} {key}={sql_args[0].get(key)!r}, 기대 {expected!r}"
        )
