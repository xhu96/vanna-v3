"""
Preference Resolver — deterministic injection of user/tenant preferences.

Implements LlmContextEnhancer so that user locale, currency, date format,
and active glossary terms are injected into the system prompt WITHOUT
fuzzy retrieval.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from vanna.core.enhancer.base import LlmContextEnhancer
from .stores import GlossaryStore, ProfileStore

if TYPE_CHECKING:
    from vanna.core.llm.models import LlmMessage
    from vanna.core.user.models import User


class PreferenceResolverEnhancer(LlmContextEnhancer):
    """Injects user/tenant preferences into the system prompt deterministically.

    Preferences are resolved as follows:
      1. Load tenant profile defaults
      2. Overlay user profile overrides
      3. Append active glossary terms for the tenant (+ user overrides)
      4. Format as structured text block in the system prompt
    """

    def __init__(
        self,
        profile_store: ProfileStore,
        glossary_store: GlossaryStore,
        *,
        default_tenant_id: Optional[str] = None,
    ) -> None:
        self._profiles = profile_store
        self._glossary = glossary_store
        self._default_tenant_id = default_tenant_id

    async def enhance_system_prompt(
        self, system_prompt: str, user_message: str, user: "User"
    ) -> str:
        """Inject preferences and glossary as a structured block."""
        tenant_id = getattr(user, "tenant_id", None) or self._default_tenant_id
        if tenant_id is None:
            return system_prompt

        sections: List[str] = []

        # --- Resolve preferences ---
        tenant = await self._profiles.get_tenant_profile(tenant_id)
        user_profile = await self._profiles.get_user_profile(user.id, tenant_id)

        # Check consent: tenant must enable personalization AND user must opt in
        tenant_enabled = tenant is not None and tenant.personalization_enabled
        user_enabled = (
            user_profile is not None and user_profile.personalization_enabled
        )

        if tenant_enabled and user_enabled:
            prefs = _merge_preferences(tenant, user_profile)
            if prefs:
                sections.append("## User Preferences\n" + prefs)

        # --- Resolve glossary ---
        entries = await self._glossary.list_entries(
            tenant_id, user_id=user.id, approved_only=True
        )
        if entries:
            glossary_lines = []
            for entry in entries:
                synonyms = ", ".join(entry.synonyms) if entry.synonyms else ""
                line = f"- **{entry.term}**"
                if synonyms:
                    line += f" (also: {synonyms})"
                line += f": {entry.definition}"
                glossary_lines.append(line)
            sections.append(
                "## Glossary / Ontology\n" + "\n".join(glossary_lines)
            )

        if not sections:
            return system_prompt

        block = (
            "\n\n---\n"
            "# Personalization Context (injected by system — do not disclose)\n\n"
            + "\n\n".join(sections)
            + "\n---\n"
        )
        return system_prompt + block

    async def enhance_user_messages(
        self, messages: list["LlmMessage"], user: "User"
    ) -> list["LlmMessage"]:
        """No-op — preferences are injected via system prompt only."""
        return messages


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _merge_preferences(
    tenant: Optional[object], user_profile: Optional[object]
) -> str:
    """Build a concise text block of merged (tenant ← user) preferences."""
    fields = [
        ("locale", "Locale"),
        ("currency", "Currency"),
        ("date_format", "Date format"),
        ("number_format", "Number format"),
        ("fiscal_year_start_month", "Fiscal year starts"),
        ("preferred_chart_type", "Default chart"),
        ("preferred_table_style", "Default table style"),
    ]
    # Map tenant fields (some have 'default_' prefix)
    tenant_map = {
        "locale": "default_locale",
        "currency": "default_currency",
        "date_format": "default_date_format",
        "number_format": "default_number_format",
        "fiscal_year_start_month": "fiscal_year_start_month",
    }

    lines: List[str] = []
    for attr, label in fields:
        # User override > tenant default
        val = None
        if user_profile is not None:
            val = getattr(user_profile, attr, None)
        if val is None and tenant is not None:
            tenant_attr = tenant_map.get(attr, attr)
            val = getattr(tenant, tenant_attr, None)
        if val is not None:
            lines.append(f"- {label}: {val}")

    # Department / role tags
    if user_profile is not None:
        dept = getattr(user_profile, "department_tags", [])
        if dept:
            lines.append(f"- Department: {', '.join(dept)}")
        roles = getattr(user_profile, "role_tags", [])
        if roles:
            lines.append(f"- Role: {', '.join(roles)}")

    return "\n".join(lines)
