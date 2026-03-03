"""
Default LLM context enhancer implementation using AgentMemory.

This implementation enriches the system prompt with relevant memories
based on the user's initial message.
"""

from typing import TYPE_CHECKING, List, Optional

from .base import LlmContextEnhancer

if TYPE_CHECKING:
    from ..llm.models import LlmMessage
    from ..user.models import User
    from ...capabilities.agent_memory import AgentMemory, TextMemorySearchResult


class DefaultLlmContextEnhancer(LlmContextEnhancer):
    """Default enhancer that uses AgentMemory to add relevant context.

    This enhancer searches the agent's memory for relevant examples and
    text snippets based on the user's message and adds them to the system prompt.
    A relatively low default similarity threshold is intentional here: natural
    language questions often only partially overlap with schema-oriented text
    memories, so retrieval should optimize for recall.
    """

    def __init__(
        self,
        agent_memory: Optional["AgentMemory"] = None,
        *,
        memory_search_limit: int = 5,
        memory_similarity_threshold: float = 0.3,
    ):
        """Initialize with optional agent memory.

        Args:
            agent_memory: Optional AgentMemory instance. If not provided,
                enhancement will be skipped.
            memory_search_limit: Maximum number of memories to inject.
            memory_similarity_threshold: Similarity threshold used when
                retrieving candidate text memories.
        """
        self.agent_memory = agent_memory
        self.memory_search_limit = memory_search_limit
        self.memory_similarity_threshold = memory_similarity_threshold

    async def enhance_system_prompt(
        self, system_prompt: str, user_message: str, user: "User"
    ) -> str:
        """Enhance system prompt with relevant memories."""
        if not self.agent_memory:
            return system_prompt

        try:
            import uuid

            from ..tool import ToolContext

            context = ToolContext(
                user=user,
                conversation_id="temp",
                request_id=str(uuid.uuid4()),
                agent_memory=self.agent_memory,
            )

            memories: List[
                "TextMemorySearchResult"
            ] = await self.agent_memory.search_text_memories(
                query=user_message,
                context=context,
                limit=self.memory_search_limit,
                similarity_threshold=self.memory_similarity_threshold,
            )

            if not memories:
                return system_prompt

            unique_contents: list[str] = []
            for result in memories:
                content = result.memory.content.strip()
                if content and content not in unique_contents:
                    unique_contents.append(content)

            if not unique_contents:
                return system_prompt

            examples_section = "\n\n## Relevant Context from Memory\n\n"
            examples_section += (
                "The following domain knowledge and context from prior "
                "interactions may be relevant:\n\n"
            )
            for content in unique_contents:
                examples_section += f"• {content}\n"

            return system_prompt + examples_section

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to enhance system prompt with memories: {e}")
            return system_prompt

    async def enhance_user_messages(
        self, messages: list["LlmMessage"], user: "User"
    ) -> list["LlmMessage"]:
        """Enhance user messages.

        The default implementation doesn't modify user messages.
        Override this to add context to user messages if needed.
        """
        return messages
