import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db.mysql import get_connection
from ..project_memory import refresh_project_memory_after_delete
from ..retriever.index_scope import mysql_visibility_condition
from ..retriever.memory_vector import delete_memory_vector, upsert_memory_vector
from .auth import get_current_user_id, require_project_access


router = APIRouter()
logger = logging.getLogger(__name__)


def _upsert_memory_vector_best_effort(row: dict):
    """Refresh Chroma's auxiliary index after a manual memory change."""
    try:
        upsert_memory_vector(row)
    except Exception:
        logger.warning("memory vector upsert failed memory_id=%s", row.get("id"))


def _delete_memory_vector_best_effort(memory_id: int):
    """Delete Chroma's auxiliary index after a manual memory deletion."""
    try:
        delete_memory_vector(memory_id)
    except Exception:
        logger.warning("memory vector delete failed memory_id=%s", memory_id)


@router.get("/projects/{project_id}/memory")
def get_memory(project_id: int, category: str = None, owner: str = None):
    require_project_access(project_id)
    from ..retriever.mysql_search import search

    return search(project_id, category=category, owner=owner)


class MemoryCreate(BaseModel):
    category: str
    content: str
    owner: Optional[str] = None
    date: Optional[str] = None
    due_date: Optional[str] = None
    topic: Optional[str] = None
    reason: Optional[str] = None


@router.post("/projects/{project_id}/memory", status_code=201)
def create_memory(project_id: int, body: MemoryCreate):
    require_project_access(project_id, min_role="member")
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Project not found")
            cursor.execute(
                "INSERT INTO memory"
                " (project_id, doc_id, category, content, reason, topic, owner, date, due_date,"
                " created_by, is_user_verified, completion_status, completion_status_source)"
                " VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, %s, 'user', 1, %s, %s)",
                (
                    project_id,
                    body.category,
                    body.content,
                    body.reason,
                    body.topic,
                    body.owner,
                    body.date or None,
                    body.due_date or None,
                    "open" if body.category == "action" else "unknown",
                    "user" if body.category == "action" else None,
                ),
            )
            memory_id = cursor.lastrowid
        conn.commit()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM memory WHERE id = %s", (memory_id,))
            row = cursor.fetchone()
        _upsert_memory_vector_best_effort(row)
        return row
    finally:
        conn.close()


class MemoryUpdate(BaseModel):
    category: Optional[str] = None
    content: Optional[str] = None
    owner: Optional[str] = None
    date: Optional[str] = None
    due_date: Optional[str] = None
    topic: Optional[str] = None
    reason: Optional[str] = None
    completed: Optional[bool] = None
    sort_order: Optional[int] = None


@router.patch("/projects/{project_id}/memory/{memory_id}")
def update_memory(project_id: int, memory_id: int, body: MemoryUpdate):
    require_project_access(project_id, min_role="member")
    raw_fields = body.model_dump(exclude_unset=True)
    fields = {
        key: value
        for key, value in raw_fields.items()
        if key in {"category", "content", "owner", "date", "topic", "reason"}
        and value is not None
    }
    if "due_date" in raw_fields:
        fields["due_date"] = raw_fields["due_date"]
    has_completed_update = "completed" in raw_fields
    if "sort_order" in raw_fields:
        fields["sort_order"] = raw_fields["sort_order"]
    if has_completed_update and raw_fields["completed"] is None:
        raise HTTPException(status_code=400, detail="completed는 true 또는 false여야 합니다.")
    if not fields and not has_completed_update:
        raise HTTPException(status_code=400, detail="수정할 필드가 없습니다.")

    fields["updated_by"] = "user"
    if any(
        key in raw_fields and raw_fields[key] is not None
        for key in {"category", "content", "owner", "date", "due_date", "topic", "reason"}
    ):
        fields["is_user_verified"] = 1

    set_parts = []
    values = []
    if has_completed_update:
        if fields.get("category") not in (None, "action"):
            raise HTTPException(
                status_code=400,
                detail="completed는 action category에서만 설정할 수 있습니다.",
            )
        if raw_fields["completed"]:
            set_parts.append("completed_at = NOW()")
            set_parts.append("completion_status = 'completed'")
        else:
            set_parts.append("completed_at = %s")
            values.append(None)
            set_parts.append("completion_status = 'open'")
        set_parts.append("completion_status_source = 'user'")
    elif "category" in fields:
        if fields["category"] == "action":
            set_parts.extend(
                [
                    "completed_at = CASE WHEN category = 'action' THEN completed_at ELSE NULL END",
                    "completion_status = CASE WHEN category = 'action' THEN completion_status ELSE 'open' END",
                    "completion_status_source = CASE WHEN category = 'action' THEN completion_status_source ELSE 'user' END",
                ]
            )
        else:
            set_parts.extend(
                [
                    "completed_at = NULL",
                    "completion_status = 'unknown'",
                    "completion_status_source = NULL",
                ]
            )
    set_parts.extend(f"{key} = %s" for key in fields)
    values.extend(fields.values())
    values.extend([memory_id, project_id])
    set_clause = ", ".join(set_parts)

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            if has_completed_update and "category" not in fields:
                cursor.execute(
                    "SELECT category FROM active_memory"
                    " WHERE id = %s AND project_id = %s FOR UPDATE",
                    (memory_id, project_id),
                )
                current_memory = cursor.fetchone()
                if not current_memory:
                    raise HTTPException(status_code=404, detail="Memory item not found")
                if current_memory.get("category") != "action":
                    raise HTTPException(
                        status_code=400,
                        detail="completed는 action category에서만 설정할 수 있습니다.",
                    )
            if fields.get("category") not in (None, "decision"):
                cursor.execute(
                    "SELECT 1 FROM active_memory WHERE superseded_by = %s"
                    " AND project_id = %s LIMIT 1",
                    (memory_id, project_id),
                )
                if cursor.fetchone():
                    raise HTTPException(
                        status_code=409,
                        detail="Cannot change category: this decision supersedes another decision",
                    )
                cursor.execute(
                    "SELECT superseded_by FROM active_memory"
                    " WHERE id = %s AND project_id = %s",
                    (memory_id, project_id),
                )
                current = cursor.fetchone()
                if current and current.get("superseded_by") is not None:
                    raise HTTPException(
                        status_code=409,
                        detail="Cannot change category: this decision is superseded by another decision",
                    )
            if any(
                raw_fields.get(key) is not None
                for key in ("category", "content", "topic", "reason", "date")
            ):
                cursor.execute(
                    "UPDATE memory_suggestions"
                    " SET status = 'rejected', resolved_at = NOW(), resolved_by = %s"
                    " WHERE project_id = %s AND kind = 'supersede' AND status = 'pending'"
                    " AND (memory_id = %s OR CAST(JSON_UNQUOTE(JSON_EXTRACT("
                    "evidence, '$.superseding_memory_id')) AS UNSIGNED) = %s)",
                    (get_current_user_id(), project_id, memory_id, memory_id),
                )
            if "due_date" in raw_fields:
                # 사용자가 마감일을 직접 설정하거나 해제하면 이전 LLM 후보는 더 이상
                # 유효하지 않다. 인박스에 승인 가능한 것처럼 남지 않도록 함께 닫는다.
                cursor.execute(
                    "UPDATE memory_suggestions"
                    " SET status = 'rejected', resolved_at = NOW(), resolved_by = %s"
                    " WHERE project_id = %s AND memory_id = %s"
                    " AND kind = 'set_due_date' AND status = 'pending'",
                    (get_current_user_id(), project_id, memory_id),
                )
            visible_sql, visible_params = mysql_visibility_condition("memory")
            cursor.execute(
                f"UPDATE memory SET {set_clause} WHERE id = %s AND project_id = %s"
                f" AND {visible_sql}",
                [*values, *visible_params],
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Memory item not found")
        conn.commit()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM active_memory WHERE id = %s", (memory_id,))
            row = cursor.fetchone()
        if row and row.get("superseded_by") is not None:
            _delete_memory_vector_best_effort(memory_id)
        else:
            _upsert_memory_vector_best_effort(row)
        return row
    finally:
        conn.close()


@router.delete("/projects/{project_id}/memory/{memory_id}", status_code=204)
def delete_memory(project_id: int, memory_id: int):
    require_project_access(project_id, min_role="member")
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            visible_sql, visible_params = mysql_visibility_condition("memory")
            cursor.execute(
                "DELETE FROM memory WHERE id = %s AND project_id = %s"
                f" AND {visible_sql}",
                [memory_id, project_id, *visible_params],
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Memory item not found")
        conn.commit()
    finally:
        conn.close()
    _delete_memory_vector_best_effort(memory_id)
    refresh_project_memory_after_delete(project_id)
