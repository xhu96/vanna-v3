"""
Demo in-memory implementation of AgentMemory.

This implementation provides a zero-dependency, minimal storage solution that
keeps all memories in RAM. It uses simple similarity algorithms (Jaccard and
difflib) instead of vector embeddings. Perfect for demos and testing.
"""

from __future__ import annotations

import asyncio
import difflib
import math
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from vanna.capabilities.agent_memory import (
    AgentMemory,
    TextMemory,
    TextMemorySearchResult,
    ToolMemory,
    ToolMemorySearchResult,
    memory_scope_for_context,
    principal_memory_scope_for_context,
)
from vanna.core.tool import ToolContext


class DemoAgentMemory(AgentMemory):
    """
    Minimal, dependency-free in-memory storage for demos and testing.
    - O(n) search over an in-memory list
    - Simple similarity: max(Jaccard(token sets), difflib ratio)
    - Optional FIFO eviction via max_items
    - Async-safe with an asyncio.Lock
    """

    supports_tenant_isolation = True
    supports_keyed_text_memory_upsert = True
    supports_keyed_tool_memory_upsert = True
    supports_tenant_keyed_tool_memory_upsert = True

    def __init__(self, *, max_items: int = 10_000):
        """
        Initialize the in-memory storage.

        Args:
            max_items: Maximum number of memories to keep. Oldest memories are
                      evicted when this limit is reached (FIFO).
        """
        self._memories: List[ToolMemory] = []
        self._text_memories: List[TextMemory] = []
        self._lock = asyncio.Lock()
        self._max_items = max_items

    @staticmethod
    def _now_iso() -> str:
        """Get current timestamp in ISO format."""
        return datetime.now().isoformat()

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize text by lowercasing and collapsing whitespace."""
        return " ".join(text.lower().split())

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Simple tokenizer that splits on whitespace."""
        return set(text.lower().split())

    @classmethod
    def _similarity(cls, a: str, b: str) -> float:
        """
        Calculate similarity between two strings using multiple methods.

        Returns the maximum of Jaccard similarity and difflib ratio.
        """
        a_norm, b_norm = cls._normalize(a), cls._normalize(b)

        # Jaccard over whitespace tokens
        ta, tb = cls._tokenize(a_norm), cls._tokenize(b_norm)
        if not ta and not tb:
            jaccard = 1.0
        elif not ta or not tb:
            jaccard = 0.0
        else:
            jaccard = len(ta & tb) / max(1, len(ta | tb))

        # difflib ratio
        ratio = difflib.SequenceMatcher(None, a_norm, b_norm).ratio()

        # Take the better of the two cheap measures
        return max(jaccard, ratio)

    async def save_tool_usage(
        self,
        question: str,
        tool_name: str,
        args: Dict[str, Any],
        context: ToolContext,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Save a tool usage pattern for future reference."""
        await self._store_tool_usage(
            question,
            tool_name,
            args,
            context,
            success=success,
            metadata=metadata,
            tenant_wide=False,
        )

    async def _store_tool_usage(
        self,
        question: str,
        tool_name: str,
        args: Dict[str, Any],
        context: ToolContext,
        *,
        success: bool,
        metadata: Optional[Dict[str, Any]],
        tenant_wide: bool,
    ) -> None:
        scoped_metadata = dict(metadata or {})
        tenant_scope = memory_scope_for_context(context)
        principal_scope = principal_memory_scope_for_context(context)
        visibility = "tenant" if tenant_wide else "principal"
        scope_identity = tenant_scope if tenant_wide else principal_scope
        scoped_metadata["tenant_scope"] = tenant_scope
        scoped_metadata["principal_scope"] = principal_scope
        scoped_metadata["memory_visibility"] = visibility
        scoped_metadata["user_id"] = context.user.id
        idempotency_key = scoped_metadata.get("idempotency_key")
        if (
            isinstance(idempotency_key, str)
            and 0 < len(idempotency_key) <= 256
            and not any(ord(character) < 32 for character in idempotency_key)
        ):
            memory_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    "vanna-tool-memory:"
                    f"{visibility}:{scope_identity}:{idempotency_key}",
                )
            )
        else:
            memory_id = str(uuid.uuid4())
        tm = ToolMemory(
            memory_id=memory_id,
            question=question,
            tool_name=tool_name,
            args=args,
            timestamp=self._now_iso(),
            success=success,
            metadata=scoped_metadata,
        )
        async with self._lock:
            self._memories = [
                memory for memory in self._memories if memory.memory_id != memory_id
            ]
            self._memories.append(tm)
            # Optional FIFO eviction
            if len(self._memories) > self._max_items:
                overflow = len(self._memories) - self._max_items
                del self._memories[:overflow]

    async def save_text_memory(self, content: str, context: ToolContext) -> TextMemory:
        """Store a text memory in RAM."""
        return await self._store_text_memory(content, context)

    async def upsert_tool_usage(
        self,
        question: str,
        tool_name: str,
        args: Dict[str, Any],
        context: ToolContext,
        *,
        memory_key: str,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Idempotently replace one principal-scoped logical tool memory."""

        if (
            not memory_key
            or len(memory_key) > 256
            or any(ord(character) < 32 for character in memory_key)
        ):
            raise ValueError("memory_key must be a bounded printable string")
        await self.save_tool_usage(
            question,
            tool_name,
            args,
            context,
            success=success,
            metadata={**(metadata or {}), "idempotency_key": memory_key},
        )

    async def upsert_tenant_tool_usage(
        self,
        question: str,
        tool_name: str,
        args: Dict[str, Any],
        context: ToolContext,
        *,
        memory_key: str,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Idempotently replace one tenant-visible feedback memory."""

        if (
            not memory_key
            or len(memory_key) > 256
            or any(ord(character) < 32 for character in memory_key)
        ):
            raise ValueError("memory_key must be a bounded printable string")
        await self._store_tool_usage(
            question,
            tool_name,
            args,
            context,
            success=success,
            metadata={**(metadata or {}), "idempotency_key": memory_key},
            tenant_wide=True,
        )

    async def upsert_text_memory(
        self,
        content: str,
        context: ToolContext,
        *,
        memory_key: str,
    ) -> TextMemory:
        """Idempotently replace one tenant-scoped logical text memory."""

        if (
            not memory_key
            or len(memory_key) > 1200
            or any(ord(character) < 32 for character in memory_key)
        ):
            raise ValueError("memory_key must be a bounded printable string")
        tenant_scope = memory_scope_for_context(context)
        memory_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"vanna-text-memory:{tenant_scope}:{memory_key}",
            )
        )
        return await self._store_text_memory(
            content,
            context,
            memory_id=memory_id,
            memory_key=memory_key,
        )

    async def _store_text_memory(
        self,
        content: str,
        context: ToolContext,
        *,
        memory_id: Optional[str] = None,
        memory_key: Optional[str] = None,
    ) -> TextMemory:
        tm = TextMemory(
            memory_id=memory_id or str(uuid.uuid4()),
            content=content,
            timestamp=self._now_iso(),
            metadata={
                "tenant_scope": memory_scope_for_context(context),
                "user_id": context.user.id,
                **({"memory_key": memory_key} if memory_key is not None else {}),
            },
        )
        async with self._lock:
            self._text_memories = [
                memory
                for memory in self._text_memories
                if memory.memory_id != tm.memory_id
            ]
            self._text_memories.append(tm)
            if len(self._text_memories) > self._max_items:
                overflow = len(self._text_memories) - self._max_items
                del self._text_memories[:overflow]
        return tm

    async def search_similar_usage(
        self,
        question: str,
        context: ToolContext,
        *,
        limit: int = 10,
        similarity_threshold: float = 0.7,
        tool_name_filter: Optional[str] = None,
    ) -> List[ToolMemorySearchResult]:
        """Search for similar tool usage patterns based on a question."""
        q = self._normalize(question)
        tenant_scope = memory_scope_for_context(context)
        principal_scope = principal_memory_scope_for_context(context)

        async with self._lock:
            scoped = [
                memory
                for memory in self._memories
                if memory.metadata
                and memory.metadata.get("tenant_scope") == tenant_scope
                and (
                    memory.metadata.get("memory_visibility") == "tenant"
                    or memory.metadata.get("principal_scope") == principal_scope
                )
                and memory.metadata.get("active", True) is not False
            ]
            rejected_sql = {
                self._normalized_sql(memory)
                for memory in scoped
                if not memory.success
                and memory.metadata
                and memory.metadata.get("patch_type") == "negative"
                and self._similarity(q, memory.question) >= similarity_threshold
            }
            rejected_sql.discard(None)

            # Ordinary memories remain principal-scoped. Validated feedback is
            # tenant-visible, and negative feedback suppresses the same SQL.
            candidates = [
                m
                for m in scoped
                if m.success
                and (tool_name_filter is None or m.tool_name == tool_name_filter)
                and self._normalized_sql(m) not in rejected_sql
            ]

            # Score each candidate by question similarity, then weight by feedback.
            results: List[tuple[ToolMemory, float, float, int, str, str]] = []
            for m in candidates:
                similarity = min(self._similarity(q, m.question), 1.0)
                weight = 1.0
                if m.metadata and isinstance(m.metadata.get("weight"), (int, float)):
                    weight = float(m.metadata["weight"])
                if not math.isfinite(weight):
                    weight = 1.0
                weight = min(max(weight, 0.0), 10.0)
                effective = similarity * weight
                patch_priority = (
                    1
                    if m.metadata and m.metadata.get("patch_type") == "corrective"
                    else 0
                )
                results.append(
                    (
                        m,
                        similarity,
                        effective,
                        patch_priority,
                        m.timestamp or "",
                        m.memory_id or "",
                    )
                )

            # Filter on raw similarity, rank by effective (similarity * weight).
            results = [r for r in results if r[1] >= similarity_threshold]
            results.sort(
                key=lambda item: (item[3], item[2], item[4], item[5]), reverse=True
            )

            out: List[ToolMemorySearchResult] = []
            for idx, result in enumerate(results[:limit], start=1):
                m, similarity = result[0], result[1]
                out.append(
                    ToolMemorySearchResult(
                        memory=m, similarity_score=similarity, rank=idx
                    )
                )
            return out

    async def search_text_memories(
        self,
        query: str,
        context: ToolContext,
        *,
        limit: int = 10,
        similarity_threshold: float = 0.7,
    ) -> List[TextMemorySearchResult]:
        """Search free-form text memories using the demo similarity metric."""
        normalized_query = self._normalize(query)
        tenant_scope = memory_scope_for_context(context)

        async with self._lock:
            scored: List[tuple[TextMemory, float]] = []
            for memory in self._text_memories:
                if (
                    not memory.metadata
                    or memory.metadata.get("tenant_scope") != tenant_scope
                ):
                    continue
                score = self._similarity(normalized_query, memory.content)
                scored.append((memory, min(score, 1.0)))

            scored = [
                (memory, score)
                for memory, score in scored
                if score >= similarity_threshold
            ]
            scored.sort(key=lambda item: item[1], reverse=True)

            results: List[TextMemorySearchResult] = []
            for idx, (memory, score) in enumerate(scored[:limit], start=1):
                results.append(
                    TextMemorySearchResult(
                        memory=memory, similarity_score=score, rank=idx
                    )
                )
            return results

    async def get_recent_memories(
        self, context: ToolContext, limit: int = 10
    ) -> List[ToolMemory]:
        """Get recently added memories. Returns most recent memories first."""
        principal_scope = principal_memory_scope_for_context(context)
        async with self._lock:
            scoped = [
                memory
                for memory in self._memories
                if memory.metadata
                and memory.metadata.get("principal_scope") == principal_scope
            ]
            return list(reversed(scoped[-limit:]))

    async def get_recent_text_memories(
        self, context: ToolContext, limit: int = 10
    ) -> List[TextMemory]:
        """Return recently added text memories."""
        tenant_scope = memory_scope_for_context(context)
        async with self._lock:
            scoped = [
                memory
                for memory in self._text_memories
                if memory.metadata
                and memory.metadata.get("tenant_scope") == tenant_scope
            ]
            return list(reversed(scoped[-limit:]))

    async def delete_text_memory(self, context: ToolContext, memory_id: str) -> bool:
        """Delete a stored text memory by ID."""
        tenant_scope = memory_scope_for_context(context)
        async with self._lock:
            for index, memory in enumerate(self._text_memories):
                if (
                    memory.memory_id == memory_id
                    and memory.metadata
                    and memory.metadata.get("tenant_scope") == tenant_scope
                ):
                    del self._text_memories[index]
                    return True
            return False

    async def delete_by_id(self, context: ToolContext, memory_id: str) -> bool:
        """Delete a memory by its ID. Returns True if deleted, False if not found."""
        principal_scope = principal_memory_scope_for_context(context)
        async with self._lock:
            for i, m in enumerate(self._memories):
                if (
                    m.memory_id == memory_id
                    and m.metadata
                    and m.metadata.get("principal_scope") == principal_scope
                ):
                    del self._memories[i]
                    return True
            return False

    async def clear_memories(
        self,
        context: ToolContext,
        tool_name: Optional[str] = None,
        before_date: Optional[str] = None,
    ) -> int:
        """Clear stored memories. Returns number of memories deleted."""
        tenant_scope = memory_scope_for_context(context)
        principal_scope = principal_memory_scope_for_context(context)
        async with self._lock:
            original_tool_count = len(self._memories)
            original_text_count = len(self._text_memories)

            # Filter memories to keep
            kept_memories = []
            for m in self._memories:
                if (
                    not m.metadata
                    or m.metadata.get("principal_scope") != principal_scope
                ):
                    kept_memories.append(m)
                    continue
                should_delete = True

                # Check tool name filter
                if tool_name and m.tool_name != tool_name:
                    should_delete = False

                # Check date filter
                if should_delete and before_date and m.timestamp:
                    if m.timestamp >= before_date:
                        should_delete = False

                # If no filters specified, delete all
                if tool_name is None and before_date is None:
                    should_delete = True

                # Keep if should not delete
                if not should_delete:
                    kept_memories.append(m)

            self._memories = kept_memories
            deleted_tool_count = original_tool_count - len(self._memories)

            # Apply filters to text memories (tool filter ignored)
            kept_text_memories = []
            for memory in self._text_memories:
                if (
                    not memory.metadata
                    or memory.metadata.get("tenant_scope") != tenant_scope
                ):
                    kept_text_memories.append(memory)
                    continue
                should_delete = (
                    tool_name is None
                )  # only delete text when not targeting a tool

                if before_date and memory.timestamp:
                    if memory.timestamp >= before_date:
                        should_delete = False

                if not should_delete:
                    kept_text_memories.append(memory)

            self._text_memories = kept_text_memories
            deleted_text_count = original_text_count - len(self._text_memories)

            return deleted_tool_count + deleted_text_count

    @classmethod
    def _normalized_sql(cls, memory: ToolMemory) -> Optional[str]:
        if memory.metadata:
            normalized = memory.metadata.get("normalized_sql")
            if isinstance(normalized, str) and normalized:
                return normalized
        sql = memory.args.get("sql")
        return cls._normalize(sql).rstrip(";") if isinstance(sql, str) else None
