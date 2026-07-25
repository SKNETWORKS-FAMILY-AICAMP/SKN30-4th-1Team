import base64
import binascii
import logging
import os
from pathlib import Path
from typing import List, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..db.mysql import get_connection
from ..pipeline.extractor import extract
from ..pipeline.ingestor import ingest
from ..graph import update_project_memory, run_qa
from ..agentic_graph import run_agentic_qa
from ..retriever import history_intent
from ..retriever.query_intent import (
    SemanticFallback,
    answer_filter_lookup,
    answer_overview,
    classify_question,
)
from ..pipeline.converters import ConversionError, convert, supported_suffixes
from .upload import _MAX_FILE_BYTES, _delete_document
from .auth import require_project_access

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


def _agentic_routing_enabled() -> bool:
    """Feature flag for the disposable tool-routing experiment."""
    return os.getenv("PAIM_QUERY_ROUTING_MODE", "agentic").strip().lower() != "legacy"


def _clip_attachment_text(text: str, limit: int, marker: str) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[{marker}]"


def _prepare_attachment_context(attachments: List[QueryAttachment]) -> tuple[str, List[str]]:
    sections = []
    sources: List[str] = []
    used_chars = 0

    for attachment in attachments:
        filename = Path(attachment.filename).name
        if Path(filename).suffix.lower() not in supported_suffixes():
            raise HTTPException(
                status_code=400,
                detail="지원하지 않는 첨부 파일 형식입니다. ("
                       + " / ".join(sorted(supported_suffixes())) + ")",
            )

        try:
            data = base64.b64decode(attachment.content_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=400, detail="첨부 파일을 읽을 수 없습니다.")

        if len(data) > _MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="첨부 파일 크기는 10 MB를 초과할 수 없습니다.")

        remaining = _ATTACHMENT_MAX_CHARS_TOTAL - used_chars
        if remaining <= 0:
            break

        # 첨부 변환 실패는 질의 전체를 막지 않는다 — 나머지 첨부와 프로젝트 기억만으로도
        # 답할 수 있어야 하므로, 실패 사유를 본문에 남기고 계속 진행한다.
        try:
            text = convert(filename, data).text.strip()
        except ConversionError as exc:
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
def query(project_id: int, body: QueryRequest):
    require_project_access(project_id)
    attachment_context, attachment_sources = _prepare_attachment_context(body.attachments)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Project not found")
    finally:
        conn.close()

    # 질문 의도가 명확하면 SQL/조망형 경로를 쓰고, 아니면 기존 LangGraph RAG로 폴백한다.
    try:
        if attachment_context:
            # 첨부 경로는 라우터(classify_question)를 타지 않으므로 이력 감지를 직접 호출한다.
            result = run_qa(
                project_id=project_id,
                question=body.question,
                history=body.history,
                attachment_context=attachment_context,
                attachment_sources=attachment_sources,
                history_mode=history_intent.detect_history_intent(body.question),
            )
            result["route"] = "semantic"
            debug = result.get("debug") or {}
            debug["route"] = "semantic"
            debug["router_stage"] = "attachment"
            result["debug"] = debug
            return result

        if _agentic_routing_enabled():
            try:
                return run_agentic_qa(project_id, body.question, body.history)
            except Exception:
                # Tool calling is not guaranteed for every local OpenAI-compatible
                # model. Keep the endpoint useful and ground the fallback in the
                # existing hybrid semantic retriever rather than the brittle router.
                logger.warning(
                    "agentic Q&A 실패, semantic RAG로 폴백: project_id=%s",
                    project_id,
                    exc_info=True,
                )
                result = run_qa(
                    project_id=project_id,
                    question=body.question,
                    history=body.history,
                    history_mode=history_intent.detect_history_intent(body.question),
                )
                result["route"] = "semantic"
                debug = result.get("debug") or {}
                debug["route"] = "semantic"
                debug["router_stage"] = "tool_agent_fallback"
                result["debug"] = debug
                return result

        decision = classify_question(body.question, body.history)
        if decision.route == "filter_lookup":
            try:
                return answer_filter_lookup(
                    project_id, body.question, body.history, decision.router_stage
                )
            except SemanticFallback:
                pass
        elif decision.route == "overview":
            return answer_overview(project_id, body.question, decision.router_stage)

        result = run_qa(
            project_id=project_id,
            question=body.question,
            history=body.history,
            history_mode=decision.history_mode,
        )
        result["route"] = "semantic"
        debug = result.get("debug") or {}
        debug["route"] = "semantic"
        debug["router_stage"] = decision.router_stage
        debug["router_model_tier"] = "fast" if decision.router_stage == "llm" else None
        result["debug"] = debug
        return result
    except Exception as e:
        logger.error("Q&A 처리 오류: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="Q&A 처리 중 오류가 발생했습니다. 서버 로그를 확인하세요.")


class GitLogUpload(BaseModel):
    content: str
    source: str = "git log"
    date: str = ""


@router.post("/projects/{project_id}/git", status_code=201)
def upload_git_log(project_id: int, body: GitLogUpload):
    # 동기 처리 — documents.status 추적 없음. 향후 /documents 엔드포인트로 통합 예정
    require_project_access(project_id, min_role="member")
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content must not be empty")

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Project not found")
            cursor.execute(
                "INSERT INTO documents (project_id, filename, doc_type) VALUES (%s, %s, %s)",
                (project_id, "git_log.txt", "git"),
            )
            doc_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()

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
        )
    except Exception:
        _delete_document(doc_id)
        raise

    # 프로젝트 메모리 갱신 (best-effort — 요약 실패해도 업로드는 성공 처리)
    try:
        update_project_memory(project_id, items)
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "프로젝트 메모리 갱신 실패 (git 업로드는 성공): project_id=%s", project_id, exc_info=True
        )

    counts = {"decision": 0, "action": 0, "issue": 0, "risk": 0}
    for item in items:
        counts[item.category] += 1

    return {"doc_id": doc_id, "extracted": counts}
