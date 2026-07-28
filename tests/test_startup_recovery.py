"""startup recovery: stale processing/syncing 작업 failed 전환 + dev user backfill 테스트."""
from unittest.mock import patch, MagicMock

from backend.startup import (
    ensure_runtime_schema,
    ensure_schema_v8,
    recover_stale_tasks,
    backfill_dev_user_membership,
)


def _make_conn():
    cursor = MagicMock()
    cursor.rowcount = 0
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    return conn, cursor


def test_ensure_schema_v8_adds_fk_and_view_when_missing():
    """I-001: FK가 없는 기존 DB에서 dangling 정리 → FK 추가 → 뷰 생성 순으로 실행된다.
    initdb.d는 기존 볼륨에서 재실행되지 않으므로 시작 시 보증이 유일한 자동 경로."""
    conn, cursor = _make_conn()
    cursor.fetchone.return_value = None  # FK 없음
    with patch("backend.startup.get_connection", return_value=conn):
        ensure_schema_v8()

    sql_calls = [c.args[0] for c in cursor.execute.call_args_list]
    dangling_idx = next(i for i, s in enumerate(sql_calls) if "SET m.superseded_by = NULL" in s)
    alter_idx = next(i for i, s in enumerate(sql_calls) if "ADD CONSTRAINT fk_memory_superseded_by" in s)
    assert dangling_idx < alter_idx  # FK를 걸기 전에 dangling 포인터를 해제(해당 decision 복귀)
    assert any("CREATE OR REPLACE VIEW active_memory" in s for s in sql_calls)
    conn.commit.assert_called_once()


def test_ensure_schema_v8_skips_alter_when_fk_exists():
    """I-001: FK가 이미 있으면 ALTER는 생략하되 뷰는 매번 보증한다(정의 드리프트 자기치유)."""
    conn, cursor = _make_conn()
    cursor.fetchone.return_value = {"1": 1}  # FK 존재
    with patch("backend.startup.get_connection", return_value=conn):
        ensure_schema_v8()

    sql_calls = [c.args[0] for c in cursor.execute.call_args_list]
    assert not any("ADD CONSTRAINT" in s for s in sql_calls)
    assert not any("SET m.superseded_by = NULL" in s for s in sql_calls)
    assert any("CREATE OR REPLACE VIEW active_memory" in s for s in sql_calls)


def test_ensure_schema_v8_failure_does_not_block_startup():
    """I-001: 스키마 보증이 실패해도 예외를 전파하지 않는다(best-effort, 기동 유지)."""
    with patch("backend.startup.get_connection", side_effect=RuntimeError("DB down")):
        ensure_schema_v8()  # 예외가 나면 테스트 실패


# ── ensure_runtime_schema (PR #49 백엔드 통합) ───────────────────────────────

def test_runtime_schema_adds_upload_progress_and_completion_columns_when_missing():
    """기존 Docker volume에도 memory_sources/project_memory 테이블과
    documents progress 컬럼을 보정한다."""
    conn, cursor = _make_conn()
    cursor.fetchone.return_value = None  # 컬럼 없음

    with patch("backend.startup.get_connection", return_value=conn):
        ensure_runtime_schema()

    sql_calls = [c[0][0] for c in cursor.execute.call_args_list]
    assert any("CREATE TABLE IF NOT EXISTS memory_sources" in sql for sql in sql_calls)
    assert any("CREATE TABLE IF NOT EXISTS project_memory" in sql for sql in sql_calls)
    assert any("ADD COLUMN progress_done" in sql for sql in sql_calls)
    assert any("ADD COLUMN progress_total" in sql for sql in sql_calls)
    assert any("ADD COLUMN completion_status" in sql for sql in sql_calls)
    assert any("ADD COLUMN completion_status_source" in sql for sql in sql_calls)
    assert any("completed_at IS NOT NULL" in sql and "'legacy'" in sql for sql in sql_calls)
    conn.commit.assert_called_once()


def test_runtime_schema_skips_alter_when_columns_exist():
    """progress 컬럼이 이미 있으면 ALTER는 생략하되 CREATE IF NOT EXISTS는 매번 실행."""
    conn, cursor = _make_conn()
    cursor.fetchone.return_value = {"1": 1}  # 컬럼 존재

    with patch("backend.startup.get_connection", return_value=conn):
        ensure_runtime_schema()

    sql_calls = [c[0][0] for c in cursor.execute.call_args_list]
    assert not any("ADD COLUMN" in sql for sql in sql_calls)
    assert any("CREATE TABLE IF NOT EXISTS memory_sources" in sql for sql in sql_calls)


def test_runtime_schema_failure_does_not_block_startup():
    """스키마 보증 실패 시 예외를 전파하지 않는다(best-effort, 기동 유지)."""
    with patch("backend.startup.get_connection", side_effect=RuntimeError("DB down")):
        ensure_runtime_schema()  # 예외가 나면 테스트 실패


def test_stale_docs_and_repos_updated():
    """stale processing/syncing 모두 UPDATE SQL이 실행됨."""
    conn, cursor = _make_conn()
    with patch("backend.startup.get_connection", return_value=conn), \
         patch.dict("os.environ", {"BACKGROUND_TASK_STALE_MINUTES": "30"}):
        recover_stale_tasks()

    sql_calls = [c[0][0] for c in cursor.execute.call_args_list]
    assert any("documents" in sql and "processing" in sql for sql in sql_calls)
    assert any("repositories" in sql and "syncing" in sql for sql in sql_calls)
    conn.commit.assert_called_once()


def test_recovery_skipped_when_disabled():
    """BACKGROUND_TASK_STALE_MINUTES=0 → DB 접근 없이 즉시 반환."""
    with patch("backend.startup.get_connection") as mock_conn, \
         patch.dict("os.environ", {"BACKGROUND_TASK_STALE_MINUTES": "0"}):
        recover_stale_tasks()
    mock_conn.assert_not_called()


def test_cutoff_uses_env_minutes():
    """BACKGROUND_TASK_STALE_MINUTES=60 → SQL 파라미터에 60 전달."""
    conn, cursor = _make_conn()
    with patch("backend.startup.get_connection", return_value=conn), \
         patch.dict("os.environ", {"BACKGROUND_TASK_STALE_MINUTES": "60"}):
        recover_stale_tasks()

    all_params = [c[0][1] for c in cursor.execute.call_args_list if len(c[0]) > 1]
    assert any(60 in params for params in all_params)


def test_db_failure_does_not_raise():
    """DB 연결 실패 시 예외를 삼키고 앱 기동을 막지 않음."""
    with patch("backend.startup.get_connection", side_effect=Exception("DB down")), \
         patch.dict("os.environ", {"BACKGROUND_TASK_STALE_MINUTES": "30"}):
        recover_stale_tasks()  # must not raise


# ── backfill_dev_user_membership ─────────────────────────────────────────────

def test_backfill_skipped_when_no_dev_user_id():
    """DEV_USER_ID 미설정 시 DB 접근 없이 즉시 반환."""
    with patch("backend.startup.get_connection") as mock_conn, \
         patch("backend.api.auth.ensure_dev_user", return_value=None):
        backfill_dev_user_membership()
    mock_conn.assert_not_called()


def test_backfill_inserts_missing_memberships():
    """DEV_USER_ID 설정 시 멤버가 없는 레거시 프로젝트에만 INSERT IGNORE 실행.

    'DEV_USER_ID가 아직 멤버가 아닌 프로젝트' 전체가 아니라
    'project_members row가 전혀 없는 프로젝트'만 대상이어야 한다.
    """
    conn, cursor = _make_conn()
    cursor.rowcount = 2
    with patch("backend.startup.get_connection", return_value=conn), \
         patch("backend.api.auth.ensure_dev_user", return_value=1):
        backfill_dev_user_membership()

    sql_calls = [c[0][0] for c in cursor.execute.call_args_list]
    insert_sql = next((s for s in sql_calls if "INSERT IGNORE INTO project_members" in s), None)
    assert insert_sql is not None
    # 프로젝트 자체에 멤버가 없는 경우만 대상 — dev user 기준 필터가 아님
    assert "NOT EXISTS" in insert_sql
    assert "WHERE user_id" not in insert_sql
    conn.commit.assert_called_once()


def test_backfill_db_failure_does_not_raise():
    """backfill 중 DB 오류 시 예외를 삼키고 앱 기동을 막지 않음."""
    with patch("backend.startup.get_connection", side_effect=Exception("DB down")), \
         patch("backend.api.auth.ensure_dev_user", return_value=1):
        backfill_dev_user_membership()  # must not raise


def test_repository_staleness_uses_sync_start_not_connect_time():
    """저장소 stale 판정은 sync_started_at 기준이어야 한다.

    connected_at은 연결 시각이라 재동기화 때 갱신되지 않는다. 그걸 기준으로 삼으면
    연결한 지 cutoff보다 오래된 저장소는 동기화를 시작하자마자(진행도와 무관하게)
    워치독에 failed로 뒤집힌다 — 사실상 모든 재동기화가 실패로 표시됐다.
    NULL은 컬럼 도입 전부터 syncing으로 남아 있던 행이라 정리 대상으로 남긴다."""
    conn, cursor = _make_conn()
    with patch("backend.startup.get_connection", return_value=conn), \
         patch.dict("os.environ", {"BACKGROUND_TASK_STALE_MINUTES": "30"}):
        recover_stale_tasks()

    repo_sql = next(
        c[0][0] for c in cursor.execute.call_args_list
        if "UPDATE repositories" in c[0][0]
    )
    assert "sync_started_at" in repo_sql
    assert "sync_started_at IS NULL" in repo_sql   # 도입 전 잔존 행도 회수한다
    assert "connected_at" not in repo_sql          # 연결 시각을 기준으로 쓰지 않는다


def test_sync_start_is_recorded_when_sync_begins():
    """동기화 시작 시 sync_started_at을 남긴다 — 위 판정의 기준값이라 없으면 무의미하다."""
    from backend.api import repository as repository_module

    conn, cursor = _make_conn()
    cursor.fetchone.return_value = {
        "id": 7, "project_id": 1, "repository_url": "https://github.com/o/r",
        "branch": "main", "status": "connected",
    }
    background = MagicMock()
    with patch.object(repository_module, "get_connection", return_value=conn), \
         patch.object(repository_module, "require_project_access"), \
         patch.object(repository_module, "_get_github_token", return_value=None):
        repository_module.sync_repository(1, 7, background)

    syncing_sql = next(
        c[0][0] for c in cursor.execute.call_args_list
        if "status='syncing'" in c[0][0]
    )
    assert "sync_started_at=NOW()" in syncing_sql
