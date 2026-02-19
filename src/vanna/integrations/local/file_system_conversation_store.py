"""
File system conversation store implementation.

This module provides a file-based implementation of the ConversationStore
interface that persists conversations to disk as a directory structure.
"""

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone
import time

from vanna.core.storage import ConversationStore, Conversation, Message
from vanna.core.user import User

logger = logging.getLogger(__name__)


def _ensure_utc(dt: datetime) -> datetime:
    """Coerce naive datetimes to UTC.

    This keeps backward compatibility with older persisted data that used
    naive UTC timestamps.
    """

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_iso_datetime(value: str) -> datetime:
    return _ensure_utc(datetime.fromisoformat(value))


def _atomic_write_json(path: Path, payload: Dict) -> None:
    """Atomically write JSON to disk (tempfile + replace)."""

    path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        delete=False,
        dir=str(path.parent),
        prefix=path.name,
        suffix=".tmp",
    ) as tmp:
        json.dump(payload, tmp, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)

    os.replace(tmp_path, path)


class FileSystemConversationStore(ConversationStore):
    """File system-based conversation store.

    Stores conversations as directories with individual message files:
    conversations/{conversation_id}/
        metadata.json - conversation metadata (id, user info, timestamps)
        messages/
            {timestamp}_{index}.json - individual message files
    """

    def __init__(self, base_dir: str = "conversations") -> None:
        """Initialize the file system conversation store.

        Args:
            base_dir: Base directory for storing conversations
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_conversation_dir(self, conversation_id: str) -> Path:
        """Get the directory path for a conversation."""
        return self.base_dir / conversation_id

    def _get_metadata_path(self, conversation_id: str) -> Path:
        """Get the metadata file path for a conversation."""
        return self._get_conversation_dir(conversation_id) / "metadata.json"

    def _get_messages_dir(self, conversation_id: str) -> Path:
        """Get the messages directory for a conversation."""
        return self._get_conversation_dir(conversation_id) / "messages"

    def _save_metadata(self, conversation: Conversation) -> None:
        """Save conversation metadata to disk."""
        conv_dir = self._get_conversation_dir(conversation.id)
        conv_dir.mkdir(parents=True, exist_ok=True)

        metadata = {
            "id": conversation.id,
            "user": conversation.user.model_dump(mode="json"),
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
        }

        metadata_path = self._get_metadata_path(conversation.id)
        _atomic_write_json(metadata_path, metadata)

    def _load_messages(self, conversation_id: str) -> List[Message]:
        """Load all messages for a conversation."""
        messages_dir = self._get_messages_dir(conversation_id)

        if not messages_dir.exists():
            return []

        messages = []
        # Sort message files by name (timestamp_index ensures correct order)
        message_files = sorted(messages_dir.glob("*.json"))

        for file_path in message_files:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                message = Message.model_validate(data)
                messages.append(message)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("Failed to load message from %s: %s", file_path, e)
                continue

        return messages

    def _append_message(
        self, conversation_id: str, message: Message, index: int
    ) -> None:
        """Append a message to the conversation."""
        messages_dir = self._get_messages_dir(conversation_id)
        messages_dir.mkdir(parents=True, exist_ok=True)

        # Use timestamp + index to ensure unique, ordered filenames.
        # time_ns reduces collision risk under concurrency.
        timestamp = time.time_ns()
        filename = f"{timestamp}_{index:06d}.json"
        file_path = messages_dir / filename

        _atomic_write_json(file_path, message.model_dump(mode="json"))

    async def create_conversation(
        self, conversation_id: str, user: User, initial_message: str
    ) -> Conversation:
        """Create a new conversation with the specified ID."""
        conversation = Conversation(
            id=conversation_id,
            user=user,
            messages=[Message(role="user", content=initial_message)],
        )

        # Save metadata
        self._save_metadata(conversation)

        # Save initial message
        self._append_message(conversation_id, conversation.messages[0], 0)

        return conversation

    async def get_conversation(
        self, conversation_id: str, user: User
    ) -> Optional[Conversation]:
        """Get conversation by ID, scoped to user."""
        metadata_path = self._get_metadata_path(conversation_id)

        if not metadata_path.exists():
            return None

        try:
            # Load metadata
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)

            # Verify ownership
            if metadata["user"]["id"] != user.id:
                return None

            # Load all messages
            messages = self._load_messages(conversation_id)

            # Reconstruct conversation
            conversation = Conversation(
                id=metadata["id"],
                user=User.model_validate(metadata["user"]),
                messages=messages,
                created_at=_parse_iso_datetime(metadata["created_at"]),
                updated_at=_parse_iso_datetime(metadata["updated_at"]),
            )

            return conversation
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning("Failed to load conversation %s: %s", conversation_id, e)
            return None

    async def update_conversation(self, conversation: Conversation) -> None:
        """Update conversation with new messages."""
        # Update the updated_at timestamp
        conversation.updated_at = datetime.now(timezone.utc)

        # Save updated metadata
        self._save_metadata(conversation)

        # Get existing messages count to determine new message indices
        existing_messages = self._load_messages(conversation.id)
        existing_count = len(existing_messages)

        # Only append new messages (ones not already saved)
        for i, message in enumerate(
            conversation.messages[existing_count:], start=existing_count
        ):
            self._append_message(conversation.id, message, i)

    async def delete_conversation(self, conversation_id: str, user: User) -> bool:
        """Delete conversation."""
        conv_dir = self._get_conversation_dir(conversation_id)

        if not conv_dir.exists():
            return False

        # Verify ownership before deleting
        conversation = await self.get_conversation(conversation_id, user)
        if not conversation:
            return False

        try:
            # Safety: ensure the directory to delete is inside base_dir.
            conv_dir_resolved = conv_dir.resolve()
            conv_dir_resolved.relative_to(self.base_dir.resolve())
        except Exception:
            logger.error("Refusing to delete path outside base_dir: %s", conv_dir)
            return False

        try:
            shutil.rmtree(conv_dir)
            return True
        except OSError as e:
            logger.warning("Failed to delete conversation %s: %s", conversation_id, e)
            return False

    async def list_conversations(
        self, user: User, limit: int = 50, offset: int = 0
    ) -> List[Conversation]:
        """List conversations for user."""
        if not self.base_dir.exists():
            return []

        conversations = []

        # Iterate through all conversation directories
        for conv_dir in self.base_dir.iterdir():
            if not conv_dir.is_dir():
                continue

            metadata_path = conv_dir / "metadata.json"
            if not metadata_path.exists():
                continue

            try:
                # Load metadata
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)

                # Skip conversations not owned by this user
                if metadata["user"]["id"] != user.id:
                    continue

                # Load messages
                messages = self._load_messages(conv_dir.name)

                # Reconstruct conversation
                conversation = Conversation(
                    id=metadata["id"],
                    user=User.model_validate(metadata["user"]),
                    messages=messages,
                    created_at=_parse_iso_datetime(metadata["created_at"]),
                    updated_at=_parse_iso_datetime(metadata["updated_at"]),
                )
                conversations.append(conversation)
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                logger.warning("Failed to load conversation from %s: %s", conv_dir, e)
                continue

        # Sort by updated_at desc
        conversations.sort(key=lambda x: x.updated_at, reverse=True)

        # Apply pagination
        return conversations[offset : offset + limit]
