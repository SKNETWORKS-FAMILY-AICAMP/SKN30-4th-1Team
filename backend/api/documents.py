import asyncio
import logging
import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from ..db.mysql import get_connection
from ..document_content import (
    ALLOWED_SUFFIXES as _ALLOWED_SUFFIXES,
    PROJECT_DOCUMENT_MAX_FILE_BYTES as _MAX_FILE_BYTES,
    DocumentContentError,
    supported_formats_label,
    validate_document_bytes,
)
from ..pipeline.converters import ConversionError, ConvertedDocument, ErrorCode, convert
from ..pipeline.extractor import extract
from ..pipeline.ingestor import ingest
from ..project_memory import refresh_project_memory_after_delete, update_project_memory
from ..quota import (
    cleanup_failed_reservation,
    compensate_cancelled_document,
    delete_document as quota_delete_document,
    fail_document,
    finalize_document,
    processing_owned,
    require_upload_user,
    reserve_document,
)
from ..rate_limit import RATE_LIMIT_UPLOAD, authenticated_user_key, limiter
from ..storage import safe_upload_name, write_reserved_file
from .auth import require_project_access
from .errors import error_response


router = APIRouter()
logger = logging.getLogger(__name__)

_UPLOAD_PROCESS_LOCK = threading.Lock()

_DOC_TYPE_KEYWORDS = {
    "meeting": ["meeting", "회의", "회의록", "minutes"],
    "planning": ["planning", "기획", "plan", "roadmap", "spec"],
}


def _infer_doc_type(filename: str) -> str:
    name = filename.lower()
    for doc_type, keywords in _DOC_TYPE_KEYWORDS.items():
        if any(keyword in name for keyword in keywords):
            return doc_type
    return "document"


def _conversion_error_response(exc: ConversionError):
    """Convert a document conversion failure to the established API response."""
    if exc.code == ErrorCode.INVALID_CONTENT:
        return error_response(415, {"code": exc.code, "message": exc.message})
    return error_response(400, exc.message, code=exc.code)


def _content_error_response(exc: DocumentContentError):
    """Keep validation failures on the existing nested 415 response contract."""
    return error_response(415, {"code": exc.code, "message": exc.message})


def _convert_upload(filename: str, data: bytes) -> ConvertedDocument:
    """Convert before reserving storage so conversion errors have no cleanup work."""
    return convert(filename, data)


def _delete_document(doc_id: int, refresh_project_memory: bool = True):
    """Transfer document accounting to durable cleanup, then refresh the summary."""
    project_id = quota_delete_document(doc_id)
    if refresh_project_memory and project_id is not None:
        refresh_project_memory_after_delete(project_id)


def _set_doc_status(doc_id: int, status: str, last_error: Optional[str] = None):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE documents"
                " SET status=%s, last_error=%s, progress_done=NULL, progress_total=NULL"
                " WHERE id=%s",
                (status, last_error, doc_id),
            )
        conn.commit()
    except Exception:
        logger.warning("documents status update failed doc_id=%s", doc_id)
    finally:
        conn.close()


def _set_doc_progress(
    doc_id: int,
    done: int,
    total: int,
    processing_token: str | None = None,
):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            if processing_token is None:
                cursor.execute(
                    "UPDATE documents SET progress_done=%s, progress_total=%s WHERE id=%s",
                    (done, total, doc_id),
                )
            else:
                cursor.execute(
                    "UPDATE documents SET progress_done=%s,progress_total=%s,"
                    "lease_expires_at=NOW()+INTERVAL 30 MINUTE"
                    " WHERE id=%s AND status='processing' AND processing_token=%s",
                    (done, total, doc_id, processing_token),
                )
        conn.commit()
    except Exception:
        logger.warning("documents progress update failed doc_id=%s", doc_id)
    finally:
        conn.close()


def _process_upload(
    project_id: int,
    doc_id: int,
    old_doc_ids: list,
    document: ConvertedDocument,
    filename: str,
    date: str,
    doc_type: str,
    file_path: str,
    processing_token: str | None = None,
):
    """LLM extract → ingest → status update → old document cleanup."""
    # ponytail: global lock; per-project queues if folder ingest throughput matters.
    while not _UPLOAD_PROCESS_LOCK.acquire(timeout=1):
        if processing_token is not None and not processing_owned(
            doc_id, processing_token, renew=True
        ):
            return
    try:
        _process_upload_locked(
            project_id,
            doc_id,
            old_doc_ids,
            document,
            filename,
            date,
            doc_type,
            file_path,
            processing_token,
        )
    finally:
        _UPLOAD_PROCESS_LOCK.release()


def _process_upload_locked(
    project_id: int,
    doc_id: int,
    old_doc_ids: list,
    document: ConvertedDocument,
    filename: str,
    date: str,
    doc_type: str,
    file_path: str,
    processing_token: str | None = None,
):
    """Upload worker body; callers serialize concurrent processing."""
    content = document.text
    try:
        if processing_token is not None and not processing_owned(
            doc_id, processing_token, renew=True
        ):
            return
        items = extract(
            content,
            default_source=filename,
            on_progress=lambda done, total: _set_doc_progress(
                doc_id, done, total, processing_token
            ),
        )
        if processing_token is not None and not processing_owned(
            doc_id, processing_token, renew=True
        ):
            return
    except asyncio.CancelledError:
        compensate_cancelled_document(doc_id)
        raise
    except Exception:
        logger.error(
            "upload_extract_failed",
            extra={"project_id": project_id, "code": "UPLOAD_EXTRACT_FAILED"},
        )
        fail_document(doc_id, "UPLOAD_EXTRACT_FAILED")
        return

    try:
        ingest(
            project_id=project_id,
            doc_id=doc_id,
            items=items,
            raw_text=content,
            source=filename,
            date=date,
            doc_type=doc_type,
            source_metadata={
                "source_kind": "document",
                "source_type": doc_type,
                "source_path": filename,
            },
            converted=document,
            processing_token=processing_token,
        )
    except asyncio.CancelledError:
        compensate_cancelled_document(doc_id)
        raise
    except Exception:
        logger.error(
            "upload_ingest_failed",
            extra={"project_id": project_id, "code": "UPLOAD_INGEST_FAILED"},
        )
        fail_document(doc_id, "UPLOAD_INGEST_FAILED")
        return

    if processing_token is None:
        _set_doc_status(doc_id, "indexed")

    try:
        update_project_memory(project_id, items)
    except Exception:
        logger.warning("프로젝트 메모리 갱신 실패 (업로드는 성공): project_id=%s", project_id)

    for old_id in old_doc_ids:
        _delete_document(old_id, refresh_project_memory=False)
    if old_doc_ids:
        refresh_project_memory_after_delete(project_id)


@router.post("/projects/{project_id}/documents", status_code=201)
@limiter.limit(RATE_LIMIT_UPLOAD, key_func=authenticated_user_key)
async def upload_document(
    request: Request,
    project_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    date: str = Form(""),
):
    try:
        filename = safe_upload_name(file.filename or "")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if Path(filename).suffix.lower() not in _ALLOWED_SUFFIXES:
        return error_response(
            400,
            f"지원하지 않는 파일 형식입니다. ({supported_formats_label()})",
            code=ErrorCode.UNSUPPORTED_FORMAT,
        )
    doc_type = _infer_doc_type(filename)

    user_id = require_upload_user()
    require_project_access(project_id, min_role="member")

    data = await file.read()
    if len(data) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="파일 크기는 10 MB를 초과할 수 없습니다.")

    try:
        validate_document_bytes(filename, data)
    except DocumentContentError as exc:
        return _content_error_response(exc)

    try:
        document = _convert_upload(filename, data)
    except ConversionError as exc:
        logger.info("문서 변환 실패 filename=%s code=%s", filename, exc.code)
        return _conversion_error_response(exc)

    if not document.text.strip():
        raise HTTPException(status_code=400, detail="content must not be empty")
    reservation = reserve_document(
        project_id, user_id, len(data), "physical", filename=filename
    )
    try:
        write_reserved_file(reservation["temp_path"], reservation["target_path"], data)
        finalized = finalize_document(reservation["reservation_id"], filename, doc_type)
    except BaseException:
        cleanup_failed_reservation(reservation["reservation_id"])
        raise

    background_tasks.add_task(
        _process_upload,
        project_id,
        finalized["doc_id"],
        finalized["old_doc_ids"],
        document,
        filename,
        date,
        doc_type,
        finalized["file_path"],
        finalized["processing_token"],
    )

    if document.warnings:
        logger.info(
            "문서 변환 경고 doc_id=%s count=%s codes=%s",
            finalized["doc_id"],
            len(document.warnings),
            sorted({warning.code for warning in document.warnings}),
        )

    return {
        "doc_id": finalized["doc_id"],
        "status": "processing",
        "format": document.format,
        "blocks": len(document.blocks),
        "pages": document.page_count,
        "warnings": document.warning_dicts(),
    }


@router.get("/projects/{project_id}/documents")
def list_documents(project_id: int):
    require_project_access(project_id)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Project not found")
            cursor.execute(
                "SELECT id, filename, doc_type, status, uploaded_at"
                " FROM documents WHERE project_id = %s ORDER BY uploaded_at DESC",
                (project_id,),
            )
            return cursor.fetchall()
    finally:
        conn.close()


@router.get("/projects/{project_id}/documents/{doc_id}/status")
def get_document_status(project_id: int, doc_id: int):
    require_project_access(project_id)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, status, last_error, progress_done, progress_total"
                " FROM documents WHERE id = %s AND project_id = %s",
                (doc_id, project_id),
            )
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Document not found")
            cursor.execute(
                "SELECT category, COUNT(*) as cnt FROM memory WHERE doc_id = %s GROUP BY category",
                (doc_id,),
            )
            counts = {"decision": 0, "action": 0, "issue": 0, "risk": 0}
            for category_row in cursor.fetchall():
                if category_row["category"] in counts:
                    counts[category_row["category"]] = category_row["cnt"]
    finally:
        conn.close()
    return {
        "doc_id": row["id"],
        "status": row["status"],
        "last_error": row.get("last_error"),
        "progress_done": row.get("progress_done"),
        "progress_total": row.get("progress_total"),
        "extracted": counts,
    }


@router.delete("/projects/{project_id}/documents/{doc_id}", status_code=204)
def delete_document(project_id: int, doc_id: int):
    require_project_access(project_id, min_role="member")
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM documents WHERE id = %s AND project_id = %s",
                (doc_id, project_id),
            )
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Document not found")
    finally:
        conn.close()
    _delete_document(doc_id)


class GitLogUpload(BaseModel):
    content: str
    source: str = "git log"
    date: str = ""


@router.post("/projects/{project_id}/git", status_code=201)
def upload_git_log(project_id: int, body: GitLogUpload):
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content must not be empty")

    user_id = require_upload_user()
    require_project_access(project_id, min_role="member")
    reservation = reserve_document(
        project_id, user_id, len(body.content.encode("utf-8")), "virtual"
    )
    try:
        finalized = finalize_document(reservation["reservation_id"], "git_log.txt", "git")
    except BaseException:
        cleanup_failed_reservation(reservation["reservation_id"])
        raise
    doc_id = finalized["doc_id"]

    try:
        items = extract(body.content, default_source=body.source)
        ingest(
            project_id=project_id,
            doc_id=doc_id,
            items=items,
            raw_text=body.content,
            source=body.source,
            date=body.date,
            doc_type="git",
            processing_token=finalized["processing_token"],
        )
    except asyncio.CancelledError:
        compensate_cancelled_document(doc_id)
        raise
    except Exception:
        logger.error(
            "git_ingest_failed",
            extra={"project_id": project_id, "code": "GIT_INGEST_FAILED"},
        )
        fail_document(doc_id, "GIT_INGEST_FAILED")
        raise HTTPException(status_code=503, detail="Git 로그 처리 중 오류가 발생했습니다.")

    for old_doc_id in finalized["old_doc_ids"]:
        quota_delete_document(old_doc_id)

    try:
        update_project_memory(project_id, items)
    except Exception:
        logger.warning(
            "git_project_memory_update_failed",
            extra={"project_id": project_id, "code": "PROJECT_MEMORY_UPDATE_FAILED"},
        )

    counts = {"decision": 0, "action": 0, "issue": 0, "risk": 0}
    for item in items:
        counts[item.category] += 1

    return {"doc_id": doc_id, "extracted": counts}
