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

    @property
    def is_usable_source(self) -> bool:
        """실제 추출 본문이 프롬프트에 포함된 첨부만 인용 가능한 근거다."""
        return self.extraction_status == "ok" and bool(self.content.strip())

    def debug(self) -> dict:
        """원문을 노출하지 않고 trace에 남길 첨부 상태를 반환한다."""
        return {
            "filename": self.filename,
            "file_type": self.file_type,
            "extraction_status": self.extraction_status,
            "source_location": self.source_location,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class _ValidatedAttachment:
    """문자 예산을 적용하기 전에 입력 경계 검증을 마친 첨부."""

    filename: str
    file_type: str
    source_location: str
    data: bytes


def _clip_attachment_text(text: str, limit: int, marker: str) -> str:
    """잘림 마커까지 포함해 ``limit``자를 넘지 않도록 텍스트를 자른다."""
    limit = max(0, limit)
    if len(text) <= limit:
        return text
    if limit == 0:
        return ""
    suffix = f"\n[{marker}]"
    # 마커가 예산을 전부 차지하면 실제 근거가 사라진다. 이 경우 잘림 여부는
    # 구조화 metadata로 전달하고, 허용된 문자만큼 원문을 보존한다.
    if len(suffix) >= limit:
        return text[:limit]
    return text[:limit - len(suffix)] + suffix


def _attachment_filename(value: str) -> str:
    """POSIX·Windows 경로 표기 모두에서 요청 파일명만 남긴다."""
    return Path(str(value or "").replace("\\", "/")).name


def _validated_attachments(
    attachments: List[QueryAttachment],
) -> List[_ValidatedAttachment]:
    """모든 첨부를 디코딩·크기 검사·내용 검증한 뒤 변환 단계로 넘긴다."""
    validated: List[_ValidatedAttachment] = []
    used_bytes = 0
    basename_counts: dict[str, int] = {}

    for attachment in attachments:
        filename = _attachment_filename(attachment.filename)
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
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

        # 문자 예산과 무관하게 요청에 포함된 모든 디코딩 완료 첨부를 검증한다.
        try:
            validate_document_bytes(filename, data)
        except DocumentContentError as exc:
            raise HTTPException(
                status_code=415,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

        basename_key = filename.casefold()
        occurrence = basename_counts.get(basename_key, 0) + 1
        basename_counts[basename_key] = occurrence
        occurrence_label = (
            filename if occurrence == 1 else f"{filename}#{occurrence}"
        )
        # Attachment and persisted project sources occupy different namespaces.
        # A request file named like a repository/document source must remain a
        # distinct provenance identity in prompts, debug, and the public API.
        source_location = f"attachment:{occurrence_label}"
        validated.append(_ValidatedAttachment(
            filename=filename,
            file_type=suffix.lstrip("."),
            source_location=source_location,
            data=data,
        ))

    return validated


def _prepare_attachment_evidence(
    attachments: List[QueryAttachment],
) -> List[AttachmentEvidence]:
    """첨부를 검증·추출해 저장하지 않는 요청 단위 근거로 만든다."""
    evidence: List[AttachmentEvidence] = []
    used_chars = 0
    per_file_limit = max(0, _ATTACHMENT_MAX_CHARS_PER_FILE)
    total_limit = max(0, _ATTACHMENT_MAX_CHARS_TOTAL)

    for attachment in _validated_attachments(attachments):
        remaining = max(0, total_limit - used_chars)
        content_limit = min(per_file_limit, remaining)
        if content_limit <= 0:
            evidence.append(AttachmentEvidence(
                filename=attachment.filename,
                file_type=attachment.file_type,
                extraction_status="skipped_budget",
                source_location=attachment.source_location,
                truncated=True,
                content="",
            ))
            continue

        # 변환 실패는 질의 전체를 막지 않는다. 모델 본문·public source에서는
        # 제외하고 구조화 diagnostics 상태만 남긴 뒤 다른 근거로 계속한다.
        try:
            text = convert(attachment.filename, attachment.data).text.strip()
            extraction_status = "ok" if text else "empty"
        except ConversionError as exc:
            # 추출 내용의 입력 경계 위반은 변환 실패가 아니라 검증 실패다.
            # diagnostics-only 변환 실패 대상이 아니며 415로 중단한다.
            if exc.code == ErrorCode.INVALID_CONTENT:
                raise HTTPException(
                    status_code=415,
                    detail={"code": exc.code, "message": exc.message},
                ) from exc
            logger.info(
                "첨부 변환 실패 filename=%s code=%s",
                attachment.filename,
                exc.code,
            )
            text = ""
            extraction_status = "failed"
        if extraction_status == "ok":
            truncated = len(text) > content_limit
            marker = (
                "전체 첨부 한도 초과로 잘림"
                if remaining <= per_file_limit
                else "첨부 내용 잘림"
            )
            text = _clip_attachment_text(text, content_limit, marker)
        else:
            # 실패·빈 파일은 diagnostics에는 남기되 모델 근거로 렌더링하지 않는다.
            text = ""
            truncated = False
        evidence.append(AttachmentEvidence(
            filename=attachment.filename,
            file_type=attachment.file_type,
            extraction_status=extraction_status,
            source_location=attachment.source_location,
            truncated=truncated,
            content=text,
        ))
        used_chars += len(text)

    return evidence


def _render_attachment_evidence(
    evidence: List[AttachmentEvidence],
) -> tuple[str, List[str]]:
    """첨부 근거를 기존 프롬프트·출처 계약에 맞게 렌더링한다."""
    usable = [item for item in evidence if item.is_usable_source]
    if not usable:
        return "", []
    sections = [
        (
            f"### {item.filename}\n"
            f"(출처: {item.source_location})\n"
            f"(유형: {item.file_type}, 추출 상태: {item.extraction_status}, "
            f"잘림: {'예' if item.truncated else '아니요'})\n"
            f"{item.content}"
        )
        for item in usable
    ]
    sources = [
        item.source_location for item in usable
    ]
    return "[첨부 자료]\n" + "\n\n".join(sections), sources


def execute_project_query(project_id: int, body: QueryRequest):
    """Execute one query without HTTP transport decorators.

    Authorization and rate limiting remain the endpoint's responsibility.
    Internal callers use this boundary without depending on transport
    decorators or consuming an anonymous HTTP limiter bucket.
    """
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
        return result
    except Exception:
        logger.error("qa_request_failed", extra={"project_id": project_id, "code": "QA_FAILED"})
        raise HTTPException(status_code=503, detail="Q&A 처리 중 오류가 발생했습니다. 서버 로그를 확인하세요.")


def _public_query_response(result: Dict) -> Dict:
    """Remove evaluation-only context from the HTTP response without mutating it."""
    public_result = dict(result)
    debug = public_result.get("debug")
    if isinstance(debug, dict):
        public_debug = dict(debug)
        public_debug.pop("model_contexts", None)
        public_result["debug"] = public_debug
    return public_result


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
    return _public_query_response(execute_project_query(project_id, body))
