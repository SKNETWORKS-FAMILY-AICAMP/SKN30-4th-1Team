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
    if completed is not None:
        legacy_status = "completed" if completed else "open"
        if completion_status not in (None, legacy_status):
            raise ValueError("completed and completion_status conflict")
        completion_status = legacy_status
    if completion_status not in (None, "open", "completed", "unknown"):
        raise ValueError("completion_status must be open, completed, or unknown")

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
        days = max(0, min(int(due_within_days), 365))
        conditions.append("m.due_date IS NOT NULL")
        conditions.append("m.due_date >= CURDATE()")
        conditions.append(f"m.due_date <= DATE_ADD(CURDATE(), INTERVAL {days} DAY)")

    where = " AND ".join(conditions)
    sql = (
        f"SELECT m.*,"
        f" ms.source_kind, ms.doc_id AS ms_doc_id, ms.repo_id AS ms_repo_id,"
        f" ms.source_type, ms.source_path, ms.source_ref, ms.source_url"
        f" FROM memory m"
        f" LEFT JOIN memory_sources ms ON ms.memory_id = m.id"
        f" WHERE {where}"
        f" ORDER BY (m.sort_order IS NULL), m.sort_order ASC, m.created_at DESC"
    )

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    finally:
        conn.close()

    result = []
    for row in rows:
        row["source_info"] = {
            "kind":    row.pop("source_kind", None),
            "doc_id":  row.pop("ms_doc_id", None),
            "repo_id": row.pop("ms_repo_id", None),
            "type":    row.pop("source_type", None),
            "path":    row.pop("source_path", None),
            "ref":     row.pop("source_ref", None),
            "url":     row.pop("source_url", None),
        }
        result.append(row)
    return result


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
        " ORDER BY m.id ASC"
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
    # 체인 행에도 source_info(repo_id·path)를 실어 충돌 없는 출처 라벨(repo#N)을
    # 만들 수 있게 한다(리뷰 C-002) — search()와 동일 형식.
    for row in rows:
        row["source_info"] = {
            "kind":    row.pop("source_kind", None),
            "doc_id":  row.pop("ms_doc_id", None),
            "repo_id": row.pop("ms_repo_id", None),
            "type":    row.pop("source_type", None),
            "path":    row.pop("source_path", None),
            "ref":     row.pop("source_ref", None),
            "url":     row.pop("source_url", None),
        }
    return rows
