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
