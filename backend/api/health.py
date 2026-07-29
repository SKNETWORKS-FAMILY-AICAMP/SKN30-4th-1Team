import asyncio
import concurrent.futures
import os
import threading
import uuid

import chromadb
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..db.mysql import get_readiness_connection
from ..request_context import get_request_id
from ..storage import ensure_upload_root_safe

router = APIRouter()

_COMPONENT_TIMEOUT = 2.0
_OVERALL_TIMEOUT = 5.0
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="readiness")
_lock = threading.Lock()
_pending: dict[str, concurrent.futures.Future] = {}

_SCHEMA = {
    "users": {"id", "email", "name", "password_hash", "created_at"},
    "projects": {"id", "name", "owner_user_id", "created_at"},
    "project_members": {"project_id", "user_id", "role", "created_at", "last_seen_at"},
    "documents": {"id", "project_id", "filename", "doc_type", "status", "file_path", "last_error", "progress_done", "progress_total", "size_bytes", "uploaded_by", "processing_token", "lease_expires_at", "uploaded_at"},
    "repositories": {"id", "project_id", "provider", "repository_url", "branch", "status", "commit_sha", "indexed_files", "last_error", "sync_warning", "last_reconciled_pr", "connected_at", "sync_started_at"},
    "memory": {"id", "project_id", "doc_id", "repo_id", "category", "content", "reason", "topic", "owner", "date", "due_date", "source", "created_by", "updated_by", "is_user_verified", "completed_at", "completion_status", "completion_status_source", "superseded_by", "superseded_at", "sort_order", "created_at"},
    "memory_sources": {"id", "memory_id", "source_kind", "doc_id", "repo_id", "source_type", "source_path", "source_ref", "source_url", "created_at"},
    "memory_suggestions": {"id", "project_id", "memory_id", "kind", "evidence", "rationale", "confidence", "status", "created_at", "resolved_at", "resolved_by"},
    "chat_sessions": {"id", "project_id", "user_id", "title", "created_at", "updated_at"},
    "chat_messages": {"id", "session_id", "role", "ciphertext", "nonce", "key_version", "token_count", "created_at"},
    "chat_summaries": {"session_id", "ciphertext", "nonce", "key_version", "source_message_id", "updated_at"},
    "project_memory": {"project_id", "summary", "updated_at"},
    "upload_quota_reservations": {"reservation_id", "user_id", "project_id", "kind", "size_bytes", "target_path", "temp_path", "created_at", "expires_at"},
    "storage_cleanup_pending": {"cleanup_id", "source_kind", "source_id", "user_id", "project_id", "document_id", "file_path", "size_bytes", "count_units", "needs_chroma", "created_at", "last_attempt_at"},
}
_VIEWS = {"active_memory": _SCHEMA["memory"]}


def _mysql_probe() -> None:
    conn = get_readiness_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    finally:
        conn.close()


def _schema_probe() -> None:
    conn = get_readiness_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()")
            found: dict[str, set[str]] = {}
            for row in cursor.fetchall():
                found.setdefault(row["TABLE_NAME"], set()).add(row["COLUMN_NAME"])
            for table, columns in _SCHEMA.items():
                if not columns.issubset(found.get(table, set())):
                    raise RuntimeError("schema manifest mismatch")
            for view, columns in _VIEWS.items():
                if not columns.issubset(found.get(view, set())):
                    raise RuntimeError("schema manifest mismatch")
            cursor.execute("SELECT 1 FROM documents WHERE size_bytes IS NULL LIMIT 1")
            if cursor.fetchone():
                raise RuntimeError("schema migration pending")
    finally:
        conn.close()


def _chroma_probe() -> None:
    client = chromadb.PersistentClient(path=os.getenv("CHROMA_PERSIST_DIR", ".chroma"))
    client.heartbeat()
    names = {item.name for item in client.list_collections()}
    name = os.getenv("CHROMA_COLLECTION_NAME", "paiM_openai_v2")
    if name in names:
        client.get_collection(name).count()


def _upload_probe() -> None:
    root = ensure_upload_root_safe(scan_tree=False)
    path = root / f".ready-{uuid.uuid4()}"
    fd = None
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(fd, b"ready")
        os.fsync(fd)
    finally:
        if fd is not None:
            os.close(fd)
        path.unlink(missing_ok=True)


_PROBES = {"mysql": _mysql_probe, "schema": _schema_probe, "chroma": _chroma_probe, "upload": _upload_probe}


def _future(name: str) -> concurrent.futures.Future:
    with _lock:
        current = _pending.get(name)
        if current is not None and not current.done():
            return current
        future = _executor.submit(_PROBES[name])
        _pending[name] = future
        return future


async def _run(name: str) -> tuple[str, str]:
    future = _future(name)
    try:
        await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)), _COMPONENT_TIMEOUT)
        return name, "ok"
    except asyncio.TimeoutError:
        return name, "timeout"
    except Exception:
        return name, "failed"


@router.get("/health/ready")
async def readiness():
    try:
        pairs = await asyncio.wait_for(
            asyncio.gather(*(_run(name) for name in _PROBES)), _OVERALL_TIMEOUT
        )
        components = {name: {"status": status} for name, status in pairs}
    except asyncio.TimeoutError:
        components = {name: {"status": "timeout"} for name in _PROBES}
    ready = all(item["status"] == "ok" for item in components.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "components": components, "request_id": get_request_id()},
    )
