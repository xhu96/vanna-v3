"""
Skill Registry — lifecycle management for skills.

Handles registration, versioning, enable/disable, environment transitions,
rollback, and audit logging for skill entries.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import (
    SkillAuditEntry,
    SkillEnvironment,
    SkillRegistryEntry,
    SkillSpec,
)
from .stores import SkillRegistryStore


class SkillRegistryError(Exception):
    """Raised on invalid registry operations."""


class SkillAuthorizationError(Exception):
    """Raised when a user lacks the required role."""


# Valid promotion paths
_PROMOTION_ORDER = [
    SkillEnvironment.DRAFT,
    SkillEnvironment.TESTED,
    SkillEnvironment.APPROVED,
    SkillEnvironment.DEFAULT,
]


class SkillRegistry:
    """Manages skill lifecycle: register, promote, enable/disable, rollback."""

    def __init__(
        self,
        store: SkillRegistryStore,
        *,
        publish_roles: Optional[List[str]] = None,
    ) -> None:
        self._store = store
        self._publish_roles = set(publish_roles or ["admin"])

    def _check_publish_role(self, actor_groups: List[str]) -> None:
        if not (set(actor_groups) & self._publish_roles):
            raise SkillAuthorizationError(
                f"Requires one of roles: {sorted(self._publish_roles)}"
            )

    async def register_skill(
        self,
        spec: SkillSpec,
        *,
        actor: str,
        tenant_id: Optional[str] = None,
    ) -> SkillRegistryEntry:
        """Register a new skill as draft. No role check required for draft creation."""
        entry = SkillRegistryEntry(
            skill_spec=spec,
            environment=SkillEnvironment.DRAFT,
            enabled=True,
            tenant_id=tenant_id or spec.tenant_id,
            created_by=actor,
        )
        entry.audit_log.append(
            SkillAuditEntry(
                action="created",
                actor=actor,
                to_env=SkillEnvironment.DRAFT,
            )
        )
        return await self._store.register(entry)

    async def get_skill(self, skill_id: str) -> Optional[SkillRegistryEntry]:
        return await self._store.get(skill_id)

    async def list_skills(
        self,
        *,
        tenant_id: Optional[str] = None,
        environment: Optional[SkillEnvironment] = None,
        enabled_only: bool = False,
    ) -> List[SkillRegistryEntry]:
        return await self._store.list_skills(
            tenant_id=tenant_id,
            environment=environment,
            enabled_only=enabled_only,
        )

    async def enable_skill(
        self, skill_id: str, *, actor: str
    ) -> SkillRegistryEntry:
        entry = await self._store.get(skill_id)
        if entry is None:
            raise SkillRegistryError(f"Skill {skill_id} not found")
        entry.enabled = True
        entry.audit_log.append(
            SkillAuditEntry(action="enabled", actor=actor)
        )
        return await self._store.update(entry)

    async def disable_skill(
        self, skill_id: str, *, actor: str
    ) -> SkillRegistryEntry:
        entry = await self._store.get(skill_id)
        if entry is None:
            raise SkillRegistryError(f"Skill {skill_id} not found")
        entry.enabled = False
        entry.audit_log.append(
            SkillAuditEntry(action="disabled", actor=actor)
        )
        return await self._store.update(entry)

    async def promote_skill(
        self,
        skill_id: str,
        target_env: SkillEnvironment,
        *,
        actor: str,
        actor_groups: Optional[List[str]] = None,
    ) -> SkillRegistryEntry:
        """Promote a skill to the next environment. Requires appropriate role."""
        # Promotion beyond draft requires publish role
        if target_env != SkillEnvironment.DRAFT:
            self._check_publish_role(actor_groups or [])

        entry = await self._store.get(skill_id)
        if entry is None:
            raise SkillRegistryError(f"Skill {skill_id} not found")

        # Validate promotion path
        current_idx = _PROMOTION_ORDER.index(entry.environment)
        target_idx = _PROMOTION_ORDER.index(target_env)
        if target_idx != current_idx + 1:
            raise SkillRegistryError(
                f"Cannot promote from {entry.environment.value} to {target_env.value}. "
                f"Next valid target is {_PROMOTION_ORDER[current_idx + 1].value}."
            )

        from_env = entry.environment
        entry.environment = target_env
        entry.skill_spec.environment = target_env
        entry.audit_log.append(
            SkillAuditEntry(
                action="promoted",
                actor=actor,
                from_env=from_env,
                to_env=target_env,
            )
        )
        return await self._store.update(entry)

    async def rollback_skill(
        self,
        skill_id: str,
        target_env: SkillEnvironment,
        *,
        actor: str,
        actor_groups: Optional[List[str]] = None,
    ) -> SkillRegistryEntry:
        """Rollback a skill to a previous environment."""
        self._check_publish_role(actor_groups or [])

        entry = await self._store.get(skill_id)
        if entry is None:
            raise SkillRegistryError(f"Skill {skill_id} not found")

        current_idx = _PROMOTION_ORDER.index(entry.environment)
        target_idx = _PROMOTION_ORDER.index(target_env)
        if target_idx >= current_idx:
            raise SkillRegistryError(
                f"Rollback target {target_env.value} must be before current {entry.environment.value}"
            )

        from_env = entry.environment
        entry.environment = target_env
        entry.skill_spec.environment = target_env
        entry.audit_log.append(
            SkillAuditEntry(
                action="rolled_back",
                actor=actor,
                from_env=from_env,
                to_env=target_env,
            )
        )
        return await self._store.update(entry)

    async def delete_skill(
        self,
        skill_id: str,
        *,
        actor: str,
        actor_groups: Optional[List[str]] = None,
    ) -> bool:
        self._check_publish_role(actor_groups or [])
        entry = await self._store.get(skill_id)
        if entry is not None:
            entry.audit_log.append(
                SkillAuditEntry(action="deleted", actor=actor)
            )
            await self._store.update(entry)
        return await self._store.delete(skill_id)

    async def get_audit_log(
        self, skill_id: str
    ) -> List[SkillAuditEntry]:
        return await self._store.get_audit_log(skill_id)
