"""Versioned v3 streaming event models."""

import time
from typing import Any, Dict, Literal

from pydantic import BaseModel, Field

from .models import ChatStreamChunk

EventType = Literal[
    "status",
    "assistant_text",
    "table_result",
    "chart_spec",
    "component",
    "error",
    "done",
]


class ChatEvent(BaseModel):
    """Typed streaming event for v3 clients."""

    event_version: Literal["v3"] = "v3"
    event_type: EventType
    conversation_id: str
    request_id: str
    timestamp: float = Field(default_factory=time.time)
    payload: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_chunk(cls, chunk: ChatStreamChunk) -> "ChatEvent":
        """Convert a v2-compatible chunk into a typed v3 event."""
        rich = chunk.rich or {}
        rich_type = rich.get("type")

        event_type: EventType = "component"
        if rich_type == "status_bar_update":
            event_type = "status"
        elif rich_type == "text":
            event_type = "assistant_text"
        elif rich_type == "dataframe":
            event_type = "table_result"
        elif rich_type == "chart":
            event_type = "chart_spec"

        return cls(
            event_type=event_type,
            conversation_id=chunk.conversation_id,
            request_id=chunk.request_id,
            timestamp=chunk.timestamp,
            payload={
                "rich": chunk.rich,
                "simple": chunk.simple,
            },
        )

    @classmethod
    def done(cls, conversation_id: str, request_id: str) -> "ChatEvent":
        """Completion event."""
        return cls(
            event_type="done",
            conversation_id=conversation_id,
            request_id=request_id,
            payload={"status": "done"},
        )

