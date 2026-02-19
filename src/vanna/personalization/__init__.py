"""
Personalization subsystem for Vanna v3.

Provides privacy-safe user/tenant profiles, glossary/ontology management,
session memory, consent controls, and PII redaction.
"""

from .models import (
    GlossaryEntry,
    SessionMemoryEntry,
    TenantProfile,
    UserProfile,
)
from .stores import (
    GlossaryStore,
    InMemoryGlossaryStore,
    InMemoryProfileStore,
    InMemorySessionMemoryStore,
    ProfileStore,
    SessionMemoryStore,
)

__all__ = [
    "UserProfile",
    "TenantProfile",
    "GlossaryEntry",
    "SessionMemoryEntry",
    "ProfileStore",
    "GlossaryStore",
    "SessionMemoryStore",
    "InMemoryProfileStore",
    "InMemoryGlossaryStore",
    "InMemorySessionMemoryStore",
]
