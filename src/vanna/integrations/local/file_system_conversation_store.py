"""
File system conversation store implementation.

This module provides a file-based implementation of the ConversationStore
interface that persists conversations to disk as a directory structure.
"""

import importlib
import json
import logging
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
from datetime import datetime
import time

from vanna.core.storage import (
    Conversation,
    ConversationAccessDeniedError,
    ConversationAlreadyExistsError,
    ConversationCorruptError,
    ConversationStore,
    InvalidConversationIdError,
    Message,
)
from vanna.core.user import User, same_principal


logger = logging.getLogger(__name__)
_SAFE_CONVERSATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PROCESS_LOCKS: Dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


class FileSystemConversationStore(ConversationStore):
    """File system-based conversation store.

    Stores conversations as directories with individual message files:
    conversations/{conversation_id}/
        metadata.json - conversation metadata (id, user info, timestamps)
        messages/
            {timestamp}_{index}.json - individual message files
    """

    supports_atomic_ownership = True
    supports_atomic_updates = True

    def __init__(self, base_dir: str = "conversations") -> None:
        """Initialize the file system conversation store.

        Args:
            base_dir: Base directory for storing conversations
        """
        self.base_dir = Path(base_dir).expanduser().absolute()
        if any(path.is_symlink() for path in (self.base_dir, *self.base_dir.parents)):
            raise InvalidConversationIdError("Invalid conversation storage root")
        self.base_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.base_dir, 0o700)
        self._locks_dir = self.base_dir / ".locks"
        if self._locks_dir.is_symlink():
            raise InvalidConversationIdError("Invalid conversation storage root")
        self._locks_dir.mkdir(mode=0o700, exist_ok=True)
        os.chmod(self._locks_dir, 0o700)

    @contextmanager
    def _conversation_lock(self, conversation_id: str) -> Iterator[None]:
        """Serialize ownership operations across threads and worker processes."""
        self._validate_conversation_id(conversation_id)
        lock_path = self._locks_dir / f"{conversation_id}.lock"
        lock_key = str(lock_path.resolve())
        with _PROCESS_LOCKS_GUARD:
            process_lock = _PROCESS_LOCKS.setdefault(lock_key, threading.RLock())

        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        os.chmod(lock_path, 0o600)
        with process_lock, os.fdopen(descriptor, "r+b") as lock_file:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)

            if os.name == "nt":  # pragma: no cover - exercised on Windows CI
                msvcrt = importlib.import_module("msvcrt")

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _get_conversation_dir(self, conversation_id: str) -> Path:
        """Get the directory path for a conversation."""
        self._validate_conversation_id(conversation_id)
        candidate = self.base_dir / conversation_id
        if candidate.is_symlink():
            raise InvalidConversationIdError("Invalid conversation identifier")
        resolved_base = self.base_dir.resolve()
        if candidate.resolve(strict=False).parent != resolved_base:
            raise InvalidConversationIdError("Invalid conversation identifier")
        return candidate

    @staticmethod
    def _validate_conversation_id(conversation_id: str) -> None:
        if not _SAFE_CONVERSATION_ID.fullmatch(conversation_id) or conversation_id in {
            ".",
            "..",
        }:
            raise InvalidConversationIdError("Invalid conversation identifier")

    def _get_metadata_path(self, conversation_id: str) -> Path:
        """Get the metadata file path for a conversation."""
        metadata_path = self._get_conversation_dir(conversation_id) / "metadata.json"
        if metadata_path.is_symlink():
            raise ConversationCorruptError("Conversation metadata cannot be trusted")
        return metadata_path

    def _get_messages_dir(self, conversation_id: str) -> Path:
        """Get the messages directory for a conversation."""
        messages_path = self._get_conversation_dir(conversation_id) / "messages"
        if messages_path.is_symlink():
            raise ConversationCorruptError("Conversation messages cannot be trusted")
        return messages_path

    @staticmethod
    def _metadata_payload(conversation: Conversation) -> Dict[str, Any]:
        return {
            "id": conversation.id,
            "user": conversation.user.model_dump(mode="json"),
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
        }

    def _create_metadata(self, conversation: Conversation) -> None:
        """Claim an identifier with an exclusive metadata create."""
        conv_dir = self._get_conversation_dir(conversation.id)
        conv_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(conv_dir, 0o700)
        metadata_path = self._get_metadata_path(conversation.id)
        try:
            descriptor = os.open(
                metadata_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
        except FileExistsError:
            metadata = self._load_metadata(conversation.id)
            if not same_principal(
                User.model_validate(metadata["user"]), conversation.user
            ):
                raise ConversationAccessDeniedError("Conversation access denied")
            raise ConversationAlreadyExistsError("Conversation already exists")

        with os.fdopen(descriptor, "w", encoding="utf-8") as file_handle:
            json.dump(self._metadata_payload(conversation), file_handle, indent=2)
            file_handle.flush()
            os.fsync(file_handle.fileno())

    def _save_metadata(self, conversation: Conversation) -> None:
        """Atomically replace metadata after its owner has been verified."""
        metadata_path = self._get_metadata_path(conversation.id)
        conv_dir = metadata_path.parent
        conv_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(conv_dir, 0o700)

        descriptor, temporary_name = tempfile.mkstemp(
            dir=conv_dir, prefix=".metadata-", suffix=".tmp"
        )
        os.chmod(temporary_name, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file_handle:
                json.dump(self._metadata_payload(conversation), file_handle, indent=2)
                file_handle.flush()
                os.fsync(file_handle.fileno())
            os.replace(temporary_name, metadata_path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def _load_metadata(self, conversation_id: str) -> Dict[str, Any]:
        metadata_path = self._get_metadata_path(conversation_id)
        try:
            os.chmod(metadata_path, 0o600)
            with open(metadata_path, encoding="utf-8") as file_handle:
                metadata = json.load(file_handle)
            if (
                not isinstance(metadata, dict)
                or metadata.get("id") != conversation_id
                or not isinstance(metadata.get("user"), dict)
                or not isinstance(metadata["user"].get("id"), str)
            ):
                raise ValueError("invalid metadata shape")
            return metadata
        except (json.JSONDecodeError, OSError, ValueError, KeyError) as exc:
            raise ConversationCorruptError(
                "Conversation metadata cannot be trusted"
            ) from exc

    def _load_messages(self, conversation_id: str) -> List[Message]:
        """Load all messages for a conversation."""
        messages_dir = self._get_messages_dir(conversation_id)

        if not messages_dir.exists():
            return []
        os.chmod(messages_dir, 0o700)

        messages = []
        # Sort message files by name (timestamp_index ensures correct order)
        message_files = sorted(messages_dir.glob("*.json"))

        for file_path in message_files:
            try:
                if file_path.is_symlink():
                    raise ConversationCorruptError(
                        "Conversation messages cannot be trusted"
                    )
                os.chmod(file_path, 0o600)
                with open(file_path, encoding="utf-8") as file_handle:
                    data = json.load(file_handle)
                message = Message.model_validate(data)
                messages.append(message)
            except (json.JSONDecodeError, ValueError) as e:
                raise ConversationCorruptError(
                    "Conversation messages cannot be trusted"
                ) from e

        return messages

    def _append_message(
        self, conversation_id: str, message: Message, index: int
    ) -> None:
        """Append one owner-only message file without following links."""

        messages_dir = self._get_messages_dir(conversation_id)
        messages_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(messages_dir, 0o700)

        timestamp = int(time.time() * 1000000)
        file_path = messages_dir / f"{timestamp}_{index:06d}.json"
        descriptor = os.open(
            file_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as file_handle:
            json.dump(message.model_dump(mode="json"), file_handle, indent=2)
            file_handle.flush()
            os.fsync(file_handle.fileno())

    async def claim_conversation(
        self, conversation_id: str, user: User
    ) -> Tuple[Conversation, bool]:
        """Atomically return the owned conversation or claim an absent ID."""

        with self._conversation_lock(conversation_id):
            existing = self._get_conversation_unlocked(conversation_id, user)
            if existing is not None:
                return existing, False
            conversation = Conversation(id=conversation_id, user=user, messages=[])
            self._create_metadata(conversation)
            return conversation, True

    async def create_conversation(
        self, conversation_id: str, user: User, initial_message: str
    ) -> Conversation:
        """Create a new conversation without replacing an allocated ID."""
        conversation = Conversation(
            id=conversation_id,
            user=user,
            messages=[Message(role="user", content=initial_message)],
        )

        with self._conversation_lock(conversation_id):
            self._create_metadata(conversation)
            self._append_message(conversation_id, conversation.messages[0], 0)
            conversation.base_message_count = len(conversation.messages)

        return conversation

    def _get_conversation_unlocked(
        self, conversation_id: str, user: User
    ) -> Optional[Conversation]:
        metadata_path = self._get_metadata_path(conversation_id)
        if not metadata_path.exists():
            return None

        metadata = self._load_metadata(conversation_id)
        if not same_principal(User.model_validate(metadata["user"]), user):
            raise ConversationAccessDeniedError("Conversation access denied")

        try:
            conversation = Conversation(
                id=metadata["id"],
                user=User.model_validate(metadata["user"]),
                messages=self._load_messages(conversation_id),
                created_at=datetime.fromisoformat(metadata["created_at"]),
                updated_at=datetime.fromisoformat(metadata["updated_at"]),
            )
            conversation.base_message_count = len(conversation.messages)
            return conversation
        except (ValueError, KeyError) as exc:
            raise ConversationCorruptError(
                "Conversation metadata cannot be trusted"
            ) from exc

    async def get_conversation(
        self, conversation_id: str, user: User
    ) -> Optional[Conversation]:
        """Get a consistent conversation snapshot scoped to its owner."""
        with self._conversation_lock(conversation_id):
            return self._get_conversation_unlocked(conversation_id, user)

    async def update_conversation(self, conversation: Conversation) -> None:
        """Update or create a conversation without changing its owner."""
        await self.update_conversation_for_user(conversation, conversation.user)

    async def update_conversation_for_user(
        self, conversation: Conversation, user: User
    ) -> None:
        """Update using the resolved actor rather than caller-supplied ownership."""
        if not same_principal(conversation.user, user):
            raise ConversationAccessDeniedError("Conversation access denied")

        with self._conversation_lock(conversation.id):
            conversation.updated_at = datetime.now()
            base_count = conversation.base_message_count
            if base_count > len(conversation.messages):
                raise ValueError("Conversation base message count is invalid")
            new_messages = conversation.messages[base_count:]

            metadata_path = self._get_metadata_path(conversation.id)
            if metadata_path.exists():
                metadata = self._load_metadata(conversation.id)
                if not same_principal(User.model_validate(metadata["user"]), user):
                    raise ConversationAccessDeniedError("Conversation access denied")
                self._save_metadata(conversation)
            else:
                # Preserve the historical upsert contract while claiming absent IDs
                # exclusively, so concurrent users cannot overwrite one another.
                self._create_metadata(conversation)

            existing_messages = self._load_messages(conversation.id)
            existing_count = len(existing_messages)
            for i, message in enumerate(new_messages, start=existing_count):
                self._append_message(conversation.id, message, i)
            conversation.base_message_count = len(conversation.messages)

    async def delete_conversation(self, conversation_id: str, user: User) -> bool:
        """Delete conversation."""
        with self._conversation_lock(conversation_id):
            conv_dir = self._get_conversation_dir(conversation_id)
            if not conv_dir.exists():
                return False

            conversation = self._get_conversation_unlocked(conversation_id, user)
            if not conversation:
                return False

            try:
                messages_dir = self._get_messages_dir(conversation_id)
                if messages_dir.exists():
                    for file_path in messages_dir.glob("*.json"):
                        file_path.unlink()
                    messages_dir.rmdir()

                metadata_path = self._get_metadata_path(conversation_id)
                if metadata_path.exists():
                    metadata_path.unlink()
                conv_dir.rmdir()
                return True
            except OSError:
                logger.warning("Failed to delete conversation %s", conversation_id)
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
                with self._conversation_lock(conv_dir.name):
                    conversation = self._get_conversation_unlocked(conv_dir.name, user)
                    if conversation is not None:
                        conversations.append(conversation)
            except ConversationAccessDeniedError:
                continue
            except (
                ConversationCorruptError,
                InvalidConversationIdError,
                ValueError,
                KeyError,
            ):
                logger.warning("Failed to load conversation from %s", conv_dir)
                continue

        # Sort by updated_at desc
        conversations.sort(key=lambda x: x.updated_at, reverse=True)

        # Apply pagination
        return conversations[offset : offset + limit]
