"""Canonical authenticated tenant and principal scope helpers."""

from __future__ import annotations

from .models import User


def tenant_scope_for_user(user: User) -> str:
    """Return the resolver-derived tenant scope with a V2 default tenant."""

    tenant_id = user.metadata.get("tenant_id")
    if isinstance(tenant_id, str) and tenant_id.strip():
        return f"tenant:{tenant_id.strip()}"
    if "tenant_id" in user.metadata:
        raise ValueError("tenant_id must be a non-empty string when supplied")
    return "tenant:default"


def principal_scope_for_user(user: User) -> tuple[str, str]:
    """Return the tenant-qualified subject used for ownership decisions."""

    subject = user.id.strip()
    if not subject:
        raise ValueError("authenticated subject must be non-empty")
    return tenant_scope_for_user(user), subject


def same_principal(left: User, right: User) -> bool:
    """Compare both tenant and subject; a subject is not globally unique."""

    return principal_scope_for_user(left) == principal_scope_for_user(right)


__all__ = ["principal_scope_for_user", "same_principal", "tenant_scope_for_user"]
