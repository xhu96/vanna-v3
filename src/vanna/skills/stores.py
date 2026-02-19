"""
Storage interfaces and in-memory implementations for the Skill Registry.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .models import (
    SkillAuditEntry,
    SkillEnvironment,
    SkillRegistryEntry,
)


class SkillRegistryStore(ABC):
    """Persistent store for skill registry entries."""

    @abstractmethod
    async def register(self, entry: SkillRegistryEntry) -> SkillRegistryEntry:
        ...

    @abstractmethod
    async def get(self, skill_id: str) -> Optional[SkillRegistryEntry]:
        ...

    @abstractmethod
    async def list_skills(
        self,
        *,
        tenant_id: Optional[str] = None,
        environment: Optional[SkillEnvironment] = None,
        enabled_only: bool = False,
    ) -> List[SkillRegistryEntry]:
        ...

    @abstractmethod
    async def update(self, entry: SkillRegistryEntry) -> SkillRegistryEntry:
        ...

    @abstractmethod
    async def delete(self, skill_id: str) -> bool:
        ...

    @abstractmethod
    async def get_audit_log(self, skill_id: str) -> List[SkillAuditEntry]:
        ...


class InMemorySkillRegistryStore(SkillRegistryStore):
    """Non-persistent, in-memory reference implementation."""

    def __init__(self) -> None:
        self._entries: Dict[str, SkillRegistryEntry] = {}

    async def register(self, entry: SkillRegistryEntry) -> SkillRegistryEntry:
        self._entries[entry.skill_id] = entry
        return entry

    async def get(self, skill_id: str) -> Optional[SkillRegistryEntry]:
        return self._entries.get(skill_id)

    async def list_skills(
        self,
        *,
        tenant_id: Optional[str] = None,
        environment: Optional[SkillEnvironment] = None,
        enabled_only: bool = False,
    ) -> List[SkillRegistryEntry]:
        results: List[SkillRegistryEntry] = []
        for entry in self._entries.values():
            if tenant_id is not None and entry.tenant_id != tenant_id:
                continue
            if environment is not None and entry.environment != environment:
                continue
            if enabled_only and not entry.enabled:
                continue
            results.append(entry)
        return results

    async def update(self, entry: SkillRegistryEntry) -> SkillRegistryEntry:
        entry.updated_at = datetime.now(timezone.utc)
        self._entries[entry.skill_id] = entry
        return entry

    async def delete(self, skill_id: str) -> bool:
        if skill_id in self._entries:
            del self._entries[skill_id]
            return True
        return False

    async def get_audit_log(self, skill_id: str) -> List[SkillAuditEntry]:
        entry = self._entries.get(skill_id)
        if entry is None:
            return []
        return list(entry.audit_log)
