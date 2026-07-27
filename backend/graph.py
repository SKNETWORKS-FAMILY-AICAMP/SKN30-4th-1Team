# PaiM LangGraph 오케스트레이션 (입력/출력 분리)
#
# 설계 원칙(유지보수):
#  - State(TypedDict)를 노드 간 "계약"으로 고정 → 노드 내부를 바꿔도 서로 안 깨짐
#  - 노드는 "얇은 래퍼": 실제 로직은 pipeline/retriever 모듈에 두고 재사용(중복 0)
#  - 분기는 named 라우팅 함수로 → 흐름 변경이 국소적
#  - 기존 qa_engine.py(LangChain)는 손대지 않고 부품으로만 사용
#
# 그래프 2개:
#  1) 입력(적재): 문서 → [저장] → [메모리] → END
#  2) 출력(질의): 질문 → [섹션(stub)] → [Q&A] → [검증] → (부족: 재검색 루프)
#                        → [계획] → [검증] → (부족: 재기획 루프) → [응답] → END
import asyncio
from typing import TypedDict, Optional, List, Dict
import logging

from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import StateGraph, START, END

from .db.mysql import get_connection
from .pipeline.extractor import extract
from .pipeline.ingestor import ingest
from .retriever import history_intent, qa_engine
from .llm.chat_model_factory import get_chat_model
from .quota import (
    cleanup_failed_reservation,
    compensate_cancelled_document,
    delete_document as quota_delete_document,
    fail_document,
    finalize_document,
    reserve_document,
)

MAX_RETRY = 1  # 재검색/재기획 최대 반복 (무한 루프 방지)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Project Memory 저장소 (provisional)
# ponytail: 프로젝트 단위 요약을 담을 최소 테이블. schema.sql은 건드리지 않고
#           CREATE TABLE IF NOT EXISTS로 additive-safe 하게 둔다. 정식 채택 시 A와 스키마 합의.
# ─────────────────────────────────────────────────────────────
_MEMORY_DDL = """
CREATE TABLE IF NOT EXISTS project_memory (
    project_id INT PRIMARY KEY,
    summary    TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
)
"""


def get_project_memory(project_id: int) -> str:
    """프로젝트의 응축 요약을 반환. 없으면 빈 문자열."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_MEMORY_DDL)
            cur.execute("SELECT summary FROM project_memory WHERE project_id = %s", (project_id,))
            row = cur.fetchone()
        conn.commit()
        return row["summary"] if row and row.get("summary") else ""
    finally:
        conn.close()


def upsert_project_memory(project_id: int, summary: str) -> None:
    """프로젝트 요약을 갱신(없으면 삽입)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_MEMORY_DDL)
            cur.execute(
                "INSERT INTO project_memory (project_id, summary) VALUES (%s, %s) "
                "ON DUPLICATE KEY UPDATE summary = VALUES(summary)",
                (project_id, summary),
            )
        conn.commit()
    finally:
        conn.close()


def delete_project_memory(project_id: int) -> None:
    """프로젝트 응축 요약 캐시를 삭제한다."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM project_memory WHERE project_id = %s", (project_id,))
        conn.commit()
    finally:
        conn.close()


def _format_summary_memory_row(row: dict) -> str:
    """남은 memory row를 재요약 프롬프트용 한 줄로 만든다."""
    meta = []
    if row.get("owner"):
        meta.append(f"담당: {row['owner']}")
    if row.get("due_date"):
        meta.append(f"마감: {str(row['due_date'])[:10]}")
    if row.get("category") == "action":
        status = row.get("completion_status") or (
            "completed" if row.get("completed_at") else "unknown"
        )
        if status == "completed":
            meta.append(
                f"완료: {str(row['completed_at'])[:10]}"
                if row.get("completed_at") else "완료"
            )
        elif status == "open":
            meta.append("미완료")
        else:
            meta.append("완료 여부 미확인")
    meta_text = f" ({', '.join(meta)})" if meta else ""
    return f"[{row['category']}] {row['content']}{meta_text}"


def regenerate_project_memory(project_id: int) -> str:
    """현재 유효한 memory row만 기준으로 프로젝트 요약 캐시를 재생성한다.

    active_memory 뷰를 읽으므로 번복(superseded)된 결정은 요약에 들어가지 않는다.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT category, content, owner, due_date, completed_at, completion_status"
                " FROM active_memory WHERE project_id = %s"
                " ORDER BY (sort_order IS NULL), sort_order ASC, created_at ASC",
                (project_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        delete_project_memory(project_id)
        return ""

    memory_lines = "\n".join(_format_summary_memory_row(row) for row in rows)
    llm = get_chat_model(tier="quality")
    prompt = (
        "다음은 현재 프로젝트에 남아 있는 memory 항목 전체이다. "
        "삭제된 항목은 절대 추측하거나 포함하지 말고, 남은 항목만 근거로 "
        "핵심 결정·진행·이슈·리스크가 드러나도록 5문장 이내의 갱신 요약을 한국어로 작성하라.\n\n"
        f"[남은 항목]\n{memory_lines}"
    )
    summary = llm.invoke(prompt).content
    upsert_project_memory(project_id, summary)
    return summary


def refresh_project_memory_after_delete(project_id: int) -> None:
    """삭제 후 요약 캐시를 best-effort로 정합화한다. 실패해도 삭제는 유지한다."""
    try:
        regenerate_project_memory(project_id)
    except Exception:
        logger.warning("project_memory refresh after delete failed project_id=%s", project_id, exc_info=True)


# ═════════════════════════════════════════════════════════════
# 1) 입력 그래프 (적재)
# ═════════════════════════════════════════════════════════════
class IngestState(TypedDict, total=False):
    # 입력 계약
    project_id: int
    filename: str
    content: str
    doc_type: str
    date: str
    uploaded_by: int
    # 노드가 채우는 값
    doc_id: int
    items: list
    project_summary: str


def store_node(state: IngestState) -> dict:
    """저장 에이전트: document 행 생성 → LLM 추출 → MySQL+Chroma 적재.
    로직은 기존 extract()/ingest() 재사용."""
    doc_type = state.get("doc_type", "meeting")
    uploaded_by = state.get("uploaded_by")
    if not isinstance(uploaded_by, int) or uploaded_by <= 0:
        raise RuntimeError("UPLOAD_USER_REQUIRED")
    reservation = reserve_document(
        state["project_id"], uploaded_by, len(state["content"].encode("utf-8")), "virtual"
    )
    try:
        finalized = finalize_document(reservation["reservation_id"], state["filename"], doc_type)
    except BaseException:
        cleanup_failed_reservation(reservation["reservation_id"])
        raise
    doc_id = finalized["doc_id"]
    try:
        items = extract(state["content"], default_source=state["filename"])
        ingest(
            project_id=state["project_id"], doc_id=doc_id, items=items,
            raw_text=state["content"], source=state["filename"],
            date=state.get("date", ""), doc_type=doc_type,
            processing_token=finalized["processing_token"],
        )
    except asyncio.CancelledError:
        compensate_cancelled_document(doc_id)
        raise
    except Exception:
        logger.error(
            "graph_ingest_failed",
            extra={"project_id": state["project_id"], "code": "GRAPH_INGEST_FAILED"},
        )
        fail_document(doc_id, "GRAPH_INGEST_FAILED")
        raise
    for old_doc_id in finalized["old_doc_ids"]:
        quota_delete_document(old_doc_id)
    return {"doc_id": doc_id, "items": items}


def update_project_memory(project_id: int, items: list) -> str:
    """적재 성공 후 호출하는 재사용 함수.
    기존 프로젝트 요약과 이번에 새로 추출된 항목(items)을 LLM으로 응축해
    프로젝트 요약을 갱신하고, 갱신된 요약 문자열을 반환한다.

    주의(best-effort): 이 함수는 실패 시 예외를 던진다. 업로드 흐름에서 호출하는 쪽이
    try/except로 감싸, 요약 실패가 업로드 자체를 실패로 만들지 않도록 처리해야 한다.
    """
    prev = get_project_memory(project_id)
    if not items:
        return prev
    new_items = "\n".join(f"[{it.category}] {it.content}" for it in items)
    llm = get_chat_model()
    prompt = (
        "다음은 프로젝트의 기존 요약과 새로 추가된 항목이다. "
        "핵심 결정·진행·이슈·리스크가 드러나도록 5문장 이내의 갱신 요약을 한국어로 작성하라.\n\n"
        f"[기존 요약]\n{prev or '(없음)'}\n\n[새 항목]\n{new_items or '(없음)'}"
    )
    summary = llm.invoke(prompt).content
    upsert_project_memory(project_id, summary)
    return summary


def memory_node(state: IngestState) -> dict:
    """메모리 에이전트: 재사용 함수(update_project_memory)로 프로젝트 요약 갱신."""
    summary = update_project_memory(state["project_id"], state.get("items", []))
    return {"project_summary": summary}


def build_ingest_graph():
    g = StateGraph(IngestState)
    g.add_node("store", store_node)
    g.add_node("memory", memory_node)
    g.add_edge(START, "store")
    g.add_edge("store", "memory")
    g.add_edge("memory", END)
    return g.compile()


# ═════════════════════════════════════════════════════════════
# 2) 출력 그래프 (질의)
# ═════════════════════════════════════════════════════════════
class QAState(TypedDict, total=False):
    # 입력 계약
    project_id: int
    question: str
    history: list
    attachment_context: str
    attachment_sources: list
    # 이력 모드 (run_qa 진입 시 1회 계산 후 불변 — rewrite_node가 question에
    # 제어용 suffix를 붙여도 체인 선택 판정이 뒤집히지 않도록 상태에 고정한다)
    history_mode: bool
    history_scope: Optional[str]       # "topical" | "global" | None(비이력)
    history_topic_tokens: List[str]
    # 노드가 채우는 값
    section: Optional[str]
    answer: str
    sources: list
    debug: dict
    answer_ok: bool
    plan: list
    plan_ok: bool
    qa_retries: int
    plan_retries: int
    result: dict


def section_node(state: QAState) -> dict:
    """섹션 매니저 (stub): 섹션 정의 확정 전까지 통과.
    ponytail: 섹션(project/도메인) 정의되면 여기서 스코프/필터 결정하도록 확장."""
    return {"section": None}


def qa_node(state: QAState) -> dict:
    """Q&A 에이전트: 하이브리드 검색 + LangChain 생성 (qa_engine 부품 재사용).
    Project Memory 요약을 컨텍스트 앞에 얹어 프로젝트 맥락을 보강한다(입력↔출력 다리)."""
    pid, q = state["project_id"], state["question"]
    # 검색 질의는 (재작성될 수 있는) question을 쓰고, 체인 선택 판정은
    # run_qa 진입 시 고정된 predicate·주제 토큰을 쓴다.
    context, sources, debug = qa_engine._build_context(
        pid, q,
        history_mode=state.get("history_mode", False),
        history_scope=state.get("history_scope"),
        history_topic_tokens=state.get("history_topic_tokens") or [],
    )

    parts = []
    if state.get("attachment_context"):
        parts.append(state["attachment_context"])

    mem = get_project_memory(pid)
    if mem:
        parts.append(f"[프로젝트 메모리]\n{mem}")
    if context:
        parts.append(context)
    context = "\n\n".join(parts)

    for source in state.get("attachment_sources") or []:
        if source not in sources:
            sources.insert(0, source)
    if state.get("attachment_sources"):
        debug["attachments"] = state["attachment_sources"]

    # 대화 히스토리를 LangChain 메시지로 변환 (qa_engine.answer와 동일 규칙)
    hist_msgs = []
    for m in (state.get("history") or [])[-qa_engine.MAX_HISTORY:]:
        if m.get("role") == "assistant":
            hist_msgs.append(AIMessage(content=m["content"]))
        else:
            hist_msgs.append(HumanMessage(content=m["content"]))

    answer_text = qa_engine._get_chain().invoke(
        {"history": hist_msgs, "context": context, "question": q}
    )
    return {"answer": answer_text, "sources": sources, "debug": debug}


def verify_answer_node(state: QAState) -> dict:
    """검증(휴리스틱): 컨텍스트가 있었고 답변이 '확인 안 됨'류가 아니면 통과.
    ponytail: 휴리스틱. 정확도 필요 시 LLM 판정으로 교체(같은 위치)."""
    debug = state.get("debug", {})
    has_ctx = (
        bool(debug.get("attachments"))
        or bool(debug.get("mysql_rows"))
        or bool(debug.get("chroma_chunks"))
    )
    ans = state.get("answer", "")
    refused = ("확인되지 않" in ans) or ("확인할 수 없" in ans)
    return {"answer_ok": has_ctx and not refused}


def rewrite_node(state: QAState) -> dict:
    """재검색: 질문을 넓혀 다시 검색하도록 힌트를 붙이고 qa_retries 증가.
    ponytail: 단순 질의 확장(휴리스틱). 품질 필요 시 LLM 재작성으로 교체."""
    q = state["question"]
    if "관련 배경" not in q:
        q = f"{q} (관련 배경과 세부 내용 포함)"
    return {"question": q, "qa_retries": state.get("qa_retries", 0) + 1}


def route_after_answer(state: QAState) -> str:
    """검증1 분기: 충분/상한이면 계획으로, 아니면 재검색."""
    if state.get("answer_ok") or state.get("qa_retries", 0) >= MAX_RETRY:
        return "plan"
    return "rewrite"


def plan_node(state: QAState) -> dict:
    """계획 에이전트: 답변을 근거로 다음 할 일(todo) 목록 기획.
    best-effort: plan 생성용 LLM 호출이 실패해도 빈 plan을 반환한다. plan은 부가기능이므로,
    실패가 그래프 전체를 죽여 이미 생성된 답변까지 잃게 만들면 안 된다."""
    llm = get_chat_model()
    prompt = (
        "아래 답변을 근거로 프로젝트에서 다음에 해야 할 구체적 todo를 3개 이내로 제안하라. "
        "각 줄을 '- '로 시작하는 한 줄 액션으로만 작성하고, 근거가 부족하면 아무것도 쓰지 마라.\n\n"
        f"[답변]\n{state.get('answer', '')}"
    )
    try:
        text = llm.invoke(prompt).content
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "plan 생성 실패 (답변은 유지): project_id=%s", state.get("project_id"), exc_info=True
        )
        return {"plan": []}
    plan = [ln.lstrip("-").strip() for ln in text.splitlines() if ln.strip().startswith("-")]
    return {"plan": plan}


def verify_plan_node(state: QAState) -> dict:
    """검증(휴리스틱): 계획이 비어있지 않으면 통과."""
    return {"plan_ok": bool(state.get("plan"))}


def replan_node(state: QAState) -> dict:
    """재기획: plan_retries 증가 후 계획 재시도."""
    return {"plan_retries": state.get("plan_retries", 0) + 1}


def route_after_plan(state: QAState) -> str:
    """검증2 분기: 타당/상한이면 응답으로, 아니면 재기획."""
    if state.get("plan_ok") or state.get("plan_retries", 0) >= MAX_RETRY:
        return "respond"
    return "replan"


def respond_node(state: QAState) -> dict:
    """응답 조립: 답변 + todo plan + 출처 + 디버그.
    route는 기존 answer() 응답과의 하위호환용으로 항상 "both"를 유지한다
    (옛 계약 {answer, sources, route, debug}에 맞춰 짠 프론트가 안 깨지도록 상위집합 보장)."""
    return {"result": {
        "answer": state.get("answer", ""),
        "plan": state.get("plan", []),
        "sources": state.get("sources", []),
        "route": "both",
        "debug": state.get("debug", {}),
    }}


def build_qa_graph():
    g = StateGraph(QAState)
    g.add_node("section", section_node)
    g.add_node("qa", qa_node)
    g.add_node("verify_answer", verify_answer_node)
    g.add_node("rewrite", rewrite_node)
    g.add_node("plan", plan_node)
    g.add_node("verify_plan", verify_plan_node)
    g.add_node("replan", replan_node)
    g.add_node("respond", respond_node)

    g.add_edge(START, "section")
    g.add_edge("section", "qa")
    g.add_edge("qa", "verify_answer")
    g.add_conditional_edges("verify_answer", route_after_answer,
                            {"plan": "plan", "rewrite": "rewrite"})
    g.add_edge("rewrite", "qa")
    g.add_edge("plan", "verify_plan")
    g.add_conditional_edges("verify_plan", route_after_plan,
                            {"respond": "respond", "replan": "replan"})
    g.add_edge("replan", "plan")
    g.add_edge("respond", END)
    return g.compile()


# ─────────────────────────────────────────────────────────────
# 편의 실행 함수 (컴파일된 그래프 싱글톤 재사용)
# ─────────────────────────────────────────────────────────────
_qa_app = None
_ingest_app = None


def _last_user_question(history: Optional[list]) -> str:
    """대화 히스토리에서 가장 최근 사용자 질문을 반환한다. 없으면 빈 문자열."""
    for message in reversed(history or []):
        if message.get("role") == "user":
            content = str(message.get("content", "")).strip()
            if content:
                return content
    return ""


def _resolve_history_state(
    question: str, history: Optional[list], history_mode: Optional[bool]
) -> tuple[bool, Optional[str], List[str], str]:
    """이력 모드 predicate·주제 토큰을 최초 질문 기준으로 1회 계산한다.

    반환값(모드·scope·토큰)은 QAState에 불변 보존된다 — rewrite_node의 재검색
    suffix가 질문을 바꿔도 체인 선택 판정(전역형/주제형·주제 토큰)은 변하지 않는다.
    effective_question은 검색 질의(멀티쿼리·dense)와 컴포넌트 관련도가 같은 주제를
    보도록 초기 question으로도 쓰인다. history_mode=None이면 자체 감지
    (호출자가 라우팅 결과를 안 넘긴 경우 호환).
    """
    if history_mode is None:
        history_mode = history_intent.detect_history_intent(question)
    if not history_mode:
        return False, None, [], question

    # 지시어 질문("그건 왜 바뀌었어?")은 직전 사용자 질문과 결합해 주제를 승계한다.
    # 단 직전 질문도 지시어면 결합하지 않는다(연쇄 승계 방지).
    effective_question = question
    if history_intent.is_deictic(question):
        previous = _last_user_question(history)
        if previous and not history_intent.is_deictic(previous):
            effective_question = f"{previous} {question}"

    topic_tokens = history_intent.extract_content_tokens(effective_question)
    scope = "topical" if topic_tokens else "global"
    return True, scope, sorted(topic_tokens), effective_question


def run_qa(
    project_id: int,
    question: str,
    history: Optional[list] = None,
    attachment_context: str = "",
    attachment_sources: Optional[list] = None,
    history_mode: Optional[bool] = None,
) -> dict:
    """출력 그래프 실행 → {answer, plan, sources, debug}."""
    global _qa_app
    if _qa_app is None:
        _qa_app = build_qa_graph()
    resolved_mode, history_scope, history_topic_tokens, effective_question = _resolve_history_state(
        question, history, history_mode
    )
    out = _qa_app.invoke({
        # 지시어 결합이 일어났으면 결합 질문으로 검색을 시작한다 — 멀티쿼리·dense와
        # 컴포넌트 관련도가 같은 주제를 보게 하기 위함. rewrite suffix는 이 위에 붙는다.
        "project_id": project_id, "question": effective_question,
        "history": history or [], "qa_retries": 0, "plan_retries": 0,
        "attachment_context": attachment_context,
        "attachment_sources": attachment_sources or [],
        "history_mode": resolved_mode,
        "history_scope": history_scope,
        "history_topic_tokens": history_topic_tokens,
    })
    return out["result"]


def run_ingest(project_id: int, filename: str, content: str, uploaded_by: int,
               doc_type: str = "meeting", date: str = "") -> dict:
    """입력 그래프 실행 → {doc_id, items, project_summary}."""
    global _ingest_app
    if _ingest_app is None:
        _ingest_app = build_ingest_graph()
    return _ingest_app.invoke({
        "project_id": project_id, "filename": filename, "content": content,
        "doc_type": doc_type, "date": date, "uploaded_by": uploaded_by,
    })
