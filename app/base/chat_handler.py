"""
Framework-agnostic chat handling logic.
"""

import uuid
from collections import OrderedDict
from typing import Any, AsyncGenerator, Optional

from vanna.core import Agent
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

        # Read capacity from security config (admin-configurable).
        self._max_lineage_entries = getattr(
            getattr(getattr(agent, "config", None), "security", None),
            "lineage_max_entries",
            100,
        )

        # Conversation-scoped lineage storage (LRU eviction).
        self._lineage_store: OrderedDict[str, Any] = OrderedDict()
        self._lineage_markdown_store: OrderedDict[str, str] = OrderedDict()

    # ------------------------------------------------------------------
    # Public lineage accessors (used by route modules)
    # ------------------------------------------------------------------

    def get_lineage(self, conversation_id: str) -> Optional[Any]:
        """Return lineage evidence for a specific conversation, or None."""
        return self._lineage_store.get(conversation_id)

    def get_lineage_markdown(self, conversation_id: str) -> Optional[str]:
        """Return lineage markdown for a specific conversation, or None."""
        return self._lineage_markdown_store.get(conversation_id)

    # ------------------------------------------------------------------
    # Streaming / polling
    # ------------------------------------------------------------------

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
                self._capture_lineage(conversation_id, rc)

            yield ChatStreamChunk.from_component(component, conversation_id, request_id)

    def _capture_lineage(self, conversation_id: str, rc: Any) -> None:
        """Snapshot lineage evidence scoped to a conversation.

        Uses LRU eviction when the store exceeds ``_MAX_LINEAGE_ENTRIES``.
        """
        # Move to end (most-recently-used) if already present
        if conversation_id in self._lineage_store:
            self._lineage_store.move_to_end(conversation_id)
            self._lineage_markdown_store.move_to_end(conversation_id)

        self._lineage_store[conversation_id] = rc.data.get("evidence")
        self._lineage_markdown_store[conversation_id] = rc.content

        # Evict oldest entries if capacity exceeded
        while len(self._lineage_store) > self._max_lineage_entries:
            self._lineage_store.popitem(last=False)
            self._lineage_markdown_store.popitem(last=False)

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
