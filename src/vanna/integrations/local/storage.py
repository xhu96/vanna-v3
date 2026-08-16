"""
In-memory conversation store implementation.

This module provides a simple in-memory implementation of the ConversationStore
interface, useful for testing and development.
"""

import threading
from typing import Dict, List, Optional, Tuple

from vanna.core.storage import (
    Conversation,
    ConversationAccessDeniedError,
    ConversationAlreadyExistsError,
    ConversationStore,
    Message,
)
from vanna.core.user import User
from vanna.core.user import same_principal


class MemoryConversationStore(ConversationStore):
    """In-memory conversation store."""

    supports_atomic_ownership = True
    supports_atomic_updates = True

    def __init__(self) -> None:
        self._conversations: Dict[str, Conversation] = {}
        self._lock = threading.RLock()

    async def claim_conversation(
        self, conversation_id: str, user: User
    ) -> Tuple[Conversation, bool]:
        """Atomically return the owned conversation or claim an absent ID."""

        with self._lock:
            existing = self._conversations.get(conversation_id)
            if existing is not None:
                if not same_principal(existing.user, user):
                    raise ConversationAccessDeniedError("Conversation access denied")
                snapshot = existing.model_copy(deep=True)
                snapshot.base_message_count = len(snapshot.messages)
                return snapshot, False
            conversation = Conversation(id=conversation_id, user=user, messages=[])
            self._conversations[conversation_id] = conversation.model_copy(deep=True)
            return conversation, True

    async def create_conversation(
        self, conversation_id: str, user: User, initial_message: str
    ) -> Conversation:
        """Create a conversation without replacing an existing owner."""
        with self._lock:
            existing = self._conversations.get(conversation_id)
            if existing is not None:
                if not same_principal(existing.user, user):
                    raise ConversationAccessDeniedError("Conversation access denied")
                raise ConversationAlreadyExistsError("Conversation already exists")

            conversation = Conversation(
                id=conversation_id,
                user=user,
                messages=[Message(role="user", content=initial_message)],
            )
            self._conversations[conversation_id] = conversation.model_copy(deep=True)
            conversation.base_message_count = len(conversation.messages)
            return conversation

    async def get_conversation(
        self, conversation_id: str, user: User
    ) -> Optional[Conversation]:
        """Get conversation by ID, scoped to user."""
        with self._lock:
            conversation = self._conversations.get(conversation_id)
            if conversation is None:
                return None
            if not same_principal(conversation.user, user):
                raise ConversationAccessDeniedError("Conversation access denied")
            snapshot = conversation.model_copy(deep=True)
            snapshot.base_message_count = len(snapshot.messages)
            return snapshot

    async def update_conversation(self, conversation: Conversation) -> None:
        """Update or create without allowing an ownership change."""
        await self.update_conversation_for_user(conversation, conversation.user)

    async def update_conversation_for_user(
        self, conversation: Conversation, user: User
    ) -> None:
        """Update using the resolved actor rather than caller-supplied ownership."""
        with self._lock:
            if not same_principal(conversation.user, user):
                raise ConversationAccessDeniedError("Conversation access denied")
            existing = self._conversations.get(conversation.id)
            if existing is not None and not same_principal(existing.user, user):
                raise ConversationAccessDeniedError("Conversation access denied")
            base_count = conversation.base_message_count
            if base_count > len(conversation.messages):
                raise ValueError("Conversation base message count is invalid")
            new_messages = [
                message.model_copy(deep=True)
                for message in conversation.messages[base_count:]
            ]
            if existing is None:
                if base_count:
                    raise ConversationAlreadyExistsError(
                        "Conversation snapshot has no persisted base"
                    )
                persisted = conversation.model_copy(deep=True)
            else:
                persisted = existing.model_copy(deep=True)
                persisted.messages.extend(new_messages)
                persisted.metadata.update(conversation.metadata)
                persisted.updated_at = max(existing.updated_at, conversation.updated_at)
            self._conversations[conversation.id] = persisted
            conversation.base_message_count = len(conversation.messages)

    async def delete_conversation(self, conversation_id: str, user: User) -> bool:
        """Delete conversation."""
        with self._lock:
            conversation = self._conversations.get(conversation_id)
            if conversation is None:
                return False
            if not same_principal(conversation.user, user):
                raise ConversationAccessDeniedError("Conversation access denied")
            del self._conversations[conversation_id]
            return True

    async def list_conversations(
        self, user: User, limit: int = 50, offset: int = 0
    ) -> List[Conversation]:
        """List conversations for user."""
        with self._lock:
            user_conversations = [
                conv
                for conv in self._conversations.values()
                if same_principal(conv.user, user)
            ]
            user_conversations.sort(key=lambda x: x.updated_at, reverse=True)
            return [
                conversation.model_copy(deep=True)
                for conversation in user_conversations[offset : offset + limit]
            ]
