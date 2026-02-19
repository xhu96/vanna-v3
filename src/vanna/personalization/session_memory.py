"""
Session memory — ephemeral, auto-expiring per-session memory.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

from .models import SessionMemoryEntry
from .redaction import redact_pii
from .stores import SessionMemoryStore


class SessionMemoryService:
    """Manages ephemeral session memories with auto-expiry and PII redaction."""

    def __init__(
        self,
        store: SessionMemoryStore,
        *,
        retention_days: int = 7,
    ) -> None:
        self._store = store
        self._retention_days = retention_days

    async def save(
        self,
        session_id: str,
        user_id: str,
        tenant_id: str,
        content: str,
    ) -> SessionMemoryEntry:
        """Save a memory after PII redaction with auto-expiry."""
        result = redact_pii(content)
        entry = SessionMemoryEntry(
            session_id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            content=result.text,
            expires_at=datetime.utcnow() + timedelta(days=self._retention_days),
        )
        return await self._store.save(entry)

    async def get_recent(
        self,
        user_id: str,
        session_id: str,
        *,
        limit: int = 20,
    ) -> List[SessionMemoryEntry]:
        return await self._store.get_recent(user_id, session_id, limit=limit)

    async def cleanup_expired(self) -> int:
        """Remove all expired entries."""
        return await self._store.cleanup_expired()
