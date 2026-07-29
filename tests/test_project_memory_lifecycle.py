from types import SimpleNamespace
from threading import Event, Thread
from unittest.mock import MagicMock

from backend import graph
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
        graph,
        "get_connection",
        MagicMock(side_effect=[
            _conn_with_cursor(select_cursor),
            _conn_with_cursor(delete_cursor),
        ]),
    )

    assert graph.regenerate_project_memory(1) == ""

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
        graph,
        "get_connection",
        MagicMock(side_effect=[
            _conn_with_cursor(select_cursor),
            _conn_with_cursor(upsert_cursor),
        ]),
    )
    monkeypatch.setattr(graph, "get_chat_model", lambda **kwargs: _FakeLLM())

    assert graph.regenerate_project_memory(1) == "남은 항목 기반 새 요약"

    sql_calls = [call.args[0] for call in upsert_cursor.execute.call_args_list]
    assert any("ON DUPLICATE KEY UPDATE summary" in sql for sql in sql_calls)
    # G-001: 요약 재료는 active_memory 뷰에서 읽는다 — superseded 결정이 요약에 들어가지 않도록
    assert "FROM active_memory" in select_cursor.execute.call_args.args[0]


def test_repository_publish_waits_for_summary_writer_then_invalidates_it(monkeypatch):
    """오래된 writer가 게시 뒤에 summary를 다시 살리지 못한다."""
    from backend.api import repository

    writer_in_llm = Event()
    release_writer = Event()
    publisher_started = Event()
    publisher_done = Event()
    errors = []
    publish_result = []

    class _BlockingLLM:
        def invoke(self, prompt):
            writer_in_llm.set()
            if not release_writer.wait(5):
                raise TimeoutError("writer release timed out")
            return SimpleNamespace(content="이전 generation 요약")

    select_cursor = MagicMock()
    select_cursor.fetchall.return_value = [{
        "category": "decision",
        "content": "이전 generation 결정",
        "owner": None,
        "due_date": None,
        "completed_at": None,
        "completion_status": None,
    }]
    upsert_cursor = MagicMock()
    summary_connections = MagicMock(side_effect=[
        _conn_with_cursor(select_cursor),
        _conn_with_cursor(upsert_cursor),
    ])
    monkeypatch.setattr(graph, "get_connection", summary_connections)
    monkeypatch.setattr(graph, "get_chat_model", lambda **kwargs: _BlockingLLM())

    publish_cursor = MagicMock()
    publish_cursor.rowcount = 1
    publish_cursor.fetchone.return_value = {"active_sync_run_id": "run-a"}
    publish_conn = _conn_with_cursor(publish_cursor)
    publish_connection = MagicMock(return_value=publish_conn)
    monkeypatch.setattr(repository, "get_connection", publish_connection)

    def write_old_summary():
        try:
            graph.regenerate_project_memory(77)
        except BaseException as exc:
            errors.append(exc)

    def publish_new_generation():
        publisher_started.set()
        try:
            publish_result.append(repository._set_repo_status(
                7,
                "run-b",
                "indexed",
                project_id=77,
            ))
        except BaseException as exc:
            errors.append(exc)
        finally:
            publisher_done.set()

    writer = Thread(target=write_old_summary, daemon=True)
    publisher = Thread(target=publish_new_generation, daemon=True)
    writer.start()
    assert writer_in_llm.wait(5)
    publisher.start()
    assert publisher_started.wait(5)

    # Publication must not even open its DB transaction while the stale writer
    # owns the project lock.
    assert publish_connection.call_count == 0
    assert not publisher_done.is_set()

    release_writer.set()
    writer.join(5)
    publisher.join(5)

    assert not writer.is_alive()
    assert not publisher.is_alive()
    assert errors == []
    assert publish_result == [(True, "run-a")]
    assert any(
        "ON DUPLICATE KEY UPDATE summary" in entry.args[0]
        for entry in upsert_cursor.execute.call_args_list
    )
    assert any(
        entry.args[0].startswith("DELETE FROM project_memory")
        and entry.args[1] == (77,)
        for entry in publish_cursor.execute.call_args_list
    )


def test_cleanup_orphan_memory_vectors_removes_missing_project_or_memory(monkeypatch):
    """존재하지 않는 project_id/memory_id를 가리키는 memory 벡터를 삭제한다."""
    active_row = {"id": 20, "project_id": 2}
    collection = MagicMock()
    collection.get.return_value = {
        "ids": ["memory:10", "memory:20", "doc:1"],
        "metadatas": [
            {"item_type": "memory", "project_id": 1, "memory_id": 10},
            {"item_type": "memory", "project_id": 2, "memory_id": 20},
            {"item_type": "document", "project_id": 1},
        ],
    }
    monkeypatch.setattr(
        memory_vector,
        "_capture_all_active_memory_rows",
        lambda: [active_row],
    )
    monkeypatch.setattr(memory_vector, "get_collection", lambda: collection)

    assert memory_vector.cleanup_orphan_memory_vectors() == 1

    collection.delete.assert_called_once_with(ids=["memory:10"])


def test_cleanup_removes_memory_with_visible_successor(monkeypatch):
    """active snapshot에 없는 predecessor 벡터는 시작 시 정리한다."""
    active_row = {"id": 42, "project_id": 1}
    collection = MagicMock()
    collection.get.return_value = {
        "ids": ["memory:10", "memory:42"],
        "metadatas": [
            {"item_type": "memory", "project_id": 1, "memory_id": 10},
            {"item_type": "memory", "project_id": 1, "memory_id": 42},
        ],
    }
    monkeypatch.setattr(
        memory_vector,
        "_capture_all_active_memory_rows",
        lambda: [active_row],
    )
    monkeypatch.setattr(memory_vector, "get_collection", lambda: collection)

    assert memory_vector.cleanup_orphan_memory_vectors() == 1

    collection.delete.assert_called_once_with(ids=["memory:10"])


def test_cleanup_keeps_predecessor_when_successor_is_not_published(monkeypatch):
    """숨겨진 successor는 기존 published predecessor를 비활성화하지 않는다."""
    predecessor = {"id": 10, "project_id": 1}
    collection = MagicMock()
    collection.get.return_value = {
        "ids": ["memory:10", "memory:20"],
        "metadatas": [
            {"item_type": "memory", "project_id": 1, "memory_id": 10},
            {"item_type": "memory", "project_id": 1, "memory_id": 20},
        ],
    }
    monkeypatch.setattr(
        memory_vector,
        "_capture_all_active_memory_rows",
        lambda: [predecessor],
    )
    monkeypatch.setattr(memory_vector, "get_collection", lambda: collection)

    assert memory_vector.cleanup_orphan_memory_vectors() == 1

    collection.delete.assert_called_once_with(ids=["memory:20"])


def test_startup_vector_snapshot_reads_active_memory_view(monkeypatch):
    cursor = MagicMock()
    cursor.fetchall.return_value = [{"id": 10, "project_id": 1}]
    monkeypatch.setattr(
        memory_vector,
        "get_connection",
        lambda: _conn_with_cursor(cursor),
    )
    rows = memory_vector._capture_all_active_memory_rows()

    assert rows == [{"id": 10, "project_id": 1}]
    assert cursor.execute.call_args.args[0] == (
        "SELECT * FROM active_memory ORDER BY id"
    )


def test_backfill_reconciles_against_active_snapshot(monkeypatch):
    """백필은 inactive 벡터를 지우고 active 누락 row만 복원한다."""
    live_row = {"id": 42, "project_id": 1}
    collection = MagicMock()
    collection.get.return_value = {
        "ids": ["memory:10"],
        "metadatas": [
            {"item_type": "memory", "project_id": 1, "memory_id": 10},
        ],
    }
    monkeypatch.setattr(
        memory_vector,
        "_capture_all_active_memory_rows",
        lambda: [live_row],
    )
    monkeypatch.setattr(memory_vector, "get_collection", lambda: collection)
    upserted = []
    monkeypatch.setattr(
        memory_vector,
        "upsert_memory_vectors",
        lambda rows: upserted.extend(rows) or len(rows),
    )

    assert memory_vector.backfill_memory_vectors() == 1

    collection.delete.assert_called_once_with(ids=["memory:10"])
    assert upserted == [live_row]
