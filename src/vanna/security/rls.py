"""Safe, AST-based row-level-security predicate injection."""

from __future__ import annotations

from sqlglot import condition, exp, parse_one


def apply_row_filter(sql: str, column: str, value: str) -> str:
    """Return ``sql`` with ``column = value`` AND-ed into its WHERE clause.

    The value is bound as a properly-escaped string literal via sqlglot, so
    untrusted ``value`` (e.g. a tenant id) cannot break out of the literal.
    The predicate is applied at the AST level, so it composes correctly with
    GROUP BY, HAVING, sub-queries, and existing WHERE clauses.
    """
    if not column.isidentifier():
        raise ValueError(f"Unsafe filter column: {column!r}")

    tree = parse_one(sql)
    predicate = condition(exp.column(column).eq(exp.Literal.string(value)))
    # ``where`` AND-combines with any existing WHERE on a Select.
    tree = tree.where(predicate)
    return tree.sql()
