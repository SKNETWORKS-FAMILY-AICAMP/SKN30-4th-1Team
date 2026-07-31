# backend/llm/chat_model_factory.py
"""LLM_PROVIDER 환경변수 기반 LangChain 채팅 모델(BaseChatModel) 팩토리.

`backend/llm/factory.py`의 get_llm_client()(Anthropic/OpenAI/Google SDK를 직접 감싼
구조화 추출용 client)와는 역할이 다르다. 이 모듈은 LangChain 체인/에이전트에 바로
연결할 수 있는 ChatModel 인스턴스를 반환한다(자유 대화형 Q&A/세션 채팅용).
"""
import os


AGENTIC_QA_PROVIDER = "openai"
AGENTIC_QA_MODEL = "gpt-4.1-mini"
OPENAI_OFFICIAL_BASE_URL = "https://api.openai.com/v1"


class AgenticQAConfigError(RuntimeError):
    """Raised before a Q&A request uses an unsupported MVP model setup."""


def _normalized_openai_base_url(value: str) -> str:
    return value.strip().rstrip("/").lower()


def validate_agentic_qa_config() -> None:
    """Validate the deliberately narrow Agentic Q&A MVP model contract.

    Other call sites may continue to use ``get_chat_model`` with Claude, Google,
    or a local server.  Only the production Agentic project-Q&A path is limited
    to the official OpenAI API and ``gpt-4.1-mini`` for the MVP.
    """
    provider = os.getenv("LLM_PROVIDER", AGENTIC_QA_PROVIDER).strip().lower()
    if provider != AGENTIC_QA_PROVIDER:
        raise AgenticQAConfigError(
            "Agentic Q&A MVP는 LLM_PROVIDER=openai만 지원합니다 "
            f"(현재 값: {provider or '<empty>'})."
        )

    model = (os.getenv("OPENAI_MODEL") or AGENTIC_QA_MODEL).strip()
    if model != AGENTIC_QA_MODEL:
        raise AgenticQAConfigError(
            f"Agentic Q&A MVP는 OPENAI_MODEL={AGENTIC_QA_MODEL}만 지원합니다 "
            f"(현재 값: {model or '<empty>'})."
        )

    for variable in ("OPENAI_BASE_URL", "OPENAI_API_BASE"):
        configured = os.getenv(variable, "")
        if configured and _normalized_openai_base_url(configured) != OPENAI_OFFICIAL_BASE_URL:
            raise AgenticQAConfigError(
                f"Agentic Q&A MVP는 공식 OpenAI API만 지원합니다. {variable}에 "
                "사용자 지정 endpoint를 설정하지 마세요."
            )

    if not os.getenv("OPENAI_API_KEY", "").strip():
        raise AgenticQAConfigError(
            "Agentic Q&A를 사용하려면 OPENAI_API_KEY가 필요합니다."
        )


def get_agentic_qa_model(temperature: float = 0):
    """Return the single supported tool-calling model for Agentic Q&A MVP."""
    validate_agentic_qa_config()
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=AGENTIC_QA_MODEL,
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=OPENAI_OFFICIAL_BASE_URL,
        temperature=temperature,
    )


def get_chat_model(temperature: float = 0):
    """LLM_PROVIDER 환경변수에 따라 LangChain 채팅 모델 반환.
    - openai  : OpenAI API
    - claude  : Anthropic API
    - google  : Google Gemini API
    - local   : OpenAI 호환 로컬 서버 (Ollama / vLLM / LM Studio / llama.cpp 등)
                LOCAL_LLM_URL, LOCAL_LLM_MODEL 환경변수로 엔드포인트·모델 지정
    """
    p = os.getenv("LLM_PROVIDER", "openai").lower()
    if p == "openai":
        from langchain_openai import ChatOpenAI
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        return ChatOpenAI(model=model, temperature=temperature)
    if p == "claude":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"), temperature=temperature)
    if p == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=os.getenv("GOOGLE_MODEL", "gemini-1.5-pro"), temperature=temperature)
    if p == "local":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=os.getenv("LOCAL_LLM_MODEL", "local-model"),
            base_url=os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1"),
            api_key="local",  # OpenAI 클라이언트가 키를 요구하므로 dummy 값
            temperature=temperature,
        )
    raise ValueError(f"지원하지 않는 LLM_PROVIDER: {p} (openai/claude/google/local 중 하나)")
