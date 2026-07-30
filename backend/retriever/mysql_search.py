import unicodedata
from typing import Optional, List, Dict
from ..db.mysql import get_connection
from .index_scope import (
    ProjectIndexScope,
    load_project_index_scope,
    mysql_visibility_condition,
)


def _literal_like_pattern(value: str) -> str:
    """Wrap a literal substring for LIKE using ``!`` as the escape character."""
    escaped = value.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return f"%{escaped}%"


def _resolve_scope(
    project_id: int,
    index_scope: ProjectIndexScope | None,
) -> ProjectIndexScope:
    scope = index_scope or load_project_index_scope(project_id)
    if scope.project_id != project_id:
        raise ValueError("index_scope project_id does not match project_id")
    return scope


def _optional_text(value, field: str) -> Optional[str]:
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError(f"{field} must be a string")
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized:
        raise ValueError(f"{field} cannot be empty")
    return normalized


def _source_info_from_row(row: dict) -> dict:
    return {
        "kind": row.pop("source_kind", None),
        "doc_id": row.pop("ms_doc_id", None),
        "repo_id": row.pop("ms_repo_id", None),
        "type": row.pop("source_type", None),
        "path": row.pop("source_path", None),
        "ref": row.pop("source_ref", None),
        "url": row.pop("source_url", None),
    }


def _source_info_key(info: dict) -> tuple[str, ...]:
    return tuple(
        "" if info.get(field) is None else str(info.get(field))
        for field in ("kind", "doc_id", "repo_id", "type", "path", "ref", "url")
    )


def _collapse_joined_sources(rows: list[dict]) -> list[dict]:
    """Collapse JOIN-expanded memory rows with deterministic provenance."""
    result: list[dict] = []
    by_id: dict[object, dict] = {}
    sources_by_id: dict[object, dict[tuple[str, ...], dict]] = {}
    empty_source = {
        "kind": None,
        "doc_id": None,
        "repo_id": None,
        "type": None,
        "path": None,
        "ref": None,
        "url": None,
    }
    for position, raw_row in enumerate(rows):
        row = dict(raw_row)
        info = _source_info_from_row(row)
        key = row.get("id")
        if key is None:
            key = ("row", position)
        if key not in by_id:
            by_id[key] = row
            sources_by_id[key] = {}
            result.append(row)
        if any(value is not None for value in info.values()):
            sources_by_id[key][_source_info_key(info)] = info

    for key, row in by_id.items():
        infos = [
            sources_by_id[key][info_key]
            for info_key in sorted(sources_by_id[key])
        ]
        row["source_infos"] = infos
        row["source_info"] = infos[0] if infos else dict(empty_source)
    return result


def _visible_successor_exists(
    row_alias: str,
    successor_alias: str,
    scope: ProjectIndexScope,
) -> tuple[str, list]:
    visible_sql, visible_params = mysql_visibility_condition(successor_alias, scope)
    return (
        f"EXISTS (SELECT 1 FROM memory {successor_alias}"
        f" WHERE {successor_alias}.id={row_alias}.superseded_by"
        f" AND {successor_alias}.project_id={row_alias}.project_id"
        f" AND {visible_sql})",
        visible_params,
    )


def search(
    project_id: int,
    category: Optional[str] = None,
    owner: Optional[str] = None,
    completion_status: Optional[str] = None,
    completed: Optional[bool] = None,
    due_within_days: Optional[int] = None,
    overdue: Optional[bool] = None,
    include_superseded: bool = False,
    text_query: Optional[str] = None,
    index_scope: ProjectIndexScope | None = None,
) -> List[Dict]:
    if type(project_id) is not int or project_id <= 0:
        raise ValueError("project_id must be a positive integer")
    if category is not None and (
        type(category) is not str
        or category not in ("decision", "action", "issue", "risk")
    ):
        raise ValueError("category is invalid")
    owner = _optional_text(owner, "owner")
    text_query = _optional_text(text_query, "text_query")
    if completed is not None and type(completed) is not bool:
        raise ValueError("completed must be a boolean")
    if overdue is not None and type(overdue) is not bool:
        raise ValueError("overdue must be a boolean")
    if type(include_superseded) is not bool:
        raise ValueError("include_superseded must be a boolean")
    if completed is not None:
        legacy_status = "completed" if completed else "open"
        if completion_status not in (None, legacy_status):
            raise ValueError("completed and completion_status conflict")
        completion_status = legacy_status
    if completion_status is not None and type(completion_status) is not str:
        raise ValueError("completion_status must be a string")
    if completion_status not in (None, "open", "completed", "unknown"):
        raise ValueError("completion_status must be open, completed, or unknown")
    if overdue not in (None, True):
        raise ValueError("overdue must be true when provided")
    if overdue is True and due_within_days is not None:
        raise ValueError("overdue and due_within_days conflict")
    if overdue is True and completion_status not in (None, "open"):
        raise ValueError("overdue is only compatible with open actions")
    if due_within_days is not None:
        if type(due_within_days) is not int:
            raise ValueError("due_within_days must be an integer")
        if not 0 <= due_within_days <= 365:
            raise ValueError("due_within_days must be between 0 and 365")

    action_filter_requested = any(
        value is not None
        for value in (completion_status, due_within_days, overdue)
    )
    if action_filter_requested:
        if category not in (None, "action"):
            raise ValueError("status and due filters apply only to action rows")
        category = "action"

    scope = _resolve_scope(project_id, index_scope)
    conditions = ["m.project_id = %s"]
    params: list = [project_id]
    visible_sql, visible_params = mysql_visibility_condition("m", scope)
    conditions.append(visible_sql)
    params.extend(visible_params)

    # A staging successor must not hide a decision in the published snapshot.
    if not include_superseded:
        successor_exists, successor_params = _visible_successor_exists(
            "m", "visible_successor", scope
        )
        conditions.append(f"NOT {successor_exists}")
        params.extend(successor_params)

    if category:
        conditions.append("m.category = %s")
        params.append(category)
    if owner:
        conditions.append("m.owner = %s")
        params.append(owner)
    if text_query and text_query.strip():
        conditions.append(
            "CONCAT_WS(' ', m.content, m.topic, m.reason) LIKE %s ESCAPE '!'"
        )
        params.append(_literal_like_pattern(text_query.strip()))
    if completion_status:
        conditions.append("m.completion_status = %s")
        params.append(completion_status)
    if overdue is True:
        conditions.append("m.due_date IS NOT NULL")
        conditions.append("m.due_date < CURDATE()")
        conditions.append("m.completion_status = 'open'")
    if due_within_days is not None:
        conditions.append("m.due_date IS NOT NULL")
        conditions.append("m.due_date >= CURDATE()")
        conditions.append(
            f"m.due_date <= DATE_ADD(CURDATE(), INTERVAL {due_within_days} DAY)"
        )

    where = " AND ".join(conditions)
    sql = (
        f"SELECT m.*,"
        f" ms.source_kind, ms.doc_id AS ms_doc_id, ms.repo_id AS ms_repo_id,"
        f" ms.source_type, ms.source_path, ms.source_ref, ms.source_url"
        f" FROM memory m"
        f" LEFT JOIN memory_sources ms ON ms.memory_id = m.id"
        f" WHERE {where}"
        f" ORDER BY (m.sort_order IS NULL), m.sort_order ASC, m.created_at DESC,"
        f" ms.repo_id ASC, ms.source_path ASC, ms.id ASC"
    )

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    finally:
        conn.close()

    return _collapse_joined_sources(rows)


def fetch_supersede_graph(
    project_id: int,
    index_scope: ProjectIndexScope | None = None,
) -> List[Dict]:
    """supersede 관계에 참여하는 decision 행만 반환한다 (이력 체인 재구성용).

    search()는 LIMIT 없이 전 행 + memory_sources JOIN이라 이력 모드 전수 조회에
    부적합하다. 이 조회는 반환 행 수·전송량이 관계 참여 행 수에 비례한다
    (참여 행 = superseded_by가 채워진 행 + 다른 행이 가리키는 행).
    """
    scope = _resolve_scope(project_id, index_scope)
    visible_sql, visible_params = mysql_visibility_condition("m", scope)
    successor_visible_sql, successor_visible_params = mysql_visibility_condition(
        "visible_successor", scope
    )
    predecessor_visible_sql, predecessor_visible_params = mysql_visibility_condition(
        "visible_predecessor", scope
    )
    sql = (
        "SELECT m.id, m.project_id, m.category, m.content, m.reason, m.topic,"
        " m.owner, m.date, m.due_date, m.completed_at,"
        " m.completion_status, m.completion_status_source, m.source,"
        " visible_successor.id AS superseded_by,"
        " CASE WHEN visible_successor.id IS NULL"
        " THEN NULL ELSE m.superseded_at END AS superseded_at,"
        " ms.source_kind, ms.doc_id AS ms_doc_id, ms.repo_id AS ms_repo_id,"
        " ms.source_type, ms.source_path, ms.source_ref, ms.source_url"
        " FROM memory m"
        " LEFT JOIN memory visible_successor"
        " ON visible_successor.id=m.superseded_by"
        " AND visible_successor.project_id=m.project_id"
        f" AND {successor_visible_sql}"
        " LEFT JOIN memory_sources ms ON ms.memory_id = m.id"
        " WHERE m.project_id = %s"
        f" AND {visible_sql}"
        " AND m.category = 'decision'"
        " AND (visible_successor.id IS NOT NULL"
        " OR EXISTS (SELECT 1 FROM memory visible_predecessor"
        " WHERE visible_predecessor.project_id=m.project_id"
        " AND visible_predecessor.superseded_by=m.id"
        f" AND {predecessor_visible_sql}))"
        " ORDER BY m.id ASC, ms.repo_id ASC, ms.source_path ASC, ms.id ASC"
    )
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                sql,
                [
                    *successor_visible_params,
                    project_id,
                    *visible_params,
                    *predecessor_visible_params,
                ],
            )
            rows = cursor.fetchall()
    finally:
        conn.close()
    return _collapse_joined_sources(rows)
