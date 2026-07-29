"""Repository generation migration and interrupted-run recovery on MySQL 8.

The generation model deliberately does not use a periodic age cutoff for repository
syncs. A repository row is the run fence: startup recovers any run left in flight,
cleans only that staging generation, and preserves the last published generation.
"""
import os
import subprocess
from unittest.mock import MagicMock, patch

import pymysql
import pytest

from backend import startup as startup_module
from backend.api import repository as repository_module

_TEMP_DB = "paim_legacy_repo_generation"
_INTERRUPTED_ERROR = "REPOSITORY_SYNC_INTERRUPTED"


def _mysql(sql: bytes, database: str | None = None):
    env = os.environ.copy()
    env["MYSQL_PWD"] = os.environ["DB_PASSWORD"]
    args = [
        "mysql",
        "--protocol=tcp",
        "-h",
        os.environ["DB_HOST"],
        "-P",
        os.environ["DB_PORT"],
        "-u",
        os.environ["DB_USER"],
    ]
    if database:
        args.append(database)
    subprocess.run(args, input=sql, env=env, check=True, capture_output=True)


def _conn():
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=_TEMP_DB,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def _column_names(table: str) -> set[str]:
    conn = _conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT COLUMN_NAME FROM information_schema.COLUMNS"
                " WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
                (_TEMP_DB, table),
            )
            return {row["COLUMN_NAME"] for row in cursor.fetchall()}
    finally:
        conn.close()


@pytest.fixture
def legacy_db(monkeypatch):
    """Create the latest-main schema that predates repository generations."""
    _mysql(
        f"DROP DATABASE IF EXISTS `{_TEMP_DB}`; CREATE DATABASE `{_TEMP_DB}`;".encode()
    )
    _mysql(
        b"""
        CREATE TABLE repositories (
            id INT PRIMARY KEY,
            project_id INT NOT NULL,
            provider VARCHAR(20) NOT NULL DEFAULT 'github',
            repository_url VARCHAR(500) NOT NULL,
            branch VARCHAR(100) NOT NULL DEFAULT 'main',
            status VARCHAR(20) NOT NULL DEFAULT 'connected',
            commit_sha VARCHAR(40) NULL,
            indexed_files INT NOT NULL DEFAULT 0,
            last_error TEXT NULL,
            sync_warning TEXT NULL,
            last_reconciled_pr INT NULL,
            sync_started_at DATETIME NULL
        );
        CREATE TABLE memory (
            id INT PRIMARY KEY AUTO_INCREMENT,
            project_id INT NOT NULL,
            repo_id INT NULL,
            superseded_by INT NULL,
            superseded_at DATETIME NULL,
            category VARCHAR(20) NOT NULL DEFAULT 'decision',
            content TEXT NOT NULL
        );
        INSERT INTO repositories (
            id, project_id, repository_url, branch, status, commit_sha, indexed_files
        ) VALUES (
            1, 1, 'https://github.com/o/r', 'main', 'indexed', 'published-sha', 4
        );
        """,
        database=_TEMP_DB,
    )
    assert "active_sync_run_id" not in _column_names("repositories")
    assert "repo_sync_run_id" not in _column_names("memory")
    conn = _conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT DATETIME_PRECISION FROM information_schema.COLUMNS"
                " WHERE TABLE_SCHEMA=%s AND TABLE_NAME='repositories'"
                " AND COLUMN_NAME='sync_started_at'",
                (_TEMP_DB,),
            )
            assert cursor.fetchone()["DATETIME_PRECISION"] == 0
    finally:
        conn.close()

    monkeypatch.setenv("DB_NAME", _TEMP_DB)
    yield
    _mysql(f"DROP DATABASE IF EXISTS `{_TEMP_DB}`;".encode())


def test_v10_adds_generation_fence_idempotently_and_preserves_rows(legacy_db):
    startup_module.ensure_schema_v10()
    startup_module.ensure_schema_v10()

    assert {
        "active_sync_run_id",
        "current_sync_run_id",
        "sync_started_at",
    }.issubset(_column_names("repositories"))
    assert "repo_sync_run_id" in _column_names("memory")

    conn = _conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT status,commit_sha,indexed_files,active_sync_run_id,"
                " current_sync_run_id,sync_started_at FROM repositories WHERE id=1"
            )
            row = cursor.fetchone()
            cursor.execute(
                "SELECT DATETIME_PRECISION FROM information_schema.COLUMNS"
                " WHERE TABLE_SCHEMA=%s AND TABLE_NAME='repositories'"
                " AND COLUMN_NAME='sync_started_at'",
                (_TEMP_DB,),
            )
            precision = cursor.fetchone()["DATETIME_PRECISION"]
            cursor.execute(
                "SELECT TABLE_NAME FROM information_schema.VIEWS"
                " WHERE TABLE_SCHEMA=%s AND TABLE_NAME IN ('published_memory','active_memory')",
                (_TEMP_DB,),
            )
            views = {view["TABLE_NAME"] for view in cursor.fetchall()}
    finally:
        conn.close()

    assert row == {
        "status": "indexed",
        "commit_sha": "published-sha",
        "indexed_files": 4,
        "active_sync_run_id": None,
        "current_sync_run_id": None,
        "sync_started_at": None,
    }
    assert precision == 6
    assert views == {"published_memory", "active_memory"}


def test_startup_recovers_interrupted_run_and_preserves_published_generation(legacy_db):
    startup_module.ensure_schema_v10()

    conn = _conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE repositories SET active_sync_run_id=%s WHERE id=1",
                ("published-run",),
            )
    finally:
        conn.close()

    background = MagicMock()
    with patch.object(repository_module, "require_project_access"), patch.object(
        repository_module, "_get_github_token", return_value=None
    ):
        response = repository_module.sync_repository(
            project_id=1,
            repo_id=1,
            background_tasks=background,
        )

    run_id = response["run_id"]
    conn = _conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT status,active_sync_run_id,current_sync_run_id,sync_started_at,"
                " commit_sha,indexed_files FROM repositories WHERE id=1"
            )
            in_flight = cursor.fetchone()
    finally:
        conn.close()

    assert in_flight["status"] == "syncing"
    assert in_flight["active_sync_run_id"] == "published-run"
    assert in_flight["current_sync_run_id"] == run_id
    assert in_flight["sync_started_at"] is not None
    assert in_flight["commit_sha"] == "published-sha"
    assert in_flight["indexed_files"] == 4

    with patch.object(repository_module, "_cleanup_repo_generation") as cleanup:
        startup_module.recover_interrupted_repository_syncs()

    conn = _conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT status,active_sync_run_id,current_sync_run_id,last_error,"
                " commit_sha,indexed_files FROM repositories WHERE id=1"
            )
            recovered = cursor.fetchone()
    finally:
        conn.close()

    assert recovered == {
        "status": "failed",
        "active_sync_run_id": "published-run",
        "current_sync_run_id": None,
        "last_error": _INTERRUPTED_ERROR,
        "commit_sha": "published-sha",
        "indexed_files": 4,
    }
    cleanup.assert_called_once_with(1, run_id)
