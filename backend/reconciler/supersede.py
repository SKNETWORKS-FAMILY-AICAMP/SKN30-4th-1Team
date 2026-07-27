"""적재 시 supersede 판별기 — 신규 decision이 기존 decision을 번복(supersede)하는지
LLM으로 판정하고, 그 결과를 memory_suggestions에 pending 제안으로 저장한다.

pr_actions(complete_action)와 같은 human-in-the-loop 패턴: 자동 적용하지 않고,
사람이 accept해야 대상(구) decision의 superseded_by가 설정된다(계층1 필터 실효).
대상 범위는 decision 한정(action은 기존 reconciler가 담당).
"""
import json
import logging
from typing import Literal, Optional, TypedDict

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from ..db.mysql import get_connection
from ..llm.chat_model_factory import get_chat_model
from ..retriever.memory_vector import find_similar_memories

logger = logging.getLogger(__name__)

_CANDIDATE_N = 5  # 신규 decision 1건당 유사도 후보 검색 개수

SUPERSEDE_SYSTEM_PROMPT = """당신은 문서 적재 직후 실행되는 PaiM Supersede 판별기입니다.
목표는 이번에 새로 추출된 결정(decision)이 기존 결정을 '번복(supersede)'하는지 판정하는 것입니다.

정의:
- supersede = 새 결정이 기존 결정을 무효화/대체/변경한다(같은 주제에서 방침이 바뀜).
- 단순 재확인·중복(duplicate)이나 무관(unrelated)은 supersede가 아니다.

규칙:
- 매칭이 없으면 빈 배열을 반환하라 — 매칭 없음도 올바른 답이다.
- 정확도 > 재현율이다. 애매하면 보고하지 말 것.
- high = 두 결정이 같은 주제에서 명백히 상충하며 새 결정이 이전을 대체한다.
- medium = 강한 의미적 대응으로 대체 관계가 유력하다.
- high/medium이 아니면 보고하지 말 것. duplicate/unrelated는 보고하지 말 것.
- 각 매칭에 rationale을 한 문장 한국어로 작성하라.
- memory_id는 '번복당하는 기존 결정', superseding_memory_id는 '번복하는 새 결정'이다.
- 입력에 없는 id를 만들지 마라. superseding_memory_id는 신규 결정 목록에만, memory_id는 기존 결정 목록에만 있어야 한다.
- 시간 순서: 번복은 '더 나중의 결정이 더 이른 결정을 대체'하는 것이다. 신규 결정의 date가 기존 결정의
  date보다 앞서면(=과거 문서를 뒤늦게 적재한 경우) supersede로 보고하지 마라. date가 없으면 내용으로만 신중히 판단하라.
"""

_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SUPERSEDE_SYSTEM_PROMPT),
        (
            "human",
            "신규 결정 목록(JSON):\n{new_decisions}\n\n"
            "기존 결정 후보 목록(JSON):\n{candidates}\n\n"
            "반환값은 matches 배열만 포함하는 구조화 객체여야 한다.",
        ),
    ]
)


class NewDecision(BaseModel):
    """판별기에 전달하는 신규 decision 입력."""

    id: int
    content: str
    topic: Optional[str] = None
    reason: Optional[str] = None
    date: Optional[str] = None


class ExistingDecision(BaseModel):
    """판별기에 전달하는 기존 decision 후보 입력."""

    id: int
    content: str
    topic: Optional[str] = None
    reason: Optional[str] = None
    date: Optional[str] = None


class SupersedeMatch(BaseModel):
    """LLM이 반환하는 supersede 후보."""

    memory_id: int = Field(description="번복당하는 기존 decision memory.id")
    superseding_memory_id: int = Field(description="번복하는 신규 decision memory.id")
    rationale: str = Field(description="한 문장 한국어 근거")
    confidence: Literal["high", "medium"]


class SupersedeResult(BaseModel):
    """판별기 구조화 출력."""

    matches: list[SupersedeMatch] = Field(default_factory=list)


class SupersedeState(TypedDict, total=False):
    project_id: int
    new_decisions: list[dict]
    candidates: list[dict]
    result: SupersedeResult


def _json_for_prompt(value: list[BaseModel]) -> str:
    """Pydantic 입력을 프롬프트용 compact JSON 문자열로 변환한다."""
    return json.dumps([v.model_dump() for v in value], ensure_ascii=False, default=str)


def _coerce_result(value) -> SupersedeResult:
    """provider별 structured output 반환값을 SupersedeResult로 정규화하고 confidence를 필터한다."""
    if isinstance(value, SupersedeResult):
        result = value
    elif isinstance(value, dict):
        result = SupersedeResult.model_validate(value)
    else:
        result = SupersedeResult.model_validate(value.model_dump())
    return SupersedeResult(
        matches=[m for m in result.matches if m.confidence in {"high", "medium"}]
    )


def _invoke_supersede_once(
    new_decisions: list[NewDecision], candidates: list[ExistingDecision]
) -> SupersedeResult:
    """LLM을 1회 호출해 supersede 매칭을 구조화 출력으로 받는다.
    with_structured_output을 우선 사용하고, 실패 시 PydanticOutputParser로 재시도한다.
    """
    prompt_vars = {
        "new_decisions": _json_for_prompt(new_decisions),
        "candidates": _json_for_prompt(candidates),
    }
    messages = _PROMPT.format_messages(**prompt_vars)
    llm = get_chat_model()

    try:
        raw = llm.with_structured_output(SupersedeResult).invoke(messages)
        logger.info("supersede_structured_output_received")
        return _coerce_result(raw)
    except Exception:
        logger.warning("supersede_structured_output_fallback")

    parser = PydanticOutputParser(pydantic_object=SupersedeResult)
    fallback_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SUPERSEDE_SYSTEM_PROMPT),
            (
                "human",
                "신규 결정 목록(JSON):\n{new_decisions}\n\n"
                "기존 결정 후보 목록(JSON):\n{candidates}\n\n"
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
        logger.info("supersede_parser_output_received")
        try:
            return _coerce_result(parser.parse(text))
        except Exception as exc:
            error_text = str(exc)
    raise ValueError(f"Supersede 구조화 출력 파싱 실패: {error_text}")


def match_node(state: SupersedeState) -> dict:
    """LangGraph 노드: 신규 decision과 기존 후보를 한 번에 판정한다."""
    news = [NewDecision.model_validate(d) for d in state["new_decisions"]]
    cands = [ExistingDecision.model_validate(c) for c in state["candidates"]]
    return {"result": _invoke_supersede_once(news, cands)}


def build_supersede_graph():
    """pr_actions와 같은 방식의 얇은 LangGraph wrapper를 만든다."""
    graph = StateGraph(SupersedeState)
    graph.add_node("match", match_node)
    graph.add_edge(START, "match")
    graph.add_edge("match", END)
    return graph.compile()


_app = None


def run_supersede(
    project_id: int, new_decisions: list[dict], candidates: list[dict]
) -> SupersedeResult:
    """컴파일된 supersede 그래프를 재사용해 매칭 후보를 반환한다."""
    global _app
    if _app is None:
        _app = build_supersede_graph()
    out = _app.invoke(
        {"project_id": project_id, "new_decisions": new_decisions, "candidates": candidates}
    )
    return out["result"]


def _short_date(value) -> Optional[str]:
    """DB 날짜 값을 프롬프트용 YYYY-MM-DD 문자열로 줄인다."""
    return str(value)[:10] if value else None


def _fetch_candidate_decisions(project_id: int, ids: set[int]) -> list[dict]:
    """후보 id 중 아직 살아있는(superseded 안 된) decision만 LLM 입력으로 조회한다."""
    if not ids:
        return []
    placeholders = ", ".join(["%s"] * len(ids))
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, content, topic, reason, date FROM memory"
                " WHERE project_id = %s AND category = 'decision'"
                " AND superseded_by IS NULL"
                f" AND id IN ({placeholders})"
                " ORDER BY created_at DESC",
                (project_id, *ids),
            )
            rows = cursor.fetchall()
    finally:
        conn.close()
    return [
        {
            "id": row["id"],
            "content": row["content"] or "",
            "topic": row.get("topic") or None,
            "reason": row.get("reason") or None,
            "date": _short_date(row.get("date")),
        }
        for row in rows
        if row.get("content")
    ]


def _insert_supersede_suggestions(
    project_id: int,
    matches: list[SupersedeMatch],
    new_ids: set[int],
    candidate_ids: set[int],
    new_dates: Optional[dict] = None,
    candidate_dates: Optional[dict] = None,
) -> int:
    """supersede 매칭을 pending suggestion으로 저장한다.
    같은 (memory_id, superseding_memory_id) pending 증거는 중복 생성하지 않는다.
    시간순서 규칙(과거 결정이 미래 결정을 번복 못 함)은 프롬프트에만 맡기지 않고
    양쪽 날짜가 있으면 여기서 결정론적으로 강제한다.
    """
    new_dates = new_dates or {}
    candidate_dates = candidate_dates or {}
    created = 0
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            for match in matches:
                if (
                    match.memory_id not in candidate_ids
                    or match.superseding_memory_id not in new_ids
                    or match.memory_id == match.superseding_memory_id
                ):
                    logger.warning("supersede_invalid_match_skipped")
                    continue
                new_date = new_dates.get(match.superseding_memory_id)
                old_date = candidate_dates.get(match.memory_id)
                # 날짜 역전 차단: 신규(대체) decision이 기존 후보보다 과거 날짜면
                # LLM이 매칭을 반환해도 저장하지 않는다 — 과거 문서를 뒤늦게 적재했을 때
                # 최신 결정이 숨겨지는 것을 방지. (YYYY-MM-DD 문자열은 사전순 = 시간순)
                if new_date and old_date and str(new_date)[:10] < str(old_date)[:10]:
                    logger.warning(
                        "supersede date-inverted match skipped: new=%s(%s) old=%s(%s)",
                        match.superseding_memory_id, new_date, match.memory_id, old_date,
                    )
                    continue
                evidence = {
                    "type": "supersede",
                    "superseding_memory_id": match.superseding_memory_id,
                }
                cursor.execute(
                    """
                    INSERT INTO memory_suggestions
                        (project_id, memory_id, kind, evidence, rationale, confidence, status)
                    SELECT %s, %s, 'supersede', %s, %s, %s, 'pending'
                    FROM DUAL
                    WHERE NOT EXISTS (
                        SELECT 1 FROM memory_suggestions
                        WHERE memory_id = %s
                          AND kind = 'supersede'
                          AND status = 'pending'
                          AND CAST(JSON_UNQUOTE(JSON_EXTRACT(evidence, '$.superseding_memory_id')) AS UNSIGNED) = %s
                    )
                    """,
                    (
                        project_id,
                        match.memory_id,
                        json.dumps(evidence, ensure_ascii=False),
                        match.rationale,
                        match.confidence,
                        match.memory_id,
                        match.superseding_memory_id,
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


def detect_supersede(project_id: int, new_decisions: list[dict]) -> dict:
    """신규 decision 목록에 대해 supersede 후보를 판별하고 pending 제안을 저장한다.

    new_decisions: {id, content, topic, reason} dict 목록(category='decision'만).
    후보가 없거나 신규 decision이 없으면 LLM을 호출하지 않는다.
    """
    news = [d for d in new_decisions if (d.get("content") or "").strip()]
    if not news:
        return {"new_decisions": 0, "candidates": 0, "matches": 0, "created": 0}

    new_ids = {int(d["id"]) for d in news}
    candidate_ids: set[int] = set()
    for d in news:
        for mid in find_similar_memories(
            project_id, d["content"], category="decision", n_results=_CANDIDATE_N, exclude_ids=new_ids
        ):
            candidate_ids.add(mid)
    candidate_ids -= new_ids

    candidates = _fetch_candidate_decisions(project_id, candidate_ids)
    if not candidates:
        logger.info(
            "supersede skipped LLM call: no live candidates project_id=%s new=%s",
            project_id,
            len(news),
        )
        return {"new_decisions": len(news), "candidates": 0, "matches": 0, "created": 0}

    result = run_supersede(project_id, news, candidates)
    created = _insert_supersede_suggestions(
        project_id,
        result.matches,
        new_ids,
        {int(c["id"]) for c in candidates},
        new_dates={int(d["id"]): d.get("date") for d in news},
        candidate_dates={int(c["id"]): c.get("date") for c in candidates},
    )
    return {
        "new_decisions": len(news),
        "candidates": len(candidates),
        "matches": len(result.matches),
        "created": created,
    }
