"""run_eval_agentic._ContextRecorder 회귀 테스트: 훅 장착·복원, 중복 제거."""
from backend.retriever import qa_engine, qa_tools
from backend.test.golden.run_eval_agentic import _ContextRecorder


def _row(row_id: int, content: str) -> dict:
    return {"id": row_id, "category": "action", "content": content}


def test_recorder_captures_mysql_rows_and_restores_originals():
    original_row_line_body = qa_engine._row_line_body
    original_build_context = qa_engine._build_context
    original_fetch_overview = qa_tools._fetch_overview_context
    original_get_project_memory = qa_tools.get_project_memory

    with _ContextRecorder() as recorder:
        assert qa_engine._row_line_body is not original_row_line_body
        qa_engine._format_mysql_row(_row(1, "SDK 연동 담당은 박현우"))
        qa_engine._format_mysql_row(_row(2, "PostGIS 채택"))
        qa_engine._format_mysql_row(_row(1, "SDK 연동 담당은 박현우"))  # 재검색 중복

    assert qa_engine._row_line_body is original_row_line_body
    assert qa_engine._build_context is original_build_context
    assert qa_tools._fetch_overview_context is original_fetch_overview
    assert qa_tools.get_project_memory is original_get_project_memory
    assert recorder.collected() == ["SDK 연동 담당은 박현우", "PostGIS 채택"]
    # rendered_contexts는 메타·출처가 붙은 완성 라인이라 순수 content와는 다르지만,
    # 그 content를 포함해야 한다(faithfulness 채점이 이 근거로 답변을 검증하므로).
    rendered = recorder.collected_rendered()
    assert len(rendered) == 2
    assert "SDK 연동 담당은 박현우" in rendered[0]
    assert "PostGIS 채택" in rendered[1]
    # SQL 구조화 기록은 sql_contexts로만 잡히고 vector_contexts는 비어 있어야 한다
    # (SQL/vector 분리 채점, PM 분석 보고서 P0 권고).
    assert recorder.collected_sql() == recorder.collected()
    assert recorder.collected_vector() == []
    # 축별 목록도 rendered 기준으로 따로 모은다 — 축별 채점의 정본이다.
    assert recorder.collected_sql_rendered() == rendered
    assert recorder.collected_vector_rendered() == []


def test_recorder_sql_rendered_keeps_owner_and_reason():
    """rendered 축별 목록은 담당·이유를 담아야 한다 — 순수 content 기준으로 채점하면
    이 필드가 정답인 질문("누가 담당?", "왜 그렇게 정했나?")에서 정답 행조차 무관
    판정을 받아 SQL 축 precision이 실제보다 낮게 나온다(modu A2/C1 실측)."""
    row = {"id": 1, "category": "decision", "content": "앱 프레임워크를 Flutter로 확정한다.",
           "owner": "김태호", "reason": "iOS/Android 동시 개발로 일정 단축 가능"}

    with _ContextRecorder() as recorder:
        qa_engine._format_mysql_row(row)

    assert recorder.collected_sql() == ["앱 프레임워크를 Flutter로 확정한다."]
    sql_rendered = recorder.collected_sql_rendered()
    assert len(sql_rendered) == 1
    assert "담당: 김태호" in sql_rendered[0]
    assert "iOS/Android 동시 개발로 일정 단축 가능" in sql_rendered[0]


def test_recorder_captures_overview_tool_summary_and_action_rows(monkeypatch):
    """실측 발견: overview형 질문(예: A1 "핵심 콘셉트가 무엇인가")은
    get_project_overview 도구만 타서 이 훅이 없으면 컨텍스트 0개로 잡혔다."""
    monkeypatch.setattr(qa_tools, "_fetch_overview_context", lambda project_id: {
        "overview_summary": "동네 500m 반경 초근접 모임 매칭 앱",
        "category_stats": {"action": 5, "decision": 2},
        "action_plan": {
            "total": 5,
            "status_counts": {"open": 3, "completed": 2, "unknown": 0},
            "items": [_row(1, "SDK 연동 진행")],
        },
    })

    with _ContextRecorder() as recorder:
        qa_tools._fetch_overview_context(1)

    collected = recorder.collected()
    assert collected[0] == "동네 500m 반경 초근접 모임 매칭 앱"
    assert collected[-1] == "SDK 연동 진행"
    # status_counts는 시스템 프롬프트가 "권위 있는 집계"로 지시하는 숫자라 답변이
    # 이걸 인용하면 채점용 컨텍스트에도 있어야 faithfulness가 정확히 나온다.
    stats_blob = collected[1]
    assert '"action_plan_status_counts": {"open": 3, "completed": 2, "unknown": 0}' in stats_blob

    # overview 도구는 LLM에게 행 dict를 JSON 그대로 넘기므로(owner/date 등 포함),
    # rendered_contexts도 그 JSON 표현이어야 faithfulness가 실제 근거와 일치한다.
    rendered = recorder.collected_rendered()
    assert rendered[0] == "동네 500m 반경 초근접 모임 매칭 앱"
    assert rendered[1] == stats_blob  # 집계 숫자는 메타 개념이 없어 두 목록이 동일
    assert '"content": "SDK 연동 진행"' in rendered[-1]
    # overview 요약·집계·액션 행 전부 MySQL(active_memory/project_memory) 출처라 sql_contexts로.
    assert recorder.collected_sql() == collected
    assert recorder.collected_vector() == []
    assert recorder.collected_sql_rendered() == rendered
    assert recorder.collected_vector_rendered() == []


def test_recorder_captures_project_memory_summary(monkeypatch):
    """실측 발견(블라인드 코드 리뷰): search_project_evidence가 "[프로젝트 메모리]"
    블록으로 LLM에 넘기는 get_project_memory() 결과도 qa_tools.py가 `from ..graph
    import get_project_memory`로 직접 복사해 온 이름이라, qa_tools 쪽을 감싸야 한다."""
    monkeypatch.setattr(qa_tools, "get_project_memory", lambda project_id: "요약: MVP는 5월 18일 출시")

    with _ContextRecorder() as recorder:
        summary = qa_tools.get_project_memory(1)

    assert summary == "요약: MVP는 5월 18일 출시"
    assert recorder.collected() == ["요약: MVP는 5월 18일 출시"]
    assert recorder.collected_rendered() == ["요약: MVP는 5월 18일 출시"]
    assert recorder.collected_sql() == ["요약: MVP는 5월 18일 출시"]
    assert recorder.collected_vector() == []
    assert recorder.collected_sql_rendered() == ["요약: MVP는 5월 18일 출시"]


def test_recorder_skips_empty_project_memory(monkeypatch):
    monkeypatch.setattr(qa_tools, "get_project_memory", lambda project_id: "")

    with _ContextRecorder() as recorder:
        qa_tools.get_project_memory(1)

    assert recorder.collected() == []


def test_recorder_captures_chroma_chunks_as_vector_contexts(monkeypatch):
    """_build_context가 반환하는 chroma_chunks는 vector_contexts로만 잡혀야 한다
    (SQL/vector 분리 채점, PM 분석 보고서 P0 권고) — sql_contexts에는 안 들어간다."""
    monkeypatch.setattr(qa_engine, "_build_context", lambda *a, **k: (
        "무시되는 렌더 문자열", ["source.md"],
        {"chroma_chunks": [
            {"text_full": "AWS SES는 비용 효율적이며 기존 AWS 인프라와 연동이 용이하다."},
            {"text_full": "re-ranking 도입 시 정답률이 12%p 상승했다."},
        ]},
    ))

    with _ContextRecorder() as recorder:
        qa_engine._build_context(1, "질문")

    expected = ["AWS SES는 비용 효율적이며 기존 AWS 인프라와 연동이 용이하다.",
                "re-ranking 도입 시 정답률이 12%p 상승했다."]
    assert recorder.collected() == expected
    assert recorder.collected_rendered() == expected
    assert recorder.collected_vector() == expected
    assert recorder.collected_sql() == []
    assert recorder.collected_vector_rendered() == expected
    assert recorder.collected_sql_rendered() == []
