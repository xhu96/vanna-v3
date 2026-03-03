"""
Basic agent implementation.
"""

import asyncio
import difflib
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from vanna.capabilities.agent_memory import AgentMemory
from vanna.capabilities.agent_memory.models import (
    TextMemory,
    TextMemorySearchResult,
    ToolMemory,
    ToolMemorySearchResult,
)
from vanna.core import Agent, ToolRegistry, User
from vanna.core.llm import LlmService
from vanna.core.tool import ToolContext
from vanna.core.user.request_context import RequestContext
from vanna.core.user.resolver import UserResolver

_CAMEL_CASE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_WORD_CHARS = re.compile(r"[^a-z0-9]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "get",
    "give",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "of",
    "on",
    "or",
    "please",
    "show",
    "tell",
    "the",
    "to",
    "what",
    "when",
    "where",
    "who",
    "with",
}


class SimpleUserResolver(UserResolver):
    """Simple user resolver that returns a default user."""

    def __init__(self, default_user: Optional[User] = None):
        self.default_user = default_user or User(
            id="default",
            username="default",
            email="default@example.com",
            group_memberships=[],
        )

    async def resolve_user(self, request_context: RequestContext) -> User:
        return self.default_user


class SimpleAgentMemory(AgentMemory):
    """Simple in-memory agent memory implementation (non-persistent).

    Memories survive only for the lifetime of the process. Use a persistent
    AgentMemory backend for cross-session recall.

    The implementation is intentionally dependency-free, but it still provides
    practical lexical retrieval for both tool memories and free-form text
    memories. This makes it suitable for demos, local development, and schema
    grounding when richer vector search is not configured.
    """

    def __init__(self, *, max_items: int = 10_000) -> None:
        self.tool_memories: List[ToolMemory] = []
        self.text_memories: List[TextMemory] = []
        self.max_items = max_items
        self._lock = asyncio.Lock()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _normalize(text: str) -> str:
        if not text:
            return ""

        camel_split = _CAMEL_CASE_BOUNDARY.sub(" ", text)
        lowered = camel_split.lower().replace("_", " ")
        normalized = _NON_WORD_CHARS.sub(" ", lowered)
        return " ".join(normalized.split())

    @classmethod
    def _tokenize(cls, text: str) -> set[str]:
        normalized = cls._normalize(text)
        if not normalized:
            return set()
        return {token for token in normalized.split() if token not in _STOPWORDS}

    @classmethod
    def _similarity(cls, query: str, candidate: str) -> float:
        """Score lexical relevance between a user query and a stored memory.

        The scorer intentionally favors recall for schema-grounding use cases:
        exact/substring matches get a strong boost, while token containment and
        edit similarity provide robust fallbacks for natural-language queries.
        """
        query_normalized = cls._normalize(query)
        candidate_normalized = cls._normalize(candidate)

        if not query_normalized or not candidate_normalized:
            return 0.0

        if query_normalized == candidate_normalized:
            return 1.0

        if query_normalized in candidate_normalized:
            return 0.98

        query_tokens = cls._tokenize(query_normalized)
        candidate_tokens = cls._tokenize(candidate_normalized)

        if not query_tokens or not candidate_tokens:
            token_overlap = 0.0
            query_coverage = 0.0
            jaccard = 0.0
        else:
            overlap = query_tokens & candidate_tokens
            token_overlap = len(overlap) / len(query_tokens)
            jaccard = len(overlap) / len(query_tokens | candidate_tokens)
            query_coverage = len(overlap) / len(query_tokens)

        sequence_ratio = difflib.SequenceMatcher(
            None, query_normalized, candidate_normalized
        ).ratio()

        return min(
            1.0,
            max(
                sequence_ratio,
                (0.65 * query_coverage) + (0.20 * jaccard) + (0.15 * sequence_ratio),
                token_overlap,
            ),
        )

    async def save_tool_usage(
        self,
        question: str,
        tool_name: str,
        args: Dict[str, Any],
        context: ToolContext,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        memory = ToolMemory(
            memory_id=str(uuid.uuid4()),
            question=question,
            tool_name=tool_name,
            args=args,
            success=success,
            metadata=metadata or {},
            timestamp=self._now_iso(),
        )

        async with self._lock:
            self.tool_memories.append(memory)
            if len(self.tool_memories) > self.max_items:
                overflow = len(self.tool_memories) - self.max_items
                del self.tool_memories[:overflow]

    async def save_text_memory(self, content: str, context: ToolContext) -> TextMemory:
        memory = TextMemory(
            memory_id=str(uuid.uuid4()),
            content=content,
            timestamp=self._now_iso(),
        )

        async with self._lock:
            self.text_memories.append(memory)
            if len(self.text_memories) > self.max_items:
                overflow = len(self.text_memories) - self.max_items
                del self.text_memories[:overflow]

        return memory

    async def search_similar_usage(
        self,
        question: str,
        context: ToolContext,
        *,
        limit: int = 10,
        similarity_threshold: float = 0.7,
        tool_name_filter: Optional[str] = None,
    ) -> List[ToolMemorySearchResult]:
        async with self._lock:
            candidates = [
                memory
                for memory in self.tool_memories
                if memory.success
                and (
                    tool_name_filter is None or memory.tool_name == tool_name_filter
                )
            ]

        scored: List[tuple[ToolMemory, float]] = []
        for memory in candidates:
            score = self._similarity(question, memory.question)
            if score >= similarity_threshold:
                scored.append((memory, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return [
            ToolMemorySearchResult(memory=memory, similarity_score=score, rank=index)
            for index, (memory, score) in enumerate(scored[:limit], start=1)
        ]

    async def search_text_memories(
        self,
        query: str,
        context: ToolContext,
        *,
        limit: int = 10,
        similarity_threshold: float = 0.7,
    ) -> List[TextMemorySearchResult]:
        async with self._lock:
            memories = list(self.text_memories)

        scored: List[tuple[TextMemory, float]] = []
        for memory in memories:
            score = self._similarity(query, memory.content)
            if score >= similarity_threshold:
                scored.append((memory, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return [
            TextMemorySearchResult(memory=memory, similarity_score=score, rank=index)
            for index, (memory, score) in enumerate(scored[:limit], start=1)
        ]

    async def get_recent_memories(
        self, context: ToolContext, limit: int = 10
    ) -> List[ToolMemory]:
        async with self._lock:
            return list(reversed(self.tool_memories[-limit:]))

    async def get_recent_text_memories(
        self, context: ToolContext, limit: int = 10
    ) -> List[TextMemory]:
        async with self._lock:
            return list(reversed(self.text_memories[-limit:]))

    async def delete_by_id(self, context: ToolContext, memory_id: str) -> bool:
        async with self._lock:
            for index, memory in enumerate(self.tool_memories):
                if memory.memory_id == memory_id:
                    del self.tool_memories[index]
                    return True
        return False

    async def delete_text_memory(self, context: ToolContext, memory_id: str) -> bool:
        async with self._lock:
            for index, memory in enumerate(self.text_memories):
                if memory.memory_id == memory_id:
                    del self.text_memories[index]
                    return True
        return False

    async def clear_memories(
        self,
        context: ToolContext,
        tool_name: Optional[str] = None,
        before_date: Optional[str] = None,
    ) -> int:
        async with self._lock:
            original_tool_count = len(self.tool_memories)
            original_text_count = len(self.text_memories)

            kept_tool_memories: List[ToolMemory] = []
            for memory in self.tool_memories:
                should_delete = True

                if tool_name and memory.tool_name != tool_name:
                    should_delete = False

                if should_delete and before_date and memory.timestamp:
                    if memory.timestamp >= before_date:
                        should_delete = False

                if tool_name is None and before_date is None:
                    should_delete = True

                if not should_delete:
                    kept_tool_memories.append(memory)

            self.tool_memories = kept_tool_memories
            deleted_tool_count = original_tool_count - len(self.tool_memories)

            kept_text_memories: List[TextMemory] = []
            for memory in self.text_memories:
                should_delete = tool_name is None

                if before_date and memory.timestamp:
                    if memory.timestamp >= before_date:
                        should_delete = False

                if not should_delete:
                    kept_text_memories.append(memory)

            self.text_memories = kept_text_memories
            deleted_text_count = original_text_count - len(self.text_memories)

            return deleted_tool_count + deleted_text_count


def create_basic_agent(llm_service: LlmService) -> Agent:
    """Create a basic agent with default components.

    Args:
        llm_service: LLM service to use

    Returns:
        Configured Agent instance
    """
    return Agent(
        llm_service=llm_service,
        tool_registry=ToolRegistry(),
        user_resolver=SimpleUserResolver(),
        agent_memory=SimpleAgentMemory(),
    )
