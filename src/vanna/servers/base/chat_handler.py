"""
Framework-agnostic chat handling logic.
"""

import uuid
from typing import Any, AsyncGenerator, List, Optional

from ...core import Agent
from .models import ChatRequest, ChatResponse, ChatStreamChunk


class ChatHandler:
    """Core chat handling logic - framework agnostic."""

    def __init__(
        self,
        agent: Agent,
    ):
        """Initialize chat handler.

        Args:
            agent: The agent to handle chat requests
        """
        self.agent = agent

        # Latest lineage evidence — populated after each completed chat turn.
        self._latest_lineage: Optional[Any] = None
        self._latest_lineage_collector: Optional[Any] = None

    async def handle_stream(
        self, request: ChatRequest
    ) -> AsyncGenerator[ChatStreamChunk, None]:
        """Stream chat responses.

        Args:
            request: Chat request

        Yields:
            Chat stream chunks
        """
        conversation_id = request.conversation_id or self._generate_conversation_id()
        # Use request_id from client for tracking, or use the one generated internally
        request_id = request.request_id or str(uuid.uuid4())

        async for component in self.agent.send_message(
            request_context=request.request_context,
            message=request.message,
            conversation_id=conversation_id,
        ):
            # Capture lineage evidence from the CardComponent emitted at end
            # of each turn by the agent.
            rc = getattr(component, "rich_component", None)
            if rc is not None and getattr(rc, "title", None) == "Evidence and Lineage":
                self._capture_lineage(rc)

            yield ChatStreamChunk.from_component(component, conversation_id, request_id)

    def _capture_lineage(self, rc: Any) -> None:
        """Snapshot the latest lineage evidence from the evidence card component."""
        self._latest_lineage = rc.data.get("evidence")
        self._latest_lineage_markdown = rc.content

    async def handle_poll(self, request: ChatRequest) -> ChatResponse:
        """Handle polling-based chat.

        Args:
            request: Chat request

        Returns:
            Complete chat response
        """
        chunks = []
        async for chunk in self.handle_stream(request):
            chunks.append(chunk)

        return ChatResponse.from_chunks(chunks)

    def _generate_conversation_id(self) -> str:
        """Generate new conversation ID."""
        return f"conv_{uuid.uuid4().hex[:8]}"
