from unittest.mock import MagicMock, patch

from backend.retriever.sql_project_state import fetch_project_overview_context


def _make_conn():
    cursor = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    return conn, cursor


def test_agentic_overview_evidence_reads_active_memory_without_top_n_truncation():
    rows = [
        {
            "id": index,
            "content": f"작업 {index}",
            "owner": f"담당자 {index}",
            "date": f"2026-07-{index:02d}",
            "due_date": None,
            "completed_at": None,
            "completion_status": ("open", "completed", "unknown")[(index - 1) % 3],
            "completion_status_source": "explicit",
            "source": f"meeting-{index}.md",
        }
        for index in range(1, 21)
    ]
    conn, cursor = _make_conn()
    cursor.fetchone.return_value = {"summary": "요약"}
    cursor.fetchall.side_effect = [
        [{"category": "action", "count": 20}],
        rows,
    ]

    with patch("backend.retriever.sql_project_state.get_connection", return_value=conn):
        context = fetch_project_overview_context(1)

    assert context["overview_summary"] == "요약"
    assert context["category_stats"] == {
        "decision": 0,
        "action": 20,
        "issue": 0,
        "risk": 0,
    }
    assert context["action_plan"]["total"] == 20
    assert context["action_plan"]["status_counts"] == {
        "open": 7,
        "completed": 7,
        "unknown": 6,
    }
    assert context["action_plan"]["items"] == rows

    active_memory_sql = [
        call.args[0]
        for call in cursor.execute.call_args_list
        if "FROM active_memory" in call.args[0]
    ]
    assert len(active_memory_sql) == 2
    assert "GROUP BY category" in active_memory_sql[0]
    assert "LIMIT" not in active_memory_sql[1]
