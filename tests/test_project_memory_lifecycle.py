from types import SimpleNamespace
from unittest.mock import MagicMock

from backend import project_memory
from backend.retriever import memory_vector


def _conn_with_cursor(cursor):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn


class _FakeLLM:
    """프로젝트 요약 재생성 테스트용 LLM stub."""

    def invoke(self, prompt):
        return SimpleNamespace(content="남은 항목 기반 새 요약")


def test_regenerate_project_memory_deletes_summary_when_no_memory(monkeypatch):
    """남은 memory가 0건이면 project_memory 행을 삭제한다."""
    select_cursor = MagicMock()
    select_cursor.fetchall.return_value = []
    delete_cursor = MagicMock()
    monkeypatch.setattr(
        project_memory,
        "get_connection",
        MagicMock(side_effect=[
            _conn_with_cursor(select_cursor),
            _conn_with_cursor(delete_cursor),
        ]),
    )

    assert project_memory.regenerate_project_memory(1) == ""

    delete_cursor.execute.assert_called_once_with(
        "DELETE FROM project_memory WHERE project_id = %s",
        (1,),
    )


def test_regenerate_project_memory_summarizes_remaining_memory(monkeypatch):
    """남은 memory가 있으면 기존 요약을 덮어쓴다."""
    select_cursor = MagicMock()
    select_cursor.fetchall.return_value = [
        {
            "category": "decision",
            "content": "남은 결정만 유지한다",
            "owner": "박제섭",
            "due_date": None,
            "completed_at": None,
        }
    ]
    upsert_cursor = MagicMock()
    monkeypatch.setattr(
        project_memory,
        "get_connection",
        MagicMock(side_effect=[
            _conn_with_cursor(select_cursor),
            _conn_with_cursor(upsert_cursor),
        ]),
    )
    monkeypatch.setattr(project_memory, "get_chat_model", lambda **kwargs: _FakeLLM())

    assert project_memory.regenerate_project_memory(1) == "남은 항목 기반 새 요약"

    sql_calls = [call.args[0] for call in upsert_cursor.execute.call_args_list]
    assert any("ON DUPLICATE KEY UPDATE summary" in sql for sql in sql_calls)
    # G-001: 요약 재료는 active_memory 뷰에서 읽는다 — superseded 결정이 요약에 들어가지 않도록
    assert "FROM active_memory" in select_cursor.execute.call_args.args[0]


def test_cleanup_orphan_memory_vectors_removes_missing_project_or_memory(monkeypatch):
    """존재하지 않는 project_id/memory_id를 가리키는 memory 벡터를 삭제한다."""
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {"id": 20, "project_id": 2, "superseded_by": None}
    ]
    collection = MagicMock()
    collection.get.return_value = {
        "ids": ["memory:10", "memory:20", "doc:1"],
        "metadatas": [
            {"item_type": "memory", "project_id": 1, "memory_id": 10},
            {"item_type": "memory", "project_id": 2, "memory_id": 20},
            {"item_type": "document", "project_id": 1},
        ],
    }
    monkeypatch.setattr(memory_vector, "get_connection", lambda: _conn_with_cursor(cursor))
    monkeypatch.setattr(memory_vector, "get_collection", lambda: collection)

    assert memory_vector.cleanup_orphan_memory_vectors() == 1

    collection.delete.assert_called_once_with(ids=["memory:10"])


def test_cleanup_removes_superseded_memory_vectors(monkeypatch):
    """F-002: superseded된 memory의 벡터도 시작 시 정리한다(자기치유).

    accept 시점의 delete_memory_vector가 실패했거나 과거 백필이 되살린 비활성 벡터가
    후보 top-N 슬롯을 차지하지 못하도록, MySQL superseded_by 상태로 수렴시킨다."""
    cursor = MagicMock()
    # active_memory 스냅샷은 superseded row를 이미 제외한다.
    cursor.fetchall.return_value = [
        {"id": 42, "project_id": 1, "superseded_by": None}
    ]
    collection = MagicMock()
    collection.get.return_value = {
        "ids": ["memory:10", "memory:42"],
        "metadatas": [
            {"item_type": "memory", "project_id": 1, "memory_id": 10},
            {"item_type": "memory", "project_id": 1, "memory_id": 42},
        ],
    }
    monkeypatch.setattr(memory_vector, "get_connection", lambda: _conn_with_cursor(cursor))
    monkeypatch.setattr(memory_vector, "get_collection", lambda: collection)

    assert memory_vector.cleanup_orphan_memory_vectors() == 1

    collection.delete.assert_called_once_with(ids=["memory:10"])


def test_backfill_skips_superseded_rows(monkeypatch):
    """F-002: 백필은 superseded_by IS NULL인 row만 색인한다.

    accept가 지운 비활성 벡터를 서버 재시작이 재생성해 D-4를 무력화하지 않도록."""
    cursor = MagicMock()
    live_row = {"id": 42, "superseded_by": None}
    cursor.fetchall.return_value = [live_row]
    collection = MagicMock()
    collection.get.return_value = {"ids": []}
    monkeypatch.setattr(memory_vector, "cleanup_orphan_memory_vectors", lambda: 0)
    monkeypatch.setattr(memory_vector, "get_connection", lambda: _conn_with_cursor(cursor))
    monkeypatch.setattr(memory_vector, "get_collection", lambda: collection)
    upserted = []
    monkeypatch.setattr(memory_vector, "upsert_memory_vectors",
                        lambda rows: upserted.extend(rows) or len(list(upserted)))

    memory_vector.backfill_memory_vectors()

    select_sql = cursor.execute.call_args_list[0].args[0]
    assert "FROM active_memory" in select_sql
    assert upserted == [live_row]
