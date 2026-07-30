from unittest.mock import MagicMock, patch

from backend.retriever import memory_vector, qa_engine


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


def test_memory_vector_upsert_and_delete():
    """memory_id 기준 ChromaDB upsert/delete 계약을 검증한다."""
    collection = MagicMock()
    row = {
        "id": 7,
        "project_id": 1,
        "doc_id": None,
        "repo_id": 3,
        "category": "decision",
        "content": "리텐션 전략을 정했다",
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
