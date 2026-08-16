"""
User domain.

This module provides the core abstractions for user management in the Vanna Agents framework.
"""

from .base import UserService
from .models import User
from .resolver import UserResolver
from .request_context import RequestContext, TRUSTED_SCHEMA_LINEAGE_METADATA_KEY
from .scope import principal_scope_for_user, same_principal, tenant_scope_for_user

__all__ = [
    "UserService",
    "User",
    "UserResolver",
    "RequestContext",
    "TRUSTED_SCHEMA_LINEAGE_METADATA_KEY",
    "principal_scope_for_user",
    "same_principal",
    "tenant_scope_for_user",
]
