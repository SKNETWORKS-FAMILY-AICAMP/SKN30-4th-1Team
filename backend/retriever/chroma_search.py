from typing import List, Dict
from ..db.chroma import get_collection
from .index_scope import (
    ProjectIndexScope,
    chroma_visibility_filter,
    load_project_index_scope,
)


def search(
    project_id: int,
    query: str,
    n_results: int = 5,
    index_scope: ProjectIndexScope | None = None,
) -> List[Dict]:
    collection = get_collection()
    scope = index_scope or load_project_index_scope(project_id)
    results = collection.query(
        query_texts=[query],
        where=chroma_visibility_filter(scope),
        n_results=n_results,
    )

    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]

    return [
        {"text": doc, "metadata": meta}
        for doc, meta in zip(docs, metas)
    ]
