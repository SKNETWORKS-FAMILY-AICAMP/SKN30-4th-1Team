from typing import List
import anthropic
from .base import BaseLLMClient, Message, LLMResponse


class ClaudeClient(BaseLLMClient):

    def __init__(self, model: str = "claude-sonnet-4-6", max_tokens: int = 4096):
        self.client = anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    def chat(self, messages: List[Message], system=None, tool_schema=None, tool_name=None) -> LLMResponse:
        kwargs = {
            "model":      self.model,
            "max_tokens": self.max_tokens,
            "temperature": 0,  # 구조화 추출은 결정적이어야 하므로 0 고정 (qa_engine 생성 체인과 동일)
            "messages":   [{"role": m.role, "content": m.content} for m in messages],
        }
        if system:
            kwargs["system"] = system
        if tool_schema and tool_name:
            kwargs["tools"] = [{
                "name":         tool_name,
                "description":  "Extract structured data.",
                "input_schema": tool_schema,
            }]
            kwargs["tool_choice"] = {"type": "tool", "name": tool_name}

        response = self.client.messages.create(**kwargs)

        for block in response.content:
            if block.type == "tool_use":
                return LLMResponse(content="", tool_input=block.input)

        text = "".join(b.text for b in response.content if hasattr(b, "text"))
        return LLMResponse(content=text)
