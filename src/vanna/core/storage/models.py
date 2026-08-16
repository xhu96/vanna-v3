"""
Storage domain models.

This module contains data models for conversation storage.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..tool.models import ToolCall
from ..user.models import User

REQUEST_ID_METADATA_KEY = "_vanna_request_id"


class Message(BaseModel):
    """Single message in a conversation."""

    role: str = Field(description="Message role (user/assistant/system/tool)")
    content: str = Field(description="Message content")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tool_calls: Optional[List[ToolCall]] = Field(default=None)
    tool_call_id: Optional[str] = Field(
        default=None, description="ID if this is a tool response"
    )


class Conversation(BaseModel):
    """Conversation containing multiple messages."""

    id: str = Field(description="Unique conversation identifier")
    user: User = Field(description="User this conversation belongs to")
    messages: List[Message] = Field(
        default_factory=list, description="Messages in conversation"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional conversation metadata"
    )
    base_message_count: int = Field(default=0, ge=0, exclude=True, repr=False)

    def add_message(self, message: Message) -> None:
        """Add a message to the conversation."""
        self.messages.append(message)
        self.updated_at = datetime.utcnow()


__all__ = ["Conversation", "Message", "REQUEST_ID_METADATA_KEY"]
