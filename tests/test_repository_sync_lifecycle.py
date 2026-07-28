"""Minimal repository generation fencing and status contract tests."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi import BackgroundTasks

from backend.api.repository import (
    SyncRequest,
    _claim_sync_run,
    _cleanup_repo_generation,
    _detect_published_generation_supersedes,
    _set_repo_status,
    _sync_owned,
    _utc_iso,
    get_repository_status,
    sync_repository,
)


RUN_ID = "11111111-1111-1111-1111-111111111111"
ACTIVE_RUN_ID = "00000000-0000-0000-0000-000000000000"


def _connection():
    cursor = MagicMock()
    cursor.rowcount = 1
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
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


def test_claim_sync_run_uses_repository_row_as_the_only_run_record():
    conn, cursor = _connection()
    started = datetime(2026, 7, 28, 17, 0, 0)
    repo = {
        "id": 7,
        "project_id": 3,
        "repository_url": "https://github.com/o/r",
        "branch": "main",
        "status": "indexed",
        "active_sync_run_id": ACTIVE_RUN_ID,
        "current_sync_run_id": None,
    }
    cursor.fetchone.side_effect = [repo, {"sync_started_at": started}]

    with patch("backend.api.repository.get_connection", return_value=conn), patch(
        "backend.api.repository.uuid.uuid4", return_value=RUN_ID
    ):
        returned_repo, run, created = _claim_sync_run(3, 7)

    assert created is True
    assert returned_repo["active_sync_run_id"] == ACTIVE_RUN_ID
    assert run == {"run_id": RUN_ID, "started_at": started}
    sql_calls = [entry.args[0] for entry in cursor.execute.call_args_list]
    assert "FOR UPDATE" in sql_calls[0]
    claim_sql = next(sql for sql in sql_calls if sql.startswith("UPDATE repositories"))
    assert "current_sync_run_id" in claim_sql
    assert "sync_started_at=UTC_TIMESTAMP(6)" in claim_sql
    assert "active_sync_run_id" not in claim_sql
    assert not any("repository_sync_runs" in sql for sql in sql_calls)


def test_claim_sync_run_reuses_the_current_run_without_duplicate_work():
    conn, cursor = _connection()
    started = datetime(2026, 7, 28, 17, 0, 0)
    cursor.fetchone.return_value = {
        "id": 7,
        "project_id": 3,
        "status": "syncing",
        "current_sync_run_id": "live-run",
        "sync_started_at": started,
    }

    with patch("backend.api.repository.get_connection", return_value=conn):
        _repo, run, created = _claim_sync_run(3, 7)

    assert created is False
    assert run == {"run_id": "live-run", "started_at": started}
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


def test_success_publish_is_fenced_and_returns_exact_previous_generation():
    conn, cursor = _connection()
    cursor.fetchone.return_value = {"active_sync_run_id": ACTIVE_RUN_ID}

    with patch("backend.api.repository.get_connection", return_value=conn):
        published, previous = _set_repo_status(
            7,
            RUN_ID,
            "indexed",
            commit_sha="abc",
            indexed_files=4,
            last_error=None,
            sync_warning=None,
        )

    assert (published, previous) == (True, ACTIVE_RUN_ID)
    lock_sql = cursor.execute.call_args_list[0].args[0]
    assert "current_sync_run_id=%s" in lock_sql
    assert "FOR UPDATE" in lock_sql
    repo_call = next(
        entry
        for entry in cursor.execute.call_args_list
        if entry.args[0].startswith("UPDATE repositories SET")
    )
    repo_sql, repo_params = repo_call.args
    assert "active_sync_run_id=%s" in repo_sql
    assert "WHERE id=%s AND current_sync_run_id=%s" in repo_sql
    assert RUN_ID in repo_params
    assert "abc" in repo_params
    suggestion_cleanup = next(
        entry
        for entry in cursor.execute.call_args_list
        if "UPDATE memory_suggestions" in entry.args[0]
    )
    assert suggestion_cleanup.args[1] == (7, RUN_ID, 7, RUN_ID)


def test_failed_run_preserves_active_generation_commit_and_file_count():
    conn, cursor = _connection()
    cursor.fetchone.return_value = {"active_sync_run_id": ACTIVE_RUN_ID}

    with patch("backend.api.repository.get_connection", return_value=conn):
        finished, previous = _set_repo_status(
            7,
            RUN_ID,
            "failed",
            commit_sha="must-not-replace",
            indexed_files=0,
            last_error="REPOSITORY_SYNC_FAILED",
        )

    assert (finished, previous) == (True, ACTIVE_RUN_ID)
    repo_sql = next(
        entry.args[0]
        for entry in cursor.execute.call_args_list
        if entry.args[0].startswith("UPDATE repositories SET")
    )
    assert "active_sync_run_id" not in repo_sql
    assert "commit_sha" not in repo_sql
    assert "indexed_files" not in repo_sql


def test_late_worker_cannot_publish_after_fence_is_replaced():
    conn, cursor = _connection()
    cursor.fetchone.return_value = None

    with patch("backend.api.repository.get_connection", return_value=conn):
        result = _set_repo_status(7, RUN_ID, "indexed", commit_sha="stale")

    assert result == (False, None)
    assert cursor.execute.call_count == 1
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


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
        "backend.db.chroma.get_collection", return_value=collection
    ):
        _cleanup_repo_generation(7, ACTIVE_RUN_ID)

    sql, params = cursor.execute.call_args_list[-1].args
    assert "repo_sync_run_id <=> %s" in sql
    assert "NOT (r.active_sync_run_id <=> %s)" in sql
    assert params == (7, ACTIVE_RUN_ID, ACTIVE_RUN_ID)
    collection.delete.assert_called_once_with(ids=["old-memory"])


def test_generation_cleanup_never_deletes_the_active_generation():
    conn, cursor = _connection()
    cursor.fetchone.return_value = {"active_sync_run_id": RUN_ID}

    with patch("backend.api.repository.get_connection", return_value=conn), patch(
        "backend.db.chroma.get_collection"
    ) as get_collection:
        _cleanup_repo_generation(7, RUN_ID)

    assert cursor.execute.call_count == 1
    get_collection.assert_not_called()


def test_generation_cleanup_skips_chroma_when_mysql_state_is_unavailable():
    with patch(
        "backend.api.repository.get_connection",
        side_effect=RuntimeError("mysql unavailable"),
    ), patch("backend.db.chroma.get_collection") as get_collection:
        _cleanup_repo_generation(7, RUN_ID)

    get_collection.assert_not_called()


def test_status_uses_repository_row_and_counts_only_active_generation():
    conn, cursor = _connection()
    started = datetime(2026, 7, 28, 17, 0, 0)
    repo = {
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
    cursor.fetchone.return_value = repo
    cursor.fetchall.return_value = [{"category": "decision", "cnt": 3}]

    with patch("backend.api.repository.require_project_access"), patch(
        "backend.api.repository.get_connection", return_value=conn
    ):
        result = get_repository_status(3, 7)

    assert result["status"] == "failed"
    assert result["run_id"] is None
    assert result["sync_started_at"] == "2026-07-28T17:00:00+00:00"
    assert result["commit_sha"] == "still-active"
    assert result["extracted"]["decision"] == 3
    assert "sync_heartbeat_at" not in result
    assert "sync_lease_expires_at" not in result
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


def test_sync_response_identifies_run_without_server_or_lease_metadata():
    started = datetime(2026, 7, 28, 17, 0, 0)
    background = BackgroundTasks()
    repo = {
        "repository_url": "https://github.com/o/r",
        "branch": "main",
    }
    run = {"run_id": RUN_ID, "started_at": started}
    with patch("backend.api.repository.require_project_access"), patch(
        "backend.api.repository._get_github_token", return_value=None
    ), patch(
        "backend.api.repository._claim_sync_run", return_value=(repo, run, True)
    ):
        result = sync_repository(3, 7, background, SyncRequest())

    assert result == {
        "repo_id": 7,
        "status": "syncing",
        "run_id": RUN_ID,
        "sync_started_at": "2026-07-28T17:00:00+00:00",
    }
    assert background.tasks[0].args[2] == RUN_ID


def test_repeated_sync_does_not_schedule_a_duplicate_worker():
    started = datetime(2026, 7, 28, 17, 0, 0)
    background = BackgroundTasks()
    repo = {"repository_url": "https://github.com/o/r", "branch": "main"}
    run = {"run_id": RUN_ID, "started_at": started}
    with patch("backend.api.repository.require_project_access"), patch(
        "backend.api.repository._get_github_token", return_value=None
    ), patch(
        "backend.api.repository._claim_sync_run", return_value=(repo, run, False)
    ):
        result = sync_repository(3, 7, background, SyncRequest())

    assert result["run_id"] == RUN_ID
    assert background.tasks == []
