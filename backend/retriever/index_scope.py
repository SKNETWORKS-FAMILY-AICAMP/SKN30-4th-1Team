"""Published repository-generation scope shared by MySQL and Chroma retrieval.

Document data has no repository generation and is always visible. Repository
data is visible only when its sync run is the repository's published
``active_sync_run_id``. Repositories created before generation tracking keep
both values NULL; that legacy pair remains visible until the first successful
generation is published.
"""
from dataclasses import dataclass
from typing import Iterable, Sequence

from ..db.mysql import get_connection


NO_REPO_ID = -1


@dataclass(frozen=True)
class ProjectIndexScope:
    project_id: int
    active_run_ids: tuple[str, ...] = ()
    legacy_repo_ids: tuple[int, ...] = ()


def _unique_sorted(values: Iterable) -> tuple:
    return tuple(sorted(set(values)))


def load_project_index_scope(project_id: int) -> ProjectIndexScope:
    """Capture one published-generation snapshot for a project."""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id,active_sync_run_id FROM repositories"
                " WHERE project_id=%s ORDER BY id",
                (project_id,),
            )
            rows = cursor.fetchall()
    finally:
        conn.close()

    return ProjectIndexScope(
        project_id=project_id,
        active_run_ids=_unique_sorted(
            str(row["active_sync_run_id"])
            for row in rows
            if row.get("active_sync_run_id")
        ),
        legacy_repo_ids=_unique_sorted(
            int(row["id"])
            for row in rows
            if not row.get("active_sync_run_id")
        ),
    )


def mysql_visibility_condition(
    alias: str = "m",
    scope: ProjectIndexScope | None = None,
) -> tuple[str, list]:
    """Return SQL and parameters that expose documents plus published repo rows.

    With no explicit scope, the correlated repository pointer is used. Passing
    a scope makes a hybrid request use the exact same snapshot for MySQL and
    Chroma even if a publish happens between the two reads.
    """
    if scope is None:
        return (
            f"({alias}.repo_id IS NULL OR EXISTS ("
            "SELECT 1 FROM repositories visible_repo"
            f" WHERE visible_repo.id={alias}.repo_id"
            f" AND visible_repo.project_id={alias}.project_id"
            " AND ("
            "visible_repo.active_sync_run_id="
            f"{alias}.repo_sync_run_id"
            " OR (visible_repo.active_sync_run_id IS NULL"
            f" AND {alias}.repo_sync_run_id IS NULL)"
            ")))",
            [],
        )

    branches = [f"{alias}.repo_id IS NULL"]
    params: list = []
    if scope.active_run_ids:
        placeholders = ", ".join(["%s"] * len(scope.active_run_ids))
        branches.append(f"{alias}.repo_sync_run_id IN ({placeholders})")
        params.extend(scope.active_run_ids)
    if scope.legacy_repo_ids:
        placeholders = ", ".join(["%s"] * len(scope.legacy_repo_ids))
        branches.append(
            f"({alias}.repo_id IN ({placeholders})"
            f" AND {alias}.repo_sync_run_id IS NULL)"
        )
        params.extend(scope.legacy_repo_ids)
    return f"({' OR '.join(branches)})", params


def _and_conditions(conditions: Sequence[dict]) -> dict:
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": list(conditions)}


def chroma_visibility_filter(
    scope: ProjectIndexScope,
    *extra_conditions: dict,
) -> dict:
    """Build a Chroma filter for documents and published repo generations.

    Existing legacy Chroma rows have no generation metadata. New staging rows
    carry ``repo_sync_staging=True``; the legacy branch explicitly excludes
    them while still matching old rows whose marker is absent. Once a run is
    published, the active-run branch exposes it regardless of that marker.
    """
    visible: list[dict] = [{"repo_id": NO_REPO_ID}]
    if scope.active_run_ids:
        visible.append(
            {"repo_sync_run_id": {"$in": list(scope.active_run_ids)}}
        )
    if scope.legacy_repo_ids:
        visible.append({
            "$and": [
                {"repo_id": {"$in": list(scope.legacy_repo_ids)}},
                {"repo_sync_staging": {"$ne": True}},
            ]
        })

    visible_condition = (
        visible[0] if len(visible) == 1 else {"$or": visible}
    )
    return _and_conditions((
        {"project_id": scope.project_id},
        visible_condition,
        *extra_conditions,
    ))
