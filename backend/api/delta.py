import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from ..db.mysql import get_connection
from ..llm.chat_model_factory import get_chat_model
from .auth import require_project_access

router = APIRouter()

_CATEGORIES = ("decision", "action", "issue", "risk")
_NO_DELTA_ANSWER = "지난 확인 이후 새 변화가 없습니다."

DELTA_BRIEFING_SYSTEM_PROMPT = """당신은 PaiM의 델타 브리핑 작성자입니다.
사용자는 프로젝트를 다시 열었고, 지난 확인 이후 무엇이 달라졌는지 빠르게 알고 싶어합니다.

작성 규칙:
- 한국어로 작성한다.
- 스탠드업 대체 브리핑 톤으로 짧고 구체적으로 쓴다.
- 반드시 다음 순서를 지킨다:
  1. 무엇이 진행됐는가: 완료된 액션과 새 완료 제안을 먼저 요약한다.
  2. 무엇이 새로 생겼는가: 새 decision/action/issue/risk를 카테고리별로 묶어 요약한다.
  3. 무엇이 급한가: 마감 임박과 기한 초과 액션을 담당자와 날짜 중심으로 정리한다.
- 입력 JSON에 없는 사실을 만들지 않는다.
- 내용이 없는 섹션은 한 줄로 '없음'이라고 쓴다.
- 8문장 이내로 답한다.
- 첫 줄은 지난 확인 이후 변화에 대한 한 문장 직답으로 쓰고, 핵심 결론은 **굵게** 표시한다.
- 이후에는 **진행**, **신규**, **긴급** 순서의 짧은 소제목 또는 불릿으로 정리한다.
- 항목이 많으면 Markdown 표를 사용하되, 한두 문장으로 충분하면 목록을 과하게 늘리지 않는다.
"""

_DELTA_BRIEFING_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", DELTA_BRIEFING_SYSTEM_PROMPT),
        ("human", "델타 집계와 신규 메모리 JSON:\n{context}"),
    ]
)
_delta_briefing_chain = None


class DeltaBriefingRequest(BaseModel):
    since: str


def _parse_since(value: str) -> tuple[str, str]:
    """ISO8601 since를 검증하고 MySQL DATETIME 비교용 문자열로 바꾼다."""
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="since must be ISO8601")
    if parsed.tzinfo:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return raw, parsed.strftime("%Y-%m-%d %H:%M:%S")


def _project_or_404(cursor, project_id: int) -> None:
    """프로젝트 존재 여부를 확인한다."""
    cursor.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Project not found")


def _action_rows(rows: list[dict]) -> list[dict]:
    """action row를 API 응답에 필요한 필드만 남긴다."""
    return [
        {
            "id": row["id"],
            "content": row["content"],
            "owner": row.get("owner"),
            "due_date": row["due_date"].isoformat()
            if hasattr(row.get("due_date"), "isoformat")
            else row.get("due_date"),
        }
        for row in rows
    ]


def _load_delta(cursor, project_id: int, since_sql: str, due_within_days: int = 3) -> dict:
    """LLM 없이 SQL 집계만으로 델타 배너 데이터를 만든다."""
    # K-002: 델타의 memory 조회는 전부 active_memory 뷰를 읽는다 — since 이후 생성됐다가
    # 이미 번복(supersede)된 결정이 신규 건수·브리핑 입력에 재노출되지 않도록.
    cursor.execute(
        "SELECT category, COUNT(*) AS cnt FROM active_memory"
        " WHERE project_id = %s AND created_at > %s"
        " GROUP BY category",
        (project_id, since_sql),
    )
    new_memory = {category: 0 for category in _CATEGORIES}
    for row in cursor.fetchall():
        if row["category"] in new_memory:
            new_memory[row["category"]] = int(row["cnt"])

    # 레거시 필드 pending_suggestions는 GET /suggestions 기본 목록(kind=complete_action)과
    # 의미를 맞춰 complete_action만 센다 — kind를 모르는 구 클라이언트가 "제안 N건" 배너를
    # 띄우고 빈 인박스를 여는 유령 카운트 방지. 전체는 pending_suggestions_by_kind로 제공
    # (신규 필드 추가라 구 클라이언트에 무해).
    cursor.execute(
        "SELECT s.kind,COUNT(*) AS cnt FROM memory_suggestions s"
        " JOIN active_memory target"
        "  ON target.id=s.memory_id AND target.project_id=s.project_id"
        " LEFT JOIN active_memory superseding"
        "  ON s.kind='supersede'"
        "  AND superseding.project_id=s.project_id"
        "  AND superseding.id=CAST(JSON_UNQUOTE(JSON_EXTRACT("
        "s.evidence, '$.superseding_memory_id')) AS UNSIGNED)"
        " WHERE s.project_id = %s AND s.status = 'pending' AND s.created_at > %s"
        " AND (s.kind<>'supersede' OR superseding.id IS NOT NULL)"
        " GROUP BY s.kind",
        (project_id, since_sql),
    )
    pending_by_kind = {row["kind"]: int(row["cnt"]) for row in cursor.fetchall()}
    pending_suggestions = pending_by_kind.get("complete_action", 0)

    cursor.execute(
        "SELECT COUNT(*) AS cnt FROM active_memory"
        " WHERE project_id = %s AND category = 'action'"
        " AND completion_status = 'completed' AND completed_at > %s",
        (project_id, since_sql),
    )
    completed_actions = int((cursor.fetchone() or {}).get("cnt") or 0)

    cursor.execute(
        "SELECT id, content, owner, due_date FROM active_memory"
        " WHERE project_id = %s AND category = 'action' AND completion_status = 'open'"
        " AND due_date IS NOT NULL"
        " AND due_date >= CURDATE()"
        " AND due_date <= DATE_ADD(CURDATE(), INTERVAL %s DAY)"
        " ORDER BY due_date ASC, id ASC",
        (project_id, due_within_days),
    )
    due_soon = _action_rows(cursor.fetchall())

    cursor.execute(
        "SELECT id, content, owner, due_date FROM active_memory"
        " WHERE project_id = %s AND category = 'action' AND completion_status = 'open'"
        " AND due_date IS NOT NULL AND due_date < CURDATE()"
        " ORDER BY due_date ASC, id ASC",
        (project_id,),
    )
    overdue = _action_rows(cursor.fetchall())

    return {
        "new_memory": new_memory,
        "pending_suggestions": pending_suggestions,
        "pending_suggestions_by_kind": pending_by_kind,
        "completed_actions": completed_actions,
        "due_soon": due_soon,
        "overdue": overdue,
    }


def _load_new_memory_items(cursor, project_id: int, since_sql: str) -> list[dict]:
    """델타 브리핑에 직접 넣을 신규 memory row를 조회한다."""
    cursor.execute(
        "SELECT id, category, content, reason, topic, owner, date, due_date,"
        " source, created_by, completed_at, completion_status,"
        " completion_status_source, created_at"
        " FROM active_memory WHERE project_id = %s AND created_at > %s"
        " ORDER BY created_at ASC, id ASC",
        (project_id, since_sql),
    )
    return cursor.fetchall()


def _has_delta_content(delta: dict) -> bool:
    """브리핑할 내용이 있는지 확인한다."""
    return (
        sum(delta["new_memory"].values())
        + delta["pending_suggestions"]
        + delta["completed_actions"]
        + len(delta["due_soon"])
        + len(delta["overdue"])
    ) > 0


def _get_delta_briefing_chain():
    """기존 LCEL 패턴으로 델타 브리핑 체인을 lazy 생성한다."""
    global _delta_briefing_chain
    if _delta_briefing_chain is None:
        _delta_briefing_chain = _DELTA_BRIEFING_PROMPT | get_chat_model() | StrOutputParser()
    return _delta_briefing_chain


@router.get("/projects/{project_id}/delta")
def get_project_delta(project_id: int, since: str, due_within_days: int = Query(3, ge=1, le=7)):
    require_project_access(project_id)
    since_raw, since_sql = _parse_since(since)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            _project_or_404(cursor, project_id)
            delta = _load_delta(cursor, project_id, since_sql, due_within_days)
    finally:
        conn.close()
    return {"since": since_raw, **delta}


@router.post("/projects/{project_id}/briefing/delta")
def create_delta_briefing(project_id: int, body: DeltaBriefingRequest):
    require_project_access(project_id, min_role="member")
    since_raw, since_sql = _parse_since(body.since)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            _project_or_404(cursor, project_id)
            delta = _load_delta(cursor, project_id, since_sql)
            if not _has_delta_content(delta):
                return {"answer": _NO_DELTA_ANSWER, "sources": []}
            new_memory_items = _load_new_memory_items(cursor, project_id, since_sql)
    finally:
        conn.close()

    context = json.dumps(
        {
            "since": since_raw,
            "delta": delta,
            "new_memory_items": new_memory_items,
        },
        ensure_ascii=False,
        default=str,
    )
    answer = _get_delta_briefing_chain().invoke({"context": context})
    return {"answer": answer, "sources": []}
