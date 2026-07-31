"""Project summary cache built from active memory rows."""

import logging
from contextlib import contextmanager
from threading import Lock, RLock

from .db.mysql import get_connection
from .llm.chat_model_factory import get_chat_model


logger = logging.getLogger(__name__)
_project_locks: dict[int, RLock] = {}
_project_locks_guard = Lock()


@contextmanager
def project_memory_write_lock(project_id: int):
    """Serialize summary writers with repository generation publication.

    The deployment contract is a single backend worker. This process-local
    lock prevents a writer based on the previous generation from restoring a
    stale summary after the active repository pointer changes.
    """
    with _project_locks_guard:
        lock = _project_locks.setdefault(project_id, RLock())
    with lock:
        yield


_MEMORY_DDL = """
CREATE TABLE IF NOT EXISTS project_memory (
    project_id INT PRIMARY KEY,
    summary    TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
)
"""


def get_project_memory(project_id: int) -> str:
    """Return the condensed project summary, or an empty string if absent."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_MEMORY_DDL)
            cur.execute("SELECT summary FROM project_memory WHERE project_id = %s", (project_id,))
            row = cur.fetchone()
        conn.commit()
        return row["summary"] if row and row.get("summary") else ""
    finally:
        conn.close()


def upsert_project_memory(project_id: int, summary: str) -> None:
    """Create or update the project summary."""
    with project_memory_write_lock(project_id):
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(_MEMORY_DDL)
                cur.execute(
                    "INSERT INTO project_memory (project_id, summary) VALUES (%s, %s) "
                    "ON DUPLICATE KEY UPDATE summary = VALUES(summary)",
                    (project_id, summary),
                )
            conn.commit()
        finally:
            conn.close()


def delete_project_memory(project_id: int) -> None:
    """Delete the project summary cache."""
    with project_memory_write_lock(project_id):
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM project_memory WHERE project_id = %s", (project_id,))
            conn.commit()
        finally:
            conn.close()


def _format_summary_memory_row(row: dict) -> str:
    """Format one active memory row for summary regeneration."""
    meta = []
    if row.get("owner"):
        meta.append(f"담당: {row['owner']}")
    if row.get("due_date"):
        meta.append(f"마감: {str(row['due_date'])[:10]}")
    if row.get("category") == "action":
        status = row.get("completion_status") or (
            "completed" if row.get("completed_at") else "unknown"
        )
        if status == "completed":
            meta.append(
                f"완료: {str(row['completed_at'])[:10]}"
                if row.get("completed_at") else "완료"
            )
        elif status == "open":
            meta.append("미완료")
        else:
            meta.append("완료 여부 미확인")
    meta_text = f" ({', '.join(meta)})" if meta else ""
    return f"[{row['category']}] {row['content']}{meta_text}"


def regenerate_project_memory(project_id: int) -> str:
    """Regenerate the summary from currently active memory rows only."""
    with project_memory_write_lock(project_id):
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT category, content, owner, due_date, completed_at, completion_status"
                    " FROM active_memory WHERE project_id = %s"
                    " ORDER BY (sort_order IS NULL), sort_order ASC, created_at ASC",
                    (project_id,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()

        if not rows:
            delete_project_memory(project_id)
            return ""

        memory_lines = "\n".join(_format_summary_memory_row(row) for row in rows)
        llm = get_chat_model()
        prompt = (
            "다음은 현재 프로젝트에 남아 있는 memory 항목 전체이다. "
            "삭제된 항목은 절대 추측하거나 포함하지 말고, 남은 항목만 근거로 "
            "핵심 결정·진행·이슈·리스크가 드러나도록 5문장 이내의 갱신 요약을 한국어로 작성하라.\n\n"
            f"[남은 항목]\n{memory_lines}"
        )
        summary = llm.invoke(prompt).content
        upsert_project_memory(project_id, summary)
        return summary


def refresh_project_memory_after_delete(project_id: int) -> None:
    """Best-effort summary refresh after a document or memory deletion."""
    try:
        regenerate_project_memory(project_id)
    except Exception:
        logger.warning(
            "project_memory refresh after delete failed project_id=%s",
            project_id,
            exc_info=True,
        )


def update_project_memory(project_id: int, items: list) -> str:
    """Merge newly extracted items into the condensed project summary."""
    with project_memory_write_lock(project_id):
        previous = get_project_memory(project_id)
        if not items:
            return previous
        new_items = "\n".join(f"[{item.category}] {item.content}" for item in items)
        llm = get_chat_model()
        prompt = (
            "다음은 프로젝트의 기존 요약과 새로 추가된 항목이다. "
            "핵심 결정·진행·이슈·리스크가 드러나도록 5문장 이내의 갱신 요약을 한국어로 작성하라.\n\n"
            f"[기존 요약]\n{previous or '(없음)'}\n\n[새 항목]\n{new_items or '(없음)'}"
        )
        summary = llm.invoke(prompt).content
        upsert_project_memory(project_id, summary)
        return summary
