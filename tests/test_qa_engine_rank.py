"""_rank_mysql_rows의 관련도 threshold 회귀 테스트.

과거엔 limit개를 무조건 채워서 무관한 행까지 컨텍스트에 섞였다(context_precision 저하 원인,
메모리 paim_ragas_precision_relevancy_causes 참고). "프레임워크"가 Kiwi에서 "프레임"+"워크"로
쪼개져 "와이어프레임"과 토큰이 겹치는 것처럼, 약한 토큰 중복만 있는 행은 limit 여유가
있어도 채워선 안 된다.
"""
from unittest.mock import MagicMock, patch

from backend.retriever import qa_engine


def _row(row_id: int, content: str) -> dict:
    return {"id": row_id, "content": content}


def test_rank_mysql_rows_excludes_rows_with_no_relevance_signal():
    rows = [
        _row(1, "Flutter 프레임워크 선택 이유 논의"),
        _row(2, "와이어프레임 초안 작성"),
        _row(3, "실시간 채팅 웹소켓 설계"),
        _row(4, "회의록 정리 담당자 배정"),
        _row(5, "테스트 서버 배포 일정"),
    ]
    fake_collection = MagicMock()
    fake_collection.query.return_value = {"ids": [[]], "distances": [[]]}

    with patch.object(qa_engine, "get_collection", return_value=fake_collection):
        selected, _ = qa_engine._rank_mysql_rows(
            project_id=1,
            rows=rows,
            queries=["Flutter 프레임워크 선택 이유"],
            limit=5,
        )

    assert [r["id"] for r in selected] == [1]


def test_rank_mysql_rows_without_floor_keeps_all_rows_for_enumeration():
    """apply_floor=False면 관련도 컷 없이 limit까지 채운다.

    query_structured_memory("액션 아이템 목록")는 열거가 계약이라, precision용 컷을
    공유하면 명백히 관련 있는 행("푸시 알림 연동")까지 잘려 목록이 사실과 달라졌다.
    """
    rows = [
        _row(1, "알림 로직 리팩토링"),
        _row(2, "푸시 알림 연동 작업"),
        _row(3, "결제 모듈 연동"),
        _row(4, "DB 인덱스 추가"),
    ]
    fake_collection = MagicMock()
    fake_collection.query.return_value = {"ids": [[]], "distances": [[]]}

    with patch.object(qa_engine, "get_collection", return_value=fake_collection):
        floored, _ = qa_engine._rank_mysql_rows(
            project_id=1, rows=rows, queries=["알림 로직"], limit=4
        )
        listed, _ = qa_engine._rank_mysql_rows(
            project_id=1, rows=rows, queries=["알림 로직"], limit=4, apply_floor=False
        )

    assert [r["id"] for r in floored] == [1]        # 컨텍스트 경로: 컷 유지
    assert sorted(r["id"] for r in listed) == [1, 2, 3, 4]  # 열거 경로: 전부 유지
    assert listed[0]["id"] == 1                     # 순위는 그대로 매겨진다


def test_memory_vector_pool_is_independent_of_final_row_limit():
    """벡터 이웃 후보 수는 MYSQL_CANDIDATE_POOL을 따라야 한다 — 최종 선정 개수인
    MYSQL_TOP_N(4)을 그대로 n_results로 넘기면 융합할 재료가 4개로 줄어 랭킹이 나빠진다.
    두 상수를 한 이름으로 공유하던 것을 분리한 회귀 테스트."""
    rows = [_row(i, f"기록 {i}") for i in range(1, 21)]
    fake_collection = MagicMock()
    fake_collection.query.return_value = {"ids": [[]], "distances": [[]]}

    with patch.object(qa_engine, "get_collection", return_value=fake_collection):
        qa_engine._memory_vector_rank_lists(project_id=1, queries=["질문"], rows=rows)

    assert fake_collection.query.call_args.kwargs["n_results"] == qa_engine.MYSQL_CANDIDATE_POOL
    assert qa_engine.MYSQL_CANDIDATE_POOL > qa_engine.MYSQL_TOP_N


def test_distance_threshold_ignores_rows_outside_the_candidate_set():
    """F-007: 임계값 기준선은 허용 후보 안에서 잡아야 한다.

    Chroma where절은 project/item_type만 거르므로 category 분기가 rows에 일부만 넘겨도
    프로젝트 전체가 돌아온다. 전체 distances로 min을 잡으면 제외 대상이 기준선을 만들어
    (제외 0.10 → cutoff 0.25) 후보 최적 행(0.40)까지 잘려 벡터 축이 통째로 사라진다.
    """
    rows = [_row(1, "허용 후보"), _row(2, "허용 후보 2")]
    excluded_id = qa_engine.memory_vector_id(999)  # rows에 없는 = 다른 카테고리 행
    fake_collection = MagicMock()
    fake_collection.query.return_value = {
        "ids": [[excluded_id, qa_engine.memory_vector_id(1), qa_engine.memory_vector_id(2)]],
        "distances": [[0.10, 0.40, 0.45]],
    }

    with patch.object(qa_engine, "get_collection", return_value=fake_collection):
        rank_lists, hits = qa_engine._memory_vector_rank_lists(
            project_id=1, queries=["질문"], rows=rows,
        )

    # 기준선이 0.40이므로 MARGIN(0.15) 안의 0.45도 살아남는다
    assert [h["memory_id"] for h in hits] == [1, 2]
    assert rank_lists and rank_lists[0] == [0, 1]


def test_history_row_renders_reason_exactly_once():
    """F-010: 이력 행에서 reason이 두 번 붙지 않는다.

    _row_line_body()에 reason 렌더링을 추가하면서 _format_history_row()의 기존 append를
    제거하지 않아 "이유: X 이유: X"가 LLM 입력과 RAGAS rendered 컨텍스트에 들어갔다.
    """
    row = {
        "id": 7, "category": "decision", "content": "배포는 주 1회로 한다.",
        "reason": "롤백 비용이 크기 때문", "topic": None, "owner": None,
        "date": None, "due_date": None, "completed_at": None,
        "source": "minutes.md", "superseded_by": None,
    }
    assert qa_engine._row_line_body(row).count("이유:") == 1
    assert qa_engine._format_history_row(row, "[decision #7][최신]").count("이유:") == 1


def test_category_match_branch_is_capped_like_the_unmatched_branch(monkeypatch):
    """category가 잡힌 질문도 미매칭 분기와 같은 상한(MYSQL_TOP_N)을 받아야 한다.

    이전엔 매칭 분기만 QA_MYSQL_ROWS_LIMIT(60)에서 보충분을 뺀 55개까지 열려 있어,
    "결정" 같은 키워드가 하나 걸리면 그 카테고리 행이 사실상 전부 컨텍스트에 실렸다
    (실측 한 문항에서 SQL 컨텍스트 42~57개). 여기서는 전 행을 동점으로 만들어
    관련도 threshold가 아니라 상한이 개수를 정하는지만 본다.
    """
    rows = [
        {"id": i, "project_id": 1, "category": "decision",
         "content": "로그인 방식을 소셜 로그인으로 결정한다.", "reason": None,
         "topic": None, "owner": None, "date": None, "due_date": None,
         "completed_at": None, "source": "minutes.md", "superseded_by": None}
        for i in range(1, 31)
    ]
    monkeypatch.setattr(qa_engine.mysql_search, "search",
                        lambda pid, **kwargs: [dict(r) for r in rows])
    fake_collection = MagicMock()
    fake_collection.get.return_value = {"documents": [], "metadatas": [], "ids": []}
    fake_collection.query.side_effect = RuntimeError("vector unavailable in test")

    with patch.object(qa_engine, "get_collection", return_value=fake_collection):
        _, _, debug = qa_engine._build_context(
            1, "로그인 방식 결정은 무엇인가?", history_mode=False, query_variants=[],
        )

    assert debug["filters"]["category"] == "decision"  # 매칭 분기를 탔는지 확인
    assert len(debug["mysql_rows"]) == qa_engine.MYSQL_TOP_N
