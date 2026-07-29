import base64
import binascii
import logging
import os
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


def _prepare_attachment_context(attachments: List[QueryAttachment]) -> tuple[str, List[str]]:
    sections = []
    sources: List[str] = []
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
        text = text or "(텍스트를 추출할 수 없습니다.)"
        text = _clip_attachment_text(text, _ATTACHMENT_MAX_CHARS_PER_FILE, "첨부 내용 잘림")
        text = _clip_attachment_text(text, remaining, "전체 첨부 한도 초과로 잘림")
        # 표준 출처 마커를 붙여 SYSTEM_QA의 인용 규칙이 첨부에도 적용되도록 한다
        # (구조화 기록·원문 맥락과 동일 형식, 리뷰 R-004).
        sections.append(f"### {filename}\n(출처: {filename})\n{text}")
        sources.append(filename)
        used_chars += len(text)

    if not sections:
        return "", []
    return "[첨부 자료]\n" + "\n\n".join(sections), sources


@router.post("/projects/{project_id}/query")
@limiter.limit(RATE_LIMIT_QUERY, key_func=authenticated_user_key)
def query(request: Request, project_id: int, body: QueryRequest):
    require_project_access(project_id)
    _warn_ignored_legacy_routing_mode()
    attachment_context, attachment_sources = _prepare_attachment_context(body.attachments)
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
