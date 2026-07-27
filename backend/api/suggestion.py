import json
import logging
from typing import Optional

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
    "complete_action_doc": "action",
    "split_action": "action",
    "supersede": "decision",
}

# 구 데스크톱이 렌더링할 수 있는 kind 집합 — 여기서 영구히 동결한다.
# kind=all은 "내가 아는 것 전부"라는 뜻으로 쓰였지만 실제로는 "앞으로 생길 것까지 전부"라
# 신규 kind가 자동으로 구 클라이언트에 샜다(split_action이 supersede 카드로 렌더링됨).
# 신규 kind를 아는 클라이언트는 ?kind=<신규kind>로 명시 조회한다.
_LEGACY_KINDS = ("complete_action", "supersede")


def _split_parts(evidence: dict, list_key: str, legacy_key: str) -> list[str]:
    """split evidence에서 분할 조각 목록을 읽는다.

    N분할 이전에 만들어져 아직 pending으로 남아 있는 제안은 단수 문자열 필드
    (done_part/remaining_part)를 갖고 있다. 그 제안을 승인 불가로 버리지 않도록
    여기서 원소 1개짜리 목록으로 승격해 같은 경로로 처리한다.
    """
    parts = evidence.get(list_key)
    if not parts:
        legacy = evidence.get(legacy_key)
        parts = [legacy] if legacy else []
    return [str(part).strip() for part in parts if str(part).strip()]


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
        " m.due_date AS memory_due_date,"
        " m.doc_id AS memory_doc_id, m.repo_id AS memory_repo_id,"
        " m.topic AS memory_topic, m.reason AS memory_reason"
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
def list_suggestions(
    project_id: int,
    status: str = "pending",
    kind: str = "complete_action",
    kinds: Optional[str] = None,
):
    require_project_access(project_id)
    if status not in _STATUSES:
        raise HTTPException(status_code=400, detail="Invalid suggestion status")
    # kind 기본값은 complete_action — supersede kind를 모르는 기존 클라이언트(데스크톱)가
    # evidence.title 없는 항목을 받아 렌더링이 죽지 않도록 구 계약을 보존한다.
    # supersede를 아는 클라이언트는 ?kind=supersede로 opt-in 조회한다.
    # kind=all은 _LEGACY_KINDS로 동결 — 신규 kind는 명시 조회로만 나간다.
    if kind != "all" and kind not in _KIND_TARGET_CATEGORY:
        raise HTTPException(status_code=400, detail="Invalid suggestion kind")

    # kinds는 여러 kind를 한 번에 받고 싶은 클라이언트용(콤마 구분) — 자기가 아는 kind를
    # 스스로 선언하는 구조라, 이후 kind가 추가돼도 선언하지 않은 클라이언트는 영향 없다.
    # kind와 동시 지정은 모호하므로 400으로 거부해 택일을 강제한다.
    kind_list: Optional[list[str]] = None
    if kinds is not None:
        if kind != "complete_action":  # 기본값이 아닌데 kinds도 왔으면 둘 다 명시한 것
            raise HTTPException(status_code=400, detail="Specify either kind or kinds, not both")
        kind_list = [k.strip() for k in kinds.split(",") if k.strip()]
        if not kind_list:
            raise HTTPException(status_code=400, detail="kinds must not be empty")
        unknown = [k for k in kind_list if k not in _KIND_TARGET_CATEGORY]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Invalid suggestion kind: {unknown[0]}")

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
            if kind_list is not None:
                placeholders = ", ".join(["%s"] * len(kind_list))
                sql += f" AND kind IN ({placeholders})"
                params.extend(kind_list)
            elif kind == "all":
                placeholders = ", ".join(["%s"] * len(_LEGACY_KINDS))
                sql += f" AND kind IN ({placeholders})"
                params.extend(_LEGACY_KINDS)
            else:
                sql += " AND kind = %s"
                params.append(kind)
            cursor.execute(sql + " ORDER BY created_at DESC", params)
            return [_suggestion_response(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def _apply_accepted_effect(cursor, project_id: int, row: dict) -> None:
    """accept 시 suggestion.kind에 따라 대상 memory에 효과를 반영한다.

    - complete_action / complete_action_doc: 미완료 action이면 completed_at 설정.
      evidence.type='document'면 그 문서의 날짜를 쓰고(과거 회의록 재처리 시 오늘 날짜로
      잘못 찍히는 걸 방지), 그 외(PR 등)는 지금까지처럼 NOW(). 두 kind는 근거 종류만
      다르고 승인 효과가 같아 분기를 공유한다.
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

    if kind in ("complete_action", "complete_action_doc"):
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
            # source(근거 종류)와 completed_at(완료 시각)은 서로 다른 축이다. 둘을 한
            # 조건으로 묶으면 날짜 없는 문서 근거가 'pr'로 기록되는데, 업로드 폼에서
            # 날짜를 안 넣는 게 기본 경로라 흔하다. completion_status_source는 검색
            # 컨텍스트에 "상태 근거: ..."로 노출되므로(qa_engine) 답변에 잘못된 근거가
            # 표시된다. split_action 분기가 날짜와 무관하게 'document'인 것과도 어긋난다.
            source = "document" if evidence.get("type") == "document" else "pr"
            # 날짜는 완료 시각 선택에만 쓴다 — 있으면 그 문서 날짜(과거 회의록을 뒤늦게
            # 적재해도 오늘로 찍히지 않게), 없으면 NOW().
            completed_sql = "%s" if evidence.get("date") else "NOW()"
            completed_params = [evidence["date"]] if evidence.get("date") else []
            cursor.execute(
                f"UPDATE memory SET completed_at = {completed_sql}, completion_status = 'completed',"
                " completion_status_source = %s, updated_by = 'user'"
                " WHERE id = %s AND project_id = %s",
                completed_params + [source, row["memory_id"], project_id],
            )
        return

    if kind == "split_action":
        # 묶음 action이 부분 완료 보고된 경우: sub-task 단위로 쪼개 완료분은 completed
        # 행으로, 잔여분은 열린 행으로 남긴다. 원본 행은 id를 유지한 채 첫 잔여분을
        # 갖고 계속 열려 있다 — 이 action을 가리키는 다른 pending 제안·벡터가 그대로
        # 유효해야 하므로 원본을 완료분 쪽에 쓰지 않는다.
        evidence = _decode_evidence(row["evidence"]) or {}
        done_parts = _split_parts(evidence, "done_parts", "done_part")
        remaining_parts = _split_parts(evidence, "remaining_parts", "remaining_part")
        if not done_parts or not remaining_parts:
            raise HTTPException(status_code=400, detail="Split evidence missing done_parts/remaining_parts")
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
            # 이미 다른 경로로 완료 처리된 action은 분할할 수 없다. complete_action과 달리
            # 여기서 멱등 성공을 반환하면 안 된다 — complete_action은 의도(완료 처리)가 이미
            # 달성돼 있지만, split은 의도(완료분 분리 + 잔여분 유지)가 아무것도 반영되지
            # 않았는데 accepted 이력만 남고, "남은 부분은 아직 열려 있다"는 정보가 조용히
            # 버려져 묶음 action이 통째로 완료된 채 남는다.
            raise HTTPException(
                status_code=409,
                detail="Action already completed — split no longer applicable, please re-derive",
            )
        original_content = evidence.get("original_content")
        if original_content is not None and current["content"] != original_content:
            raise HTTPException(
                status_code=409,
                detail="Action content changed since this suggestion was created — stale, please re-derive",
            )
        cursor.execute(
            "UPDATE memory SET content = %s, updated_by = 'user'"
            " WHERE id = %s AND project_id = %s",
            (remaining_parts[0], row["memory_id"], project_id),
        )

        def insert_part(content: str, *, done: bool) -> int:
            """분할된 sub-task 하나를 새 memory 행으로 만들고 id를 돌려준다."""
            if done:
                # complete_action과 동일하게: evidence에 문서 날짜가 있으면 그 날짜를,
                # 없으면(빈 문자열 등 — 업로드 폼에서 날짜를 안 넣은 경우) NOW()를 쓴다.
                # 빈 문자열을 그대로 DATETIME 컬럼에 넣으면 안 됨.
                completed_sql = "%s" if evidence.get("date") else "NOW()"
                completed_params = [evidence["date"]] if evidence.get("date") else []
                # 완료 행에는 마감일을 승계하지 않는다 — 마감/지연 조회에 완료된 일이 섞인다.
                status, due_date = "completed", None
            else:
                completed_sql = "NULL"
                completed_params = []
                # 잔여분은 아직 열려 있으므로 원본의 마감일을 그대로 승계한다. 승계하지
                # 않으면 마감이 걸린 묶음 action을 쪼갠 순간 잔여분이 마감 조회에서 빠진다.
                status, due_date = "open", row.get("memory_due_date")
            cursor.execute(
                f"""
                INSERT INTO memory
                    (project_id, doc_id, repo_id, category, content, owner, date, source,
                     topic, reason, due_date,
                     completed_at, completion_status, completion_status_source, updated_by)
                VALUES (%s, %s, %s, 'action', %s, %s, %s, %s, %s, %s, %s,
                        {completed_sql}, %s, 'document', 'user')
                """,
                # topic/reason은 원본에서 승계 — format_memory_document가 BM25·벡터 입력에
                # 쓰는 필드라, 비우면 떼어낸 행이 검색에서 주제·근거 신호를 잃는다.
                [
                    project_id, row.get("memory_doc_id"), row.get("memory_repo_id"),
                    content, row.get("memory_owner"), row.get("memory_date"),
                    row.get("memory_source"), row.get("memory_topic"), row.get("memory_reason"),
                    due_date,
                ] + completed_params + [status],
            )
            return cursor.lastrowid

        # ponytail: 신규 행은 sort_order를 안 받아 목록 끝으로 간다. 원본 옆에 붙이려면
        # 형제 행 재정렬이 필요한데, 지금은 사용자가 드래그로 옮길 수 있어 미룬다.
        row["_split_new_memory_ids"] = (
            [insert_part(part, done=False) for part in remaining_parts[1:]]
            + [insert_part(part, done=True) for part in done_parts]
        )
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

    # split_action accept가 확정되면 원본(첫 잔여분)·신규(나머지 조각 전부) 행 모두 벡터를
    # 최신 상태로 맞춘다 — 그러지 않으면 원본 벡터에 방금 떼어낸 내용이 그대로 남는다.
    split_ids = row.get("_split_new_memory_ids")
    if status == "accepted" and row["kind"] == "split_action" and split_ids:
        try:
            from ..retriever.memory_vector import upsert_memory_vectors
            conn2 = get_connection()
            try:
                with conn2.cursor() as cursor2:
                    ids = [row["memory_id"]] + split_ids
                    cursor2.execute(
                        "SELECT * FROM memory WHERE id IN ({}) AND project_id = %s".format(
                            ",".join(["%s"] * len(ids))
                        ),
                        ids + [project_id],
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
