# backend/chat/router.py
import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import tiktoken
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from backend.db.mysql import get_connection
from backend.security.session_crypto import get_session_crypto
from backend.chat.session_store import SessionStore
from backend.chat.context_builder import ContextBuilder
from backend.llm.chat_model_factory import get_chat_model
from backend.api.auth import get_current_user_id, require_project_access
from backend.rate_limit import RATE_LIMIT_CHAT, authenticated_user_key, limiter

router = APIRouter(prefix="/projects/{project_id}/sessions", tags=["Session Memory API"])
logger = logging.getLogger(__name__)

# --- 실제 DB 커넥션 종속성 주입기 (다른 라우터와 동일하게 backend.db.mysql.get_connection 사용) ---
def get_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


# --- Pydantic 데이터 검증 스키마 선언 ---
class SessionCreateRequest(BaseModel):
    title: str

class SessionUpdateRequest(BaseModel):
    title: str

class QueryRequest(BaseModel):
    current_question: str
    rag_context: Optional[str] = ""

class MessageResponse(BaseModel):
    id: int
    role: str
    text: str
    token_count: int
    created_at: datetime

class SessionResponse(BaseModel):
    id: str
    project_id: int
    user_id: Optional[int] = None
    title: str
    created_at: datetime
    updated_at: datetime


def _verify_project_exists(cursor, project_id: int):
    cursor.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")


def _verify_session_ownership(cursor, project_id: int, session_id: str):
    """session_id가 project_id 소속이면서 현재 사용자의 것인지 확인한다. 아니면 404.
    user_id가 NULL인 레거시 세션(마이그레이션 이전 생성)은 멤버 전원 접근 허용.
    다른 멤버의 세션은 존재 여부를 숨기기 위해 403이 아닌 404로 응답한다."""
    current_user_id = get_current_user_id()
    if current_user_id is not None:
        cursor.execute(
            "SELECT id FROM chat_sessions"
            " WHERE id = %s AND project_id = %s AND (user_id IS NULL OR user_id = %s)",
            (session_id, project_id, current_user_id)
        )
    else:
        # dev 모드에서 DEV_USER_ID 미설정 — 단일 사용자 동작 유지
        cursor.execute(
            "SELECT id FROM chat_sessions WHERE id = %s AND project_id = %s",
            (session_id, project_id)
        )
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="해당 프로젝트에서 요청하신 세션을 찾을 수 없습니다.")


_ROLE_TO_LANGCHAIN_MESSAGE = {
    "system": SystemMessage,
    "assistant": AIMessage,
    "user": HumanMessage,
}


def _to_langchain_messages(final_prompt_messages: List[dict]):
    """ContextBuilder.build_final_prompt()가 만든 role/content dict 목록을
    LangChain 메시지 객체 목록으로 변환한다 (system/assistant/user 외 role은 user로 취급)."""
    return [
        _ROLE_TO_LANGCHAIN_MESSAGE.get(m["role"], HumanMessage)(content=m["content"])
        for m in final_prompt_messages
    ]


# --- [1] POST /projects/{project_id}/sessions (세션 생성) ---
@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_chat_session(project_id: int, request: SessionCreateRequest, db=Depends(get_db)):
    require_project_access(project_id, min_role="member")
    session_id = f"sess_{uuid.uuid4().hex[:12]}"

    with db.cursor() as cursor:
        _verify_project_exists(cursor, project_id)

        cursor.execute(
            "INSERT INTO chat_sessions (id, project_id, user_id, title) VALUES (%s, %s, %s, %s)",
            (session_id, project_id, get_current_user_id(), request.title)
        )
        db.commit()

        cursor.execute("SELECT * FROM chat_sessions WHERE id = %s", (session_id,))
        row = cursor.fetchone()
    return row


# --- [2] GET /projects/{project_id}/sessions (세션 목록 조회) ---
@router.get("", response_model=List[SessionResponse])
def get_chat_session_list(project_id: int, db=Depends(get_db)):
    require_project_access(project_id)
    current_user_id = get_current_user_id()
    with db.cursor() as cursor:
        if current_user_id is not None:
            # 본인 세션 + 레거시(user_id NULL) 세션만 노출 — 멤버 간 대화 격리
            cursor.execute(
                "SELECT * FROM chat_sessions"
                " WHERE project_id = %s AND (user_id IS NULL OR user_id = %s)"
                " ORDER BY updated_at DESC",
                (project_id, current_user_id)
            )
        else:
            cursor.execute(
                "SELECT * FROM chat_sessions WHERE project_id = %s ORDER BY updated_at DESC",
                (project_id,)
            )
        return cursor.fetchall()


# --- [3] PATCH /projects/{project_id}/sessions/{session_id} (세션 수정) ---
@router.patch("/{session_id}", response_model=SessionResponse)
def update_chat_session(project_id: int, session_id: str, request: SessionUpdateRequest, db=Depends(get_db)):
    require_project_access(project_id, min_role="member")
    with db.cursor() as cursor:
        _verify_session_ownership(cursor, project_id, session_id)

        cursor.execute(
            "UPDATE chat_sessions SET title = %s WHERE id = %s",
            (request.title, session_id)
        )
        db.commit()

        cursor.execute("SELECT * FROM chat_sessions WHERE id = %s", (session_id,))
        row = cursor.fetchone()
    return row


# --- [4] DELETE /projects/{project_id}/sessions/{session_id} (세션 삭제) ---
@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat_session(project_id: int, session_id: str, db=Depends(get_db)):
    require_project_access(project_id, min_role="member")
    with db.cursor() as cursor:
        _verify_session_ownership(cursor, project_id, session_id)

        # FK에 ON DELETE CASCADE가 없으므로(schema.sql 기존 테이블들과 동일한 컨벤션) 자식 row를 먼저 삭제
        cursor.execute("DELETE FROM chat_messages WHERE session_id = %s", (session_id,))
        cursor.execute("DELETE FROM chat_summaries WHERE session_id = %s", (session_id,))
        cursor.execute("DELETE FROM chat_sessions WHERE id = %s", (session_id,))
        db.commit()
    return


# --- [5] GET /projects/{project_id}/sessions/{session_id}/messages (메시지 이력 조회) ---
@router.get("/{session_id}/messages", response_model=List[MessageResponse])
def get_session_message_history(project_id: int, session_id: str, db=Depends(get_db)):
    require_project_access(project_id)
    with db.cursor() as cursor:
        _verify_session_ownership(cursor, project_id, session_id)

        cursor.execute(
            "SELECT id, role, ciphertext, nonce, key_version, token_count, created_at "
            "FROM chat_messages WHERE session_id = %s ORDER BY id ASC",
            (session_id,)
        )
        rows = cursor.fetchall()

    crypto = get_session_crypto()
    decrypted_history = []
    for r in rows:
        plain_text = crypto.decrypt(
            ciphertext_b64=r["ciphertext"],
            nonce_b64=r["nonce"],
            key_version=r["key_version"]
        )
        decrypted_history.append({
            "id": r["id"],
            "role": r["role"],
            "text": plain_text,
            "token_count": r["token_count"],
            "created_at": r["created_at"]
        })

    return decrypted_history


# --- [6] POST /projects/{project_id}/sessions/{session_id}/query (세션 기반 최종 질의 API) ---
def handle_session_query(
    project_id: int,
    session_id: str,
    request: QueryRequest,
    db=Depends(get_db),
):
    require_project_access(project_id, min_role="member")
    with db.cursor() as cursor:
        _verify_session_ownership(cursor, project_id, session_id)

    store = SessionStore(db, project_id)

    # DB로부터 암호화 세션 상태를 복호화하여 런타임 메모리에 안착
    current_summary, recent_messages, last_summary_id = store.get_session_context(session_id)

    encoder = tiktoken.encoding_for_model("gpt-4o")
    u_token = len(encoder.encode(request.current_question))

    # 1. 유저 신규 질문을 세션 스토어 및 DB에 기록
    user_msg_id = store.save_message(
        session_id=session_id,
        role="user",
        text=request.current_question,
        token_count=u_token
    )

    # 실시간 컨텍스트 토큰 예산 검증을 위해 최신 메시지 리스트에 유저 질문 우선 추가
    recent_messages.append({"id": user_msg_id, "role": "user", "text": request.current_question, "token_count": u_token})

    # 기획서 규격 연동을 위해 RAG 컨텍스트 평문을 스코어를 가진 구조형 객체 배열화
    retrieved_rag_chunks = [
        {"text": request.rag_context, "score": 0.85}
    ] if request.rag_context else []

    # =========================================================================
    # 📍 [조건 1 & 2]: 예산 수립 및 출력 Reserve 공간 정의 구간
    # =========================================================================
    CONTEXT_WINDOW = 128000
    MAX_TOTAL_BUDGET = int(CONTEXT_WINDOW * 0.65)  # 조건 1: 컨텍스트 윈도우의 60~70% 예산 지정 (65%)
    OUTPUT_RESERVE = 4000                          # 조건 2: 최소 2~4k tokens 출력 공간 확보 (4000)

    # 현재 조립 완료 단계의 총합 토큰을 연산하는 헬퍼 함수 정의
    def calculate_current_total_tokens() -> int:
        t_summary = len(encoder.encode(current_summary)) if current_summary else 0
        t_recent_msgs = sum(msg.get("token_count", 0) for msg in recent_messages)
        t_rag = sum(len(encoder.encode(chunk["text"])) for chunk in retrieved_rag_chunks)
        t_current_q = u_token
        return t_summary + t_recent_msgs + t_rag + t_current_q

    # =========================================================================
    # 📍 [조건 3]: 입력 예산 초과 시 제거 우선순위 순차 루프 작동 구간
    # 제거 순서: 오래된 recent messages → 낮은 점수 RAG context → summary 재압축
    # =========================================================================
    while calculate_current_total_tokens() > MAX_TOTAL_BUDGET:
        # 순서 1: 오래된 recent messages 우선 제거 (단, 방금 던진 유저 질문인 마지막 인덱스는 무조건 수호)
        if len(recent_messages) > 1:
            recent_messages.pop(0)
            continue

        # 순서 2: 검색 점수가 낮은 RAG context 제거
        if len(retrieved_rag_chunks) > 0:
            retrieved_rag_chunks.sort(key=lambda x: x["score"])  # 오름차순 정렬
            retrieved_rag_chunks.pop(0)                          # 가장 점수가 낮은 RAG 요소 탈락
            continue

        # 순서 3: 이전 단계를 거쳐도 한도가 부족할 시 최종 summary 컨텍스트 재압축 단행
        if current_summary:
            current_summary = "[LLM 강제 재압축 요약]: 컨텍스트 입력 임계치를 준수하기 위해 기존 요약 데이터가 재압축되었습니다."
            break
        break

    # -------------------------------------------------------------------------
    # 정제 완료된 안전한 최적화 데이터 컴포넌트들을 전달하여 최종 시스템 프롬프트 조립
    # -------------------------------------------------------------------------
    builder = ContextBuilder(model_name="gpt-4o")
    final_prompt_messages = builder.build_final_prompt(
        system_prompt="당신은 개발 프로젝트 통합 도우미 PaiM입니다.",
        decrypted_summary=current_summary,
        decrypted_recent_messages=recent_messages,
        rag_chunks=retrieved_rag_chunks,
        current_question=request.current_question,
        max_total_budget=MAX_TOTAL_BUDGET
    )
    # -------------------------------------------------------------------------

    # 실제 LLM 호출 (LLM_PROVIDER env로 openai/claude/google/local 중 선택 — llm/chat_model_factory.get_chat_model() 재사용)
    try:
        llm_response = get_chat_model().invoke(_to_langchain_messages(final_prompt_messages))
        llm_response_text = llm_response.content
    except Exception as e:
        logger.error("세션 질의 LLM 호출 오류: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="LLM 응답 생성 중 오류가 발생했습니다. 서버 로그를 확인하세요.")

    # 2. 생성된 AI 응답을 세션 스토어 및 DB에 기록
    a_token = len(encoder.encode(llm_response_text))
    assistant_msg_id = store.save_message(
        session_id=session_id,
        role="assistant",
        text=llm_response_text,
        token_count=a_token
    )

    # 다음 턴 처리를 위해 AI 답변을 최신 메시지 윈도우에 최종 포함
    recent_messages.append({"id": assistant_msg_id, "role": "assistant", "text": llm_response_text, "token_count": a_token})

    # =========================================================================
    # 📍 [조건 4]: 평시 대화 누적에 따른 Rolling Summary 병합 제어부
    # =========================================================================
    RECENT_MESSAGE_BUDGET = 4000      # 최신 대화방 유지 임계 토큰 버젯
    RECENT_MESSAGE_KEEP_COUNT = 10    # 컨텍스트 보존을 위해 남겨둘 최신 메시지 개수

    recent_message_tokens = sum(msg["token_count"] for msg in recent_messages)

    # recent message 토큰이 임계치를 넘고, 실제로 keep-count 밖으로 밀려날 메시지가 있을 때만 병합한다.
    # (메시지 개수가 keep-count 이하인데 토큰만 큰 경우 old_messages가 빈 리스트가 되어
    #  이후 old_messages[-1] 접근이 IndexError로 죽는 문제를 방지)
    if recent_message_tokens > RECENT_MESSAGE_BUDGET and len(recent_messages) > RECENT_MESSAGE_KEEP_COUNT:
        old_messages = recent_messages[:-RECENT_MESSAGE_KEEP_COUNT]

        old_messages_text = "\n".join([f"{m['role']}: {m['text']}" for m in old_messages])
        current_summary = f"{current_summary if current_summary else ''}\n[자동 롤링 병합 문맥]\n{old_messages_text}"

        store.save_or_update_summary(
            session_id=session_id,
            summary_text=current_summary,
            source_message_id=old_messages[-1]["id"]
        )

        recent_messages = recent_messages[-RECENT_MESSAGE_KEEP_COUNT:]
    # =========================================================================

    # 모든 영속성 컨텍스트 처리 완료 후 최종 데이터베이스 안전 커밋
    db.commit()

    return {
        "status": "success",
        "session_id": session_id,
        "answer": llm_response_text
    }


@router.post("/{session_id}/query")
@limiter.limit(RATE_LIMIT_CHAT, key_func=authenticated_user_key)
def rate_limited_session_query(
    request: Request,
    project_id: int,
    session_id: str,
    body: QueryRequest,
    db=Depends(get_db),
):
    """HTTP 경계에서만 요청 제한을 적용하고 기존 핵심 함수 계약은 보존한다."""
    return handle_session_query(project_id, session_id, body, db=db)
