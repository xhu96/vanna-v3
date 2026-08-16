"""
Storage domain interface.

This module contains the abstract base class for conversation storage.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from .models import Conversation
from ..user.models import User
from ..user.scope import same_principal


class ConversationStoreError(RuntimeError):
    """Base error for fail-closed conversation storage operations."""


class ConversationAccessDeniedError(ConversationStoreError):
    """Raised when a caller attempts to access another user's conversation."""


class ConversationAlreadyExistsError(ConversationStoreError):
    """Raised when a conversation identifier is already allocated."""


class ConversationCorruptError(ConversationStoreError):
    """Raised when persisted conversation state cannot be trusted."""


class InvalidConversationIdError(ConversationStoreError, ValueError):
    """Raised when an identifier cannot be mapped to safe local storage."""


class ConversationStore(ABC):
    """Abstract base class for conversation storage."""

    supports_atomic_ownership: bool = False
    supports_atomic_updates: bool = False

    async def claim_conversation(
        self, conversation_id: str, user: User
    ) -> Tuple[Conversation, bool]:
        """Load or claim an identifier, returning ``(conversation, created)``.

        This compatibility implementation preserves V2 stores but is not atomic.
        Stores admitted to a production server must override it atomically.
        """

        conversation = await self.get_conversation(conversation_id, user)
        if conversation is not None:
            return conversation, False
        conversation = Conversation(id=conversation_id, user=user, messages=[])
        await self.update_conversation_for_user(conversation, user)
        return conversation, True

    @abstractmethod
    async def create_conversation(
        self, conversation_id: str, user: User, initial_message: str
    ) -> Conversation:
        """Create a conversation without replacing an allocated identifier."""
        pass

    @abstractmethod
    async def get_conversation(
        self, conversation_id: str, user: User
    ) -> Optional[Conversation]:
        """Return an owned conversation, None if absent, or deny foreign access."""
        pass

    @abstractmethod
    async def update_conversation(self, conversation: Conversation) -> None:
        """Update a conversation without changing its persisted owner."""
        pass

    async def update_conversation_for_user(
        self, conversation: Conversation, user: User
    ) -> None:
        """Compatibility bridge for actor-aware updates.

        Built-in production-capable stores override this method atomically.
        Legacy stores retain their V2 behavior but are not eligible for
        production mode until they implement the ownership contract.
        """
        if not same_principal(conversation.user, user):
            raise ConversationAccessDeniedError("Conversation access denied")
        await self.update_conversation(conversation)

    @abstractmethod
    async def delete_conversation(self, conversation_id: str, user: User) -> bool:
        """Delete conversation."""
        pass

    @abstractmethod
    async def list_conversations(
        self, user: User, limit: int = 50, offset: int = 0
    ) -> List[Conversation]:
        """List conversations for user."""
        pass
