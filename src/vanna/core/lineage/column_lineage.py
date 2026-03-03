"""Column-level lineage extraction using SQLGlot.

Parses a SQL statement and returns the set of (source_table, column, alias)
edges visible in the outermost SELECT list and FROM/JOIN clauses.  The
function is intentionally best-effort: it returns an empty list rather than
raising for any SQL it cannot parse or dialect it does not recognise.

Optional dependency: sqlglot>=20.0.0  (install with ``pip install vanna[de]``)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

try:
    import sqlglot
    import sqlglot.expressions as exp
except ImportError:  # pragma: no cover
    sqlglot = None  # type: ignore[assignment]
    exp = None  # type: ignore[assignment]

from .models import ColumnLineageEdge


def extract_column_lineage(sql: str, dialect: str = "") -> list[ColumnLineageEdge]:
    """Return column-level lineage edges for *sql*.

    Each edge records the source table qualifier (or ``"unknown"`` when no
    qualifier is present), the column name, and the output alias if one was
    declared.  Wildcard ``*`` selections are captured as-is.

    Args:
        sql: A single SQL statement (or multi-statement string; only the first
            parseable SELECT statement is analysed).
        dialect: Optional SQLGlot dialect name, e.g. ``"duckdb"``, ``"bigquery"``,
            ``"postgres"``.  An empty string lets SQLGlot auto-detect.

    Returns:
        A list of :class:`ColumnLineageEdge` instances, possibly empty.
    """
    if sqlglot is None:
        return []

    edges: list[ColumnLineageEdge] = []

    try:
        statements = sqlglot.parse(sql, dialect=dialect or None)
    except Exception:
        return []

    for statement in statements:
        if statement is None:
            continue
        # Only inspect SELECT-shaped statements.
        if not isinstance(statement, (exp.Select, exp.Subquery, exp.Union)):
            # Walk into CTEs and subqueries automatically below.
            pass

        try:
            _collect_edges(statement, edges)
        except Exception:
            # Best-effort: never raise to the caller.
            continue

    return edges


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _collect_edges(node: exp.Expression, edges: list[ColumnLineageEdge]) -> None:
    """Recursively collect column edges from *node* and all sub-expressions."""
    for select_node in node.find_all(exp.Select):
        for projection in select_node.expressions:
            _handle_projection(projection, edges)


def _handle_projection(
    projection: exp.Expression, edges: list[ColumnLineageEdge]
) -> None:
    """Extract a single edge from a SELECT list projection."""
    alias: str | None = None

    if isinstance(projection, exp.Alias):
        alias = projection.alias
        inner = projection.this
    else:
        inner = projection

    if isinstance(inner, exp.Star):
        edges.append(
            ColumnLineageEdge(source_table="*", column="*", alias=alias)
        )
        return

    if isinstance(inner, exp.Column):
        table = inner.table or "unknown"
        column = inner.name
        edges.append(
            ColumnLineageEdge(source_table=table, column=column, alias=alias)
        )
        return

    # For expressions (CASE, function calls, arithmetic), collect any column
    # references nested inside them.
    for col in inner.find_all(exp.Column):
        table = col.table or "unknown"
        edges.append(
            ColumnLineageEdge(source_table=table, column=col.name, alias=alias)
        )
