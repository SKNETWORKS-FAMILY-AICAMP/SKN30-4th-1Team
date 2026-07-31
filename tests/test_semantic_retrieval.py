import types
from unittest.mock import MagicMock, patch

import pytest

from backend.retriever import memory_vector, qa_engine
from backend.retriever.index_scope import ProjectIndexScope


def test_multi_query_generation_falls_back_to_original(monkeypatch):
    """재표현 LLM 호출 실패 시 원 질문 단독 검색으로 폴백한다."""
    monkeypatch.setattr(
        qa_engine,
        "get_chat_model",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("llm down")),
    )

    assert qa_engine._generate_multi_queries("왜 PR AUC를 선택했어?") == ["왜 PR AUC를 선택했어?"]


def test_multi_query_prompt_does_not_force_exactly_three_rewrites():
    assert "2~3개" in qa_engine.MULTI_QUERY_PROMPT
    assert "3개를 반환" not in qa_engine.MULTI_QUERY_PROMPT
    assert "고유 용어도 의미를 바꾸지 않는 범위" in qa_engine.MULTI_QUERY_PROMPT


def test_multi_queries_preserve_original_and_normalize_duplicates(monkeypatch):
    """원 질문을 첫 검색어로 두고 표기 중복 제거 후 총 4개까지만 유지한다."""
    monkeypatch.setattr(
        qa_engine,
        "load_project_index_scope",
        lambda project_id: ProjectIndexScope(project_id),
    )
    monkeypatch.setattr(qa_engine.mysql_search, "search", lambda *args, **kwargs: [])
    collection = MagicMock()
    collection.get.return_value = {"documents": [], "metadatas": [], "ids": []}

    with patch("backend.retriever.qa_engine.get_collection", return_value=collection):
        _, _, debug = qa_engine._build_context(
            1,
            "  SDK   연동은? ",
            history_mode=False,
            query_variants=[
                "sdk 연동은?",
                "ＳＤＫ 연동은?",
                "SDK 담당자",
                "연동 책임자",
                "SDK 일정",
                "초과 검색어",
            ],
        )

    assert debug["multi_queries"] == [
        "SDK 연동은?",
        "SDK 담당자",
        "연동 책임자",
        "SDK 일정",
    ]


def test_category_substrings_do_not_narrow_structured_retrieval(monkeypatch):
    """일반 질문의 우연한 부분문자열을 category 필터로 해석하지 않는다."""
    rows = [
        {
            "id": 1,
            "category": "action",
            "content": "전환 계획을 작성한다",
            "source": "plan.md",
        },
        {
            "id": 2,
            "category": "issue",
            "content": "전환 중 호환성 쟁점을 확인한다",
            "source": "issues.md",
        },
    ]
    monkeypatch.setattr(
        qa_engine,
        "load_project_index_scope",
        lambda project_id: ProjectIndexScope(project_id),
    )
    monkeypatch.setattr(qa_engine, "_generate_multi_queries", lambda q: [q])
    monkeypatch.setattr(
        qa_engine.mysql_search,
        "search",
        lambda project_id, **kwargs: rows,
    )
    monkeypatch.setattr(
        qa_engine,
        "_rank_mysql_rows",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("small unfiltered result sets must not be category-ranked")
        ),
    )
    collection = MagicMock()
    collection.get.return_value = {"documents": [], "metadatas": [], "ids": []}

    with patch("backend.retriever.qa_engine.get_collection", return_value=collection):
        context, sources, debug = qa_engine._build_context(
            1,
            "결정적 전환의 배경을 알려줘",
            history_mode=False,
        )

    assert debug["filters"] == {"category": None}
    assert "[action] 전환 계획을 작성한다" in context
    assert "[issue] 전환 중 호환성 쟁점을 확인한다" in context
    assert sources == ["plan.md", "issues.md"]
    assert not hasattr(qa_engine, "_CATEGORY_KEYWORDS")


def test_only_authoritative_query_text_can_admit_hybrid_evidence(monkeypatch):
    """모델 재표현이 일치해도 사용자/서버 질의와 무관한 근거는 입장하지 못한다."""
    unrelated_row = {
        "id": 1,
        "category": "decision",
        "content": "Nimbus ledger was archived",
        "source": "nimbus.md",
    }
    unrelated_text = "Nimbus ledger archive record"
    unrelated_meta = {
        "source": "nimbus.md",
        "doc_id": 7,
        "repo_id": -1,
        "item_type": "document",
    }
    collection = MagicMock()
    collection.get.return_value = {
        "documents": [unrelated_text],
        "metadatas": [unrelated_meta],
        "ids": ["doc7_chunk0"],
    }
    vectorstore = MagicMock()
    vectorstore.similarity_search_with_score.return_value = [
        (
            types.SimpleNamespace(
                page_content=unrelated_text,
                metadata=unrelated_meta,
            ),
            0.01,
        )
    ]
    monkeypatch.setattr(
        qa_engine,
        "load_project_index_scope",
        lambda project_id: ProjectIndexScope(project_id),
    )
    monkeypatch.setattr(
        qa_engine.mysql_search,
        "search",
        lambda project_id, **kwargs: [unrelated_row],
    )
    monkeypatch.setattr(qa_engine, "_get_vectorstore", lambda: vectorstore)

    with patch("backend.retriever.qa_engine.get_collection", return_value=collection):
        context, sources, debug = qa_engine._build_context(
            1,
            "Orion routing status",
            history_mode=False,
            query_variants=[
                "Orion routing status",
                "Nimbus ledger archive",
            ],
        )

    assert context == ""
    assert sources == []
    assert debug["mysql_candidate_count"] == 1
    assert debug["mysql_admitted_count"] == 0
    assert debug["chroma_candidate_count"] == 1
    assert debug["chroma_admitted_count"] == 0
    vectorstore.similarity_search_with_score.assert_not_called()


def test_server_history_effective_query_can_admit_matching_evidence(monkeypatch):
    """첫 서버 이력 결합 질의는 사용자 이전 주제를 보존하므로 입장 근거가 된다."""
    row = {
        "id": 1,
        "category": "decision",
        "content": "Nimbus routing moved to the relay",
        "source": "routing.md",
    }
    collection = MagicMock()
    collection.get.return_value = {"documents": [], "metadatas": [], "ids": []}
    monkeypatch.setattr(
        qa_engine,
        "load_project_index_scope",
        lambda project_id: ProjectIndexScope(project_id),
    )
    monkeypatch.setattr(
        qa_engine.mysql_search,
        "search",
        lambda project_id, **kwargs: [row],
    )

    with patch("backend.retriever.qa_engine.get_collection", return_value=collection):
        context, sources, debug = qa_engine._build_context(
            1,
            "What changed?",
            history_mode=False,
            query_variants=["Explain Nimbus routing. What changed?"],
        )

    assert "Nimbus routing moved to the relay" in context
    assert sources == ["routing.md"]
    assert debug["mysql_admitted_count"] == 1


def test_dense_mapping_preserves_equal_text_source_identity(monkeypatch):
    """동일 본문의 dense hit도 repo metadata로 정확한 코퍼스 행에 매핑한다."""
    text = "Orion routing uses a relay"
    metas = [
        {
            "source": "README.md",
            "source_path": "README.md",
            "repo_id": 1,
            "doc_id": -1,
            "chunk_index": 0,
            "item_type": "document",
        },
        {
            "source": "README.md",
            "source_path": "README.md",
            "repo_id": 2,
            "doc_id": -1,
            "chunk_index": 0,
            "item_type": "document",
        },
    ]
    collection = MagicMock()
    collection.get.return_value = {
        "documents": [text, text],
        "metadatas": metas,
        "ids": ["repo1_chunk0", "repo2_chunk0"],
    }
    vectorstore = MagicMock()
    vectorstore.similarity_search_with_score.return_value = [
        (types.SimpleNamespace(page_content=text, metadata=metas[1]), 0.01),
        (types.SimpleNamespace(page_content=text, metadata=metas[0]), 0.02),
    ]
    monkeypatch.setattr(
        qa_engine,
        "load_project_index_scope",
        lambda project_id: ProjectIndexScope(project_id),
    )
    monkeypatch.setattr(qa_engine.mysql_search, "search", lambda *args, **kwargs: [])
    monkeypatch.setattr(qa_engine, "_get_vectorstore", lambda: vectorstore)

    with patch("backend.retriever.qa_engine.get_collection", return_value=collection):
        _, sources, debug = qa_engine._build_context(
            1,
            "Orion routing",
            history_mode=False,
            query_variants=["Orion routing"],
        )

    by_source = {
        chunk["source_label"]: chunk
        for chunk in debug["chroma_chunks"]
    }
    assert by_source["README.md (repo#2)"]["dense_rank"] == 1
    assert by_source["README.md (repo#1)"]["dense_rank"] == 2
    assert set(sources) == {"README.md (repo#1)", "README.md (repo#2)"}


def test_topical_history_excludes_zero_relevance_components(monkeypatch):
    """topical 이력은 주제 토큰이 겹치지 않는 컴포넌트를 추가하지 않는다."""
    graph_rows = [
        {
            "id": 1,
            "category": "decision",
            "content": "Orion routing used direct delivery",
            "source": "orion.md",
            "superseded_by": 2,
            "date": "2026-01-01",
        },
        {
            "id": 2,
            "category": "decision",
            "content": "Orion routing uses a relay",
            "source": "orion.md",
            "superseded_by": None,
            "date": "2026-02-01",
        },
        {
            "id": 3,
            "category": "decision",
            "content": "Nimbus storage used local disks",
            "source": "nimbus.md",
            "superseded_by": 4,
            "date": "2026-03-01",
        },
        {
            "id": 4,
            "category": "decision",
            "content": "Nimbus storage uses remote disks",
            "source": "nimbus.md",
            "superseded_by": None,
            "date": "2026-04-01",
        },
    ]
    collection = MagicMock()
    collection.get.return_value = {"documents": [], "metadatas": [], "ids": []}
    monkeypatch.setattr(
        qa_engine,
        "load_project_index_scope",
        lambda project_id: ProjectIndexScope(project_id),
    )
    monkeypatch.setattr(qa_engine.mysql_search, "search", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        qa_engine.mysql_search,
        "fetch_supersede_graph",
        lambda *args, **kwargs: graph_rows,
    )

    with patch("backend.retriever.qa_engine.get_collection", return_value=collection):
        context, sources, debug = qa_engine._build_context(
            1,
            "Show Orion routing history",
            history_mode=True,
            history_scope="topical",
            history_topic_tokens=["Orion", "routing"],
            query_variants=["Show Orion routing history"],
        )

    assert "Orion routing" in context
    assert "Nimbus storage" not in context
    assert sources == ["orion.md"]
    assert debug["chains_added"] == 1
    assert debug["history_rows_added"] == 2
    assert debug["history_truncated"] is False


@pytest.mark.parametrize(
    "scope,tokens",
    [(None, []), ("topical", [])],
)
def test_history_retrieval_requires_explicit_nonempty_scope(scope, tokens):
    """직접 호출도 누락 scope를 global로 확대하지 않는다."""
    with pytest.raises(ValueError):
        qa_engine._build_context(
            1,
            "Show earlier states",
            history_mode=True,
            history_scope=scope,
            history_topic_tokens=tokens,
        )


def test_memory_vector_upsert_and_delete():
    """memory_id 기준 ChromaDB upsert/delete 계약을 검증한다."""
    collection = MagicMock()
    row = {
        "id": 7,
        "project_id": 1,
        "doc_id": None,
        "repo_id": 3,
        "category": "decision",
        "content": "Orion relay strategy selected",
        "owner": "박제섭",
        "source": "README.md",
    }

    with patch("backend.retriever.memory_vector.get_collection", return_value=collection):
        memory_vector.upsert_memory_vector(row)
        memory_vector.delete_memory_vector(7)

    collection.upsert.assert_called_once()
    kwargs = collection.upsert.call_args.kwargs
    assert kwargs["ids"] == ["memory:7"]
    assert kwargs["metadatas"][0]["item_type"] == "memory"
    assert kwargs["metadatas"][0]["repo_id"] == 3
    collection.delete.assert_called_once_with(ids=["memory:7"])
