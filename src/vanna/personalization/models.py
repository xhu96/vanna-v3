"""
Pydantic models for the personalization subsystem.

Provides durable, explicit-field models for user/tenant profiles,
glossary entries, and ephemeral session memory. No free-form blobs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Provenance(BaseModel):
    """Tracks who created or modified a record, and when."""

    author: str = Field(description="User or system that created/modified this record")
    source: str = Field(
        default="api", description="Origin of the change (api, import, migration)"
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class UserProfile(BaseModel):
    """Durable, privacy-safe user preferences.

    All fields are explicit (no free-form metadata blobs).
    Raw query results and PII must NOT be stored here.
    """

    user_id: str = Field(description="Unique user identifier")
    tenant_id: str = Field(description="Tenant this profile belongs to")

    # Locale / formatting
    locale: Optional[str] = Field(
        default=None, description="IETF locale tag, e.g. en-US"
    )
    currency: Optional[str] = Field(
        default=None, description="ISO 4217 currency code, e.g. USD"
    )
    fiscal_year_start_month: Optional[int] = Field(
        default=None, ge=1, le=12, description="Month fiscal year starts (1-12)"
    )
    date_format: Optional[str] = Field(
        default=None, description="Preferred date format, e.g. YYYY-MM-DD"
    )
    number_format: Optional[str] = Field(
        default=None,
        description="Preferred number format, e.g. 1,000.00 or 1.000,00",
    )

    # Organisational tags (non-sensitive)
    department_tags: List[str] = Field(
        default_factory=list, description="Non-sensitive department tags"
    )
    role_tags: List[str] = Field(
        default_factory=list, description="Non-sensitive role tags"
    )

    # Presentation defaults
    preferred_chart_type: Optional[str] = Field(
        default=None, description="Default chart type (bar, line, pie, …)"
    )
    preferred_table_style: Optional[str] = Field(
        default=None, description="Default table style (compact, full, …)"
    )

    # Consent
    personalization_enabled: bool = Field(
        default=False,
        description="Explicit opt-in flag; profile is inactive when False",
    )

    # Provenance & timestamps
    provenance: Optional[Provenance] = Field(
        default=None, description="Who created / last modified this profile"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TenantProfile(BaseModel):
    """Tenant-wide defaults that individual user profiles can override."""

    tenant_id: str = Field(description="Unique tenant identifier")

    # Defaults
    default_locale: Optional[str] = Field(default=None)
    default_currency: Optional[str] = Field(default=None)
    fiscal_year_start_month: Optional[int] = Field(default=None, ge=1, le=12)
    default_date_format: Optional[str] = Field(default=None)
    default_number_format: Optional[str] = Field(default=None)

    # Governance
    personalization_enabled: bool = Field(
        default=False,
        description="Master switch — if False, no user in this tenant can use personalization",
    )
    session_memory_retention_days: int = Field(
        default=7, ge=1, description="How many days session memory entries are kept"
    )

    # Timestamps
    provenance: Optional[Provenance] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class GlossaryEntry(BaseModel):
    """Tenant-scoped glossary term with optional user-level overrides."""

    entry_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique entry identifier",
    )
    tenant_id: str = Field(description="Tenant this entry belongs to")
    user_id: Optional[str] = Field(
        default=None,
        description="If set, this is a user-level override of the tenant entry",
    )

    term: str = Field(description="The canonical glossary term")
    synonyms: List[str] = Field(
        default_factory=list, description="Alternative names / abbreviations"
    )
    definition: str = Field(description="Plain-language definition of the term")
    category: Optional[str] = Field(
        default=None, description="Optional category (metric, dimension, entity, …)"
    )

    # Approval
    approved: bool = Field(default=False, description="Whether admin-approved")
    approved_by: Optional[str] = Field(default=None)

    # Timestamps
    provenance: Optional[Provenance] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SessionMemoryEntry(BaseModel):
    """Ephemeral, auto-expiring memory tied to a user session."""

    session_id: str = Field(description="Session identifier")
    user_id: str = Field(description="User who owns this session")
    tenant_id: str = Field(description="Tenant context")
    content: str = Field(description="Session memory content (already redacted)")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime = Field(description="When this memory auto-expires")
