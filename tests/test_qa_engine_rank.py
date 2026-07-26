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
