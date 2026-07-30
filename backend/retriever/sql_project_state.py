"""Read-only SQL state builders used by Agentic retrieval tools."""

from __future__ import annotations

from collections import Counter

from ..db.mysql import get_connection


def fetch_project_overview_context(project_id: int) -> dict:
    """Return the current project summary and complete active Action Plan.

    This is evidence assembly only. The Agentic orchestrator decides whether to
    call it and writes the final answer; it is not an independent overview path.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT summary FROM project_memory WHERE project_id = %s",
                (project_id,),
            )
            project_memory = cursor.fetchone() or {}
            cursor.execute(
                "SELECT category, COUNT(*) AS count FROM active_memory"
                " WHERE project_id = %s GROUP BY category",
                (project_id,),
            )
            stats = cursor.fetchall()
            cursor.execute(
                "SELECT id, content, owner, date, due_date, completed_at,"
                " completion_status, completion_status_source, source"
                " FROM active_memory"
                " WHERE project_id = %s AND category = 'action'"
                " ORDER BY (sort_order IS NULL), sort_order ASC, created_at ASC, id ASC",
                (project_id,),
            )
            action_items = cursor.fetchall()
    finally:
        conn.close()

    counts = Counter(row.get("completion_status") for row in action_items)
    category_stats = {category: 0 for category in ("decision", "action", "issue", "risk")}
    category_stats.update({row["category"]: row["count"] for row in stats})
    return {
        "overview_summary": project_memory.get("summary", ""),
        "category_stats": category_stats,
        "action_plan": {
            "total": len(action_items),
            "status_counts": {
                status: counts[status]
                for status in ("open", "completed", "unknown")
            },
            "items": action_items,
        },
    }
