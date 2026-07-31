"""get_chat_model() provider 라우팅 단위 테스트.

각 LLM_PROVIDER 값이 올바른 LangChain 객체를 반환하는지 검증.
실제 API 호출은 하지 않으며 dummy 키로 생성자만 테스트한다.
"""
import pytest


_OPENAI_OFFICIAL_BASE_URL = "https://api.openai.com/v1"


def test_import_without_api_key(monkeypatch):
    """API 키 없이도 모듈 import가 성공해야 한다 (lazy init 검증)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    import backend.llm.chat_model_factory  # noqa: F401 — import 자체가 크래시하지 않아야 함
    import backend.retriever.qa_engine as q
    assert not hasattr(q, "_chain")


def test_get_chat_model_openai(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-dummy")
    from backend.llm.chat_model_factory import get_chat_model
    from langchain_openai import ChatOpenAI
    assert isinstance(get_chat_model(), ChatOpenAI)


def test_get_chat_model_openai_default_model(monkeypatch):
    """OPENAI_MODEL 미설정 시 기본값이 gpt-4.1-mini여야 한다."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-dummy")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    from backend.llm.chat_model_factory import get_chat_model
    assert get_chat_model().model_name == "gpt-4.1-mini"


def test_openai_clients_use_pinned_official_base_url(monkeypatch):
    """운영 Compose의 빈 base URL 회귀가 채팅·추출·임베딩을 깨뜨리지 않아야 한다."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-dummy")
    monkeypatch.setenv("OPENAI_BASE_URL", _OPENAI_OFFICIAL_BASE_URL)
    monkeypatch.setenv("OPENAI_API_BASE", _OPENAI_OFFICIAL_BASE_URL)

    from backend.llm.chat_model_factory import get_chat_model
    from backend.llm.openai_client import OpenAIClient
    from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

    chat_model = get_chat_model()
    extraction_client = OpenAIClient()
    embedding_client = OpenAIEmbeddingFunction(model_name="text-embedding-3-small")

    assert str(chat_model.root_client.base_url).rstrip("/") == _OPENAI_OFFICIAL_BASE_URL
    assert str(extraction_client.client.base_url).rstrip("/") == _OPENAI_OFFICIAL_BASE_URL
    assert str(embedding_client.client.base_url).rstrip("/") == _OPENAI_OFFICIAL_BASE_URL


def test_get_chat_model_fast_falls_back_to_quality(monkeypatch):
    """OPENAI_MODEL_FAST 미설정 시 fast tier도 quality 모델을 쓴다."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-dummy")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-quality")
    monkeypatch.delenv("OPENAI_MODEL_FAST", raising=False)
    from backend.llm.chat_model_factory import get_chat_model
    assert get_chat_model(tier="fast").model_name == "gpt-quality"


def test_get_chat_model_fast_uses_fast_model(monkeypatch):
    """OPENAI_MODEL_FAST 설정 시 fast tier가 해당 모델을 쓴다."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-dummy")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-quality")
    monkeypatch.setenv("OPENAI_MODEL_FAST", "gpt-fast")
    from backend.llm.chat_model_factory import get_chat_model
    assert get_chat_model(tier="fast").model_name == "gpt-fast"


def test_get_chat_model_claude(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy")
    from backend.llm.chat_model_factory import get_chat_model
    from langchain_anthropic import ChatAnthropic
    assert isinstance(get_chat_model(), ChatAnthropic)


def test_get_chat_model_google(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "google")
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy")
    from backend.llm.chat_model_factory import get_chat_model
    from langchain_google_genai import ChatGoogleGenerativeAI
    assert isinstance(get_chat_model(), ChatGoogleGenerativeAI)


def test_get_chat_model_local(monkeypatch):
    """local provider는 OpenAI 호환 클라이언트(ChatOpenAI)를 반환해야 한다."""
    monkeypatch.setenv("LLM_PROVIDER", "local")
    from backend.llm.chat_model_factory import get_chat_model
    from langchain_openai import ChatOpenAI
    assert isinstance(get_chat_model(), ChatOpenAI)


def test_get_chat_model_invalid_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "unknown_provider")
    from backend.llm.chat_model_factory import get_chat_model
    with pytest.raises(ValueError, match="지원하지 않는 LLM_PROVIDER"):
        get_chat_model()
