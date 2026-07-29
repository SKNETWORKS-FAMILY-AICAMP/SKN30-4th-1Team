"""전사 결과를 Project Memory로 적재하는 경로.

핸드오버의 STT 항목은 "전사"가 아니라 **"STT 전사 → Project Memory 생성"** 이다.
전사문만 만들고 끝내면 기존 파이프라인과 연결되지 않으므로, 여기서 extractor와
ingestor에 이어 붙인다.

문서 업로드 경로(`backend/api/upload.py`)를 건드리지 않는 이유는 담당 범위 때문이다.
이 모듈은 호출 가능한 함수만 제공하고, HTTP 노출은 별도 합의 후에 붙인다.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from ..pipeline.extractor import extract
from ..pipeline.ingestor import ingest
from ..project_memory import update_project_memory
from .base import Transcript

logger = logging.getLogger(__name__)

# memory_sources.source_kind는 VARCHAR(20). 문서·저장소와 구분되는 제3의 출처다.
SOURCE_KIND = "transcript"


def ingest_transcript(
    project_id: int,
    transcript: Transcript,
    date: str = "",
    doc_id: Optional[int] = None,
    processing_token: Optional[str] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> dict:
    """전사문에서 decision/action/issue/risk를 추출해 두 저장소에 적재한다.

    반환값은 호출자가 사용자에게 보여줄 요약이다. 적재 자체가 실패하면 예외를
    그대로 올린다 — 부분 적재를 성공으로 위장하지 않는다.

    doc_id를 주면 documents 행에 연결되고, 주지 않으면 문서 없는 메모리로 적재된다.
    documents 행 생성은 DB 소유 경계(API 계층)의 일이라 여기서 하지 않는다.
    """
    # 타임스탬프가 붙은 형태를 넘긴다. LLM이 "언제 나온 발언인지"를 읽을 수 있어야
    # 추출 결과에 시각 근거가 남는다.
    # 구간 자체를 본다. 텍스트 길이로 판정하면 부가 문구 때문에 가드가 뚫린다.
    if not transcript.segments:
        raise ValueError("전사문이 비어 있어 적재할 내용이 없습니다.")
    text = transcript.text
    if not text.strip():
        raise ValueError("전사문이 비어 있어 적재할 내용이 없습니다.")

    # 추출에는 지시문이 포함된 llm_text를, 저장에는 전사문 자체(text)를 쓴다.
    # 둘을 같은 값으로 두면 LLM 지시문이 벡터 저장소에 색인되어 검색 결과와
    # 인용 출처로 노출된다.
    items = extract(
        transcript.llm_text,
        default_source=transcript.source,
        source_kind=SOURCE_KIND,
        on_progress=on_progress,
    )

    ingest(
        project_id=project_id,
        doc_id=doc_id,
        items=items,
        raw_text=text,
        source=transcript.source,
        date=date,
        doc_type="meeting",  # 음성 녹음은 회의록으로 취급한다
        source_metadata={
            "source_kind": SOURCE_KIND,
            "source_type": "meeting",
            "source_path": transcript.source,
            # 어떤 모델로 전사했는지 남긴다 — 전사 품질이 의심될 때 되짚는 근거가 된다.
            "source_ref": f"{transcript.provider}:{transcript.model}",
        },
        processing_token=processing_token,
    )

    # Keep this function a complete Project Memory path even when called outside HTTP.
    # The overview is derived state, so its failure must not roll back a successful ingest.
    try:
        update_project_memory(project_id, items)
    except Exception:
        logger.warning(
            "STT 프로젝트 메모리 갱신 실패 (적재는 성공): project_id=%s",
            project_id,
        )

    logger.info(
        "STT 적재 완료 project_id=%s source=%s segments=%s items=%s",
        project_id, transcript.source, len(transcript.segments), len(items),
    )

    return {
        "source": transcript.source,
        "segments": len(transcript.segments),
        "duration": transcript.duration,
        "language": transcript.language,
        "extracted": len(items),
        "warnings": transcript.warning_dicts(),
    }


def transcribe_and_ingest(
    project_id: int,
    filename: str,
    data: bytes,
    date: str = "",
    doc_id: Optional[int] = None,
    language: Optional[str] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> dict:
    """오디오 업로드부터 Project Memory 생성까지 한 번에 수행한다."""
    from .transcriber import transcribe

    transcript = transcribe(filename, data, language=language)
    return ingest_transcript(
        project_id=project_id,
        transcript=transcript,
        date=date,
        doc_id=doc_id,
        on_progress=on_progress,
    )
