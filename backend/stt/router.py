"""Authenticated audio upload endpoint for STT-backed Project Memory ingestion."""
from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile

from ..api.auth import require_project_access
from ..project_memory import refresh_project_memory_after_delete
from ..quota import (
    cleanup_failed_reservation,
    compensate_cancelled_document,
    delete_document,
    fail_document,
    finalize_document,
    processing_owned,
    require_upload_user,
    reserve_document,
)
from ..rate_limit import RATE_LIMIT_UPLOAD, authenticated_user_key, limiter
from ..storage import safe_upload_name, validate_managed_file, write_reserved_file
from .base import TranscriptionError
from .pipeline import ingest_transcript
from .transcriber import (
    current_provider_name,
    max_audio_bytes,
    supported_suffixes,
    supports_diarization,
    transcribe,
)


router = APIRouter()
logger = logging.getLogger(__name__)
_STT_PROCESS_LOCK = threading.Lock()


def _fail_audio_document(doc_id: int, error_code: str) -> None:
    """Persist a stable, non-secret error code and schedule all side-effect cleanup."""
    fail_document(doc_id, error_code)


def _process_audio_locked(
    project_id: int,
    doc_id: int,
    old_doc_ids: list[int],
    filename: str,
    file_path: str,
    date: str,
    processing_token: str,
) -> None:
    if not processing_owned(doc_id, processing_token, renew=True):
        return

    try:
        data = validate_managed_file(file_path, project_id).read_bytes()
        transcript = transcribe(filename, data)
        if not processing_owned(doc_id, processing_token, renew=True):
            return
        ingest_transcript(
            project_id=project_id,
            transcript=transcript,
            date=date,
            doc_id=doc_id,
            processing_token=processing_token,
            on_progress=lambda done, total: _set_progress(
                doc_id, done, total, processing_token
            ),
        )
    except asyncio.CancelledError:
        compensate_cancelled_document(doc_id)
        raise
    except TranscriptionError as exc:
        logger.info(
            "stt_transcription_failed",
            extra={"project_id": project_id, "code": exc.code},
        )
        error_code = exc.code.upper()
        if not error_code.startswith("STT_"):
            error_code = f"STT_{error_code}"
        _fail_audio_document(doc_id, error_code)
        return
    except Exception:
        logger.error(
            "stt_ingest_failed",
            extra={"project_id": project_id, "code": "STT_INGEST_FAILED"},
        )
        _fail_audio_document(doc_id, "STT_INGEST_FAILED")
        return

    for old_doc_id in old_doc_ids:
        delete_document(old_doc_id)
    if old_doc_ids:
        refresh_project_memory_after_delete(project_id)


def _process_audio(
    project_id: int,
    doc_id: int,
    old_doc_ids: list[int],
    filename: str,
    file_path: str,
    date: str,
    processing_token: str,
) -> None:
    # Keep provider calls serialized. A single CLOVA request may run for minutes, and the
    # ordinary upload rate limit alone is not a concurrency bound.
    while not _STT_PROCESS_LOCK.acquire(timeout=1):
        if not processing_owned(doc_id, processing_token, renew=True):
            return
    try:
        _process_audio_locked(
            project_id,
            doc_id,
            old_doc_ids,
            filename,
            file_path,
            date,
            processing_token,
        )
    finally:
        _STT_PROCESS_LOCK.release()


def _set_progress(doc_id: int, done: int, total: int, processing_token: str) -> None:
    """Renew the processing lease while extraction runs without exposing DB errors."""
    from ..api.documents import _set_doc_progress

    _set_doc_progress(doc_id, done, total, processing_token)


@router.post("/projects/{project_id}/audio", status_code=201)
@limiter.limit(RATE_LIMIT_UPLOAD, key_func=authenticated_user_key)
async def upload_audio(
    request: Request,
    project_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    date: str = Form(""),
):
    """Store an audio recording, transcribe it, and ingest it as meeting memory."""
    try:
        filename = safe_upload_name(file.filename or "")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")

    try:
        suffixes = supported_suffixes()
        size_limit = max_audio_bytes()
        provider = current_provider_name()
        diarization = supports_diarization()
    except TranscriptionError as exc:
        raise HTTPException(status_code=503, detail=exc.to_dict()) from exc

    if Path(filename).suffix.lower() not in suffixes:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_audio_format",
                "message": "지원하지 않는 오디오 형식입니다. ("
                + " / ".join(sorted(suffixes))
                + ")",
            },
        )

    # Resolve identity and project membership before reading the multipart body into memory.
    user_id = require_upload_user()
    require_project_access(project_id, min_role="member")

    data = await file.read(size_limit + 1)
    if len(data) > size_limit:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "audio_too_large",
                "message": f"오디오 크기는 {size_limit // (1024 * 1024)} MB를 초과할 수 없습니다.",
            },
        )
    if not data:
        raise HTTPException(
            status_code=400,
            detail={"code": "empty_audio", "message": "오디오 파일이 비어 있습니다."},
        )

    reservation = reserve_document(
        project_id, user_id, len(data), "physical", filename=filename
    )
    try:
        write_reserved_file(reservation["temp_path"], reservation["target_path"], data)
        finalized = finalize_document(reservation["reservation_id"], filename, "meeting")
    except BaseException:
        cleanup_failed_reservation(reservation["reservation_id"])
        raise

    background_tasks.add_task(
        _process_audio,
        project_id,
        finalized["doc_id"],
        finalized["old_doc_ids"],
        filename,
        finalized["file_path"],
        date,
        finalized["processing_token"],
    )
    return {
        "doc_id": finalized["doc_id"],
        "status": "processing",
        "provider": provider,
        "diarization": diarization,
    }
