"""Transactional document quota reservations and durable cleanup ownership."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import HTTPException

from .config import quota_limits
from .db.mysql import get_connection
from .storage import delete_managed_file, reservation_paths

logger = logging.getLogger(__name__)
RESERVATION_MINUTES = 15
LEASE_MINUTES = 30


def _quota_error() -> HTTPException:
    return HTTPException(
        status_code=413,
        detail={"code": "UPLOAD_QUOTA_EXCEEDED", "message": "업로드 저장 한도를 초과했습니다."},
    )


def _user_error() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"code": "UPLOAD_USER_REQUIRED", "message": "업로드 사용자를 확인할 수 없습니다."},
    )


def require_upload_user() -> int:
    """Resolve a real positive users row before any quota/file side effect."""
    from .api.auth import ensure_dev_user, get_current_user_id

    try:
        user_id = get_current_user_id()
        ensured_user_id = ensure_dev_user()
        if user_id is None:
            user_id = ensured_user_id
        if user_id is None or int(user_id) <= 0:
            raise _user_error()
        user_id = int(user_id)
        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id FROM users WHERE id=%s", (user_id,))
                if not cursor.fetchone():
                    raise _user_error()
        finally:
            conn.close()
        return user_id
    except HTTPException:
        raise
    except Exception:
        raise _user_error()


def _lock_user_project(cursor, user_id: int, project_id: int) -> None:
    cursor.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (user_id,))
    if not cursor.fetchone():
        raise _user_error()
    cursor.execute("SELECT id FROM projects WHERE id=%s FOR UPDATE", (project_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Project not found")


def _usage(cursor, user_id: int, project_id: int) -> tuple[int, int, int]:
    cursor.execute(
        "SELECT COALESCE(SUM(size_bytes),0) AS bytes,COUNT(*) AS count"
        " FROM documents WHERE project_id=%s AND status<>'failed'",
        (project_id,),
    )
    project_docs = cursor.fetchone()
    cursor.execute(
        "SELECT COALESCE(SUM(size_bytes),0) AS bytes,COUNT(*) AS count"
        " FROM upload_quota_reservations WHERE project_id=%s",
        (project_id,),
    )
    project_reservations = cursor.fetchone()
    cursor.execute(
        "SELECT COALESCE(SUM(size_bytes),0) AS bytes,COALESCE(SUM(count_units),0) AS count"
        " FROM storage_cleanup_pending WHERE project_id=%s",
        (project_id,),
    )
    project_cleanup = cursor.fetchone()
    cursor.execute(
        "SELECT COALESCE(SUM(size_bytes),0) AS bytes FROM documents"
        " WHERE uploaded_by=%s AND status<>'failed'",
        (user_id,),
    )
    user_docs = cursor.fetchone()
    cursor.execute(
        "SELECT COALESCE(SUM(size_bytes),0) AS bytes FROM upload_quota_reservations WHERE user_id=%s",
        (user_id,),
    )
    user_reservations = cursor.fetchone()
    cursor.execute(
        "SELECT COALESCE(SUM(size_bytes),0) AS bytes FROM storage_cleanup_pending WHERE user_id=%s",
        (user_id,),
    )
    user_cleanup = cursor.fetchone()
    project_bytes = sum(int(row["bytes"] or 0) for row in (project_docs, project_reservations, project_cleanup))
    project_count = sum(int(row["count"] or 0) for row in (project_docs, project_reservations, project_cleanup))
    user_bytes = sum(int(row["bytes"] or 0) for row in (user_docs, user_reservations, user_cleanup))
    return project_bytes, project_count, user_bytes


def reserve_document(
    project_id: int,
    user_id: int,
    size_bytes: int,
    kind: str,
    *,
    filename: str | None = None,
) -> dict:
    if size_bytes < 0 or kind not in {"physical", "virtual"}:
        raise ValueError("invalid reservation")
    reservation_id = str(uuid.uuid4())
    temp_path = target_path = None
    if kind == "physical":
        if not filename:
            raise ValueError("physical reservation requires filename")
        temp, target = reservation_paths(project_id, reservation_id, filename)
        temp_path, target_path = str(temp), str(target)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            _lock_user_project(cursor, user_id, project_id)
            project_bytes, project_count, user_bytes = _usage(cursor, user_id, project_id)
            project_limit, user_limit, count_limit = quota_limits()
            if (
                project_bytes + size_bytes > project_limit
                or user_bytes + size_bytes > user_limit
                or project_count + 1 > count_limit
            ):
                raise _quota_error()
            cursor.execute(
                "INSERT INTO upload_quota_reservations"
                " (reservation_id,user_id,project_id,kind,size_bytes,target_path,temp_path,expires_at)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,NOW()+INTERVAL %s MINUTE)",
                (reservation_id, user_id, project_id, kind, size_bytes, target_path, temp_path, RESERVATION_MINUTES),
            )
        conn.commit()
        return {
            "reservation_id": reservation_id,
            "user_id": user_id,
            "project_id": project_id,
            "kind": kind,
            "size_bytes": size_bytes,
            "target_path": target_path,
            "temp_path": temp_path,
        }
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def finalize_document(reservation_id: str, filename: str, doc_type: str) -> dict:
    """Atomically move one unexpired reservation into one processing document."""
    snapshot_conn = get_connection()
    try:
        with snapshot_conn.cursor() as cursor:
            cursor.execute(
                "SELECT user_id,project_id FROM upload_quota_reservations WHERE reservation_id=%s",
                (reservation_id,),
            )
            snapshot = cursor.fetchone()
    finally:
        snapshot_conn.close()
    if not snapshot:
        raise RuntimeError("reservation unavailable")

    token = str(uuid.uuid4())
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            _lock_user_project(cursor, snapshot["user_id"], snapshot["project_id"])
            cursor.execute(
                "SELECT *,expires_at>NOW() AS is_active FROM upload_quota_reservations"
                " WHERE reservation_id=%s FOR UPDATE",
                (reservation_id,),
            )
            row = cursor.fetchone()
            if not row or not row["is_active"]:
                raise RuntimeError("reservation expired")
            cursor.execute(
                "SELECT id FROM documents WHERE project_id=%s AND filename=%s AND status<>'failed'",
                (row["project_id"], filename),
            )
            old_doc_ids = [item["id"] for item in cursor.fetchall()]
            cursor.execute(
                "INSERT INTO documents"
                " (project_id,filename,doc_type,status,file_path,size_bytes,uploaded_by,processing_token,lease_expires_at)"
                " VALUES (%s,%s,%s,'processing',%s,%s,%s,%s,NOW()+INTERVAL %s MINUTE)",
                (
                    row["project_id"], filename, doc_type, row.get("target_path"),
                    row["size_bytes"], row["user_id"], token, LEASE_MINUTES,
                ),
            )
            doc_id = cursor.lastrowid
            cursor.execute("DELETE FROM upload_quota_reservations WHERE reservation_id=%s", (reservation_id,))
        conn.commit()
        return {
            "doc_id": doc_id,
            "project_id": row["project_id"],
            "processing_token": token,
            "file_path": row.get("target_path"),
            "old_doc_ids": old_doc_ids,
        }
    except BaseException as exc:
        try:
            conn.rollback()
        except Exception:
            # A lost COMMIT acknowledgement commonly leaves the socket unusable;
            # reconciliation must still run on a fresh connection.
            pass
        # COMMIT acknowledgement can be lost after MySQL has durably committed.
        # Re-read by the pre-generated fence token so the caller neither abandons
        # a completed reservation nor strands a processing document.
        committed = None
        try:
            verify_conn = get_connection()
            try:
                with verify_conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT id,project_id,file_path FROM documents"
                        " WHERE processing_token=%s AND status='processing' LIMIT 1",
                        (token,),
                    )
                    committed = cursor.fetchone()
            finally:
                verify_conn.close()
        except Exception:
            committed = None
        if committed is not None:
            if isinstance(exc, Exception):
                return {
                    "doc_id": committed["id"],
                    "project_id": committed["project_id"],
                    "processing_token": token,
                    "file_path": committed.get("file_path"),
                    "old_doc_ids": old_doc_ids,
                }
            # Cancellation and other BaseException subclasses must still
            # propagate, but the durably committed document can no longer be
            # compensated through its already-deleted reservation. Transfer
            # accounting to the cleanup ledger before re-raising.
            compensate_cancelled_document(committed["id"])
        raise
    finally:
        conn.close()


def _existing_reservation_path(row: dict) -> str | None:
    target = row.get("target_path")
    temp = row.get("temp_path")
    if target and Path(target).exists():
        return target
    return temp or target


def abandon_reservation(reservation_id: str) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM upload_quota_reservations WHERE reservation_id=%s", (reservation_id,)
            )
            snapshot = cursor.fetchone()
            if not snapshot:
                return
            _lock_user_project(cursor, snapshot["user_id"], snapshot["project_id"])
            cursor.execute(
                "SELECT * FROM upload_quota_reservations WHERE reservation_id=%s FOR UPDATE",
                (reservation_id,),
            )
            row = cursor.fetchone()
            if not row:
                return
            cursor.execute(
                "INSERT IGNORE INTO storage_cleanup_pending"
                " (cleanup_id,source_kind,source_id,user_id,project_id,document_id,file_path,size_bytes,count_units,needs_chroma)"
                " VALUES (%s,'reservation',%s,%s,%s,NULL,%s,%s,1,0)",
                (
                    str(uuid.uuid4()), reservation_id, row["user_id"], row["project_id"],
                    _existing_reservation_path(row), row["size_bytes"],
                ),
            )
            cursor.execute("DELETE FROM upload_quota_reservations WHERE reservation_id=%s", (reservation_id,))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def cleanup_failed_reservation(reservation_id: str) -> None:
    """Best-effort compensation that never masks the triggering failure."""
    try:
        abandon_reservation(reservation_id)
    except Exception:
        logger.warning(
            "reservation_abandon_deferred",
            extra={"code": "RESERVATION_ABANDON_FAILED"},
        )
        return
    try:
        cleanup_pending()
    except Exception:
        logger.warning(
            "storage_cleanup_retry_pending",
            extra={"code": "STORAGE_CLEANUP_FAILED"},
        )


def processing_owned(doc_id: int, token: str, *, renew: bool = False) -> bool:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            if renew:
                cursor.execute(
                    "UPDATE documents SET lease_expires_at=NOW()+INTERVAL %s MINUTE"
                    " WHERE id=%s AND status='processing' AND processing_token=%s",
                    (LEASE_MINUTES, doc_id, token),
                )
                owned = cursor.rowcount == 1
                if not owned:
                    # DATETIME has second precision, so an immediate renewal can
                    # assign the same value and report zero changed rows even
                    # though this token still owns the processing document.
                    cursor.execute(
                        "SELECT 1 FROM documents"
                        " WHERE id=%s AND status='processing' AND processing_token=%s"
                        " FOR UPDATE",
                        (doc_id, token),
                    )
                    owned = cursor.fetchone() is not None
                conn.commit()
                return owned
            cursor.execute(
                "SELECT 1 FROM documents WHERE id=%s AND status='processing' AND processing_token=%s",
                (doc_id, token),
            )
            return cursor.fetchone() is not None
    finally:
        conn.close()


def transfer_document_to_cleanup(
    doc_id: int,
    error_code: str,
    *,
    delete_row: bool = False,
    expected_processing_token: str | None = None,
) -> int | None:
    snapshot_conn = get_connection()
    try:
        with snapshot_conn.cursor() as cursor:
            cursor.execute("SELECT project_id,uploaded_by FROM documents WHERE id=%s", (doc_id,))
            snapshot = cursor.fetchone()
    finally:
        snapshot_conn.close()
    if not snapshot:
        return None
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            if snapshot.get("uploaded_by") is not None:
                cursor.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (snapshot["uploaded_by"],))
                cursor.fetchone()
            cursor.execute("SELECT id FROM projects WHERE id=%s FOR UPDATE", (snapshot["project_id"],))
            if not cursor.fetchone():
                return None
            cursor.execute("SELECT * FROM documents WHERE id=%s FOR UPDATE", (doc_id,))
            row = cursor.fetchone()
            if not row:
                return None
            if row["status"] == "failed" and not delete_row:
                # 실패 처리 경로(fail_document/fail_stale_document)는 이미 failed인 문서를
                # 다시 정리 큐에 넣지 않는다 — 멱등성 장치. 반면 사용자 삭제(delete_row=True)는
                # failed 문서에도 적용돼야 한다. 이 구분이 없어 DELETE 요청이 204를 돌려주면서
                # 행은 그대로 남았고, 재시도해도 같아서 지울 방법이 아예 없었다.
                return None
            if expected_processing_token is not None:
                if (
                    row["status"] != "processing"
                    or row.get("processing_token") != expected_processing_token
                ):
                    return None
                cursor.execute(
                    "SELECT 1 FROM documents WHERE id=%s AND lease_expires_at<NOW()",
                    (doc_id,),
                )
                if not cursor.fetchone():
                    return None
            cursor.execute(
                "INSERT IGNORE INTO storage_cleanup_pending"
                " (cleanup_id,source_kind,source_id,user_id,project_id,document_id,file_path,size_bytes,count_units,needs_chroma)"
                " VALUES (%s,'document',%s,%s,%s,%s,%s,%s,1,1)",
                (
                    str(uuid.uuid4()), str(doc_id), row.get("uploaded_by"), row["project_id"],
                    doc_id, row.get("file_path"), row["size_bytes"],
                ),
            )
            cursor.execute("DELETE FROM memory WHERE doc_id=%s", (doc_id,))
            if delete_row:
                # status 조건 없음 — 위 분기에서 delete_row=True만 failed를 통과시키므로,
                # 여기서 다시 거르면 그 문서가 영구히 안 지워진다(이중 차단이었다).
                cursor.execute("DELETE FROM documents WHERE id=%s", (doc_id,))
            else:
                cursor.execute(
                    "UPDATE documents SET status='failed',last_error=%s,size_bytes=0,file_path=NULL,"
                    "processing_token=NULL,lease_expires_at=NULL,progress_done=NULL,progress_total=NULL"
                    " WHERE id=%s AND status<>'failed'",
                    (error_code, doc_id),
                )
        conn.commit()
        return snapshot["project_id"]
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _delete_doc_vectors(document_id: int) -> None:
    from .db.chroma import delete_from_existing_collection

    delete_from_existing_collection(where={"doc_id": document_id})


def cleanup_pending(cleanup_id: str | None = None) -> int:
    """Retry durable cleanup; a row is released only after all external work succeeds."""
    conn = get_connection()
    cleaned = 0
    try:
        with conn.cursor() as cursor:
            if cleanup_id:
                cursor.execute(
                    "SELECT * FROM storage_cleanup_pending WHERE cleanup_id=%s FOR UPDATE", (cleanup_id,)
                )
            else:
                cursor.execute("SELECT * FROM storage_cleanup_pending ORDER BY created_at FOR UPDATE")
            rows = cursor.fetchall()
            for row in rows:
                try:
                    if row.get("file_path"):
                        delete_managed_file(row["file_path"], row["project_id"])
                    if row.get("needs_chroma") and row.get("document_id") is not None:
                        _delete_doc_vectors(row["document_id"])
                except Exception:
                    cursor.execute(
                        "UPDATE storage_cleanup_pending SET last_attempt_at=NOW() WHERE cleanup_id=%s",
                        (row["cleanup_id"],),
                    )
                    logger.warning(
                        "storage_cleanup_deferred",
                        extra={"project_id": row["project_id"], "code": "STORAGE_CLEANUP_FAILED"},
                    )
                    continue
                cursor.execute("DELETE FROM storage_cleanup_pending WHERE cleanup_id=%s", (row["cleanup_id"],))
                cleaned += 1
        conn.commit()
        return cleaned
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def fail_document(doc_id: int, error_code: str) -> None:
    transfer_document_to_cleanup(doc_id, error_code)
    try:
        cleanup_pending()
    except Exception:
        logger.warning("storage_cleanup_retry_pending", extra={"code": "STORAGE_CLEANUP_FAILED"})


def compensate_cancelled_document(doc_id: int) -> None:
    """Best-effort document compensation without consuming process-control signals."""
    try:
        fail_document(doc_id, "UPLOAD_CANCELLED")
    except Exception:
        logger.error(
            "cancelled_document_cleanup_failed",
            extra={"code": "UPLOAD_CANCELLATION_CLEANUP_FAILED"},
        )


def fail_stale_document(doc_id: int, processing_token: str) -> None:
    transfer_document_to_cleanup(
        doc_id,
        "UPLOAD_PROCESSING_STALE",
        expected_processing_token=processing_token,
    )
    try:
        cleanup_pending()
    except Exception:
        logger.warning("storage_cleanup_retry_pending", extra={"code": "STORAGE_CLEANUP_FAILED"})


def delete_document(doc_id: int) -> int | None:
    project_id = transfer_document_to_cleanup(doc_id, "DOCUMENT_DELETED", delete_row=True)
    try:
        cleanup_pending()
    except Exception:
        logger.warning("storage_cleanup_retry_pending", extra={"code": "STORAGE_CLEANUP_FAILED"})
    return project_id


def recover_quota_state() -> None:
    """Move expired reservations to cleanup and retry every durable cleanup row."""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT reservation_id FROM upload_quota_reservations WHERE expires_at<=NOW()")
            expired = [row["reservation_id"] for row in cursor.fetchall()]
    finally:
        conn.close()
    for reservation_id in expired:
        try:
            abandon_reservation(reservation_id)
        except Exception:
            logger.warning("reservation_recovery_deferred", extra={"code": "RESERVATION_RECOVERY_FAILED"})
    cleanup_pending()
