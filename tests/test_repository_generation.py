from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi import BackgroundTasks

from backend.api.repository import (
    SyncRequest,
    _claim_sync_run,
    _cleanup_repo_generation,
    _collect_repo_sources,
    _detect_published_generation_supersedes,
    _set_repo_status,
    _sync_owned,
    _utc_iso,
    get_repository_status,
    sync_repository,
)
from backend.api.suggestion import _resolve_suggestion


RUN_ID = "11111111-1111-1111-1111-111111111111"
ACTIVE_RUN_ID = "00000000-0000-0000-0000-000000000000"


def _connection():
    cursor = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn, cursor


def test_repository_run_timestamps_are_explicit_utc():
    assert _utc_iso(datetime(2026, 7, 28, 17, 0, 0)) == (
        "2026-07-28T17:00:00+00:00"
    )
    assert _utc_iso(
        datetime(
            2026,
            7,
            29,
            2,
            0,
            0,
            tzinfo=timezone(timedelta(hours=9)),
        )
    ) == "2026-07-28T17:00:00+00:00"


def test_claim_sync_run_creates_fenced_generation():
    conn, cursor = _connection()
    cursor.fetchone.side_effect = [
        {
            "id": 7,
            "project_id": 3,
            "status": "indexed",
            "current_sync_run_id": None,
        },
        {"sync_started_at": datetime(2026, 7, 30, 1, 2, 3)},
    ]
    with patch("backend.api.repository.get_connection", return_value=conn), patch(
        "backend.api.repository.uuid.uuid4", return_value=RUN_ID
    ):
        repo, run, created = _claim_sync_run(3, 7)

    assert created is True
    assert repo["id"] == 7
    assert run["run_id"] == RUN_ID
    update_sql, params = cursor.execute.call_args_list[1].args
    assert "current_sync_run_id=%s" in update_sql
    assert params == (RUN_ID, 7)
    conn.commit.assert_called_once()


def test_claim_sync_run_reuses_current_run_without_scheduling_duplicate():
    conn, cursor = _connection()
    cursor.fetchone.return_value = {
        "id": 7,
        "project_id": 3,
        "status": "syncing",
        "current_sync_run_id": ACTIVE_RUN_ID,
        "sync_started_at": datetime(2026, 7, 30, 1, 2, 3),
    }
    with patch("backend.api.repository.get_connection", return_value=conn):
        _, run, created = _claim_sync_run(3, 7)

    assert created is False
    assert run["run_id"] == ACTIVE_RUN_ID
    assert cursor.execute.call_count == 1


def test_sync_ownership_is_only_the_current_repository_fence():
    conn, cursor = _connection()
    cursor.fetchone.return_value = {
        "current_sync_run_id": RUN_ID,
        "status": "syncing",
    }

    with patch("backend.api.repository.get_connection", return_value=conn):
        assert _sync_owned(7, RUN_ID) is True

    sql = cursor.execute.call_args.args[0]
    assert "repositories" in sql
    assert "repository_sync_runs" not in sql


def test_success_publish_is_fenced_and_invalidates_summary_atomically():
    conn, cursor = _connection()
    cursor.fetchone.return_value = {"active_sync_run_id": ACTIVE_RUN_ID}
    cursor.rowcount = 1

    with patch("backend.api.repository.get_connection", return_value=conn):
        result = _set_repo_status(
            7,
            RUN_ID,
            "indexed",
            commit_sha="abc",
            indexed_files=4,
            last_error=None,
            sync_warning=None,
            project_id=3,
        )

    assert result == (True, ACTIVE_RUN_ID)
    sql_calls = [entry.args[0] for entry in cursor.execute.call_args_list]
    assert any("current_sync_run_id=%s" in sql and "FOR UPDATE" in sql for sql in sql_calls)
    assert any(sql.startswith("UPDATE repositories SET") for sql in sql_calls)
    assert any(sql.startswith("DELETE FROM project_memory") for sql in sql_calls)
    conn.commit.assert_called_once()


def test_failed_run_does_not_replace_active_commit_or_file_count():
    conn, cursor = _connection()
    cursor.fetchone.return_value = {"active_sync_run_id": ACTIVE_RUN_ID}
    cursor.rowcount = 1

    with patch("backend.api.repository.get_connection", return_value=conn):
        result = _set_repo_status(
            7,
            RUN_ID,
            "failed",
            commit_sha="must-not-replace",
            indexed_files=0,
            last_error="REPOSITORY_SYNC_FAILED",
        )

    assert result == (True, ACTIVE_RUN_ID)
    repo_sql = next(
        call.args[0]
        for call in cursor.execute.call_args_list
        if call.args[0].startswith("UPDATE repositories SET")
    )
    assert "active_sync_run_id" not in repo_sql
    assert "commit_sha" not in repo_sql
    assert "indexed_files" not in repo_sql


def test_late_worker_cannot_publish_after_fence_is_replaced():
    conn, cursor = _connection()
    cursor.fetchone.return_value = None
    with patch("backend.api.repository.get_connection", return_value=conn):
        result = _set_repo_status(7, RUN_ID, "indexed", project_id=3)

    assert result == (False, None)
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def test_generation_cleanup_never_deletes_active_generation():
    conn, cursor = _connection()
    cursor.fetchone.return_value = {"active_sync_run_id": RUN_ID}
    with patch("backend.api.repository.get_connection", return_value=conn), patch(
        "backend.db.chroma.get_existing_collection"
    ) as get_existing:
        _cleanup_repo_generation(7, RUN_ID)

    assert cursor.execute.call_count == 1
    get_existing.assert_not_called()


def test_generation_cleanup_deletes_only_the_exact_run():
    conn, cursor = _connection()
    cursor.fetchone.return_value = {"active_sync_run_id": RUN_ID}
    collection = MagicMock()
    collection.get.return_value = {
        "ids": ["old-memory", "new-staging", "legacy"],
        "metadatas": [
            {"repo_sync_run_id": ACTIVE_RUN_ID},
            {"repo_sync_run_id": RUN_ID},
            {},
        ],
    }

    with patch("backend.api.repository.get_connection", return_value=conn), patch(
        "backend.db.chroma.get_existing_collection", return_value=collection
    ):
        _cleanup_repo_generation(7, ACTIVE_RUN_ID)

    sql, params = cursor.execute.call_args_list[-1].args
    assert "repo_sync_run_id <=> %s" in sql
    assert "NOT (r.active_sync_run_id <=> %s)" in sql
    assert params == (7, ACTIVE_RUN_ID, ACTIVE_RUN_ID)
    collection.get.assert_called_once_with(where={"repo_id": 7})
    collection.delete.assert_called_once_with(ids=["old-memory"])


def test_legacy_generation_cleanup_matches_missing_or_empty_vector_metadata():
    conn, cursor = _connection()
    cursor.fetchone.return_value = {"active_sync_run_id": RUN_ID}
    collection = MagicMock()
    collection.get.return_value = {
        "ids": ["missing", "empty", "published"],
        "metadatas": [
            {},
            {"repo_sync_run_id": ""},
            {"repo_sync_run_id": RUN_ID},
        ],
    }

    with patch("backend.api.repository.get_connection", return_value=conn), patch(
        "backend.db.chroma.get_existing_collection", return_value=collection
    ):
        _cleanup_repo_generation(7, None)

    assert cursor.execute.call_args_list[-1].args[1] == (7, None, None)
    collection.delete.assert_called_once_with(ids=["missing", "empty"])


def test_generation_cleanup_skips_chroma_when_mysql_state_is_unavailable():
    with patch(
        "backend.api.repository.get_connection",
        side_effect=RuntimeError("mysql unavailable"),
    ), patch("backend.db.chroma.get_existing_collection") as get_existing:
        _cleanup_repo_generation(7, RUN_ID)

    get_existing.assert_not_called()


def test_status_counts_only_active_generation():
    conn, cursor = _connection()
    started = datetime(2026, 7, 28, 17, 0, 0)
    cursor.fetchone.return_value = {
        "id": 7,
        "provider": "github",
        "repository_url": "https://github.com/o/r",
        "branch": "main",
        "status": "failed",
        "commit_sha": "still-active",
        "indexed_files": 4,
        "last_error": "REPOSITORY_SYNC_FAILED",
        "sync_warning": None,
        "active_sync_run_id": ACTIVE_RUN_ID,
        "current_sync_run_id": None,
        "sync_started_at": started,
    }
    cursor.fetchall.return_value = [{"category": "decision", "cnt": 3}]

    with patch("backend.api.repository.require_project_access"), patch(
        "backend.api.repository.get_connection", return_value=conn
    ):
        result = get_repository_status(3, 7)

    assert result["status"] == "failed"
    assert result["run_id"] is None
    assert result["commit_sha"] == "still-active"
    assert result["extracted"]["decision"] == 3
    count_call = next(
        entry for entry in cursor.execute.call_args_list if "COUNT(*)" in entry.args[0]
    )
    assert count_call.args[1] == (7, ACTIVE_RUN_ID, ACTIVE_RUN_ID)


def test_published_generation_defers_supersede_until_after_publish():
    conn, cursor = _connection()
    cursor.fetchall.return_value = [
        {
            "id": 91,
            "content": "새 배포 정책을 적용한다",
            "topic": "배포",
            "reason": "안정성",
            "date": datetime(2026, 7, 28).date(),
        }
    ]
    with patch("backend.api.repository.get_connection", return_value=conn), patch(
        "backend.reconciler.supersede.detect_supersede"
    ) as detect:
        _detect_published_generation_supersedes(3, 7, RUN_ID)

    detect.assert_called_once()
    assert cursor.execute.call_args.args[1] == (3, 7, RUN_ID)


def test_sync_response_identifies_run_and_repeated_call_does_not_duplicate():
    started = datetime(2026, 7, 28, 17, 0, 0)
    repo = {"repository_url": "https://github.com/o/r", "branch": "main"}
    run = {"run_id": RUN_ID, "started_at": started}

    first_background = BackgroundTasks()
    with patch("backend.api.repository.require_project_access"), patch(
        "backend.api.repository._get_github_token", return_value=None
    ), patch(
        "backend.api.repository._claim_sync_run", return_value=(repo, run, True)
    ):
        first = sync_repository(3, 7, first_background, SyncRequest())

    assert first["run_id"] == RUN_ID
    assert first["sync_started_at"] == "2026-07-28T17:00:00+00:00"
    assert first_background.tasks[0].args[2] == RUN_ID

    repeated_background = BackgroundTasks()
    with patch("backend.api.repository.require_project_access"), patch(
        "backend.api.repository._get_github_token", return_value=None
    ), patch(
        "backend.api.repository._claim_sync_run", return_value=(repo, run, False)
    ):
        repeated = sync_repository(3, 7, repeated_background, SyncRequest())

    assert repeated["run_id"] == RUN_ID
    assert repeated_background.tasks == []


def test_accepting_supersede_closes_other_pending_edges_to_hidden_memory():
    conn, cursor = _connection()
    row = {
        "id": 8,
        "project_id": 1,
        "memory_id": 10,
        "kind": "supersede",
        "evidence": '{"type":"supersede","superseding_memory_id":42}',
        "rationale": "new decision replaces old",
        "confidence": "high",
        "status": "pending",
        "created_at": "2026-07-30 00:00:00",
        "resolved_at": None,
        "resolved_by": None,
        "memory_category": "decision",
        "memory_completed_at": None,
        "memory_due_date": None,
        "memory_superseded_by": None,
    }
    updated = {**row, "status": "accepted", "resolved_by": 99}
    cursor.fetchone.side_effect = [row, {"id": 42}, updated]
    cursor.rowcount = 1

    with patch("backend.api.suggestion.require_project_access"), patch(
        "backend.api.suggestion.get_current_user_id", return_value=99
    ), patch(
        "backend.api.suggestion.get_connection", return_value=conn
    ), patch(
        "backend.retriever.memory_vector.delete_memory_vector"
    ), patch(
        "backend.project_memory.refresh_project_memory_after_delete"
    ):
        result = _resolve_suggestion(1, 8, "accepted")

    assert result["status"] == "accepted"
    competing = next(
        entry
        for entry in cursor.execute.call_args_list
        if "SET status='rejected'" in entry.args[0]
    )
    assert competing.args[1] == (99, 1, 8, 10, 10)
    conn.commit.assert_called_once()


def test_collection_pins_branch_head_and_uses_it_for_commit_and_readme():
    responses = [
        {"sha": "abc123"},
        [
            {
                "sha": "abc123",
                "commit": {"message": "head", "author": {"date": "2026-07-30"}},
            }
        ],
        {},
        [],
        [],
    ]
    with patch("backend.api.repository._gh_get", side_effect=responses) as get:
        sources, latest, warnings = _collect_repo_sources("o/r", "main")

    assert latest == "abc123"
    assert warnings == []
    paths = [entry.args[0] for entry in get.call_args_list]
    assert paths[0] == "/repos/o/r/commits/main"
    assert "sha=abc123" in paths[1]
    assert "ref=abc123" in paths[2]
    assert "commits.txt" in sources
