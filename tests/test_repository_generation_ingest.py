from unittest.mock import MagicMock, patch

from backend.pipeline.ingestor import ingest
from backend.pipeline.models import MemoryItem


def _connection(lastrowid=41):
    cursor = MagicMock()
    cursor.lastrowid = lastrowid
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    return conn, cursor


def test_repository_ingest_tags_mysql_and_chroma_with_sync_run():
    conn, cursor = _connection()
    collection = MagicMock()
    item = MemoryItem(category="decision", content="세대 게시를 적용한다")

    with patch(
        "backend.pipeline.ingestor.get_connection", return_value=conn
    ), patch(
        "backend.pipeline.ingestor.get_collection", return_value=collection
    ), patch(
        "backend.pipeline.ingestor.upsert_memory_vectors"
    ) as upsert_vectors, patch(
        "backend.reconciler.supersede.detect_supersede"
    ) as detect_supersede:
        ingest(
            project_id=3,
            doc_id=None,
            repo_id=7,
            repo_sync_run_id="run-123",
            items=[item],
            raw_text="세대 게시 원문",
            source="README.md",
            date="",
            doc_type="repository",
        )

    memory_insert = next(
        call
        for call in cursor.execute.call_args_list
        if "INSERT INTO memory" in call.args[0]
        and "memory_sources" not in call.args[0]
    )
    assert "repo_sync_run_id" in memory_insert.args[0]
    assert "run-123" in memory_insert.args[1]

    [vector_row] = upsert_vectors.call_args.args[0]
    assert vector_row["repo_sync_run_id"] == "run-123"

    chunk_call = collection.add.call_args.kwargs
    assert all("run-123" in chunk_id for chunk_id in chunk_call["ids"])
    assert chunk_call["metadatas"][0]["repo_sync_run_id"] == "run-123"
    assert chunk_call["metadatas"][0]["repo_sync_staging"] is True
    detect_supersede.assert_not_called()


def test_document_ingest_keeps_generation_empty_and_non_staging():
    conn, _ = _connection()
    collection = MagicMock()

    with patch(
        "backend.pipeline.ingestor.get_connection", return_value=conn
    ), patch(
        "backend.pipeline.ingestor.get_collection", return_value=collection
    ), patch(
        "backend.pipeline.ingestor.upsert_memory_vectors"
    ):
        ingest(
            project_id=3,
            doc_id=9,
            items=[],
            raw_text="문서 원문",
            source="meeting.md",
            date="",
            doc_type="meeting",
        )

    chunk_call = collection.add.call_args.kwargs
    assert all(chunk_id.startswith("doc9_") for chunk_id in chunk_call["ids"])
    assert chunk_call["metadatas"][0]["repo_sync_run_id"] == ""
    assert chunk_call["metadatas"][0]["repo_sync_staging"] is False
