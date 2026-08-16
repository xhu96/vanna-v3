"""
Request and response models for server endpoints.
"""

import json
import math
import time
import uuid
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator

from ...components import UiComponent, RichComponent
from ...core.component_manager import ComponentUpdate
from ...core.user.request_context import RequestContext

MAX_PUBLIC_METADATA_BYTES = 64 * 1024
MAX_PUBLIC_METADATA_DEPTH = 8
MAX_PUBLIC_METADATA_ITEMS = 100
MAX_PUBLIC_METADATA_STRING = 4096
_RESERVED_METADATA_KEYS = {
    "schema_hash",
    "schema_snapshot_id",
    "schema_version",
    "schema_drift_detected",
}


def validate_public_chat_metadata(metadata: Any) -> Dict[str, Any]:
    """Validate untrusted chat metadata before server-owned values are attached."""

    if not isinstance(metadata, dict):
        raise ValueError("chat metadata must be an object")

    def validate(value: Any, *, depth: int) -> None:
        if depth > MAX_PUBLIC_METADATA_DEPTH:
            raise ValueError("chat metadata exceeds the nesting limit")
        if value is None or isinstance(value, (str, bool, int)):
            if isinstance(value, str) and len(value) > MAX_PUBLIC_METADATA_STRING:
                raise ValueError("chat metadata string exceeds the length limit")
            return
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("chat metadata numbers must be finite")
            return
        if isinstance(value, dict):
            if len(value) > MAX_PUBLIC_METADATA_ITEMS:
                raise ValueError("chat metadata object exceeds the item limit")
            for key, item in value.items():
                if not isinstance(key, str) or not key or len(key) > 128:
                    raise ValueError("chat metadata keys must be bounded strings")
                normalized = key.casefold()
                if (
                    normalized.startswith("_vanna_")
                    or normalized in _RESERVED_METADATA_KEYS
                ):
                    raise ValueError("chat metadata contains a reserved key")
                validate(item, depth=depth + 1)
            return
        if isinstance(value, list):
            if len(value) > MAX_PUBLIC_METADATA_ITEMS:
                raise ValueError("chat metadata list exceeds the item limit")
            for item in value:
                validate(item, depth=depth + 1)
            return
        raise ValueError("chat metadata must contain JSON values only")

    validate(metadata, depth=0)
    encoded = json.dumps(
        metadata,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_PUBLIC_METADATA_BYTES:
        raise ValueError("chat metadata exceeds the serialized byte limit")
    return metadata


class ChatRequest(BaseModel):
    """Request model for chat endpoints."""

    message: str = Field(description="User message")
    conversation_id: Optional[str] = Field(default=None, description="Conversation ID")
    request_id: Optional[str] = Field(
        default=None, description="Request ID for tracing"
    )
    request_context: RequestContext = Field(
        default_factory=RequestContext,
        description="Request context for user resolution",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        return validate_public_chat_metadata(value)


class ChatStreamChunk(BaseModel):
    """Single chunk in a streaming chat response."""

    rich: Dict[str, Any] = Field(description="Rich component data for advanced UIs")
    simple: Optional[Dict[str, Any]] = Field(
        default=None, description="Simple component data for basic UIs"
    )

    # Stream metadata
    conversation_id: str = Field(description="Conversation ID")
    request_id: str = Field(description="Request ID")
    timestamp: float = Field(default_factory=time.time, description="Timestamp")

    @classmethod
    def from_component(
        cls,
        component: Union[UiComponent, RichComponent],
        conversation_id: str,
        request_id: str,
    ) -> "ChatStreamChunk":
        """Create chunk from UI component or rich component."""

        if isinstance(component, UiComponent):
            # Full UiComponent with both rich and simple
            rich_data = component.rich_component.serialize_for_frontend()
            simple_data = None
            if component.simple_component:
                simple_data = component.simple_component.serialize_for_frontend()

            return cls(
                rich=rich_data,
                simple=simple_data,
                conversation_id=conversation_id,
                request_id=request_id,
            )

        # Rich component only (no simple fallback)
        rich_data = component.serialize_for_frontend()
        return cls(
            rich=rich_data,
            simple=None,
            conversation_id=conversation_id,
            request_id=request_id,
        )

    @classmethod
    def from_component_update(
        cls, update: ComponentUpdate, conversation_id: str, request_id: str
    ) -> "ChatStreamChunk":
        """Create chunk from component update."""
        update_payload = update.serialize_for_frontend()
        return cls(
            rich=update_payload,
            simple=None,  # Component updates don't have simple representations
            conversation_id=conversation_id,
            request_id=request_id,
        )


class ChatResponse(BaseModel):
    """Complete chat response for polling endpoints."""

    chunks: List[ChatStreamChunk] = Field(description="Response chunks")
    conversation_id: str = Field(description="Conversation ID")
    request_id: str = Field(description="Request ID")
    total_chunks: int = Field(description="Total number of chunks")

    @classmethod
    def from_chunks(cls, chunks: List[ChatStreamChunk]) -> "ChatResponse":
        """Create response from chunks."""
        if not chunks:
            return cls(chunks=[], conversation_id="", request_id="", total_chunks=0)

        return cls(
            chunks=chunks,
            conversation_id=chunks[0].conversation_id,
            request_id=chunks[0].request_id,
            total_chunks=len(chunks),
        )
