"""
Agent memory capability interface for tool usage learning.

This module contains the abstract base class for agent memory operations,
following the same pattern as the FileSystem interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from vanna.core.tool import ToolContext
    from .models import (
        ToolMemorySearchResult,
        TextMemory,
        TextMemorySearchResult,
        ToolMemory,
    )


class AgentMemory(ABC):
    """Abstract base class for agent memory operations."""

    # Legacy vector backends must opt in only after every read, write, and delete
    # operation enforces authenticated tenant/principal scope.
    supports_tenant_isolation: bool = False
    # Schema drift patches require deterministic replacement by logical entity.
    # Backends must opt in only when retries upsert the same tenant-scoped record.
    supports_keyed_text_memory_upsert: bool = False
    # Feedback retries require deterministic replacement by one logical patch key.
    supports_keyed_tool_memory_upsert: bool = False
    # Reviewed and immediate feedback patches can intentionally benefit every
    # authenticated principal in one tenant. This remains a separate capability
    # so ordinary tool-memory writes cannot accidentally widen their scope.
    supports_tenant_keyed_tool_memory_upsert: bool = False

    @abstractmethod
    async def save_tool_usage(
        self,
        question: str,
        tool_name: str,
        args: Dict[str, Any],
        context: "ToolContext",
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Save a tool usage pattern for future reference."""
        pass

    @abstractmethod
    async def save_text_memory(
        self, content: str, context: "ToolContext"
    ) -> "TextMemory":
        """Save a free-form text memory."""
        pass

    async def upsert_tool_usage(
        self,
        question: str,
        tool_name: str,
        args: Dict[str, Any],
        context: "ToolContext",
        *,
        memory_key: str,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Replace one tenant/principal-scoped tool memory by logical key.

        This optional V3 capability is required by the feedback outbox. Backends
        must not opt in unless a retry of the same key replaces exactly one
        record rather than appending another influence entry.
        """

        del question, tool_name, args, context, memory_key, success, metadata
        raise NotImplementedError("keyed tool-memory upsert is not supported")

    async def upsert_tenant_tool_usage(
        self,
        question: str,
        tool_name: str,
        args: Dict[str, Any],
        context: "ToolContext",
        *,
        memory_key: str,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Replace one tenant-visible tool memory by logical key.

        This optional V3 capability is reserved for trusted services such as the
        validated feedback workflow. Principal-scoped writes remain the default.
        """

        del question, tool_name, args, context, memory_key, success, metadata
        raise NotImplementedError("tenant keyed tool-memory upsert is not supported")

    async def upsert_text_memory(
        self,
        content: str,
        context: "ToolContext",
        *,
        memory_key: str,
    ) -> "TextMemory":
        """Replace a tenant-scoped text memory by a stable logical key.

        This is optional for V2 compatibility. Callers that require exactly-once
        schema state must check ``supports_keyed_text_memory_upsert`` first.
        """

        del content, context, memory_key
        raise NotImplementedError("keyed text-memory upsert is not supported")

    @abstractmethod
    async def search_similar_usage(
        self,
        question: str,
        context: "ToolContext",
        *,
        limit: int = 10,
        similarity_threshold: float = 0.7,
        tool_name_filter: Optional[str] = None,
    ) -> List[ToolMemorySearchResult]:
        """Search for similar tool usage patterns based on a question."""
        pass

    @abstractmethod
    async def search_text_memories(
        self,
        query: str,
        context: "ToolContext",
        *,
        limit: int = 10,
        similarity_threshold: float = 0.7,
    ) -> List["TextMemorySearchResult"]:
        """Search stored text memories based on a query."""
        pass

    @abstractmethod
    async def get_recent_memories(
        self, context: "ToolContext", limit: int = 10
    ) -> List[ToolMemory]:
        """Get recently added memories. Returns most recent memories first."""
        pass

    @abstractmethod
    async def get_recent_text_memories(
        self, context: "ToolContext", limit: int = 10
    ) -> List["TextMemory"]:
        """Fetch recently stored text memories."""
        pass

    @abstractmethod
    async def delete_by_id(self, context: "ToolContext", memory_id: str) -> bool:
        """Delete a memory by its ID. Returns True if deleted, False if not found."""
        pass

    @abstractmethod
    async def delete_text_memory(self, context: "ToolContext", memory_id: str) -> bool:
        """Delete a text memory by its ID. Returns True if deleted, False if not found."""
        pass

    @abstractmethod
    async def clear_memories(
        self,
        context: "ToolContext",
        tool_name: Optional[str] = None,
        before_date: Optional[str] = None,
    ) -> int:
        """Clear stored memories (tool or text). Returns number of memories deleted."""
        pass
