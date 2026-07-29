"""TASK-007 — 출처 인용(답변 근거 파일명) 회귀 테스트.

제품 경로가 컨텍스트에 추적 가능한 출처 마커를 싣고, SYSTEM_QA가 유형 라벨이
아닌 실제 파일명 인용을 지시하는지 결정론적으로 확인한다(LLM 미호출).
"""
import base64
import types
from unittest.mock import MagicMock, patch

from backend.retriever import qa_engine


# ── 출처 라벨(충돌 없는 식별자) ────────────────────────────────────────────────

def test_source_label_document_is_filename():
    assert qa_engine._source_label("2026-03-02_회의록.md") == "2026-03-02_회의록.md"


def test_source_label_repo_disambiguates_same_name():
    # 저장소가 다르면 동명 파일도 구분되어야 한다(리뷰 R-002).
    a = qa_engine._source_label("README.md", repo_id=1, path="README.md")
    b = qa_engine._source_label("README.md", repo_id=2, path="README.md")
    assert a != b
    assert "repo#1" in a and "repo#2" in b


def test_source_label_ignores_absent_repo_sentinel():
    # Chroma 메타의 repo_id 부재 센티넬(-1)·None·"" 은 접미 없음.
    assert qa_engine._source_label("a.md", repo_id=-1) == "a.md"
    assert qa_engine._source_label("a.md", repo_id=None) == "a.md"
    assert qa_engine._source_label("a.md", repo_id="") == "a.md"


# ── 구조화 기록·SYSTEM_QA ──────────────────────────────────────────────────────

def test_structured_row_line_has_source_marker():
    row = {"category": "action", "content": "채팅 개발 착수",
           "source": "2026-03-02_회의.md", "owner": "이수진",
           "source_info": {"repo_id": None, "path": None}}
    line = qa_engine._row_line_body(row)
    assert "(출처: 2026-03-02_회의.md)" in line


def test_structured_row_line_repo_marker():
    row = {"category": "decision", "content": "README 정비",
           "source": "README.md",
           "source_info": {"repo_id": 7, "path": "README.md"}}
    assert "(출처: README.md (repo#7))" in qa_engine._row_line_body(row)


def test_system_qa_has_citation_rule():
    assert "출처 인용" in qa_engine.SYSTEM_QA
    # 유형 라벨을 출처로 쓰지 말라는 지시가 있어야 한다.
    assert "유형 이름을" in qa_engine.SYSTEM_QA
    assert "컨텍스트에 없는 출처를 지어내지 마라" in qa_engine.SYSTEM_QA


# ── 원문 청크 컨텍스트에 출처 마커가 실리는지 (_build_context 수준) ────────────

def _chunk_collection(metas_texts):
    col = MagicMock()
    col.get.return_value = {
        "documents": [t for t, _ in metas_texts],
        "metadatas": [m for _, m in metas_texts],
        "ids": [f"c{i}" for i in range(len(metas_texts))],
    }
    col.query.side_effect = RuntimeError("no vector in test")
    return col


def _vectorstore(order):
    store = MagicMock()
    store.similarity_search_with_score.side_effect = (
        lambda query, k, filter=None: [
            (types.SimpleNamespace(page_content=t,
                                   metadata={"item_type": "document"}), 0.1)
            for t in order.get(query, [])
        ])
    return store


def test_chroma_context_carries_source_marker(monkeypatch):
    text = "채팅 개발은 5월 착수한다"
    meta = {"source": "2026-03-02_회의.md", "date": "2026-03-02",
            "item_type": "document", "source_path": "", "repo_id": -1}
    monkeypatch.setattr(qa_engine, "_generate_multi_queries",
                        lambda q: ["채팅 착수"])
    monkeypatch.setattr(qa_engine.mysql_search, "search", lambda pid, **kw: [])
    monkeypatch.setattr(qa_engine.mysql_search, "fetch_supersede_graph",
                        lambda pid: [])
    monkeypatch.setattr(qa_engine, "_get_vectorstore",
                        lambda: _vectorstore({"채팅 착수": [text]}))
    with patch("backend.retriever.qa_engine.get_collection",
               return_value=_chunk_collection([(text, meta)])):
        context, _sources, debug = qa_engine._build_context(1, "채팅 착수")
    assert "[원문 맥락]" in context
    assert "(출처: 2026-03-02_회의.md)" in context
    assert debug["chroma_chunks"][0]["source_label"] == "2026-03-02_회의.md"


# ── 첨부 컨텍스트 마커(리뷰 R-004) ─────────────────────────────────────────────

def test_attachment_context_has_source_marker():
    from backend.api import query as query_api
    content = base64.b64encode("첨부 본문 내용".encode()).decode()
    att = query_api.QueryAttachment(filename="설계.md", content_base64=content)
    ctx, sources = query_api._prepare_attachment_context([att])
    assert "(출처: 설계.md)" in ctx
    assert "설계.md" in sources
