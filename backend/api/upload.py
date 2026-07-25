import logging
import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File, Form, Request
from pydantic import BaseModel
from ..db.mysql import get_connection
from ..document_content import (
    ALLOWED_SUFFIXES as _ALLOWED_SUFFIXES,
    MAX_FILE_BYTES as _MAX_FILE_BYTES,
    DocumentContentError,
    extract_document_text,
)
from ..pipeline.extractor import extract
from ..pipeline.ingestor import ingest
from ..retriever.memory_vector import delete_memory_vector, upsert_memory_vector
from ..storage import save_file, delete_file, safe_upload_name
from ..graph import refresh_project_memory_after_delete, update_project_memory
from ..rate_limit import RATE_LIMIT_UPLOAD, authenticated_user_key, limiter
from .auth import get_current_user_id, require_project_access

router = APIRouter()
logger = logging.getLogger(__name__)

_UPLOAD_PROCESS_LOCK = threading.Lock()

_DOC_TYPE_KEYWORDS = {
    "meeting":  ["meeting", "회의", "회의록", "minutes"],
    "planning": ["planning", "기획", "plan", "roadmap", "spec"],
}

def _infer_doc_type(filename: str) -> str:
    name = filename.lower()
    for doc_type, keywords in _DOC_TYPE_KEYWORDS.items():
        if any(kw in name for kw in keywords):
            return doc_type
    return "document"


# ── 파일 텍스트 추출 ──────────────────────────────────────────────

def _read_pdf(data: bytes) -> str:
    return extract_document_text("document.pdf", data)


def _extract_text(filename: str, data: bytes) -> str:
    return extract_document_text(filename, data)


# ── 내부 헬퍼 ─────────────────────────────────────────────────────

def _delete_chroma_vectors(doc_id: int):
    try:
        from ..db.chroma import get_collection
        get_collection().delete(where={"doc_id": doc_id})
    except Exception:
        logger.warning("ChromaDB vector cleanup failed for doc_id=%s", doc_id, exc_info=True)


def _delete_document(doc_id: int, refresh_project_memory: bool = True):
    """MySQL memory/documents 행 삭제 + ChromaDB 벡터 삭제 + 원본 파일 삭제."""
    conn = get_connection()
    file_path = None
    project_id = None
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT project_id, file_path FROM documents WHERE id = %s", (doc_id,))
            row = cursor.fetchone()
            if row:
                project_id = row.get("project_id")
                file_path = row.get("file_path")
            cursor.execute("DELETE FROM memory WHERE doc_id = %s", (doc_id,))
            cursor.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
        conn.commit()
    except Exception:
        logger.warning("MySQL delete failed for doc_id=%s", doc_id, exc_info=True)
    finally:
        conn.close()
    _delete_chroma_vectors(doc_id)
    if file_path:
        delete_file(file_path)
    if refresh_project_memory and project_id is not None:
        refresh_project_memory_after_delete(project_id)


def _delete_doc_memory(doc_id: int):
    """ingest 실패 시 부분 커밋된 memory 행 정리 (documents 행은 유지)."""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM memory WHERE doc_id = %s", (doc_id,))
        conn.commit()
    except Exception:
        logger.warning("memory cleanup failed doc_id=%s", doc_id, exc_info=True)
    finally:
        conn.close()


def _upsert_memory_vector_best_effort(row: dict):
    """수동 memory 변경 후 ChromaDB 보조 인덱스를 갱신한다."""
    try:
        upsert_memory_vector(row)
    except Exception:
        logger.warning("memory vector upsert failed memory_id=%s", row.get("id"), exc_info=True)


def _delete_memory_vector_best_effort(memory_id: int):
    """수동 memory 삭제 후 ChromaDB 보조 인덱스를 삭제한다."""
    try:
        delete_memory_vector(memory_id)
    except Exception:
        logger.warning("memory vector delete failed memory_id=%s", memory_id, exc_info=True)


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
        logger.warning("documents status update failed doc_id=%s", doc_id, exc_info=True)
    finally:
        conn.close()


def _set_doc_progress(doc_id: int, done: int, total: int):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE documents SET progress_done=%s, progress_total=%s WHERE id=%s",
                (done, total, doc_id),
            )
        conn.commit()
    except Exception:
        logger.warning("documents progress update failed doc_id=%s", doc_id, exc_info=True)
    finally:
        conn.close()


# ── 백그라운드 처리 ───────────────────────────────────────────────

def _process_upload(
    project_id: int,
    doc_id: int,
    old_doc_ids: list,
    content: str,
    filename: str,
    date: str,
    doc_type: str,
    file_path: str,
):
    """LLM extract → ingest → status 갱신 → 이전 문서 정리."""
    # ponytail: global lock; per-project queues if folder ingest throughput matters.
    with _UPLOAD_PROCESS_LOCK:
        _process_upload_locked(project_id, doc_id, old_doc_ids, content, filename, date, doc_type, file_path)


def _process_upload_locked(
    project_id: int,
    doc_id: int,
    old_doc_ids: list,
    content: str,
    filename: str,
    date: str,
    doc_type: str,
    file_path: str,
):
    """실제 업로드 처리 본문. 호출자는 동시 실행을 제한한다."""
    try:
        items = extract(
            content,
            default_source=filename,
            on_progress=lambda done, total: _set_doc_progress(doc_id, done, total),
        )
    except Exception as exc:
        logger.error("extract 실패 doc_id=%s", doc_id, exc_info=True)
        delete_file(file_path)
        _set_doc_status(doc_id, "failed", last_error=str(exc))
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
        )
    except Exception as exc:
        logger.error("ingest 실패 doc_id=%s", doc_id, exc_info=True)
        _delete_doc_memory(doc_id)
        _delete_chroma_vectors(doc_id)
        delete_file(file_path)
        _set_doc_status(doc_id, "failed", last_error=str(exc))
        return

    _set_doc_status(doc_id, "indexed")

    # 6단계: 프로젝트 메모리 갱신 (best-effort — 요약 실패해도 업로드는 성공 처리)
    try:
        update_project_memory(project_id, items)
    except Exception:
        logger.warning("프로젝트 메모리 갱신 실패 (업로드는 성공): project_id=%s", project_id, exc_info=True)

    for old_id in old_doc_ids:
        _delete_document(old_id, refresh_project_memory=False)
    if old_doc_ids:
        refresh_project_memory_after_delete(project_id)


# ── Documents ─────────────────────────────────────────────────────

@router.post("/projects/{project_id}/documents", status_code=201)
@limiter.limit(RATE_LIMIT_UPLOAD, key_func=authenticated_user_key)
async def upload_document(
    request: Request,
    project_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    date: str = Form(""),
):
    require_project_access(project_id, min_role="member")
    try:
        filename = safe_upload_name(file.filename or "")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if Path(filename).suffix.lower() not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="지원하지 않는 파일 형식입니다. (.md / .txt / .pdf)")
    doc_type = _infer_doc_type(filename)

    data = await file.read()
    if len(data) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="파일 크기는 10 MB를 초과할 수 없습니다.")
    try:
        content = extract_document_text(filename, data)
    except DocumentContentError as exc:
        raise HTTPException(
            status_code=415,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    if not content.strip():
        raise HTTPException(status_code=400, detail="content must not be empty")

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Project not found")
            cursor.execute(
                "SELECT id FROM documents WHERE project_id = %s AND filename = %s",
                (project_id, filename),
            )
            old_doc_ids = [row["id"] for row in cursor.fetchall()]
    finally:
        conn.close()

    file_path = save_file(project_id, filename, data)

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO documents (project_id, filename, doc_type, status, file_path)"
                " VALUES (%s, %s, %s, 'processing', %s)",
                (project_id, filename, doc_type, file_path),
            )
            doc_id = cursor.lastrowid
        conn.commit()
    except Exception:
        conn.rollback()
        delete_file(file_path)
        raise
    finally:
        conn.close()

    background_tasks.add_task(
        _process_upload, project_id, doc_id, old_doc_ids,
        content, filename, date, doc_type, file_path,
    )

    return {"doc_id": doc_id, "status": "processing"}


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
            for r in cursor.fetchall():
                if r["category"] in counts:
                    counts[r["category"]] = r["cnt"]
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


# ── Memory ────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/memory")
def get_memory(project_id: int, category: str = None, owner: str = None):
    require_project_access(project_id)
    from ..retriever.mysql_search import search
    return search(project_id, category=category, owner=owner)


class MemoryCreate(BaseModel):
    category: str
    content: str
    owner: Optional[str] = None
    date: Optional[str] = None
    due_date: Optional[str] = None
    topic: Optional[str] = None
    reason: Optional[str] = None


@router.post("/projects/{project_id}/memory", status_code=201)
def create_memory(project_id: int, body: MemoryCreate):
    require_project_access(project_id, min_role="member")
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Project not found")
            cursor.execute(
                "INSERT INTO memory"
                " (project_id, doc_id, category, content, reason, topic, owner, date, due_date,"
                " created_by, is_user_verified, completion_status, completion_status_source)"
                " VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, %s, 'user', 1, %s, %s)",
                (
                    project_id, body.category, body.content, body.reason, body.topic,
                    body.owner, body.date or None, body.due_date or None,
                    "open" if body.category == "action" else "unknown",
                    "user" if body.category == "action" else None,
                ),
            )
            memory_id = cursor.lastrowid
        conn.commit()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM memory WHERE id = %s", (memory_id,))
            row = cursor.fetchone()
        _upsert_memory_vector_best_effort(row)
        return row
    finally:
        conn.close()


class MemoryUpdate(BaseModel):
    category: Optional[str] = None
    content: Optional[str] = None
    owner: Optional[str] = None
    date: Optional[str] = None
    due_date: Optional[str] = None
    topic: Optional[str] = None
    reason: Optional[str] = None
    completed: Optional[bool] = None
    sort_order: Optional[int] = None


@router.patch("/projects/{project_id}/memory/{memory_id}")
def update_memory(project_id: int, memory_id: int, body: MemoryUpdate):
    require_project_access(project_id, min_role="member")
    raw_fields = body.model_dump(exclude_unset=True)
    fields = {
        k: v
        for k, v in raw_fields.items()
        if k in {"category", "content", "owner", "date", "topic", "reason"} and v is not None
    }
    if "due_date" in raw_fields:
        fields["due_date"] = raw_fields["due_date"]
    has_completed_update = "completed" in raw_fields
    if "sort_order" in raw_fields:
        fields["sort_order"] = raw_fields["sort_order"]
    if has_completed_update and raw_fields["completed"] is None:
        raise HTTPException(status_code=400, detail="completed는 true 또는 false여야 합니다.")
    if not fields and not has_completed_update:
        raise HTTPException(status_code=400, detail="수정할 필드가 없습니다.")

    fields["updated_by"] = "user"
    if any(
        k in raw_fields and raw_fields[k] is not None
        for k in {"category", "content", "owner", "date", "due_date", "topic", "reason"}
    ):
        fields["is_user_verified"] = 1

    set_parts = []
    values = []
    if has_completed_update:
        if fields.get("category") not in (None, "action"):
            raise HTTPException(
                status_code=400,
                detail="completed는 action category에서만 설정할 수 있습니다.",
            )
        if raw_fields["completed"]:
            set_parts.append("completed_at = NOW()")
            set_parts.append("completion_status = 'completed'")
        else:
            set_parts.append("completed_at = %s")
            values.append(None)
            set_parts.append("completion_status = 'open'")
        set_parts.append("completion_status_source = 'user'")
    elif "category" in fields:
        if fields["category"] == "action":
            # 기존 action의 명시 상태는 유지한다. 비action을 action으로 바꾸는
            # 사용자 편집만 새로 열린 작업으로 확정한다.
            set_parts.extend([
                "completed_at = CASE WHEN category = 'action' THEN completed_at ELSE NULL END",
                (
                    "completion_status = CASE WHEN category = 'action'"
                    " THEN completion_status ELSE 'open' END"
                ),
                (
                    "completion_status_source = CASE WHEN category = 'action'"
                    " THEN completion_status_source ELSE 'user' END"
                ),
            ])
        else:
            # 완료 상태는 action 전용 의미이므로 category를 벗어나면 제거한다.
            set_parts.extend([
                "completed_at = NULL",
                "completion_status = 'unknown'",
                "completion_status_source = NULL",
            ])
    set_parts.extend(f"{k} = %s" for k in fields)
    values.extend(fields.values())
    values.extend([memory_id, project_id])
    set_clause = ", ".join(set_parts)

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            if has_completed_update and "category" not in fields:
                cursor.execute(
                    "SELECT category FROM memory"
                    " WHERE id = %s AND project_id = %s FOR UPDATE",
                    (memory_id, project_id),
                )
                current_memory = cursor.fetchone()
                if not current_memory:
                    raise HTTPException(status_code=404, detail="Memory item not found")
                if current_memory.get("category") != "action":
                    raise HTTPException(
                        status_code=400,
                        detail="completed는 action category에서만 설정할 수 있습니다.",
                    )
            # category를 decision 밖으로 바꾸는 변경은, 이 row를 대체자(superseded_by)로
            # 참조하는 결정이 있으면 거부 — accept 시점 검증(살아있는 decision만 대체자 허용)이
            # 사후 PATCH로 무력화되어 비decision이 결정을 숨기는 상태를 만들지 않도록.
            if fields.get("category") not in (None, "decision"):
                cursor.execute(
                    "SELECT 1 FROM memory WHERE superseded_by = %s AND project_id = %s LIMIT 1",
                    (memory_id, project_id),
                )
                if cursor.fetchone():
                    raise HTTPException(
                        status_code=409,
                        detail="Cannot change category: this decision supersedes another decision",
                    )
                # 이 row 자신이 이미 번복된(superseded) decision이면 category 이탈 거부 —
                # 사람이 승인한 supersede 관계는 decision→decision이어야 하며, 허용하면
                # 새 category의 항목이 active_memory에서 계속 숨겨진 채 남는다.
                cursor.execute(
                    "SELECT superseded_by FROM memory WHERE id = %s AND project_id = %s",
                    (memory_id, project_id),
                )
                current = cursor.fetchone()
                if current and current.get("superseded_by") is not None:
                    raise HTTPException(
                        status_code=409,
                        detail="Cannot change category: this decision is superseded by another decision",
                    )
            # 의미 필드(category/content/topic/reason/date)가 바뀌면 이 row가
            # 대상(memory_id)이든 대체자(evidence.superseding_memory_id)든 관련된
            # pending supersede 제안을 자동 reject한다. 제안의 LLM 판정은 생성 시점
            # 내용 기준이라 사용자가 결정을 수정하면 근거가 낡고, 특히 대상의
            # category 이탈은 accept/reject 모두 404인 영구 미해소(zombie)를 만든다.
            # 사람이 확정한 상태(superseded_by)는 위 409로 지키고,
            # LLM의 추측(pending 제안)은 사용자의 수정에 양보한다.
            if any(raw_fields.get(k) is not None
                   for k in ("category", "content", "topic", "reason", "date")):
                cursor.execute(
                    "UPDATE memory_suggestions"
                    " SET status = 'rejected', resolved_at = NOW(), resolved_by = %s"
                    " WHERE project_id = %s AND kind = 'supersede' AND status = 'pending'"
                    " AND (memory_id = %s OR CAST(JSON_UNQUOTE(JSON_EXTRACT("
                    "evidence, '$.superseding_memory_id')) AS UNSIGNED) = %s)",
                    (get_current_user_id(), project_id, memory_id, memory_id),
                )
            cursor.execute(
                f"UPDATE memory SET {set_clause} WHERE id = %s AND project_id = %s",
                values,
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Memory item not found")
        conn.commit()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM memory WHERE id = %s", (memory_id,))
            row = cursor.fetchone()
        if row and row.get("superseded_by") is not None:
            # superseded(숨겨진) memory의 벡터는 upsert로 부활시키지 않는다 — accept가
            # 삭제한 상태를 유지해 비활성 벡터가 후보/RAG top-N을 차지하지 못하게 한다.
            _delete_memory_vector_best_effort(memory_id)
        else:
            _upsert_memory_vector_best_effort(row)
        return row
    finally:
        conn.close()


@router.delete("/projects/{project_id}/memory/{memory_id}", status_code=204)
def delete_memory(project_id: int, memory_id: int):
    require_project_access(project_id, min_role="member")
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM memory WHERE id = %s AND project_id = %s",
                (memory_id, project_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Memory item not found")
        conn.commit()
    finally:
        conn.close()
    _delete_memory_vector_best_effort(memory_id)
    refresh_project_memory_after_delete(project_id)
