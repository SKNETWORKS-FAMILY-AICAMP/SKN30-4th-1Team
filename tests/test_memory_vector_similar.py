"""find_similar_memories — supersede 후보 recall 단위 테스트."""
from unittest.mock import patch

from backend.retriever import memory_vector
from backend.retriever.index_scope import ProjectIndexScope


class _FakeCollection:
    def __init__(self, metas):
        self._metas = metas
        self.where = None
        self.query_texts = None
        self.n_results = None

    def query(self, query_texts, where, n_results):
        self.query_texts = query_texts
        self.where = where
        self.n_results = n_results
        return {"metadatas": [self._metas]}


def _patch_collection(metas):
    coll = _FakeCollection(metas)
    return coll, patch("backend.retriever.memory_vector.get_collection", return_value=coll)


def test_find_similar_returns_memory_ids_excluding_self():
    """exclude_ids와 중복 metadata는 제외하고 memory_id만 순서대로 반환한다."""
    metas = [
        {"memory_id": 10, "category": "decision"},
        {"memory_id": 3, "category": "decision"},   # exclude 대상
        {"memory_id": 10, "category": "decision"},  # 중복
        {"memory_id": 7, "category": "decision"},
    ]
    coll, cm = _patch_collection(metas)
    with cm:
        ids = memory_vector.find_similar_memories(
            1, "새 결정 내용", category="decision", n_results=5,
            exclude_ids={3}, index_scope=ProjectIndexScope(1),
        )
    assert ids == [10, 7]


def test_find_similar_builds_and_where_with_category():
    """project_id·item_type=memory·category를 $and로 결합해 검색한다."""
    coll, cm = _patch_collection([])
    with cm:
        memory_vector.find_similar_memories(
            2, "내용", category="decision", n_results=4,
            index_scope=ProjectIndexScope(2),
        )
    assert coll.where == {
        "$and": [
            {"project_id": 2},
            {"repo_id": -1},
            {"item_type": "memory"},
            {"category": "decision"},
        ]
    }
    assert coll.n_results == 4


def test_find_similar_excludes_via_query_nin():
    """C-1: exclude_ids를 ChromaDB where($nin)에 넣어 top-N 슬롯을 소모하지 않게 한다."""
    coll, cm = _patch_collection([])
    with cm:
        memory_vector.find_similar_memories(
            1, "내용", category="decision", exclude_ids={5, 3},
            index_scope=ProjectIndexScope(1),
        )
    assert {"memory_id": {"$nin": [3, 5]}} in coll.where["$and"]


def test_find_similar_without_category_uses_two_conditions():
    """category 미지정이면 project_id·item_type만으로 검색한다."""
    coll, cm = _patch_collection([])
    with cm:
        memory_vector.find_similar_memories(
            2, "내용", index_scope=ProjectIndexScope(2)
        )
    assert coll.where == {
        "$and": [{"project_id": 2}, {"repo_id": -1}, {"item_type": "memory"}]
    }


def test_find_similar_empty_text_skips_query():
    """빈 텍스트는 ChromaDB를 호출하지 않고 빈 목록을 반환한다."""
    with patch("backend.retriever.memory_vector.get_collection") as mock_coll:
        ids = memory_vector.find_similar_memories(1, "   ", category="decision")
    assert ids == []
    mock_coll.assert_not_called()
