import json
import logging
from typing import Literal, Optional, TypedDict

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from ..db.mysql import get_connection
from ..llm.chat_model_factory import get_chat_model

logger = logging.getLogger(__name__)

RECONCILER_SYSTEM_PROMPT = """당신은 repo sync 직후 실행되는 PaiM Reconciler입니다.
목표는 이번 sync에서 새로 들어온 머지 PR이 Project Memory의 열린 액션을 완료했는지 판정하는 것입니다.

규칙:
- 매칭이 없으면 빈 배열을 반환하라 — 매칭 없음도 올바른 답이다.
- 정확도 > 재현율이다. 애매하면 보고하지 말 것.
- high = PR이 액션 내용을 명시적으로 수행/언급한다.
- medium = PR 제목/본문 요약과 액션 사이에 강한 의미적 대응이 있다.
- high/medium이 아니면 보고하지 말 것.
- 각 매칭에는 rationale을 한 문장 한국어로 작성하라.
- 하나의 PR이 여러 액션을 해결할 수 있고, 하나의 액션에 여러 PR을 매칭할 수 있다.
- 입력에 없는 memory_id 또는 PR number를 만들지 마라.
"""

_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", RECONCILER_SYSTEM_PROMPT),
        (
            "human",
            "머지된 PR 목록(JSON):\n{prs}\n\n"
            "열린 액션 목록(JSON):\n{actions}\n\n"
            "반환값은 matches 배열만 포함하는 구조화 객체여야 한다.",
        ),
    ]
)


class MergedPullRequest(BaseModel):
    """Reconciler에 전달하는 머지 PR 입력."""

    number: int
    title: str
    body_summary: str = ""
    url: str = ""
    merged_at: str = ""


class OpenAction(BaseModel):
    """Reconciler에 전달하는 열린 action 입력."""

    id: int
    content: str
    owner: Optional[str] = None
    due_date: Optional[str] = None


class ActionCompletionMatch(BaseModel):
    """LLM이 반환하는 PR→action 완료 후보."""

    memory_id: int = Field(description="완료된 것으로 보이는 action memory.id")
    pr_number: int = Field(description="근거가 된 merged PR number")
    rationale: str = Field(description="한 문장 한국어 근거")
    confidence: Literal["high", "medium"]


class ReconcileResult(BaseModel):
    """Reconciler 구조화 출력."""

    matches: list[ActionCompletionMatch] = Field(default_factory=list)


class ReconcilerState(TypedDict, total=False):
    project_id: int
    prs: list[dict]
    actions: list[dict]
    result: ReconcileResult


def _json_for_prompt(value: list[BaseModel]) -> str:
    """Pydantic 입력을 프롬프트에 넣을 compact JSON 문자열로 변환한다."""
    return json.dumps([v.model_dump() for v in value], ensure_ascii=False, default=str)


def _coerce_result(value) -> ReconcileResult:
    """LangChain provider별 structured output 반환값을 ReconcileResult로 정규화한다."""
    if isinstance(value, ReconcileResult):
        result = value
    elif isinstance(value, dict):
        result = ReconcileResult.model_validate(value)
    else:
        result = ReconcileResult.model_validate(value.model_dump())
    return ReconcileResult(
        matches=[m for m in result.matches if m.confidence in {"high", "medium"}]
    )


def _invoke_reconciler_once(prs: list[MergedPullRequest], actions: list[OpenAction]) -> ReconcileResult:
    """LLM을 1회 호출해 전체 PR/action 매칭을 구조화 출력으로 받는다.
    with_structured_output을 우선 사용하고, 지원 실패 시 PydanticOutputParser로 1회 재시도한다.
    """
    prompt_vars = {"prs": _json_for_prompt(prs), "actions": _json_for_prompt(actions)}
    messages = _PROMPT.format_messages(**prompt_vars)
    llm = get_chat_model()

    try:
        raw = llm.with_structured_output(ReconcileResult).invoke(messages)
        logger.info("reconciler_structured_output_received")
        return _coerce_result(raw)
    except Exception:
        logger.warning("reconciler_structured_output_fallback")

    parser = PydanticOutputParser(pydantic_object=ReconcileResult)
    fallback_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", RECONCILER_SYSTEM_PROMPT),
            (
                "human",
                "머지된 PR 목록(JSON):\n{prs}\n\n"
                "열린 액션 목록(JSON):\n{actions}\n\n"
                "{format_instructions}\n\n"
                "이전 오류: {error}",
            ),
        ]
    )
    error_text = ""
    for _ in range(2):
        text = llm.invoke(
            fallback_prompt.format_messages(
                **prompt_vars,
                format_instructions=parser.get_format_instructions(),
                error=error_text or "(없음)",
            )
        ).content
        logger.info("reconciler_parser_output_received")
        try:
            return _coerce_result(parser.parse(text))
        except Exception as exc:
            error_text = str(exc)
    raise ValueError(f"Reconciler 구조화 출력 파싱 실패: {error_text}")


def _invoke_reconciler(prs: list[MergedPullRequest], actions: list[OpenAction]) -> ReconcileResult:
    """매칭 0건이면 같은 입력으로 1회만 재호출한다."""
    result = _invoke_reconciler_once(prs, actions)
    if not result.matches and prs and actions:
        logger.info(
            "reconciler empty result; retrying once prs=%s actions=%s",
            len(prs),
            len(actions),
        )
        return _invoke_reconciler_once(prs, actions)
    return result


def match_node(state: ReconcilerState) -> dict:
    """LangGraph 노드: 이번 sync의 PR 목록과 열린 action 목록을 한 번에 판정한다."""
    prs = [MergedPullRequest.model_validate(pr) for pr in state["prs"]]
    actions = [OpenAction.model_validate(action) for action in state["actions"]]
    return {"result": _invoke_reconciler(prs, actions)}


def build_reconciler_graph():
    """노드 연결만 담당하는 얇은 LangGraph wrapper를 만든다."""
    graph = StateGraph(ReconcilerState)
    graph.add_node("match", match_node)
    graph.add_edge(START, "match")
    graph.add_edge("match", END)
    return graph.compile()


_app = None


def run_reconciler(project_id: int, prs: list[dict], actions: list[dict]) -> ReconcileResult:
    """컴파일된 Reconciler 그래프를 재사용해 PR→action 후보를 반환한다."""
    global _app
    if _app is None:
        _app = build_reconciler_graph()
    out = _app.invoke({"project_id": project_id, "prs": prs, "actions": actions})
    return out["result"]


def _short_date(value) -> Optional[str]:
    """DB 날짜 값을 프롬프트용 YYYY-MM-DD 문자열로 줄인다."""
    return str(value)[:10] if value else None


def _fetch_open_actions(project_id: int) -> list[dict]:
    """프로젝트의 미완료 action만 Reconciler 입력으로 조회한다."""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, content, owner, due_date FROM memory"
                " WHERE project_id = %s AND category = 'action'"
                " AND completion_status = 'open'"
                " ORDER BY created_at DESC",
                (project_id,),
            )
            rows = cursor.fetchall()
    finally:
        conn.close()
    return [
        {
            "id": row["id"],
            "content": row["content"] or "",
            "owner": row.get("owner") or None,
            "due_date": _short_date(row.get("due_date")),
        }
        for row in rows
        if row.get("content")
    ]


def _advance_watermark(repo_id: int, pr_number: int) -> None:
    """성공적으로 판정한 최대 PR 번호를 repositories 워터마크에 반영한다."""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE repositories"
                " SET last_reconciled_pr = GREATEST(COALESCE(last_reconciled_pr, 0), %s)"
                " WHERE id = %s",
                (pr_number, repo_id),
            )
        conn.commit()
    finally:
        conn.close()


def _insert_suggestions(
    project_id: int,
    matches: list[ActionCompletionMatch],
    prs: list[dict],
    action_ids: set[int],
) -> int:
    """high/medium 매칭을 pending suggestion으로 저장한다. 같은 pending PR 증거는 중복 생성하지 않는다."""
    pr_by_number = {int(pr["number"]): pr for pr in prs}
    created = 0
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            for match in matches:
                if match.memory_id not in action_ids or match.pr_number not in pr_by_number:
                    logger.warning("reconciler_invalid_match_skipped")
                    continue
                pr = pr_by_number[match.pr_number]
                evidence = {
                    "type": "pr",
                    "number": pr["number"],
                    "title": pr.get("title", ""),
                    "url": pr.get("url", ""),
                    "merged_at": pr.get("merged_at", ""),
                }
                cursor.execute(
                    """
                    INSERT INTO memory_suggestions
                        (project_id, memory_id, kind, evidence, rationale, confidence, status)
                    SELECT %s, %s, 'complete_action', %s, %s, %s, 'pending'
                    FROM DUAL
                    WHERE NOT EXISTS (
                        SELECT 1 FROM memory_suggestions
                        WHERE memory_id = %s
                          AND kind = 'complete_action'
                          AND status = 'pending'
                          AND CAST(JSON_UNQUOTE(JSON_EXTRACT(evidence, '$.number')) AS UNSIGNED) = %s
                    )
                    """,
                    (
                        project_id,
                        match.memory_id,
                        json.dumps(evidence, ensure_ascii=False),
                        match.rationale,
                        match.confidence,
                        match.memory_id,
                        match.pr_number,
                    ),
                )
                created += max(cursor.rowcount, 0)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return created


def reconcile_repository_prs(project_id: int, repo_id: int, prs: list[dict]) -> dict:
    """repo sync가 넘긴 merged PR 목록을 열린 action과 대조하고 suggestion을 저장한다."""
    if not prs:
        return {"prs": 0, "actions": 0, "matches": 0, "created": 0}

    actions = _fetch_open_actions(project_id)
    matches: list[ActionCompletionMatch] = []
    created = 0
    if actions:
        result = run_reconciler(project_id, prs, actions)
        matches = result.matches
        created = _insert_suggestions(
            project_id,
            matches,
            prs,
            {int(action["id"]) for action in actions},
        )
    else:
        logger.info("reconciler skipped LLM call: no open actions project_id=%s", project_id)

    max_pr = max(int(pr["number"]) for pr in prs)
    _advance_watermark(repo_id, max_pr)
    return {
        "prs": len(prs),
        "actions": len(actions),
        "matches": len(matches),
        "created": created,
        "last_reconciled_pr": max_pr,
    }
