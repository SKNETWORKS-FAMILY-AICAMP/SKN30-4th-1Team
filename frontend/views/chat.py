# Q&A 채팅 페이지: 질문 입력 → Agentic Q&A 호출 → 답변 + 검색 메타 렌더링.
# 프로젝트별 대화 히스토리를 session_state에 유지해 멀티턴 대화를 지원.
import html
import streamlit as st
from backend.agentic_graph import run_agentic_qa


ROUTE_LABEL = {
    "mysql":  "구조화 DB 검색",
    "chroma": "벡터 유사도 검색",
    "both":   "DB + 벡터 복합 검색",
    "semantic": "Agentic 검색",
}


def render(project_id: int, project_name: str):
    """채팅 페이지 렌더링.
    - session_state[chat_history_{project_id}]로 프로젝트별 히스토리 분리
    - 기존 메시지 재렌더링 후 새 입력 처리
    - api_history에서 현재 질문은 제외 (qa_engine 내부에서 컨텍스트로 조합됨)
    """
    st.header("Q&A 채팅")
    st.markdown(
        f'<span style="font-size:12px;font-weight:600;color:#1E88E5;'
        f'background:#E3F2FD;padding:2px 10px;border-radius:10px;">'
        f'📁 {html.escape(project_name)}</span>',
        unsafe_allow_html=True,
    )

    # 프로젝트별 히스토리 키로 분리 (다른 프로젝트 전환 시 각각 유지됨)
    history_key = f"chat_history_{project_id}"
    if history_key not in st.session_state:
        st.session_state[history_key] = []

    history = st.session_state[history_key]

    # 기존 대화 히스토리 렌더링
    for msg in history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant" and msg.get("meta"):
                _render_meta(msg["meta"])

    question = st.chat_input(f"{project_name} 프로젝트에 대해 질문하세요...")
    if not question:
        return

    history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    # 현재 질문 제외한 이전 히스토리만 API에 전달
    api_history = [
        {"role": m["role"], "content": m["content"]}
        for m in history[:-1]
    ]

    with st.chat_message("assistant"):
        with st.spinner("답변 생성 중..."):
            try:
                result = run_agentic_qa(
                    project_id=project_id,
                    question=question,
                    history=api_history,
                )
            except Exception as e:
                st.error(f"Q&A 오류: {e}\n\nLLM_PROVIDER 및 API 키 설정을 확인하세요.")
                history.pop()  # 오류 시 사용자 질문도 히스토리에서 제거
                return
        st.markdown(result["answer"])
        _render_meta(result)

    history.append({
        "role":    "assistant",
        "content": result["answer"],
        "meta":    result,
    })


def _render_meta(result: dict):
    """답변 아래에 검색 경로·출처·디버그 정보를 표시.
    debug 항목은 접기 가능한 expander로 표시. XSS 방지를 위해 html.escape 적용.
    """
    route = result.get("route", "")
    sources = result.get("sources", [])
    debug = result.get("debug", {})

    parts = []
    if route:
        parts.append(f"🔍 {ROUTE_LABEL.get(route, route)}")
    if sources:
        parts.append("출처: " + ", ".join(sources))
    if parts:
        st.caption(" &nbsp;|&nbsp; ".join(parts))

    if debug:
        with st.expander("검색 컨텍스트 디버그", expanded=False):
            mysql_rows = debug.get("mysql_rows", [])
            chroma_chunks = debug.get("chroma_chunks", [])

            if mysql_rows:
                st.markdown(f"**MySQL — {len(mysql_rows)}개 항목**")
                for r in mysql_rows:
                    # DB 값에 HTML 특수문자가 있을 수 있으므로 escape 후 렌더링
                    cat = html.escape(str(r['category']))
                    content = html.escape(str(r['content']))
                    source = html.escape(str(r['source']))
                    st.markdown(
                        f"- `[{cat}]` {content}  \n"
                        f"  <small>출처: {source}</small>",
                        unsafe_allow_html=True,
                    )

            if chroma_chunks:
                st.markdown(f"**ChromaDB — {len(chroma_chunks)}개 청크 (상위 유사도)**")
                for i, c in enumerate(chroma_chunks, 1):
                    date_str = f"({c['date']})" if c['date'] else ""
                    st.markdown(f"**#{i}** `{c['source']}` {date_str}")
                    st.text(c["text"])
