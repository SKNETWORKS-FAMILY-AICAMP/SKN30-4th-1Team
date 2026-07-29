"""Chroma 삭제 경로가 임베딩 클라이언트를 요구하지 않는지 고정한다.

`get_collection()` 은 임베딩 함수를 만들려고 OPENAI_API_KEY 를 요구한다(placeholder 도 거부).
그러나 metadata 조건 삭제에는 임베딩이 필요 없다. 키가 없거나 만료된 환경에서
`get_collection()` 을 타면:

- 감싸이지 않은 경로(project 삭제)는 500 으로 실패한다
- try/except 로 감싸인 경로(repository 정리)는 조용히 벡터를 남긴다
  → 삭제한 저장소 내용이 계속 검색에 잡힌다

`delete_from_existing_collection()` 이 그 용도의 헬퍼이며 quota 의 문서 정리 경로는
이미 이것을 쓴다. 이 테스트는 나머지 경로도 같은 계약을 지키는지 단언한다.
"""
from unittest.mock import MagicMock, patch

from backend.api import repository as repository_module


def _silent_conn():
    """DB 접근을 무해하게 만드는 커넥션 목."""
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = None
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    return conn


def test_clear_repo_indexed_data_uses_key_free_delete():
    """저장소 재동기화 전 정리가 임베딩 클라이언트를 만들지 않는다."""
    with patch.object(repository_module, "get_connection", return_value=_silent_conn()), \
         patch("backend.db.chroma.delete_from_existing_collection") as key_free, \
         patch("backend.db.chroma.get_collection") as needs_key:
        repository_module._clear_repo_indexed_data(repo_id=7)

    key_free.assert_called_once_with(where={"repo_id": 7})
    needs_key.assert_not_called()


def test_delete_repo_data_uses_key_free_delete():
    """저장소 삭제가 임베딩 클라이언트를 만들지 않는다."""
    with patch.object(repository_module, "get_connection", return_value=_silent_conn()), \
         patch("backend.db.chroma.delete_from_existing_collection") as key_free, \
         patch("backend.db.chroma.get_collection") as needs_key:
        repository_module._delete_repo_data(repo_id=9)

    key_free.assert_called_once_with(where={"repo_id": 9})
    needs_key.assert_not_called()


def test_documents_module_has_no_dead_chroma_helper():
    """`_delete_chroma_vectors` 는 호출부가 0인 죽은 코드였다.

    `quota._delete_doc_vectors` 가 같은 doc_id 조건으로 실제 삭제를 수행한다.
    되살아나면 키를 요구하는 경로가 다시 생기므로 부재를 고정한다.
    """
    from backend.api import documents as documents_module

    assert not hasattr(documents_module, "_delete_chroma_vectors")
