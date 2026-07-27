# 추출된 MemoryItem 목록을 MySQL(구조화)과 ChromaDB(벡터) 두 저장소에 적재하는 모듈.
# MySQL은 카테고리별 검색, ChromaDB는 의미 유사도 검색에 사용.
import json
import logging
import re
from typing import List, Optional
from .models import MemoryItem, CompletionReport
from .extractor import _OPEN_ACTIONS_ITEM_CHARS
from ..db.mysql import get_connection
from ..db.chroma import get_collection
from ..retriever.memory_vector import upsert_memory_vectors

logger = logging.getLogger(__name__)

# ChromaDB metadata 값은 str/int/float/bool만 허용 — None 대신 이 값 사용
_NO_ID = -1

CHUNK_SIZE = 600  # ChromaDB 적재 시 원문 청크 크기 (문자 수)
CHUNK_OVERLAP = 150


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
    processing_token: Optional[str] = None,
    completions: Optional[List[CompletionReport]] = None,
    open_actions: Optional[List[dict]] = None,
):
    """추출 결과를 두 DB에 순서대로 저장.
    1단계: MySQL — items 각각을 memory + memory_sources 테이블에 INSERT (같은 트랜잭션)
    2단계: ChromaDB — 원문(raw_text)을 청크로 분할해 벡터 임베딩으로 저장
    """
    chunks = _split_text(raw_text)

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
                documents=chunks,
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
                } for _ in chunks],
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

    # 문서 기반 완료 판정(extract()가 open_actions를 받아 같은 호출에서 함께 판정한 결과):
    # 사후 reconciler 없이도 이 문서가 기존 열린 action의 진행 상황을 보고했으면 여기서
    # pending 제안으로만 남긴다(자동 반영 아님). fully_complete면 완료 제안, 아니면(묶음
    # action의 일부만 확인) 완료된 부분만 떼어내는 분할 제안 — 둘 다 사람 승인이 있어야
    # 실제 반영되고, 완료 시점은 이 문서 날짜를 쓴다.
    if completions:
        # 제안 생성은 적재 성공을 막지 않는 부차 단계다 — 위 supersede 블록과 동일하게
        # best-effort로 격리한다. 여기서 예외가 새면 호출부(upload._process_upload_locked)의
        # except가 fail_document를 불러, 이미 status='indexed'로 커밋된 문서의 memory 행·
        # 파일·벡터를 전부 삭제한다(제안 하나 실패의 대가로 적재 결과를 파괴).
        try:
            # LLM에게 실제로 보여준 action id 집합 — 프롬프트의 "never invent one"은 지시일 뿐
            # 검증이 아니므로, 반환된 action_id가 이 목록에 있는지 대조한다(PR 경로가
            # pr_actions.py에서 하는 것과 같은 방어). 호출부가 목록을 안 넘기면 DB 상태
            # 검사만 적용한다.
            allowed_action_ids = (
                {int(a["id"]) for a in open_actions} if open_actions is not None else None
            )
            # evidence에 넣을 문서 날짜도 memory 행과 동일하게 정규화 — 무효한 날짜
            # ("2026-02-30", 한국어 표기 등)가 그대로 저장되면 승인 시 DATETIME 컬럼에
            # 들어가 strict 모드에서 500 + 롤백, 느슨한 설정에서는 잘못된 완료 시각이 남는다.
            # None이면 승인 시 NOW() 폴백 경로를 탄다(빈 문자열과 동일 취급).
            evidence_date = _normalize_date(date)
            conn = get_connection()
            try:
                # 항목별로 개별 커밋 — completions 하나(예: LLM이 목록에 없는 action_id를
                # 잘못 반환해 FK 위반)가 실패해도 같은 문서의 다른 정상 제안까지 같이
                # 롤백되지 않게 격리한다.
                for c in completions:
                    if allowed_action_ids is not None and c.action_id not in allowed_action_ids:
                        logger.warning(
                            "완료 판정에 없는 action_id 무시(환각 또는 예산 절단분)"
                            " action_id=%s project_id=%s", c.action_id, project_id,
                        )
                        continue
                    try:
                        with conn.cursor() as cursor:
                            # 제안 생성 시점의 실제 content를 같이 저장 — 승인 시점에 그 사이
                            # 다른 제안이 먼저 적용돼 content가 바뀌었는지 대조하기 위함
                            # (complete_action/split_action 둘 다 — 낡은 제안이 최신 content를
                            # 잘못 덮어쓰는 것 방지).
                            # category/completion_status까지 함께 확인 — 목록 조회 이후 상태가
                            # 바뀌었거나(이미 완료됨) LLM이 decision id를 섞어 반환한 경우를
                            # 여기서 거른다. 조건에 안 맞으면 제안을 만들지 않는다.
                            cursor.execute(
                                "SELECT content FROM memory WHERE id = %s AND project_id = %s"
                                " AND category = 'action' AND completion_status = 'open'",
                                (c.action_id, project_id),
                            )
                            current = cursor.fetchone()
                            if current is None:
                                logger.warning(
                                    "완료 판정 대상이 열린 action이 아님 — 제안 생성 안 함"
                                    " action_id=%s project_id=%s", c.action_id, project_id,
                                )
                                continue
                            original_content = current["content"]

                            if c.fully_complete:
                                # PR 기반 complete_action과 별도 kind — evidence 스키마가 달라
                                # (title/number/url 없음) 구 데스크톱이 evidence.title.trim()에서
                                # 죽는다. 신규 kind는 레거시 응답에서 제외되므로 데스크톱이
                                # 대응하기 전까지 안전하게 격리된다.
                                kind = "complete_action_doc"
                                evidence = {
                                    "type": "document", "doc_id": doc_id,
                                    "source": source, "date": evidence_date, "quote": c.evidence,
                                    "original_content": original_content,
                                }
                                rationale = f"'{source}' 문서가 완료로 보고: {c.evidence}"
                            else:
                                if not c.done_parts or not c.remaining_parts:
                                    continue  # 부분 완료인데 분할 근거가 없으면 애매하니 건너뜀
                                overlap = set(c.done_parts) & set(c.remaining_parts)
                                if overlap:
                                    # 같은 sub-task가 완료·잔여 양쪽에 있으면 승인 시 그 조각이
                                    # open 행과 completed 행으로 동시에 존재하게 된다. 검색은 둘 다
                                    # 반환하므로 LLM이 서로 모순되는 근거를 받는다. 어느 쪽이
                                    # 맞는지 판단할 근거가 없으니 제안하지 않는다(절단 가드와 동일
                                    # 방침). 표기가 다른 부분 겹침("알림" vs "알림 설정")은 정확
                                    # 일치가 아니라 여기서 못 걸러진다 — 사람 승인이 그 방어선이다.
                                    logger.warning(
                                        "완료/잔여 조각이 겹쳐 split 제안 생략"
                                        " action_id=%s project_id=%s overlap=%s",
                                        c.action_id, project_id, sorted(overlap),
                                    )
                                    continue
                                if len(original_content or "") > _OPEN_ACTIONS_ITEM_CHARS:
                                    # 프롬프트에는 앞 _OPEN_ACTIONS_ITEM_CHARS자만 들어갔으므로
                                    # LLM은 이 action의 뒷부분을 본 적이 없다. 그 상태의
                                    # remaining_part를 승인하면 content를 통째로 덮어써
                                    # (suggestion._apply_accepted_effect) 못 본 부분이 소실된다.
                                    # stale 검사는 전체 content끼리 비교라 이 경로를 못 막는다.
                                    # 완료분만 떼는 판단 자체가 근거 없이 이뤄진 것이므로 제안하지 않는다.
                                    logger.warning(
                                        "action content가 프롬프트 예산으로 잘려 split 제안 생략"
                                        " action_id=%s project_id=%s len=%s",
                                        c.action_id, project_id, len(original_content),
                                    )
                                    continue
                                kind = "split_action"
                                evidence = {
                                    "type": "document", "doc_id": doc_id,
                                    "source": source, "date": evidence_date, "quote": c.evidence,
                                    "done_parts": c.done_parts, "remaining_parts": c.remaining_parts,
                                    "original_content": original_content,
                                }
                                rationale = (
                                    f"'{source}' 문서가 일부만 완료로 보고: {c.evidence}"
                                    f" (완료: {' / '.join(c.done_parts)}"
                                    f" / 남음: {' / '.join(c.remaining_parts)})"
                                )
                            # 중복 방지 키에 근거 문서(doc_id)를 포함한다 — PR 경로(pr_actions)가
                            # $.number를, supersede 경로가 $.superseding_memory_id를 키에 넣는 것과
                            # 같은 규칙이다. 문서 경로만 (memory_id, kind)로만 걸러서, 같은 action에
                            # 대해 다른 문서가 보고한 진행 상황이 앞 제안이 pending인 동안 통째로
                            # 버려졌다(0행 INSERT라 예외도 로그도 없음). 문서는 이미 indexed라
                            # 재처리되지 않으므로 그 판정은 영구 소실이었다. 같은 문서를 재처리할
                            # 때의 멱등성은 doc_id가 같아 그대로 유지된다.
                            cursor.execute(
                                """
                                INSERT INTO memory_suggestions
                                    (project_id, memory_id, kind, evidence, rationale, confidence, status)
                                SELECT %s, %s, %s, %s, %s, 'high', 'pending'
                                FROM DUAL
                                WHERE NOT EXISTS (
                                    SELECT 1 FROM memory_suggestions
                                    WHERE memory_id = %s AND kind = %s AND status = 'pending'
                                      AND CAST(JSON_UNQUOTE(JSON_EXTRACT(evidence, '$.doc_id')) AS UNSIGNED) = %s
                                )
                                """,
                                (
                                    project_id, c.action_id, kind,
                                    json.dumps(evidence, ensure_ascii=False), rationale,
                                    c.action_id, kind, doc_id,
                                ),
                            )
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        logger.warning(
                            "문서 기반 완료 제안 저장 실패(이 action만 건너뜀) action_id=%s project_id=%s",
                            c.action_id, project_id, exc_info=True,
                        )
            finally:
                conn.close()
        except Exception:
            # exc_info=True — 이 가드의 존재 이유가 "예상 못 한 실패로부터 적재 결과를
            # 지키는 것"이라, 원인을 남기지 않으면 왜 제안이 안 생겼는지 추적할 수 없다.
            # 안쪽 per-item 핸들러와도 동일한 수준으로 맞춘다.
            logger.warning(
                "document_completion_suggestion_failed",
                extra={"project_id": project_id, "code": "DOC_COMPLETION_SUGGESTION_FAILED"},
                exc_info=True,
            )
