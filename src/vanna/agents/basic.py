"""
Basic agent implementation.
"""

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
    """Simple in-memory agent memory implementation (non-persistent)."""

    def __init__(self) -> None:
        self.tool_memories: List[Dict[str, Any]] = []
        self.text_memories: List[TextMemory] = []

    async def save_tool_usage(
        self,
        question: str,
        tool_name: str,
        args: Dict[str, Any],
        context: ToolContext,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        pass

    async def save_text_memory(self, content: str, context: ToolContext) -> TextMemory:
        # Return a dummy memory
        return TextMemory(
            id="dummy",
            content=content,
            user_id=context.user.id,
            timestamp=0,
        )

    async def search_similar_usage(
        self,
        question: str,
        context: ToolContext,
        *,
        limit: int = 10,
        similarity_threshold: float = 0.7,
        tool_name_filter: Optional[str] = None,
    ) -> List[ToolMemorySearchResult]:
        return []

    async def search_text_memories(
        self,
        query: str,
        context: ToolContext,
        *,
        limit: int = 10,
        similarity_threshold: float = 0.7,
    ) -> List[TextMemorySearchResult]:
        return []

    async def get_recent_memories(
        self, context: ToolContext, limit: int = 10
    ) -> List[ToolMemory]:
        return []

    async def get_recent_text_memories(
        self, context: ToolContext, limit: int = 10
    ) -> List[TextMemory]:
        return []

    async def delete_by_id(self, context: ToolContext, memory_id: str) -> bool:
        return False

    async def delete_text_memory(self, context: ToolContext, memory_id: str) -> bool:
        return False

    async def clear_memories(
        self,
        context: ToolContext,
        tool_name: Optional[str] = None,
        before_date: Optional[str] = None,
    ) -> int:
        return 0


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
