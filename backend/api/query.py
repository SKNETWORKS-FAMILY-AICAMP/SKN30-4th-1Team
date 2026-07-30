import base64
import binascii
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from ..db.mysql import get_connection
from ..document_content import (
    ALLOWED_SUFFIXES,
    QUERY_ATTACHMENT_MAX_FILE_BYTES,
    QUERY_ATTACHMENT_MAX_TOTAL_BYTES,
    DocumentContentError,
    supported_formats_label,
    validate_document_bytes,
)
from ..agentic_graph import run_agentic_qa
from ..pipeline.converters import ConversionError, ErrorCode, convert
from .auth import require_project_access
from ..rate_limit import RATE_LIMIT_QUERY, authenticated_user_key, limiter

router = APIRouter()
logger = logging.getLogger(__name__)
_ATTACHMENT_MAX_CHARS_PER_FILE = int(os.getenv("QUERY_ATTACHMENT_MAX_CHARS_PER_FILE", "20000"))
_ATTACHMENT_MAX_CHARS_TOTAL = int(os.getenv("QUERY_ATTACHMENT_MAX_CHARS_TOTAL", "40000"))


class QueryAttachment(BaseModel):
    filename: str
    content_base64: str


class QueryRequest(BaseModel):
    question: str
    history: List[Dict] = []
    attachments: List[QueryAttachment] = []


@dataclass(frozen=True)
class AttachmentEvidence:
    """현재 요청에서만 사용하는 첨부 근거와 인용용 provenance."""

    filename: str
    file_type: str
    extraction_status: str
    source_location: str
    truncated: bool
    content: str

    def debug(self) -> dict:
        """원문을 노출하지 않고 trace에 남길 첨부 상태를 반환한다."""
        return {
            "filename": self.filename,
            "file_type": self.file_type,
            "extraction_status": self.extraction_status,
            "source_location": self.source_location,
            "truncated": self.truncated,
        }


def _warn_ignored_legacy_routing_mode() -> None:
    """Keep the existing env name observable while the runtime is Agentic-only."""
    if os.getenv("PAIM_QUERY_ROUTING_MODE", "").strip().lower() == "legacy":
        logger.warning(
            "legacy_query_routing_mode_ignored",
            extra={"code": "LEGACY_QUERY_ROUTING_MODE_IGNORED"},
        )


def _clip_attachment_text(text: str, limit: int, marker: str) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[{marker}]"


def _prepare_attachment_evidence(
    attachments: List[QueryAttachment],
) -> List[AttachmentEvidence]:
    """첨부를 검증·추출해 저장하지 않는 요청 단위 근거로 만든다."""
    evidence: List[AttachmentEvidence] = []
    used_chars = 0
    used_bytes = 0

    for attachment in attachments:
        filename = Path(attachment.filename).name
        if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
            raise HTTPException(
                status_code=400,
                detail=f"지원하지 않는 첨부 파일 형식입니다. ({supported_formats_label()})",
            )

        try:
            data = base64.b64decode(attachment.content_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=400, detail="첨부 파일을 읽을 수 없습니다.")

        if len(data) > QUERY_ATTACHMENT_MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="첨부 파일 크기가 허용 한도를 초과했습니다.")
        used_bytes += len(data)
        if used_bytes > QUERY_ATTACHMENT_MAX_TOTAL_BYTES:
            raise HTTPException(status_code=413, detail="전체 첨부 파일 크기가 허용 한도를 초과했습니다.")

        remaining = _ATTACHMENT_MAX_CHARS_TOTAL - used_chars
        if remaining <= 0:
            continue

        # 안전성 검증 실패(MIME·인코딩·제어문자)는 질의를 중단시킨다 — 415.
        # 관대한 정책은 "검증을 통과한 파일의 변환 실패"에만 적용된다. 모든 실패를
        # 삼키면 main의 입력 경계 계약이 무력화된다.
        try:
            validate_document_bytes(filename, data)
        except DocumentContentError as exc:
            raise HTTPException(
                status_code=415,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

        # 변환 실패는 질의 전체를 막지 않는다 — 나머지 첨부와 프로젝트 기억만으로도
        # 답할 수 있어야 하므로, 실패 사유를 본문에 남기고 계속 진행한다.
        try:
            text = convert(filename, data).text.strip()
            extraction_status = "ok" if text else "empty"
        except ConversionError as exc:
            # 추출 내용의 입력 경계 위반은 변환 실패가 아니라 검증 실패다.
            # 관대한 placeholder 정책 대상이 아니며 415로 중단한다.
            if exc.code == ErrorCode.INVALID_CONTENT:
                raise HTTPException(
                    status_code=415,
                    detail={"code": exc.code, "message": exc.message},
                ) from exc
            logger.info("첨부 변환 실패 filename=%s code=%s", filename, exc.code)
            text = ""
            extraction_status = "failed"
        text = text or "(텍스트를 추출할 수 없습니다.)"
        truncated = (
            len(text) > _ATTACHMENT_MAX_CHARS_PER_FILE
            or len(text) > remaining
        )
        text = _clip_attachment_text(text, _ATTACHMENT_MAX_CHARS_PER_FILE, "첨부 내용 잘림")
        text = _clip_attachment_text(text, remaining, "전체 첨부 한도 초과로 잘림")
        evidence.append(AttachmentEvidence(
            filename=filename,
            file_type=Path(filename).suffix.lower().lstrip("."),
            extraction_status=extraction_status,
            source_location=filename,
            truncated=truncated,
            content=text,
        ))
        used_chars += len(text)

    return evidence


def _render_attachment_evidence(
    evidence: List[AttachmentEvidence],
) -> tuple[str, List[str]]:
    """첨부 근거를 기존 프롬프트·출처 계약에 맞게 렌더링한다."""
    if not evidence:
        return "", []
    sections = [
        (
            f"### {item.filename}\n"
            f"(출처: {item.filename})\n"
            f"(유형: {item.file_type}, 추출 상태: {item.extraction_status}, "
            f"잘림: {'예' if item.truncated else '아니요'})\n"
            f"{item.content}"
        )
        for item in evidence
    ]
    sources = [item.filename for item in evidence]
    return "[첨부 자료]\n" + "\n\n".join(sections), sources


def _prepare_attachment_context(attachments: List[QueryAttachment]) -> tuple[str, List[str]]:
    """기존 내부 호출자를 위한 첨부 컨텍스트 호환 함수."""
    return _render_attachment_evidence(_prepare_attachment_evidence(attachments))


@router.post(
    "/projects/{project_id}/query",
    summary="Query project knowledge without server chat persistence",
    description=(
        "Processes the supplied question and history for this request only. "
        "It does not create or update server-backed chat sessions."
    ),
    openapi_extra={"x-paim-chat-persistence": "none"},
)
@limiter.limit(RATE_LIMIT_QUERY, key_func=authenticated_user_key)
def query(request: Request, project_id: int, body: QueryRequest):
    require_project_access(project_id)
    _warn_ignored_legacy_routing_mode()
    attachment_evidence = _prepare_attachment_evidence(body.attachments)
    attachment_context, attachment_sources = _render_attachment_evidence(
        attachment_evidence
    )
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Project not found")
    finally:
        conn.close()

    # Agentic 오케스트레이터가 하나 이상의 검색 Tool을 호출하고 최종 답변을 작성한다.
    # 첨부는 저장하지 않는 임시 Evidence로만 같은 질문의 LLM 메시지에 포함한다.
    try:
        result = run_agentic_qa(
            project_id=project_id,
            question=body.question,
            history=body.history,
            attachment_context=attachment_context,
            attachment_sources=attachment_sources,
            attachment_evidence=[item.debug() for item in attachment_evidence],
        )
        result["route"] = "semantic"
        debug = result.get("debug") or {}
        debug["route"] = "semantic"
        debug["router_stage"] = "tool_agent"
        result["debug"] = debug
        return result
    except Exception:
        logger.error("qa_request_failed", extra={"project_id": project_id, "code": "QA_FAILED"})
        raise HTTPException(status_code=503, detail="Q&A 처리 중 오류가 발생했습니다. 서버 로그를 확인하세요.")
