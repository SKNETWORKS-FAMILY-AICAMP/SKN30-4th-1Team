import json
import logging

import pymysql
from fastapi import APIRouter, HTTPException

from ..db.mysql import get_connection
from .auth import get_current_user_id, require_project_access

logger = logging.getLogger(__name__)

router = APIRouter()

_STATUSES = {"pending", "accepted", "rejected"}


def _decode_evidence(value):
    """MySQL JSON 반환값을 API 응답용 dict로 정규화한다."""
    if isinstance(value, dict):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return value


def _suggestion_response(row: dict) -> dict:
    """DB row를 suggestions API 응답 형태로 변환한다."""
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "memory_id": row["memory_id"],
        "kind": row["kind"],
        "evidence": _decode_evidence(row["evidence"]),
        "rationale": row["rationale"],
        "confidence": row["confidence"],
        "status": row["status"],
        "created_at": row["created_at"],
        "resolved_at": row.get("resolved_at"),
        "resolved_by": row.get("resolved_by"),
    }


# suggestion.kind별로 대상 memory가 가져야 하는 category — accept 시 잘못된 대상 방지.
_KIND_TARGET_CATEGORY = {
    "complete_action": "action",
    "split_action": "action",
    "supersede": "decision",
}


def _suggestion_or_404(cursor, project_id: int, suggestion_id: int) -> dict:
    """프로젝트에 속한 suggestion과 대상 memory 상태를 함께 조회한다.

    kind에 따라 대상 memory의 category가 달라지므로(action/decision) category 필터는
    SQL이 아니라 조회 후 kind 기준으로 검증한다.
    """
    cursor.execute(
        "SELECT s.*, m.category AS memory_category,"
        " m.completed_at AS memory_completed_at,"
        " m.superseded_by AS memory_superseded_by,"
        " m.owner AS memory_owner, m.date AS memory_date, m.source AS memory_source,"
        " m.doc_id AS memory_doc_id, m.repo_id AS memory_repo_id"
        " FROM memory_suggestions s"
        " JOIN memory m ON m.id = s.memory_id AND m.project_id = s.project_id"
        " WHERE s.id = %s AND s.project_id = %s",
        (suggestion_id, project_id),
    )
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    expected = _KIND_TARGET_CATEGORY.get(row["kind"])
    if expected is not None and row.get("memory_category") != expected:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return row


@router.get("/projects/{project_id}/suggestions")
def list_suggestions(project_id: int, status: str = "pending", kind: str = "complete_action"):
    require_project_access(project_id)
    if status not in _STATUSES:
        raise HTTPException(status_code=400, detail="Invalid suggestion status")
    # kind 기본값은 complete_action — supersede kind를 모르는 기존 클라이언트(데스크톱)가
    # evidence.title 없는 항목을 받아 렌더링이 죽지 않도록 구 계약을 보존한다.
    # supersede를 아는 클라이언트는 ?kind=supersede 또는 ?kind=all로 opt-in 조회한다.
    if kind != "all" and kind not in _KIND_TARGET_CATEGORY:
        raise HTTPException(status_code=400, detail="Invalid suggestion kind")

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Project not found")
            sql = (
                "SELECT * FROM memory_suggestions"
                " WHERE project_id = %s AND status = %s"
            )
            params = [project_id, status]
            if kind != "all":
                sql += " AND kind = %s"
                params.append(kind)
            cursor.execute(sql + " ORDER BY created_at DESC", params)
            return [_suggestion_response(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def _apply_accepted_effect(cursor, project_id: int, row: dict) -> None:
    """accept 시 suggestion.kind에 따라 대상 memory에 효과를 반영한다.

    - complete_action: 미완료 action이면 completed_at 설정. evidence.type='document'면
      그 문서의 날짜를 쓰고(과거 회의록 재처리 시 오늘 날짜로 잘못 찍히는 걸 방지),
      그 외(PR 등)는 지금까지처럼 NOW().
    - supersede: 아직 살아있는 decision이면 superseded_by=evidence.superseding_memory_id,
      superseded_at=NOW() 설정(계층1 필터가 이때부터 실효).
    지원하지 않는 kind는 명시적으로 거부한다 — 알 수 없는 kind가 기본 분기로 흘러
    엉뚱한 대상에 completed_at을 설정하는 것을 막는다.
    """
    kind = row["kind"]
    if kind == "supersede":
        evidence = _decode_evidence(row["evidence"]) or {}
        superseding_id = evidence.get("superseding_memory_id")
        if superseding_id is None:
            raise HTTPException(status_code=400, detail="Supersede evidence missing target")
        # 대체(신) 항목을 트랜잭션 안에서 검증 — 제안 생성 후 상태가 바뀌었을 수 있다.
        #   존재+project: 삭제/재동기화로 사라진 id로 기존 decision을 숨기지 않도록.
        #   category='decision': 사용자가 대체 row를 action 등으로 수정한 경우 거부.
        #   superseded_by IS NULL: 이미 번복된 decision은 대체자가 될 수 없다(순환 가드 —
        #     A→B accept 후 B→A를 accept하면 둘 다 숨어 해당 주제 결정이 전멸한다).
        #   FOR UPDATE: 상호(A→B·B→A) 제안 동시 승인 시 두 검증이 모두 상대를
        #     활성으로 읽고 각자 다른 행을 갱신해 순환이 완성되는 TOCTOU를 차단 —
        #     행 잠금으로 한쪽이 상대 커밋을 대기한 뒤 superseded 상태를 보고 409.
        cursor.execute(
            "SELECT id FROM memory WHERE id = %s AND project_id = %s"
            " AND category = 'decision' AND superseded_by IS NULL"
            " FOR UPDATE",
            (superseding_id, project_id),
        )
        if not cursor.fetchone():
            raise HTTPException(
                status_code=409,
                detail="Superseding decision no longer exists or is not a live decision",
            )
        current = row.get("memory_superseded_by")
        if current is not None:
            # 같은 대상으로 이미 처리됐으면 멱등, 다른 대상이면 충돌로 거부해
            # API 승인 이력과 실제 superseded_by 불일치를 방지한다.
            if int(current) == int(superseding_id):
                return
            raise HTTPException(status_code=409, detail="Decision already superseded by another decision")
        # 조건부 UPDATE + rowcount 확인: 읽은 뒤 다른 요청이 먼저 설정한 경합도 충돌로 거부.
        cursor.execute(
            "UPDATE memory SET superseded_by = %s, superseded_at = NOW(), updated_by = 'user'"
            " WHERE id = %s AND project_id = %s AND superseded_by IS NULL",
            (superseding_id, row["memory_id"], project_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=409, detail="Decision already superseded by another decision")
        return

    if kind == "complete_action":
        # 미완료 action 완료 처리. 행 잠금 + 최신 상태 재확인: split_action이 먼저 승인돼
        # 이 action의 content가 이미 바뀌었으면(예: 이 제안은 "인원관리 및 알림" 전체를
        # 근거로 만들어졌는데, 그 사이 split으로 "알림"만 남았다면) 그 변경을 반영 못 하는
        # 낡은 근거이므로 적용하지 않는다. evidence에 original_content가 없는(PR 기반 등
        # 기존 경로) 제안은 이 검사를 건너뛰고 기존 동작을 유지한다.
        cursor.execute(
            "SELECT content, completed_at FROM memory"
            " WHERE id = %s AND project_id = %s FOR UPDATE",
            (row["memory_id"], project_id),
        )
        current = cursor.fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail="Target action no longer exists")
        if current["completed_at"] is None:
            evidence = _decode_evidence(row["evidence"]) or {}
            original_content = evidence.get("original_content")
            if original_content is not None and current["content"] != original_content:
                raise HTTPException(
                    status_code=409,
                    detail="Action content changed since this suggestion was created — stale, please re-derive",
                )
            if evidence.get("type") == "document" and evidence.get("date"):
                cursor.execute(
                    "UPDATE memory SET completed_at = %s, completion_status = 'completed',"
                    " completion_status_source = 'document', updated_by = 'user'"
                    " WHERE id = %s AND project_id = %s",
                    (evidence["date"], row["memory_id"], project_id),
                )
            else:
                cursor.execute(
                    "UPDATE memory SET completed_at = NOW(), completion_status = 'completed',"
                    " completion_status_source = 'pr', updated_by = 'user'"
                    " WHERE id = %s AND project_id = %s",
                    (row["memory_id"], project_id),
                )
        return

    if kind == "split_action":
        # 묶음 action의 일부만 완료 보고된 경우: 원본은 남은 부분만 남기고 계속 열어두고,
        # 완료된 부분은 새 action으로 떼어내 바로 completed 처리한다.
        evidence = _decode_evidence(row["evidence"]) or {}
        done_part = evidence.get("done_part")
        remaining_part = evidence.get("remaining_part")
        if not done_part or not remaining_part:
            raise HTTPException(status_code=400, detail="Split evidence missing done_part/remaining_part")
        # 행 잠금 + 최신 상태 재확인: 이 제안이 만들어진 뒤 다른 제안(같은 memory_id)이
        # 먼저 승인돼 completed 되거나 content가 바뀌었으면, 이 제안은 그 사이 상황을
        # 반영 못 하는 낡은 근거이므로 그대로 적용하지 않고 거부한다(정확도 우선).
        cursor.execute(
            "SELECT content, completed_at FROM memory"
            " WHERE id = %s AND project_id = %s FOR UPDATE",
            (row["memory_id"], project_id),
        )
        current = cursor.fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail="Target action no longer exists")
        if current["completed_at"] is not None:
            return  # 이미 다른 경로로 완료 처리됨 — 분할 대상 없음, 멱등 처리
        original_content = evidence.get("original_content")
        if original_content is not None and current["content"] != original_content:
            raise HTTPException(
                status_code=409,
                detail="Action content changed since this suggestion was created — stale, please re-derive",
            )
        cursor.execute(
            "UPDATE memory SET content = %s, updated_by = 'user'"
            " WHERE id = %s AND project_id = %s",
            (remaining_part, row["memory_id"], project_id),
        )
        # complete_action과 동일하게: evidence에 문서 날짜가 있으면 그 날짜를, 없으면(빈
        # 문자열 등 — 업로드 폼에서 날짜를 안 넣은 경우) NOW()를 쓴다. 빈 문자열을 그대로
        # DATETIME 컬럼에 넣으면 안 됨.
        completed_sql = "%s" if evidence.get("date") else "NOW()"
        completed_params = [evidence["date"]] if evidence.get("date") else []
        cursor.execute(
            f"""
            INSERT INTO memory
                (project_id, doc_id, repo_id, category, content, owner, date, source,
                 completed_at, completion_status, completion_status_source, updated_by)
            VALUES (%s, %s, %s, 'action', %s, %s, %s, %s, {completed_sql}, 'completed', 'document', 'user')
            """,
            [
                project_id, row.get("memory_doc_id"), row.get("memory_repo_id"),
                done_part, row.get("memory_owner"), row.get("memory_date"), row.get("memory_source"),
            ] + completed_params,
        )
        row["_split_new_memory_id"] = cursor.lastrowid  # 아래 post-commit 벡터 동기화용
        return

    raise HTTPException(status_code=400, detail="Unsupported suggestion kind")


def _resolve_suggestion(project_id: int, suggestion_id: int, status: str) -> dict:
    """suggestion을 accepted/rejected로 닫고, accepted면 kind별 효과를 대상 memory에 반영한다."""
    # 상태를 변경하는 동작이므로 member 이상 권한 필요 — 타 프로젝트 무단 조작(IDOR) 방지.
    require_project_access(project_id, min_role="member")
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            row = _suggestion_or_404(cursor, project_id, suggestion_id)
            if row["status"] != "pending":
                raise HTTPException(status_code=400, detail="Suggestion already resolved")

            if status == "accepted":
                _apply_accepted_effect(cursor, project_id, row)

            # 조건부 UPDATE + rowcount 확인: 초기 pending 검사 후 다른 요청이 먼저
            # 해소했을 수 있다. 나중 요청이 확정된 상태를 덮어쓰면(예: accept가
            # superseded_by를 커밋한 뒤 reject가 status만 rejected로 변경) 효과와
            # 기록이 어긋나므로 409로 거부한다.
            cursor.execute(
                "UPDATE memory_suggestions SET status = %s, resolved_at = NOW(), resolved_by = %s"
                " WHERE id = %s AND project_id = %s AND status = 'pending'",
                (status, get_current_user_id(), suggestion_id, project_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=409, detail="Suggestion already resolved")
            cursor.execute(
                "SELECT * FROM memory_suggestions WHERE id = %s AND project_id = %s",
                (suggestion_id, project_id),
            )
            updated = cursor.fetchone() or {**row, "status": status}
        conn.commit()
    except pymysql.err.OperationalError as exc:
        conn.rollback()
        # 교차 잠금 데드락(1213): 상호 supersede 동시 승인 등에서 InnoDB가 한쪽
        # 트랜잭션을 중단시킨 경우 — 서버 오류가 아니라 경합 충돌로 응답한다.
        if exc.args and exc.args[0] == 1213:
            raise HTTPException(status_code=409, detail="Concurrent suggestion resolution conflict")
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # supersede accept가 확정되면 번복된 decision의 벡터를 제거해 벡터 상태를 MySQL과 동기화한다.
    # 그러지 않으면 비활성(superseded) 벡터가 이후 supersede 후보 검색의 top-N 슬롯을 계속 차지해
    # 유효 후보를 밀어낼 수 있다(commit 이후 best-effort — 실패해도 accept 결과는 유지).
    if status == "accepted" and row["kind"] == "supersede":
        try:
            from ..retriever.memory_vector import delete_memory_vector
            delete_memory_vector(row["memory_id"])
        except Exception:
            logger.warning("superseded 벡터 삭제 실패 memory_id=%s", row["memory_id"], exc_info=True)
        # 프로젝트 요약 캐시도 재생성한다 — 조망형 답변이 이 캐시를 직접 읽으므로,
        # 갱신하지 않으면 방금 숨긴 구 결정이 요약에 남아 계속 노출된다.
        # (삭제 경로들과 동일한 best-effort 헬퍼 재사용, 실패해도 accept 결과는 유지)
        from ..graph import refresh_project_memory_after_delete
        refresh_project_memory_after_delete(project_id)

    # split_action accept가 확정되면 원본(남은 부분)·신규(완료된 부분) 두 행 모두 벡터를
    # 최신 상태로 맞춘다 — 그러지 않으면 원본 벡터에 방금 떼어낸 완료 내용이 그대로 남는다.
    if status == "accepted" and row["kind"] == "split_action" and row.get("_split_new_memory_id"):
        try:
            from ..retriever.memory_vector import upsert_memory_vectors
            conn2 = get_connection()
            try:
                with conn2.cursor() as cursor2:
                    cursor2.execute(
                        "SELECT * FROM memory WHERE id IN (%s, %s) AND project_id = %s",
                        (row["memory_id"], row["_split_new_memory_id"], project_id),
                    )
                    upsert_memory_vectors(cursor2.fetchall())
            finally:
                conn2.close()
        except Exception:
            logger.warning(
                "split_action 벡터 동기화 실패 memory_id=%s", row["memory_id"], exc_info=True
            )

    return _suggestion_response(updated)


@router.post("/projects/{project_id}/suggestions/{suggestion_id}/accept")
def accept_suggestion(project_id: int, suggestion_id: int):
    return _resolve_suggestion(project_id, suggestion_id, "accepted")


@router.post("/projects/{project_id}/suggestions/{suggestion_id}/reject")
def reject_suggestion(project_id: int, suggestion_id: int):
    return _resolve_suggestion(project_id, suggestion_id, "rejected")
