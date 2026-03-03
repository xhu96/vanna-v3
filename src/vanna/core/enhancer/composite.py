"""
Composite LLM context enhancer that chains multiple enhancers sequentially.

Use this to compose enhancers — e.g. memory-based context + personalization
preferences — into a single ``LlmContextEnhancer`` accepted by the Agent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

from .base import LlmContextEnhancer

if TYPE_CHECKING:
    from ..llm.models import LlmMessage
    from ..user.models import User


class CompositeEnhancer(LlmContextEnhancer):
    """Chains multiple ``LlmContextEnhancer`` instances sequentially.

    Each enhancer receives the output of the previous one, allowing
    additive context injection without conflict.

    Example::

        from vanna.core.enhancer import CompositeEnhancer, DefaultLlmContextEnhancer
        from vanna.personalization.preference_resolver import PreferenceResolverEnhancer

        enhancer = CompositeEnhancer([
            DefaultLlmContextEnhancer(agent_memory),
            PreferenceResolverEnhancer(profile_store, glossary_store),
        ])
        agent = Agent(llm_service=..., llm_context_enhancer=enhancer)
    """

    def __init__(self, enhancers: List[LlmContextEnhancer]) -> None:
        self._enhancers = list(enhancers)

    async def enhance_system_prompt(
        self, system_prompt: str, user_message: str, user: "User"
    ) -> str:
        for enhancer in self._enhancers:
            system_prompt = await enhancer.enhance_system_prompt(
                system_prompt, user_message, user
            )
        return system_prompt

    async def enhance_user_messages(
        self, messages: list["LlmMessage"], user: "User"
    ) -> list["LlmMessage"]:
        for enhancer in self._enhancers:
            messages = await enhancer.enhance_user_messages(messages, user)
        return messages
