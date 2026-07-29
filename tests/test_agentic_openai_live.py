"""Opt-in live smoke for the exact Agentic Q&A MVP tool-calling model."""

import os

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from backend.llm.chat_model_factory import get_agentic_qa_model
from backend.retriever.qa_tools import QA_TOOLS


@pytest.mark.skipif(
    os.getenv("PAIM_RUN_LIVE_OPENAI_SMOKE") != "1",
    reason="PAIM_RUN_LIVE_OPENAI_SMOKE=1인 명시적 live 실행만 허용",
)
def test_gpt_4_1_mini_returns_a_required_qa_tool_call():
    model = get_agentic_qa_model()
    bound = model.bind_tools(QA_TOOLS, tool_choice="any")

    response = bound.invoke([
        SystemMessage(content="프로젝트 질문은 제공된 검색 도구로 먼저 확인하세요."),
        HumanMessage(content="SDK 연동 담당자가 누구인지 프로젝트 기록에서 확인해줘."),
    ])

    assert response.tool_calls
    assert response.tool_calls[0]["name"] in {tool.name for tool in QA_TOOLS}
