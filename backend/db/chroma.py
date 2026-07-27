import os
import chromadb
from chromadb.utils import embedding_functions

_client = None
_collection = None

# 기존 chromadb 기본 임베딩(384-dim)과 분리하기 위해 별도 컬렉션명 사용.
# CHROMA_COLLECTION_NAME 미설정 시 "paiM_openai_v2"(cosine space) 사용.
# v1(L2 space)과 거리지표가 달라 컬렉션명을 분리 — 전환 시 전체 재인덱싱 필요.
_DEFAULT_COLLECTION = "paiM_openai_v2"


def delete_from_existing_collection(where: dict) -> None:
    """Delete metadata-matched rows without creating a collection or embedding client."""
    persist_dir = os.getenv("CHROMA_PERSIST_DIR", ".chroma")
    collection_name = os.getenv("CHROMA_COLLECTION_NAME", _DEFAULT_COLLECTION)
    client = chromadb.PersistentClient(path=persist_dir)
    names = {item.name for item in client.list_collections()}
    if collection_name in names:
        client.get_collection(collection_name).delete(where=where)


def get_collection():
    global _client, _collection
    if _collection is None:
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key or api_key.startswith("sk-placeholder"):
            raise RuntimeError(
                "OPENAI_API_KEY가 설정되지 않았습니다. "
                "벡터 임베딩에 OpenAI API key가 필요합니다."
            )
        persist_dir = os.getenv("CHROMA_PERSIST_DIR", ".chroma")
        collection_name = os.getenv("CHROMA_COLLECTION_NAME", _DEFAULT_COLLECTION)
        _client = chromadb.PersistentClient(path=persist_dir)
        # 임베딩은 OpenAI(text-embedding-3-small) 사용 — 한국어 검색 품질 확보.
        # 검색측(qa_engine)도 반드시 같은 모델을 써야 벡터가 맞으므로 EMBED_MODEL로 공유한다.
        openai_ef = embedding_functions.OpenAIEmbeddingFunction(
            api_key=api_key,
            model_name=os.getenv("EMBED_MODEL", "text-embedding-3-small"),
        )
        # cosine space 명시 — 검색측(qa_engine)의 유사도 임계값·거리지표를 맞춘다.
        _collection = _client.get_or_create_collection(
            collection_name, embedding_function=openai_ef,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection
