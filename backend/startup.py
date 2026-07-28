import asyncio
import logging
import os

from .db.mysql import get_connection
from .storage import delete_managed_file, validate_managed_file

logger = logging.getLogger(__name__)

_STALE_DOC_ERROR = "UPLOAD_PROCESSING_STALE"
_STALE_REPO_ERROR = "Repository sync interrupted or stale after server restart."


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        (table_name, column_name),
    )
    return cursor.fetchone() is not None


def ensure_runtime_schema() -> None:
    """기존 Docker volume에도 upload/status 경로가 요구하는 additive schema를 보장.

    memory_sources·project_memory 테이블과 documents 진행률 컬럼은 initdb.d로만
    생성되는데, 비어 있지 않은 mysql_data 볼륨에서는 initdb.d가 재실행되지 않아
    기존 DB가 이를 받지 못한다. 실패해도 기동은 유지한다(best-effort) —
    다른 startup 보증 함수들과 동일한 정책.
    """
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memory_sources (
                        id          INT PRIMARY KEY AUTO_INCREMENT,
                        memory_id   INT NOT NULL,
                        source_kind VARCHAR(20)  NOT NULL,
                        doc_id      INT NULL,
                        repo_id     INT NULL,
                        source_type VARCHAR(30)  NULL,
                        source_path VARCHAR(500) NULL,
                        source_ref  VARCHAR(100) NULL,
                        source_url  VARCHAR(500) NULL,
                        created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (memory_id) REFERENCES memory(id) ON DELETE CASCADE,
                        FOREIGN KEY (doc_id)    REFERENCES documents(id) ON DELETE SET NULL,
                        FOREIGN KEY (repo_id)   REFERENCES repositories(id) ON DELETE SET NULL,
                        INDEX idx_memory_sources_memory_id (memory_id),
                        INDEX idx_memory_sources_doc_id    (doc_id),
                        INDEX idx_memory_sources_repo_id   (repo_id)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS project_memory (
                        project_id INT PRIMARY KEY,
                        summary    TEXT,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        FOREIGN KEY (project_id) REFERENCES projects(id)
                    )
                    """
                )
                if not _column_exists(cursor, "documents", "progress_done"):
                    cursor.execute(
                        "ALTER TABLE documents ADD COLUMN progress_done INT DEFAULT NULL AFTER last_error"
                    )
                if not _column_exists(cursor, "documents", "progress_total"):
                    cursor.execute(
                        "ALTER TABLE documents ADD COLUMN progress_total INT DEFAULT NULL AFTER progress_done"
                    )
                if not _column_exists(cursor, "memory", "completion_status"):
                    cursor.execute(
                        "ALTER TABLE memory ADD COLUMN completion_status"
                        " VARCHAR(20) NOT NULL DEFAULT 'unknown' AFTER completed_at"
                    )
                if not _column_exists(cursor, "memory", "completion_status_source"):
                    cursor.execute(
                        "ALTER TABLE memory ADD COLUMN completion_status_source"
                        " VARCHAR(20) NULL AFTER completion_status"
                    )
                if not _column_exists(cursor, "repositories", "sync_started_at"):
                    cursor.execute(
                        "ALTER TABLE repositories ADD COLUMN sync_started_at"
                        " DATETIME NULL AFTER connected_at"
                    )
                # 기존 NULL을 미완료로 추측하지 않는다. 확인 가능한 완료 행만 보존한다.
                cursor.execute(
                    "UPDATE memory SET completion_status = 'completed',"
                    " completion_status_source = COALESCE(completion_status_source, 'legacy')"
                    " WHERE completed_at IS NOT NULL AND completion_status <> 'completed'"
                )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.error(
            "런타임 스키마 보증 실패 — 앱은 계속 기동됩니다"
            " (memory_sources/project_memory/문서 진행률 경로가 동작하지 않을 수 있음)",
            exc_info=True,
        )


def ensure_schema_v8() -> None:
    """migrate_v8(self-FK + active_memory 뷰)을 앱 시작 시 idempotent하게 보증한다.

    docker initdb.d는 비어 있지 않은 mysql_data 볼륨에서 재실행되지 않으므로,
    기존 DB는 수동 마이그레이션 없이는 v8을 받지 못한다. active_memory 뷰가 없으면
    조망형 API·요약 재생성이 즉시 실패(500)하는 hard-dependency라 수동 절차에
    의존할 수 없다 — information_schema로 존재를 확인하고 없을 때만 생성한다.
    """
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS"
                    " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'memory'"
                    " AND CONSTRAINT_NAME = 'fk_memory_superseded_by'"
                    " AND CONSTRAINT_TYPE = 'FOREIGN KEY'"
                )
                if not cursor.fetchone():
                    # FK 추가 전에 이미 dangling인 포인터를 해제해 해당 decision을 복귀시킨다.
                    cursor.execute(
                        "UPDATE memory m"
                        " LEFT JOIN (SELECT id FROM memory) live ON live.id = m.superseded_by"
                        " SET m.superseded_by = NULL, m.superseded_at = NULL"
                        " WHERE m.superseded_by IS NOT NULL AND live.id IS NULL"
                    )
                    cursor.execute(
                        "ALTER TABLE memory ADD CONSTRAINT fk_memory_superseded_by"
                        " FOREIGN KEY (superseded_by) REFERENCES memory(id) ON DELETE SET NULL"
                    )
                    logger.info("v8 스키마 보증: fk_memory_superseded_by 추가")
                # 뷰는 CREATE OR REPLACE라 매 기동 시 실행해도 안전 — 정의 드리프트도 자기치유.
                cursor.execute(
                    "CREATE OR REPLACE VIEW active_memory AS"
                    " SELECT * FROM memory WHERE superseded_by IS NULL"
                )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.error(
            "v8 스키마 보증 실패 — 앱은 계속 기동됩니다"
            " (active_memory 조회·supersede 복귀가 동작하지 않을 수 있음)",
            exc_info=True,
        )


def ensure_schema_v9() -> None:
    """Install v9 quota schema and finish filesystem-aware legacy backfill.

    Unlike older best-effort migrations, quota accounting is a startup gate: serving
    requests with a partially migrated table could undercount storage.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            additions = (
                ("size_bytes", "BIGINT UNSIGNED NULL AFTER progress_total"),
                ("uploaded_by", "INT NULL AFTER size_bytes"),
                ("processing_token", "CHAR(36) NULL AFTER uploaded_by"),
                ("lease_expires_at", "DATETIME NULL AFTER processing_token"),
            )
            for name, definition in additions:
                if not _column_exists(cursor, "documents", name):
                    cursor.execute(f"ALTER TABLE documents ADD COLUMN {name} {definition}")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS upload_quota_reservations (
                    reservation_id CHAR(36) PRIMARY KEY, user_id INT NOT NULL,
                    project_id INT NOT NULL, kind VARCHAR(20) NOT NULL,
                    size_bytes BIGINT UNSIGNED NOT NULL, target_path VARCHAR(500) NULL,
                    temp_path VARCHAR(500) NULL, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME NOT NULL,
                    CONSTRAINT fk_quota_reservation_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
                    CONSTRAINT fk_quota_reservation_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT,
                    INDEX idx_quota_reservations_user (user_id),
                    INDEX idx_quota_reservations_project (project_id),
                    INDEX idx_quota_reservations_expiry (expires_at)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS storage_cleanup_pending (
                    cleanup_id CHAR(36) PRIMARY KEY, source_kind VARCHAR(20) NOT NULL,
                    source_id VARCHAR(64) NOT NULL, user_id INT NULL, project_id INT NOT NULL,
                    document_id INT NULL, file_path VARCHAR(500) NULL,
                    size_bytes BIGINT UNSIGNED NOT NULL, count_units INT UNSIGNED NOT NULL DEFAULT 1,
                    needs_chroma TINYINT(1) NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, last_attempt_at DATETIME NULL,
                    UNIQUE KEY uq_cleanup_source (source_kind, source_id),
                    INDEX idx_cleanup_user (user_id), INDEX idx_cleanup_project (project_id)
                )
                """
            )
            cursor.execute(
                "SELECT d.id,d.project_id,d.status,d.file_path,p.owner_user_id"
                " FROM documents d JOIN projects p ON p.id=d.project_id"
                " WHERE d.size_bytes IS NULL ORDER BY d.id FOR UPDATE"
            )
            legacy_rows = cursor.fetchall()
            for row in legacy_rows:
                file_path = row.get("file_path")
                if row["status"] == "failed":
                    if file_path:
                        delete_managed_file(file_path, row["project_id"])
                    size_bytes = 0
                    file_path = None
                elif file_path:
                    path = validate_managed_file(file_path, row["project_id"])
                    size_bytes = path.stat(follow_symlinks=False).st_size
                else:
                    size_bytes = 0
                cursor.execute(
                    "UPDATE documents SET size_bytes=%s,uploaded_by=%s,file_path=%s WHERE id=%s AND size_bytes IS NULL",
                    (size_bytes, row.get("owner_user_id"), file_path, row["id"]),
                )
            cursor.execute("SELECT COUNT(*) AS count FROM documents WHERE size_bytes IS NULL")
            if cursor.fetchone()["count"]:
                raise RuntimeError("v9 document backfill incomplete")
            cursor.execute(
                "SELECT IS_NULLABLE FROM information_schema.COLUMNS"
                " WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='documents' AND COLUMN_NAME='size_bytes'"
            )
            column = cursor.fetchone()
            if column and column["IS_NULLABLE"] == "YES":
                cursor.execute(
                    "ALTER TABLE documents MODIFY COLUMN size_bytes BIGINT UNSIGNED NOT NULL DEFAULT 0"
                )
            cursor.execute(
                "SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE()"
                " AND TABLE_NAME='documents' AND INDEX_NAME='idx_documents_uploaded_by'"
            )
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE documents ADD INDEX idx_documents_uploaded_by (uploaded_by)")
            cursor.execute(
                "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA=DATABASE()"
                " AND TABLE_NAME='documents' AND CONSTRAINT_NAME='fk_documents_uploaded_by'"
            )
            if not cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE documents ADD CONSTRAINT fk_documents_uploaded_by"
                    " FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL"
                )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_schema_v10() -> None:
    """migrate_v10(문서 기반 완료 제안을 complete_action_doc으로 재분류)를 기동 시 보증한다.

    v8과 같은 이유로 런타임 가드가 필요하다 — initdb.d는 기존 볼륨에서 재실행되지 않아
    compose 마운트만으로는 이미 저장된 행이 그대로 남는다. 남으면 kind=all 조회에
    evidence.title 없는 행이 섞여 구 데스크톱 제안 패널이 죽는다.

    migrate_v10.sql과 동일한 UPDATE 한 문장이며 재실행 안전(두 번째 실행은 0행).
    v9(quota)와 달리 실패해도 기동을 막지 않는다 — 렌더링 호환 문제라 서빙 자체를
    중단시킬 사유는 아니다.
    """
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE memory_suggestions SET kind = 'complete_action_doc'"
                    " WHERE kind = 'complete_action'"
                    " AND JSON_UNQUOTE(JSON_EXTRACT(evidence, '$.type')) = 'document'"
                )
                if cursor.rowcount:
                    logger.info("v10 스키마 보증: 문서 기반 제안 %d건 재분류", cursor.rowcount)
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.error(
            "v10 스키마 보증 실패 — 앱은 계속 기동됩니다"
            " (문서 기반 완료 제안이 구 클라이언트 렌더링을 깨뜨릴 수 있음)",
            exc_info=True,
        )


def backfill_dev_user_membership() -> None:
    """DEV_USER_ID가 설정된 경우, project_members row가 없는 기존 프로젝트에 owner 멤버십을 보장.

    마이그레이션 이전에 생성된 레거시 프로젝트는 project_members 행이 없으므로
    DEV_USER_ID 사용 시 403 또는 목록 누락이 발생한다.
    서버 기동마다 실행되며 INSERT IGNORE로 멱등성을 보장한다.
    """
    from .api.auth import ensure_dev_user
    user_id = ensure_dev_user()
    if user_id is None:
        return

    try:
        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT IGNORE INTO project_members (project_id, user_id, role)"
                    " SELECT p.id, %s, 'owner' FROM projects p"
                    " WHERE NOT EXISTS ("
                    "   SELECT 1 FROM project_members pm WHERE pm.project_id = p.id"
                    " )",
                    (user_id,),
                )
                count = cursor.rowcount
            conn.commit()
        finally:
            conn.close()

        if count:
            logger.info("Dev user backfill: %d legacy project(s)에 owner 멤버십 추가 (user_id=%s)", count, user_id)
        else:
            logger.info("Dev user backfill: 누락된 멤버십 없음 (user_id=%s)", user_id)

    except Exception:
        logger.error("Dev user membership backfill 실패 — 앱은 계속 기동됩니다", exc_info=True)


def recover_stale_tasks() -> None:
    """서버 재시작 시 stale processing/syncing 작업을 failed로 전환.

    stale 판정 기준이 두 테이블에서 다르지만, 축은 같다 — 둘 다 '이 작업이 언제
    시작했는가'를 본다:
    - documents: lease_expires_at 기반(NULL이거나 만료된 것). 임계값은 lease를 발급하는
      쪽의 LEASE_MINUTES(quota.py)이며 아래 cutoff와 무관하다.
    - repositories: sync_started_at이 cutoff보다 오래된 것(NULL 포함 — 컬럼 도입 전부터
      syncing으로 남아 있던 행은 서버 재시작으로 이미 죽은 작업이므로 정리 대상이다).

    따라서 BACKGROUND_TASK_STALE_MINUTES는 repositories에서만 임계값으로 쓰이고,
    documents에는 recovery on/off 스위치로만 작용한다(<= 0 이면 전체 비활성화).
    """
    raw = os.getenv("BACKGROUND_TASK_STALE_MINUTES", "30")
    try:
        stale_minutes = int(raw)
    except ValueError:
        logger.warning("BACKGROUND_TASK_STALE_MINUTES 값이 정수가 아닙니다: %s, 기본값 30 사용", raw)
        stale_minutes = 30

    if stale_minutes <= 0:
        logger.info("Startup recovery 비활성화 (BACKGROUND_TASK_STALE_MINUTES=%s)", stale_minutes)
        return

    try:
        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id,processing_token FROM documents WHERE status='processing'"
                    " AND (lease_expires_at IS NULL OR lease_expires_at<NOW())",
                )
                stale_documents = cursor.fetchall()

                cursor.execute(
                    "UPDATE repositories SET status='failed', last_error=%s"
                    " WHERE status='syncing'"
                    " AND (sync_started_at IS NULL"
                    "      OR sync_started_at < NOW() - INTERVAL %s MINUTE)",
                    (_STALE_REPO_ERROR, stale_minutes),
                )
                repo_count = cursor.rowcount
            conn.commit()
        finally:
            conn.close()

        from .quota import fail_stale_document
        for document in stale_documents:
            token = document.get("processing_token")
            if token:
                fail_stale_document(document["id"], token)
            else:
                # v8 legacy processing rows have no owner token. Assigning no new
                # owner is safe; migrate them through the ordinary failed path.
                from .quota import fail_document
                fail_document(document["id"], _STALE_DOC_ERROR)
        doc_count = len(stale_documents)

        if doc_count or repo_count:
            logger.warning(
                "Startup recovery: %d document(s), %d repository(ies) stale → failed",
                doc_count,
                repo_count,
            )
        else:
            logger.info("Startup recovery: stale 작업 없음 (cutoff=%d분)", stale_minutes)

    except Exception:
        logger.error("Startup recovery 실패 — 앱은 계속 기동됩니다", exc_info=True)


def recover_quota_tasks() -> bool:
    """Recover quota ownership independently from the stale-task policy."""
    try:
        from .quota import recover_quota_state

        recover_quota_state()
        return True
    except Exception:
        logger.error("quota_recovery_failed", extra={"code": "QUOTA_RECOVERY_FAILED"})
        return False


_WATCHDOG_INTERVAL_SECONDS = 60  # 1분마다 stale 체크


def _run_recovery_cycle() -> None:
    """Run one serialized runtime recovery cycle outside the event loop."""
    recover_quota_tasks()
    try:
        recover_stale_tasks()
    except Exception:
        logger.error("Watchdog recover_stale_tasks 실패", exc_info=True)


async def stale_watchdog(executor) -> None:
    """런타임 워치독 — 서버가 살아있는 동안 주기적으로 stale 작업을 failed로 전환.

    서버 재시작 없이 백그라운드 작업이 멈춘 경우에도 프론트가 무한 폴링하지 않도록 보장.
    BACKGROUND_TASK_STALE_MINUTES <= 0 이면 비활성화.
    """
    while True:
        await asyncio.sleep(_WATCHDOG_INTERVAL_SECONDS)
        await asyncio.get_running_loop().run_in_executor(executor, _run_recovery_cycle)
