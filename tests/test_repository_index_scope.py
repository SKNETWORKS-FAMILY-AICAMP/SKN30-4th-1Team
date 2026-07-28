from unittest.mock import MagicMock, patch

import chromadb

from backend.retriever.index_scope import (
    ProjectIndexScope,
    chroma_visibility_filter,
    load_project_index_scope,
    mysql_visibility_condition,
)


def _connection_with_rows(rows):
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    return conn, cursor


def test_load_scope_separates_active_and_legacy_repositories():
    conn, cursor = _connection_with_rows([
        {"id": 9, "active_sync_run_id": None},
        {"id": 2, "active_sync_run_id": "run-b"},
        {"id": 1, "active_sync_run_id": "run-a"},
    ])
    with patch(
        "backend.retriever.index_scope.get_connection", return_value=conn
    ):
        scope = load_project_index_scope(7)

    assert scope == ProjectIndexScope(
        7,
        active_run_ids=("run-a", "run-b"),
        legacy_repo_ids=(9,),
    )
    assert cursor.execute.call_args.args[1] == (7,)
    conn.close.assert_called_once()


def test_mysql_visibility_includes_documents_active_and_null_legacy_pair():
    scope = ProjectIndexScope(
        7,
        active_run_ids=("published-run",),
        legacy_repo_ids=(11,),
    )
    sql, params = mysql_visibility_condition("m", scope)

    assert "m.repo_id IS NULL" in sql
    assert "m.repo_sync_run_id IN (%s)" in sql
    assert "m.repo_id IN (%s)" in sql
    assert "m.repo_sync_run_id IS NULL" in sql
    assert params == ["published-run", 11]

    live_sql, live_params = mysql_visibility_condition("m")
    assert "visible_repo.active_sync_run_id=m.repo_sync_run_id" in live_sql
    assert "visible_repo.active_sync_run_id IS NULL" in live_sql
    assert "m.repo_sync_run_id IS NULL" in live_sql
    assert live_params == []


def test_chroma_filter_hides_staging_and_inactive_generations(tmp_path):
    collection = chromadb.PersistentClient(
        path=str(tmp_path / "chroma")
    ).get_or_create_collection("scope")
    collection.add(
        ids=["document", "legacy", "staging", "active", "inactive"],
        embeddings=[[1.0, 0.0]] * 5,
        documents=["doc", "legacy", "staging", "active", "inactive"],
        metadatas=[
            {"project_id": 7, "repo_id": -1},
            # Pre-generation rows have neither generation nor staging metadata.
            {"project_id": 7, "repo_id": 11},
            {
                "project_id": 7,
                "repo_id": 11,
                "repo_sync_run_id": "staging-run",
                "repo_sync_staging": True,
            },
            {
                "project_id": 7,
                "repo_id": 12,
                "repo_sync_run_id": "published-run",
                "repo_sync_staging": True,
            },
            {
                "project_id": 7,
                "repo_id": 12,
                "repo_sync_run_id": "old-run",
                "repo_sync_staging": True,
            },
        ],
    )
    scope = ProjectIndexScope(
        7,
        active_run_ids=("published-run",),
        legacy_repo_ids=(11,),
    )

    result = collection.get(where=chroma_visibility_filter(scope))

    assert set(result["ids"]) == {"document", "legacy", "active"}


def test_chroma_filter_composes_item_type_with_visibility():
    scope = ProjectIndexScope(3, active_run_ids=("run-1",))

    where = chroma_visibility_filter(scope, {"item_type": "memory"})

    assert where["$and"][0] == {"project_id": 3}
    assert where["$and"][-1] == {"item_type": "memory"}
    assert {"repo_sync_run_id": {"$in": ["run-1"]}} in (
        where["$and"][1]["$or"]
    )
