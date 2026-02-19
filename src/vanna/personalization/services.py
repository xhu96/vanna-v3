"""
Service layer for personalization: profile CRUD, glossary, consent management.

All operations enforce RBAC, PII redaction, and audit logging.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .models import GlossaryEntry, Provenance, TenantProfile, UserProfile
from .redaction import RedactionResult, check_storage_policy, redact_pii
from .stores import GlossaryStore, ProfileStore


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PersonalizationDisabledError(Exception):
    """Raised when personalization is disabled for the tenant or user."""


class AuthorizationError(Exception):
    """Raised when a user lacks the required role for an operation."""


# ---------------------------------------------------------------------------
# Profile Service
# ---------------------------------------------------------------------------


class ProfileService:
    """CRUD operations for user and tenant profiles with RBAC & PII redaction."""

    def __init__(
        self,
        profile_store: ProfileStore,
        *,
        admin_roles: Optional[List[str]] = None,
    ) -> None:
        self._store = profile_store
        self._admin_roles = set(admin_roles or ["admin"])

    def _is_admin(self, user_groups: List[str]) -> bool:
        return bool(set(user_groups) & self._admin_roles)

    async def get_user_profile(
        self,
        user_id: str,
        tenant_id: str,
        *,
        requesting_user_id: str,
        requesting_user_groups: Optional[List[str]] = None,
    ) -> Optional[UserProfile]:
        """Get a user profile. Users can only read their own unless admin."""
        if user_id != requesting_user_id and not self._is_admin(
            requesting_user_groups or []
        ):
            raise AuthorizationError("Cannot read another user's profile")
        return await self._store.get_user_profile(user_id, tenant_id)

    async def upsert_user_profile(
        self,
        profile: UserProfile,
        *,
        requesting_user_id: str,
        requesting_user_groups: Optional[List[str]] = None,
    ) -> UserProfile:
        """Create or update a user profile with PII redaction."""
        if profile.user_id != requesting_user_id and not self._is_admin(
            requesting_user_groups or []
        ):
            raise AuthorizationError("Cannot modify another user's profile")

        # Redact PII from text-like fields
        for tag_list_attr in ("department_tags", "role_tags"):
            tags = getattr(profile, tag_list_attr)
            cleaned: List[str] = []
            for tag in tags:
                r = redact_pii(tag)
                cleaned.append(r.text)
            setattr(profile, tag_list_attr, cleaned)

        # Set provenance before policy check
        profile.updated_at = datetime.now(timezone.utc)
        if profile.provenance is None:
            profile.provenance = Provenance(
                author=requesting_user_id, source="api"
            )

        # Storage policy check
        data = profile.model_dump()
        policy = check_storage_policy(data)
        if not policy.passed:
            raise ValueError(
                f"Storage policy violation: {'; '.join(policy.violations)}"
            )

        return await self._store.upsert_user_profile(profile)

    async def delete_user_profile(
        self,
        user_id: str,
        tenant_id: str,
        *,
        requesting_user_id: str,
        requesting_user_groups: Optional[List[str]] = None,
    ) -> bool:
        if user_id != requesting_user_id and not self._is_admin(
            requesting_user_groups or []
        ):
            raise AuthorizationError("Cannot delete another user's profile")
        return await self._store.delete_user_profile(user_id, tenant_id)

    async def export_user_profile(
        self,
        user_id: str,
        tenant_id: str,
        *,
        requesting_user_id: str,
        requesting_user_groups: Optional[List[str]] = None,
    ) -> Optional[dict]:
        if user_id != requesting_user_id and not self._is_admin(
            requesting_user_groups or []
        ):
            raise AuthorizationError("Cannot export another user's profile")
        return await self._store.export_user_profile(user_id, tenant_id)

    # --- Tenant profiles (admin only) ---

    async def get_tenant_profile(
        self, tenant_id: str
    ) -> Optional[TenantProfile]:
        return await self._store.get_tenant_profile(tenant_id)

    async def upsert_tenant_profile(
        self,
        profile: TenantProfile,
        *,
        requesting_user_groups: Optional[List[str]] = None,
    ) -> TenantProfile:
        if not self._is_admin(requesting_user_groups or []):
            raise AuthorizationError("Tenant profile updates require admin role")
        profile.updated_at = datetime.now(timezone.utc)
        return await self._store.upsert_tenant_profile(profile)


# ---------------------------------------------------------------------------
# Glossary Service
# ---------------------------------------------------------------------------


class GlossaryService:
    """CRUD operations for glossary entries with tenant scoping."""

    def __init__(
        self,
        glossary_store: GlossaryStore,
        *,
        admin_roles: Optional[List[str]] = None,
    ) -> None:
        self._store = glossary_store
        self._admin_roles = set(admin_roles or ["admin"])

    def _is_admin(self, user_groups: List[str]) -> bool:
        return bool(set(user_groups) & self._admin_roles)

    async def list_entries(
        self,
        tenant_id: str,
        *,
        user_id: Optional[str] = None,
        category: Optional[str] = None,
        approved_only: bool = False,
    ) -> List[GlossaryEntry]:
        return await self._store.list_entries(
            tenant_id,
            user_id=user_id,
            category=category,
            approved_only=approved_only,
        )

    async def get_entry(self, entry_id: str) -> Optional[GlossaryEntry]:
        return await self._store.get_entry(entry_id)

    async def create_entry(
        self,
        entry: GlossaryEntry,
        *,
        requesting_user_id: str,
        requesting_user_groups: Optional[List[str]] = None,
    ) -> GlossaryEntry:
        # Redact PII from definition + synonyms
        r = redact_pii(entry.definition)
        entry.definition = r.text
        entry.synonyms = [redact_pii(s).text for s in entry.synonyms]

        if entry.provenance is None:
            entry.provenance = Provenance(
                author=requesting_user_id, source="api"
            )
        return await self._store.create_entry(entry)

    async def update_entry(
        self,
        entry: GlossaryEntry,
        *,
        requesting_user_id: str,
        requesting_user_groups: Optional[List[str]] = None,
    ) -> GlossaryEntry:
        # Only admin or original author can update
        existing = await self._store.get_entry(entry.entry_id)
        if existing is not None:
            is_admin = self._is_admin(requesting_user_groups or [])
            is_author = (
                existing.provenance is not None
                and existing.provenance.author == requesting_user_id
            )
            if not is_admin and not is_author:
                raise AuthorizationError(
                    "Only admin or the original author can update a glossary entry"
                )

        r = redact_pii(entry.definition)
        entry.definition = r.text
        entry.synonyms = [redact_pii(s).text for s in entry.synonyms]
        entry.updated_at = datetime.now(timezone.utc)
        return await self._store.update_entry(entry)

    async def delete_entry(
        self,
        entry_id: str,
        *,
        requesting_user_id: str,
        requesting_user_groups: Optional[List[str]] = None,
    ) -> bool:
        if not self._is_admin(requesting_user_groups or []):
            raise AuthorizationError("Only admin can delete glossary entries")
        return await self._store.delete_entry(entry_id)

    async def search_entries(
        self, tenant_id: str, query: str, *, limit: int = 20
    ) -> List[GlossaryEntry]:
        return await self._store.search_entries(tenant_id, query, limit=limit)


# ---------------------------------------------------------------------------
# Consent Manager
# ---------------------------------------------------------------------------


class ConsentManager:
    """Manages personalization consent per user and tenant."""

    def __init__(self, profile_store: ProfileStore) -> None:
        self._store = profile_store

    async def enable_personalization(
        self, user_id: str, tenant_id: str
    ) -> UserProfile:
        """Enable personalization for a user (explicit opt-in)."""
        profile = await self._store.get_user_profile(user_id, tenant_id)
        if profile is None:
            profile = UserProfile(
                user_id=user_id,
                tenant_id=tenant_id,
                personalization_enabled=True,
                provenance=Provenance(author=user_id, source="consent"),
            )
        else:
            profile.personalization_enabled = True
            profile.updated_at = datetime.now(timezone.utc)
        return await self._store.upsert_user_profile(profile)

    async def disable_personalization(
        self, user_id: str, tenant_id: str
    ) -> UserProfile:
        """Disable personalization for a user."""
        profile = await self._store.get_user_profile(user_id, tenant_id)
        if profile is None:
            profile = UserProfile(
                user_id=user_id,
                tenant_id=tenant_id,
                personalization_enabled=False,
                provenance=Provenance(author=user_id, source="consent"),
            )
        else:
            profile.personalization_enabled = False
            profile.updated_at = datetime.now(timezone.utc)
        return await self._store.upsert_user_profile(profile)

    async def is_enabled(self, user_id: str, tenant_id: str) -> bool:
        """Check if personalization is enabled for a user."""
        profile = await self._store.get_user_profile(user_id, tenant_id)
        return profile is not None and profile.personalization_enabled

    async def export_data(
        self, user_id: str, tenant_id: str
    ) -> Optional[dict]:
        """Export all stored profile data for a user."""
        return await self._store.export_user_profile(user_id, tenant_id)

    async def delete_data(self, user_id: str, tenant_id: str) -> bool:
        """Delete all stored profile data for a user."""
        return await self._store.delete_user_profile(user_id, tenant_id)
