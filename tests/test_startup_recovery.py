"""startup recovery: stale processing/syncing 작업 failed 전환 + dev user backfill 테스트."""
from unittest.mock import patch, MagicMock

from backend.startup import (
    ensure_runtime_schema,
    ensure_schema_v8,
    ensure_schema_v10,
    recover_interrupted_repository_syncs,
    cleanup_stale_repository_generations,
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


# ── ensure_schema_v10 (repository generations) ─────────────────────────────

def test_ensure_schema_v10_adds_minimal_generation_columns_without_ledger():
    conn, cursor = _make_conn()
    cursor.fetchone.return_value = None

    with patch("backend.startup.get_connection", return_value=conn):
        ensure_schema_v10()

    sql_calls = [c.args[0] for c in cursor.execute.call_args_list]
    assert any("ADD COLUMN active_sync_run_id" in sql for sql in sql_calls)
    assert any("ADD COLUMN current_sync_run_id" in sql for sql in sql_calls)
    assert any("ADD COLUMN sync_started_at" in sql for sql in sql_calls)
    assert any("ADD COLUMN repo_sync_run_id" in sql for sql in sql_calls)
    assert not any("repository_sync_runs" in sql for sql in sql_calls)
    assert any("idx_memory_repo_sync_run" in sql for sql in sql_calls)
    assert any("CREATE OR REPLACE VIEW published_memory" in sql for sql in sql_calls)
    active_view = next(
        sql for sql in sql_calls if "CREATE OR REPLACE VIEW active_memory" in sql
    )
    assert "published_memory successor" in active_view
    conn.commit.assert_called_once()


def test_ensure_schema_v10_is_startup_gate():
    conn, _cursor = _make_conn()
    conn.cursor.side_effect = RuntimeError("migration failed")

    with patch("backend.startup.get_connection", return_value=conn):
        try:
            ensure_schema_v10()
        except RuntimeError as exc:
            assert str(exc) == "migration failed"
        else:
            raise AssertionError("v10 migration failure must stop startup")
    conn.rollback.assert_called_once()


# ── repository run recovery ─────────────────────────────────────────────────

def test_startup_fails_interrupted_runs_without_clearing_active_generation():
    conn, cursor = _make_conn()
    cursor.rowcount = 2
    cursor.fetchall.return_value = [
        {"id": 7, "current_sync_run_id": "interrupted-run"}
    ]

    with patch("backend.startup.get_connection", return_value=conn), patch(
        "backend.api.repository._cleanup_repo_generation"
    ) as cleanup:
        recover_interrupted_repository_syncs()

    sql_calls = [c.args[0] for c in cursor.execute.call_args_list]
    repo_update = next(sql for sql in sql_calls if "UPDATE repositories" in sql)
    assert "current_sync_run_id=NULL" in repo_update
    assert "active_sync_run_id=NULL" not in repo_update
    assert not any("repository_sync_runs" in sql for sql in sql_calls)
    cleanup.assert_called_once_with(7, "interrupted-run")
    conn.commit.assert_called_once()


def test_interrupted_run_recovery_is_a_startup_gate():
    conn, cursor = _make_conn()
    cursor.execute.side_effect = RuntimeError("recovery failed")

    with patch("backend.startup.get_connection", return_value=conn):
        try:
            recover_interrupted_repository_syncs()
        except RuntimeError as exc:
            assert str(exc) == "recovery failed"
        else:
            raise AssertionError("interrupted sync recovery failure must stop startup")
    conn.rollback.assert_called_once()


def test_stale_recovery_only_handles_document_leases():
    conn, cursor = _make_conn()
    cursor.fetchall.return_value = []
    with patch("backend.startup.get_connection", return_value=conn), \
         patch.dict("os.environ", {"BACKGROUND_TASK_STALE_MINUTES": "30"}):
        recover_stale_tasks()

    sql_calls = [c[0][0] for c in cursor.execute.call_args_list]
    assert any("documents" in sql and "processing" in sql for sql in sql_calls)
    assert not any("repositories" in sql for sql in sql_calls)
    assert not any("repository_sync_runs" in sql for sql in sql_calls)
    conn.commit.assert_called_once()


def test_recovery_skipped_when_disabled():
    """BACKGROUND_TASK_STALE_MINUTES=0 → DB 접근 없이 즉시 반환."""
    with patch("backend.startup.get_connection") as mock_conn, \
         patch.dict("os.environ", {"BACKGROUND_TASK_STALE_MINUTES": "0"}):
        recover_stale_tasks()
    mock_conn.assert_not_called()


def test_runtime_recovery_never_touches_repository_state():
    conn, cursor = _make_conn()
    with patch("backend.startup.get_connection", return_value=conn), \
         patch.dict("os.environ", {"BACKGROUND_TASK_STALE_MINUTES": "60"}):
        recover_stale_tasks()

    sql_calls = [c.args[0] for c in cursor.execute.call_args_list]
    assert not any("connected_at" in sql for sql in sql_calls)
    assert not any("repositories" in sql for sql in sql_calls)
    assert any("lease_expires_at" in sql for sql in sql_calls)


def test_startup_cleanup_retries_all_inactive_generations_before_serving():
    conn, cursor = _make_conn()
    cursor.fetchall.return_value = [
        {"id": 7, "active_sync_run_id": "active-run"}
    ]
    collection = MagicMock()
    collection.get.return_value = {
        "ids": ["active", "old", "legacy"],
        "metadatas": [
            {"repo_sync_run_id": "active-run"},
            {"repo_sync_run_id": "old-run"},
            {},
        ],
    }

    with patch("backend.startup.get_connection", return_value=conn), patch(
        "backend.db.chroma.get_collection", return_value=collection
    ):
        cleanup_stale_repository_generations()

    delete_sql = next(
        call
        for call in cursor.execute.call_args_list
        if call.args[0].startswith("DELETE FROM memory")
    )
    assert "NOT (repo_sync_run_id <=> %s)" in delete_sql.args[0]
    assert delete_sql.args[1] == (7, "active-run")
    collection.delete.assert_called_once_with(ids=["old", "legacy"])


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
