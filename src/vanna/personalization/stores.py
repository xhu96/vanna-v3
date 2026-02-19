"""
Storage interfaces and in-memory implementations for the personalization subsystem.

All stores follow the ABC pattern for pluggable backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .models import GlossaryEntry, SessionMemoryEntry, TenantProfile, UserProfile


# ---------------------------------------------------------------------------
# Profile Store
# ---------------------------------------------------------------------------


class ProfileStore(ABC):
    """Persistent store for user and tenant profiles."""

    # --- User profiles ---

    @abstractmethod
    async def get_user_profile(
        self, user_id: str, tenant_id: str
    ) -> Optional[UserProfile]:
        ...

    @abstractmethod
    async def upsert_user_profile(self, profile: UserProfile) -> UserProfile:
        ...

    @abstractmethod
    async def delete_user_profile(self, user_id: str, tenant_id: str) -> bool:
        ...

    @abstractmethod
    async def export_user_profile(
        self, user_id: str, tenant_id: str
    ) -> Optional[dict]:
        """Return JSON-serialisable dict of all stored profile data."""
        ...

    # --- Tenant profiles ---

    @abstractmethod
    async def get_tenant_profile(self, tenant_id: str) -> Optional[TenantProfile]:
        ...

    @abstractmethod
    async def upsert_tenant_profile(self, profile: TenantProfile) -> TenantProfile:
        ...


class InMemoryProfileStore(ProfileStore):
    """Non-persistent, in-memory reference implementation."""

    def __init__(self) -> None:
        self._user_profiles: Dict[Tuple[str, str], UserProfile] = {}
        self._tenant_profiles: Dict[str, TenantProfile] = {}

    async def get_user_profile(
        self, user_id: str, tenant_id: str
    ) -> Optional[UserProfile]:
        return self._user_profiles.get((user_id, tenant_id))

    async def upsert_user_profile(self, profile: UserProfile) -> UserProfile:
        profile.updated_at = datetime.now(timezone.utc)
        self._user_profiles[(profile.user_id, profile.tenant_id)] = profile
        return profile

    async def delete_user_profile(self, user_id: str, tenant_id: str) -> bool:
        key = (user_id, tenant_id)
        if key in self._user_profiles:
            del self._user_profiles[key]
            return True
        return False

    async def export_user_profile(
        self, user_id: str, tenant_id: str
    ) -> Optional[dict]:
        profile = self._user_profiles.get((user_id, tenant_id))
        if profile is None:
            return None
        return profile.model_dump(mode="json")

    async def get_tenant_profile(self, tenant_id: str) -> Optional[TenantProfile]:
        return self._tenant_profiles.get(tenant_id)

    async def upsert_tenant_profile(self, profile: TenantProfile) -> TenantProfile:
        profile.updated_at = datetime.now(timezone.utc)
        self._tenant_profiles[profile.tenant_id] = profile
        return profile


# ---------------------------------------------------------------------------
# Glossary Store
# ---------------------------------------------------------------------------


class GlossaryStore(ABC):
    """Persistent store for glossary / ontology entries."""

    @abstractmethod
    async def list_entries(
        self,
        tenant_id: str,
        *,
        user_id: Optional[str] = None,
        category: Optional[str] = None,
        approved_only: bool = False,
    ) -> List[GlossaryEntry]:
        ...

    @abstractmethod
    async def get_entry(self, entry_id: str) -> Optional[GlossaryEntry]:
        ...

    @abstractmethod
    async def create_entry(self, entry: GlossaryEntry) -> GlossaryEntry:
        ...

    @abstractmethod
    async def update_entry(self, entry: GlossaryEntry) -> GlossaryEntry:
        ...

    @abstractmethod
    async def delete_entry(self, entry_id: str) -> bool:
        ...

    @abstractmethod
    async def search_entries(
        self, tenant_id: str, query: str, *, limit: int = 20
    ) -> List[GlossaryEntry]:
        """Simple substring / keyword search for glossary terms."""
        ...


class InMemoryGlossaryStore(GlossaryStore):
    """Non-persistent, in-memory reference implementation."""

    def __init__(self) -> None:
        self._entries: Dict[str, GlossaryEntry] = {}

    async def list_entries(
        self,
        tenant_id: str,
        *,
        user_id: Optional[str] = None,
        category: Optional[str] = None,
        approved_only: bool = False,
    ) -> List[GlossaryEntry]:
        results: List[GlossaryEntry] = []
        for entry in self._entries.values():
            if entry.tenant_id != tenant_id:
                continue
            if user_id is not None and entry.user_id != user_id:
                # Include tenant-level entries (user_id=None) plus user overrides
                if entry.user_id is not None:
                    continue
            if category is not None and entry.category != category:
                continue
            if approved_only and not entry.approved:
                continue
            results.append(entry)
        return results

    async def get_entry(self, entry_id: str) -> Optional[GlossaryEntry]:
        return self._entries.get(entry_id)

    async def create_entry(self, entry: GlossaryEntry) -> GlossaryEntry:
        self._entries[entry.entry_id] = entry
        return entry

    async def update_entry(self, entry: GlossaryEntry) -> GlossaryEntry:
        entry.updated_at = datetime.now(timezone.utc)
        self._entries[entry.entry_id] = entry
        return entry

    async def delete_entry(self, entry_id: str) -> bool:
        if entry_id in self._entries:
            del self._entries[entry_id]
            return True
        return False

    async def search_entries(
        self, tenant_id: str, query: str, *, limit: int = 20
    ) -> List[GlossaryEntry]:
        query_lower = query.lower()
        results: List[GlossaryEntry] = []
        for entry in self._entries.values():
            if entry.tenant_id != tenant_id:
                continue
            if (
                query_lower in entry.term.lower()
                or query_lower in entry.definition.lower()
                or any(query_lower in s.lower() for s in entry.synonyms)
            ):
                results.append(entry)
                if len(results) >= limit:
                    break
        return results


# ---------------------------------------------------------------------------
# Session Memory Store
# ---------------------------------------------------------------------------


class SessionMemoryStore(ABC):
    """Store for ephemeral, auto-expiring session memories."""

    @abstractmethod
    async def save(self, entry: SessionMemoryEntry) -> SessionMemoryEntry:
        ...

    @abstractmethod
    async def get_recent(
        self, user_id: str, session_id: str, *, limit: int = 20
    ) -> List[SessionMemoryEntry]:
        ...

    @abstractmethod
    async def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count of deleted rows."""
        ...


class InMemorySessionMemoryStore(SessionMemoryStore):
    """Non-persistent, in-memory reference implementation."""

    def __init__(self) -> None:
        self._entries: List[SessionMemoryEntry] = []

    async def save(self, entry: SessionMemoryEntry) -> SessionMemoryEntry:
        self._entries.append(entry)
        return entry

    async def get_recent(
        self, user_id: str, session_id: str, *, limit: int = 20
    ) -> List[SessionMemoryEntry]:
        now = datetime.now(timezone.utc)
        results = [
            e
            for e in self._entries
            if e.user_id == user_id
            and e.session_id == session_id
            and e.expires_at > now
        ]
        results.sort(key=lambda e: e.created_at, reverse=True)
        return results[:limit]

    async def cleanup_expired(self) -> int:
        now = datetime.now(timezone.utc)
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.expires_at > now]
        return before - len(self._entries)
