"""Trusted source scopes for portable database catalog queries."""

from __future__ import annotations

from collections.abc import Callable, Collection
from typing import Optional, TypeAlias

from sqlglot import exp, parse_one

from vanna.core.tool import ToolContext
from vanna.security.sql_policy import SqlPolicyViolation

CatalogScopeSource: TypeAlias = (
    Collection[str] | Callable[[ToolContext], Collection[str]]
)


def resolve_catalog_scope(
    context: ToolContext,
    source: Optional[CatalogScopeSource],
    *,
    metadata_key: str,
    label: str,
    required: bool,
) -> tuple[str, ...]:
    """Resolve a bounded allowlist only from configuration or trusted user claims."""

    resolved: object = source
    if resolved is None:
        resolved = context.user.metadata.get(metadata_key)
    if callable(resolved):
        try:
            resolved = resolved(context)
        except Exception:
            raise SqlPolicyViolation(
                f"Schema catalog {label} scope resolution failed."
            ) from None
    if resolved is None and not required:
        return ()
    if isinstance(resolved, (str, bytes)) or not isinstance(resolved, Collection):
        raise SqlPolicyViolation(
            f"Schema catalog execution requires an explicit {label} allowlist."
        )

    values: set[str] = set()
    for value in resolved:
        if not isinstance(value, str):
            raise SqlPolicyViolation(f"Schema catalog {label} scope is invalid.")
        normalized = value.strip()
        if (
            not normalized
            or len(normalized) > 256
            or any(ord(character) < 32 for character in normalized)
        ):
            raise SqlPolicyViolation(f"Schema catalog {label} scope is invalid.")
        values.add(normalized)
        if len(values) > 1_000:
            raise SqlPolicyViolation(f"Schema catalog {label} scope is too large.")
    if required and not values:
        raise SqlPolicyViolation(
            f"Schema catalog execution requires an explicit {label} allowlist."
        )
    return tuple(sorted(values))


def scope_select_query(
    sql: str,
    *,
    column: str,
    values: tuple[str, ...],
    dialect: str,
) -> str:
    """Add a literal allowlist predicate to a constant catalog SELECT."""

    if not values:
        return sql
    tree = parse_one(sql, read=dialect)
    predicate = exp.In(
        this=exp.column(column),
        expressions=[exp.convert(value) for value in values],
    )
    where = tree.args.get("where")
    if isinstance(where, exp.Where):
        where.set("this", exp.and_(where.this, predicate))
    else:
        tree.set("where", exp.Where(this=predicate))
    return tree.sql(dialect=dialect)


__all__ = ["CatalogScopeSource", "resolve_catalog_scope", "scope_select_query"]
