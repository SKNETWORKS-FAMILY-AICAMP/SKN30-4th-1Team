"""OpenAI 계약을 실제 API 호출 없이 검증하는 Agentic Q&A MVP 테스트."""

import pytest

from backend.llm.chat_model_factory import (
    AGENTIC_QA_MODEL,
    AgenticQAConfigError,
    get_agentic_qa_model,
    validate_agentic_qa_config,
)
from backend.retriever.qa_tools import QA_TOOLS


def _valid_mvp_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-dummy")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)


def test_agentic_qa_uses_fixed_openai_model_without_network(monkeypatch):
    _valid_mvp_env(monkeypatch)

    model = get_agentic_qa_model()

    assert model.model_name == AGENTIC_QA_MODEL
    assert str(model.openai_api_base).rstrip("/") == "https://api.openai.com/v1"


def test_agentic_qa_defaults_to_the_mvp_provider_and_model(monkeypatch):
    _valid_mvp_env(monkeypatch)
    monkeypatch.delenv("LLM_PROVIDER")
    monkeypatch.delenv("OPENAI_MODEL")

    assert get_agentic_qa_model().model_name == AGENTIC_QA_MODEL


def test_openai_bind_tools_converts_any_to_required_without_network(monkeypatch):
    """LangChain의 OpenAI 변환까지 검사해 첫 라운드 도구 강제를 고정한다."""
    _valid_mvp_env(monkeypatch)
    model = get_agentic_qa_model()

    automatic = model.bind_tools(QA_TOOLS)
    required = model.bind_tools(QA_TOOLS, tool_choice="any")

    assert "tool_choice" not in automatic.kwargs
    assert required.kwargs["tool_choice"] == "required"
    assert {
        tool["function"]["name"] for tool in required.kwargs["tools"]
    } == {tool.name for tool in QA_TOOLS}
    assert all(tool["type"] == "function" for tool in required.kwargs["tools"])


@pytest.mark.parametrize("provider", ["claude", "google", "local"])
def test_agentic_qa_rejects_non_openai_provider(monkeypatch, provider):
    _valid_mvp_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", provider)

    with pytest.raises(AgenticQAConfigError, match="LLM_PROVIDER=openai"):
        validate_agentic_qa_config()


def test_agentic_qa_rejects_non_mvp_model(monkeypatch):
    _valid_mvp_env(monkeypatch)
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1")

    with pytest.raises(AgenticQAConfigError, match="OPENAI_MODEL=gpt-4.1-mini"):
        validate_agentic_qa_config()


@pytest.mark.parametrize("variable", ["OPENAI_BASE_URL", "OPENAI_API_BASE"])
def test_agentic_qa_rejects_openai_compatible_custom_endpoint(monkeypatch, variable):
    _valid_mvp_env(monkeypatch)
    monkeypatch.setenv(variable, "http://localhost:11434/v1")

    with pytest.raises(AgenticQAConfigError, match="공식 OpenAI API"):
        validate_agentic_qa_config()


def test_agentic_qa_allows_explicit_official_endpoint(monkeypatch):
    _valid_mvp_env(monkeypatch)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1/")

    validate_agentic_qa_config()


def test_agentic_qa_requires_api_key(monkeypatch):
    _valid_mvp_env(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY")

    with pytest.raises(AgenticQAConfigError, match="OPENAI_API_KEY"):
        validate_agentic_qa_config()


def test_readiness_agentic_probe_accepts_mvp_contract(monkeypatch):
    from backend.api.health import _agentic_qa_config_probe

    _valid_mvp_env(monkeypatch)
    _agentic_qa_config_probe()


def test_readiness_agentic_probe_rejects_provider_drift(monkeypatch):
    from backend.api.health import _agentic_qa_config_probe

    _valid_mvp_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    with pytest.raises(AgenticQAConfigError, match="LLM_PROVIDER=openai"):
        _agentic_qa_config_probe()
