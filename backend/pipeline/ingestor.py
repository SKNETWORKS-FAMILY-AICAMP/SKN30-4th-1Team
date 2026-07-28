# 추출된 MemoryItem 목록을 MySQL(구조화)과 ChromaDB(벡터) 두 저장소에 적재하는 모듈.
# MySQL은 카테고리별 검색, ChromaDB는 의미 유사도 검색에 사용.
import logging
import re
from typing import List, Optional, Tuple
from .models import MemoryItem
from .converters import ConvertedDocument, chunk_document
from ..db.mysql import get_connection
from ..db.chroma import get_collection
from ..retriever.memory_vector import upsert_memory_vectors

logger = logging.getLogger(__name__)

# ChromaDB metadata 값은 str/int/float/bool만 허용 — None 대신 이 값 사용
_NO_ID = -1

CHUNK_SIZE = 600  # ChromaDB 적재 시 원문 청크 크기 (문자 수)
CHUNK_OVERLAP = 150

# 출처 좌표를 알 수 없는 청크(구조 정보 없는 평문 경로)의 기본 metadata.
# 키 집합은 두 경로가 같아야 한다 — ChromaDB where 필터가 키 유무로 갈리면
# 같은 질의가 문서 출처에 따라 다른 결과를 낸다.
_UNKNOWN_CHUNK_META = {
    "block_start": _NO_ID,
    "block_end": _NO_ID,
    "page_start": _NO_ID,
    "page_end": _NO_ID,
    "heading": "",
}


def _rollback_after_ingest_failure(conn) -> None:
    try:
        conn.rollback()
    except Exception:
        logger.error("ingest_rollback_failed", extra={"code": "INGEST_ROLLBACK_FAILED"})


def _close_after_ingest_failure(conn) -> None:
    try:
        conn.close()
    except Exception:
        logger.error("ingest_connection_close_failed", extra={"code": "INGEST_CLOSE_FAILED"})


def _normalize_date(date_str: Optional[str]) -> Optional[str]:
    """LLM이 반환한 다양한 날짜 형식을 MySQL DATE 타입이 수용하는 YYYY-MM-DD로 통일.
    유효하지 않은 날짜(예: 2026-02-30)는 None 반환하여 DB INSERT 오류를 방지.
    """
    from datetime import datetime as _dt
    if not date_str:
        return None

    def _validated(y: str, mo: str, d: str) -> Optional[str]:
        try:
            _dt(int(y), int(mo), int(d))
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        except ValueError:
            return None

    # 이미 YYYY-MM-DD인 경우 (LLM이 올바르게 반환한 경우)
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', date_str)
    if m:
        return _validated(*m.groups())
    # 한국어 형식: 2026년 6월 2일
    m = re.match(r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일', date_str)
    if m:
        return _validated(*m.groups())
    # 슬래시/점 구분자: YYYY/MM/DD 또는 YYYY.MM.DD
    m = re.match(r'(\d{4})[./](\d{1,2})[./](\d{1,2})', date_str)
    if m:
        return _validated(*m.groups())
    return None


def _split_text(text: str) -> List[str]:
    """원문 텍스트를 CHUNK_SIZE 단위로 분할. ChromaDB는 짧은 청크가 검색 정확도가 더 높음."""
    if len(text) <= CHUNK_SIZE:
        return [text.strip()] if text.strip() else []

    sentences = re.split(r'(?<=[.\n])\s*', text)
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # 단일 문장이 CHUNK_SIZE를 초과하면 강제 분할 후 chunks에 직접 추가
        if len(sentence) > CHUNK_SIZE:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""
            for i in range(0, len(sentence), CHUNK_SIZE):
                piece = sentence[i:i + CHUNK_SIZE].strip()
                if piece:
                    chunks.append(piece)
            continue

        if len(current_chunk) + len(sentence) + (1 if current_chunk else 0) <= CHUNK_SIZE:
            current_chunk = current_chunk + " " + sentence if current_chunk else sentence
        else:
            if current_chunk:
                chunks.append(current_chunk)

            # 오버랩: 이전 청크 뒷부분 일부를 가져와 새 청크 시작
            overlap_text = current_chunk[-CHUNK_OVERLAP:] if len(current_chunk) > CHUNK_OVERLAP else current_chunk
            if " " in overlap_text:
                overlap_text = overlap_text[overlap_text.find(" ") + 1:]

            candidate = (overlap_text + " " + sentence).strip() if overlap_text else sentence
            # overlap을 붙여도 CHUNK_SIZE를 넘으면 overlap 없이 sentence만으로 시작
            current_chunk = candidate if len(candidate) <= CHUNK_SIZE else sentence

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def _build_chunks(
    raw_text: str,
    converted: Optional[ConvertedDocument],
) -> List[Tuple[str, dict]]:
    """(청크 텍스트, 출처 metadata) 목록을 만든다.

    converted가 있으면 페이지·문단 번호가 살아 있는 구조 기반 청킹을 쓰고,
    없으면(리포지토리 동기화 등 파일 변환을 거치지 않는 경로) 기존 평문
    분할로 되돌아간다. 두 경로의 metadata 키 집합은 동일하게 유지한다.
    """
    if converted is not None and converted.blocks:
        return [
            (chunk.text, chunk.to_metadata())
            for chunk in chunk_document(converted, CHUNK_SIZE, CHUNK_OVERLAP)
        ]
    return [
        (text, {"chunk_index": index, **_UNKNOWN_CHUNK_META})
        for index, text in enumerate(_split_text(raw_text))
    ]


def _completed_at_sql(item: MemoryItem, item_date: Optional[str], source_date: str) -> tuple[str, list]:
    """completed=true 항목의 완료 시각 SQL 조각을 만든다."""
    if item.category != "action" or not item.completed:
        return "%s", [None]

    completed_date = item_date or _normalize_date(source_date)
    if completed_date:
        return "%s", [f"{completed_date} 00:00:00"]
    return "NOW()", []


def _completion_status(item: MemoryItem) -> str:
    if item.category != "action":
        return "unknown"
    if item.completed is True:
        return "completed"
    if item.completed is False:
        return "open"
    return "unknown"


def _insert_memory_source(
    cursor,
    memory_id: int,
    doc_id: Optional[int],
    repo_id: Optional[int],
    metadata: Optional[dict],
) -> None:
    """memory_sources 테이블에 출처 정보를 INSERT.
    source_kind는 metadata에서 읽되, 없으면 repo_id 유무로 자동 결정.
    """
    sm = metadata or {}
    source_kind = sm.get("source_kind") or ("repository" if repo_id is not None else "document")
    cursor.execute(
        "INSERT INTO memory_sources"
        " (memory_id, source_kind, doc_id, repo_id, source_type, source_path, source_ref, source_url)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            memory_id,
            source_kind,
            doc_id,
            repo_id,
            sm.get("source_type"),
            sm.get("source_path"),
            sm.get("source_ref"),
            sm.get("source_url"),
        ),
    )


def ingest(
    project_id: int,
    doc_id: Optional[int],
    items: List[MemoryItem],
    raw_text: str,
    source: str,
    date: str,
    doc_type: str,
    repo_id: Optional[int] = None,
    source_metadata: Optional[dict] = None,
    converted: Optional[ConvertedDocument] = None,
    processing_token: Optional[str] = None,
):
    """추출 결과를 두 DB에 순서대로 저장.
    1단계: MySQL — items 각각을 memory + memory_sources 테이블에 INSERT (같은 트랜잭션)
    2단계: ChromaDB — 원문(raw_text)을 청크로 분할해 벡터 임베딩으로 저장

    converted를 넘기면 청크마다 원본 페이지·문단 번호가 metadata로 함께 저장되어
    답변의 출처를 문서 내부 위치까지 되짚을 수 있다. 넘기지 않으면 raw_text 기준
    평문 분할로 동작한다(기존 동작).
    """
    chunks = _build_chunks(raw_text, converted)

    conn = get_connection()
    memory_rows = []
    try:
        with conn.cursor() as cursor:
            if doc_id is not None and processing_token is not None:
                cursor.execute(
                    "SELECT status,processing_token FROM documents WHERE id=%s FOR UPDATE",
                    (doc_id,),
                )
                owner = cursor.fetchone()
                if (
                    not owner
                    or owner["status"] != "processing"
                    or owner.get("processing_token") != processing_token
                ):
                    raise RuntimeError("DOCUMENT_PROCESSING_FENCE_LOST")
            for item in items:
                # 본문에서 date가 추출되지 않았으면 업로드 폼의 source date를 폴백으로 저장한다.
                # LLM 입력만이 아니라 행 자체에 보존해야, 이 항목이 미래 적재의 supersede
                # 후보가 될 때 시간순서 검증(과거 문서가 최신 결정을 번복 못 함)이 유지된다.
                item_date = _normalize_date(item.date) or _normalize_date(date)
                completed_sql, completed_params = _completed_at_sql(item, item_date, date)
                completion_status = _completion_status(item)
                completion_source = None
                if item.category == "action" and item.completed is not None:
                    completion_source = (source_metadata or {}).get("source_kind") or (
                        "repository" if repo_id is not None else "document"
                    )
                cursor.execute(
                    f"""
                    INSERT INTO memory
                        (project_id, doc_id, repo_id, category, content,
                         reason, topic, owner, date, source, completed_at,
                         completion_status, completion_status_source)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            {completed_sql}, %s, %s)
                    """,
                    [
                        project_id, doc_id, repo_id,
                        item.category, item.content,
                        item.reason, item.topic,
                        item.owner, item_date,
                        source,
                    ] + completed_params + [completion_status, completion_source],
                )
                memory_id = cursor.lastrowid
                completed_at = completed_params[0] if completed_params else "NOW"
                _insert_memory_source(cursor, memory_id, doc_id, repo_id, source_metadata)
                memory_rows.append({
                    "id": memory_id,
                    "project_id": project_id,
                    "doc_id": doc_id,
                    "repo_id": repo_id,
                    "category": item.category,
                    "content": item.content,
                    "reason": item.reason,
                    "topic": item.topic,
                    "owner": item.owner,
                    "date": item_date,
                    "due_date": None,
                    "completed_at": completed_at if item.completed else None,
                    "completion_status": completion_status,
                    "completion_status_source": completion_source,
                    "source": source,
                })
        # Repository ingest preserves the existing MySQL-first contract. Document
        # ingest keeps the row lock and transaction through all Chroma writes.
        if processing_token is None:
            conn.commit()
    except BaseException:
        try:
            _rollback_after_ingest_failure(conn)
        finally:
            _close_after_ingest_failure(conn)
        raise

    try:
        upsert_memory_vectors(memory_rows)

        if chunks:
            # 같은 repo 안의 source별 chunk ID 충돌을 피한다.
            import hashlib
            src_hash = hashlib.md5(source.encode()).hexdigest()[:6]
            if repo_id is not None:
                chunk_prefix = f"repo{repo_id}_{src_hash}"
            elif doc_id is not None:
                chunk_prefix = f"doc{doc_id}"
            else:
                chunk_prefix = src_hash

            sm = source_metadata or {}
            collection = get_collection()
            collection.add(
                ids=[f"{chunk_prefix}_chunk{i}" for i in range(len(chunks))],
                documents=[text for text, _ in chunks],
                metadatas=[{
                    "project_id": project_id,
                    "doc_id": doc_id if doc_id is not None else _NO_ID,
                    "repo_id": repo_id if repo_id is not None else _NO_ID,
                    "source": source,
                    "item_type": "document",
                    "date": date or "",
                    "doc_type": doc_type,
                    "source_kind": sm.get("source_kind", ""),
                    "source_type": sm.get("source_type", ""),
                    "source_path": sm.get("source_path", ""),
                    "source_ref": sm.get("source_ref", ""),
                    "source_url": sm.get("source_url", ""),
                    # 문서 내부 출처 좌표 — 답변의 근거를 "몇 페이지 몇 번째 문단"까지 되짚는다.
                    "source_format": converted.format if converted is not None else "",
                    **chunk_meta,
                } for _, chunk_meta in chunks],
            )

        if processing_token is not None:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE documents SET status='indexed',last_error=NULL,processing_token=NULL,"
                    "lease_expires_at=NULL,progress_done=NULL,progress_total=NULL"
                    " WHERE id=%s AND status='processing' AND processing_token=%s",
                    (doc_id, processing_token),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("DOCUMENT_PROCESSING_FENCE_LOST")
            conn.commit()
    except BaseException:
        try:
            if processing_token is not None:
                _rollback_after_ingest_failure(conn)
        finally:
            _close_after_ingest_failure(conn)
        raise
    else:
        conn.close()

    # 계층2 supersede 판별: 이번에 적재된 신규 decision이 기존 decision을 번복하는지 LLM으로 판정해
    # pending 제안을 만든다. **모든 적재 단계(벡터 upsert + chunk add)가 성공한 뒤**에 실행해,
    # chunk add 실패로 적재가 롤백/정리될 때 삭제될 신규 memory를 가리키는 제안이 남지 않게 한다.
    # 적재 성공을 막지 않도록 best-effort로 격리하고, 신규 decision이 없으면 호출 자체를 생략한다.
    # 판정 정확도를 위해 신규 decision의 date도 함께 넘긴다(시간 순서 검증용).
    # source date 폴백은 INSERT 시점에 행 자체에 적용되므로 r["date"]에 이미 반영돼 있다.
    new_decisions = [
        {"id": r["id"], "content": r["content"], "topic": r["topic"],
         "reason": r["reason"], "date": r["date"]}
        for r in memory_rows
        if r["category"] == "decision"
    ]
    if new_decisions:
        try:
            from ..reconciler.supersede import detect_supersede
            detect_supersede(project_id, new_decisions)
        except Exception:
            logger.warning(
                "supersede_detection_failed",
                extra={"project_id": project_id, "code": "SUPERSEDE_DETECTION_FAILED"},
            )
