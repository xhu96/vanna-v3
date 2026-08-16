"""Server-derived scope helpers shared by local memory implementations."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vanna.core.tool import ToolContext

from vanna.core.user import principal_scope_for_user, tenant_scope_for_user


def memory_scope_for_context(context: "ToolContext") -> str:
    """Return a stable tenant scope with a V2-compatible default tenant."""

    return tenant_scope_for_user(context.user)


def principal_memory_scope_for_context(context: "ToolContext") -> str:
    """Return an opaque tenant-plus-subject scope for unreviewed tool memory."""

    encoded = json.dumps(
        principal_scope_for_user(context.user),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"principal:{hashlib.sha256(encoded).hexdigest()}"


__all__ = ["memory_scope_for_context", "principal_memory_scope_for_context"]
