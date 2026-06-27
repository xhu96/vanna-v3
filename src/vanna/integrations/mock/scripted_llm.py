"""Deterministic, scripted LLM for reproducible offline evaluation."""

from __future__ import annotations

from typing import AsyncGenerator, Dict, List

from vanna.core.llm import LlmService, LlmRequest, LlmResponse, LlmStreamChunk
from vanna.core.tool import ToolSchema


class ScriptedLlmService(LlmService):
    """Return a canned answer chosen by substring-matching the last user message.

    Deterministic: no network, no randomness. Used to drive the real Agent and
    evaluators over a fixed dataset so the eval gate measures real (reproducible)
    pipeline behavior rather than hardcoded numbers.
    """

    def __init__(self, responses: Dict[str, str], default: str = "SELECT 1"):
        self.responses = {k.lower(): v for k, v in responses.items()}
        self.default = default
        self.call_count = 0

    def _answer_for(self, request: LlmRequest) -> str:
        text = ""
        for msg in request.messages:
            if getattr(msg, "role", None) == "user":
                text = (msg.content or "").lower()
        for key, value in self.responses.items():
            if key in text:
                return value
        return self.default

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        self.call_count += 1
        return LlmResponse(
            content=self._answer_for(request),
            finish_reason="stop",
            usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        )

    async def stream_request(
        self, request: LlmRequest
    ) -> AsyncGenerator[LlmStreamChunk, None]:
        yield LlmStreamChunk(content=self._answer_for(request), finish_reason="stop")

    async def validate_tools(self, tools: List[ToolSchema]) -> List[str]:
        return []
