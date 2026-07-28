"""`repositories.sync_started_at` 도입을 실제 MySQL 8.0 에서 검증한다.

`schema.sql` 은 fresh init 에만 적용된다. 기존 볼륨에는 컬럼이 없으므로
`ensure_runtime_schema()` 의 idempotent ALTER 가 없으면 동기화 시작 UPDATE 가
unknown-column 오류로 500 을 내고 stale recovery 도 같은 오류로 실패한다.

단위 목은 SQL 문자열의 존재만 확인할 뿐 실제 ALTER 성공·기존 row 보존·DDL commit·
unknown-column 여부를 잡지 못한다. 그래서 실제 MySQL 로 검증한다.

`v8_db` 를 쓰지 않는다 — 그 서비스와 `schema_v8.sql` 은 SQL 마이그레이션 정리
태스크의 제거 대상이라 의존하면 이 테스트가 함께 깨진다. 대신 같은 MySQL 서버 안에
테스트 전용 임시 database 를 만든다.
"""
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pymysql
import pytest

from backend.api import repository as repository_module
from backend import startup as startup_module

_TEMP_DB = "paim_legacy_repo_schema"


def _mysql(sql: bytes, database: str | None = None):
    env = os.environ.copy()
    env["MYSQL_PWD"] = os.environ["DB_PASSWORD"]
    args = [
        "mysql", "--protocol=tcp",
        "-h", os.environ["DB_HOST"], "-P", os.environ["DB_PORT"],
        "-u", os.environ["DB_USER"],
    ]
    if database:
        args.append(database)
    subprocess.run(args, input=sql, env=env, check=True, capture_output=True)


def _conn():
    return pymysql.connect(
        host=os.environ["DB_HOST"], port=int(os.environ["DB_PORT"]),
        user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
        database=_TEMP_DB, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor, autocommit=True,
    )


def _column_exists() -> bool:
    conn = _conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM information_schema.COLUMNS"
                " WHERE TABLE_SCHEMA=%s AND TABLE_NAME='repositories'"
                " AND COLUMN_NAME='sync_started_at'",
                (_TEMP_DB,),
            )
            return cursor.fetchone()["n"] == 1
    finally:
        conn.close()


@pytest.fixture
def legacy_db(monkeypatch):
    """컬럼이 없는 '기존 DB' 를 재현한다."""
    schema = Path(__file__).parents[3] / "backend" / "db" / "schema.sql"
    _mysql(
        f"DROP DATABASE IF EXISTS `{_TEMP_DB}`; CREATE DATABASE `{_TEMP_DB}`;".encode()
    )
    _mysql(schema.read_bytes(), database=_TEMP_DB)
    # 레거시 상태 재현 — 이 컬럼이 없는 것이 이 테스트의 전제다.
    _mysql(b"ALTER TABLE repositories DROP COLUMN sync_started_at;", database=_TEMP_DB)
    assert not _column_exists()

    conn = _conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO users(id,email,name) VALUES (1,'a@t','a')")
            cursor.execute("INSERT INTO projects(id,name,owner_user_id) VALUES (1,'p',1)")
            cursor.execute(
                "INSERT INTO repositories(id,project_id,provider,repository_url,branch,status)"
                " VALUES (1,1,'github','https://github.com/o/r','main','connected')"
            )
    finally:
        conn.close()

    monkeypatch.setenv("DB_NAME", _TEMP_DB)
    yield
    _mysql(f"DROP DATABASE IF EXISTS `{_TEMP_DB}`;".encode())


def test_runtime_schema_adds_column_idempotently_and_preserves_rows(legacy_db):
    """컬럼 없는 기존 DB 에서 ALTER 가 적용되고, 재실행해도 안전하며 기존 row 가 남는다."""
    startup_module.ensure_runtime_schema()
    assert _column_exists()

    startup_module.ensure_runtime_schema()   # 멱등성
    assert _column_exists()

    conn = _conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id,status,sync_started_at FROM repositories")
            rows = cursor.fetchall()
    finally:
        conn.close()

    assert len(rows) == 1                      # 기존 row 보존
    assert rows[0]["status"] == "connected"
    assert rows[0]["sync_started_at"] is None   # 새 컬럼은 NULL


def test_sync_records_start_time_and_recovery_respects_it(legacy_db):
    """실제 sync UPDATE 가 시작 시각을 남기고, stale recovery 가 그것을 기준으로 판정한다."""
    startup_module.ensure_runtime_schema()

    # 인증·GitHub token 만 안정된 경계에서 패치한다. background 수집은 실행되지 않는다
    # (BackgroundTasks 목이 add_task 를 삼킨다).
    with patch.object(repository_module, "require_project_access"), \
         patch.object(repository_module, "_get_github_token", return_value=None):
        repository_module.sync_repository(
            project_id=1, repo_id=1, background_tasks=MagicMock(),
        )

    conn = _conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT status,sync_started_at FROM repositories WHERE id=1")
            row = cursor.fetchone()
    finally:
        conn.close()

    assert row["status"] == "syncing"
    assert row["sync_started_at"] is not None   # 기준 시각이 실제로 기록됐다

    # 방금 시작한 동기화는 recovery 가 건드리지 않는다.
    with patch.dict(os.environ, {"BACKGROUND_TASK_STALE_MINUTES": "30"}):
        startup_module.recover_stale_tasks()

    conn = _conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT status FROM repositories WHERE id=1")
            assert cursor.fetchone()["status"] == "syncing", \
                "방금 시작한 동기화가 stale 로 뒤집혔다 — 이것이 원 결함이다"

            # 시작 시각을 과거로 돌리면 회수 대상이 된다.
            # 시각 연산을 DB 쪽에서 한다 — Python 의 datetime.now() 는 호스트 로컬
            # 시간(KST)이고 컨테이너의 NOW() 는 UTC 라, Python 으로 만든 "3시간 전"이
            # MySQL 에게는 미래로 보여 조건에 걸리지 않는다.
            cursor.execute(
                "UPDATE repositories SET sync_started_at = NOW() - INTERVAL 3 HOUR"
                " WHERE id=1"
            )
    finally:
        conn.close()

    with patch.dict(os.environ, {"BACKGROUND_TASK_STALE_MINUTES": "30"}):
        startup_module.recover_stale_tasks()

    conn = _conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT status FROM repositories WHERE id=1")
            assert cursor.fetchone()["status"] == "failed"
    finally:
        conn.close()


def test_recovery_reclaims_rows_left_syncing_before_the_column_existed(legacy_db):
    """컬럼 도입 전부터 syncing 으로 남아 있던 행(NULL)도 회수 대상이다.

    서버 재시작으로 이미 죽은 작업이므로 방치하면 영원히 syncing 으로 남는다.
    """
    startup_module.ensure_runtime_schema()

    conn = _conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE repositories SET status='syncing', sync_started_at=NULL WHERE id=1"
            )
    finally:
        conn.close()

    with patch.dict(os.environ, {"BACKGROUND_TASK_STALE_MINUTES": "30"}):
        startup_module.recover_stale_tasks()

    conn = _conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT status FROM repositories WHERE id=1")
            assert cursor.fetchone()["status"] == "failed"
    finally:
        conn.close()
