from unittest.mock import MagicMock, patch

import pytest

from backend.retriever.index_scope import (
    ProjectIndexScope,
    chroma_visibility_filter,
    load_project_index_scope,
    mysql_visibility_condition,
)


def _connection(rows):
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn, cursor


def test_load_scope_separates_published_and_legacy_repositories():
    conn, cursor = _connection(
        [
            {"id": 1, "active_sync_run_id": "run-b"},
            {"id": 2, "active_sync_run_id": None},
            {"id": 3, "active_sync_run_id": "run-a"},
        ]
    )
    with patch("backend.retriever.index_scope.get_connection", return_value=conn):
        scope = load_project_index_scope(7)

    assert scope == ProjectIndexScope(7, ("run-a", "run-b"), (2,))
    assert cursor.execute.call_args.args[1] == (7,)


def test_mysql_scope_contains_documents_active_runs_and_legacy_pairs():
    scope = ProjectIndexScope(7, ("run-a", "run-b"), (2, 4))
    sql, params = mysql_visibility_condition("m", scope)

    assert "m.repo_id IS NULL" in sql
    assert "m.repo_sync_run_id IN (%s, %s)" in sql
    assert "m.repo_id IN (%s, %s)" in sql
    assert "m.repo_sync_run_id IS NULL" in sql
    assert params == ["run-a", "run-b", 2, 4]


def test_correlated_mysql_scope_uses_repository_pointer():
    sql, params = mysql_visibility_condition("candidate")
    assert "visible_repo.active_sync_run_id=candidate.repo_sync_run_id" in sql
    assert "candidate.repo_sync_run_id IS NULL" in sql
    assert params == []


def test_chroma_scope_excludes_staging_rows_from_legacy_branch():
    scope = ProjectIndexScope(7, ("run-a",), (2,))
    where = chroma_visibility_filter(scope, {"item_type": "memory"})
    rendered = repr(where)

    assert "run-a" in rendered
    assert "repo_sync_staging" in rendered
    assert "item_type" in rendered
    assert "project_id" in rendered


def test_scope_is_immutable():
    with pytest.raises(Exception):
        ProjectIndexScope(1).project_id = 2
