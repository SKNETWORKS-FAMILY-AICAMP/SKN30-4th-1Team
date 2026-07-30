from typing import List
import google.generativeai as genai
from .base import BaseLLMClient, Message, LLMResponse


class GoogleClient(BaseLLMClient):

    def __init__(self, model: str = "gemini-1.5-pro", max_tokens: int = 2000):
        self.model = genai.GenerativeModel(model)
        self.max_tokens = max_tokens

    def chat(self, messages: List[Message], system=None, tool_schema=None, tool_name=None) -> LLMResponse:
        if system:
            self.model._system_instruction = system

        if tool_schema and tool_name:
            raise NotImplementedError(
                "Google provider does not support structured extraction (nested List schema). "
                "Use LLM_PROVIDER=claude or LLM_PROVIDER=openai for document ingestion."
            )

        history = []
        for m in messages[:-1]:
            role = "model" if m.role == "assistant" else "user"
            history.append({"role": role, "parts": [m.content]})

        chat = self.model.start_chat(history=history)
        response = chat.send_message(
            messages[-1].content,
            generation_config={"max_output_tokens": self.max_tokens},
        )
        return LLMResponse(content=response.text)
