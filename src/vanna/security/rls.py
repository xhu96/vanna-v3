"""Scope-aware row-level-security rewriting for read-only SQL queries."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Collection, Iterable, Optional

from sqlglot import exp, parse
from sqlglot.errors import ParseError
from sqlglot.optimizer.scope import traverse_scope
from sqlglot.optimizer.scope import Scope


_IDENTIFIER = re.compile(r'^(?:[A-Za-z_][A-Za-z0-9_$]*|"[^"]+"|`[^`]+`|\[[^\]]+\])$')
_SCALAR_TYPES = (str, int, float, bool, type(None))
_TABLE_PART_SEPARATOR = "\x1f"


@dataclass(frozen=True)
class RowFilterPolicy:
    """A predicate applied before rows leave matching physical tables."""

    column: str
    value: str | int | float | bool | None
    tables: Optional[frozenset[str]] = None

    def __post_init__(self) -> None:
        _parse_identifier(self.column, "filter column")
        if not isinstance(self.value, _SCALAR_TYPES):
            raise ValueError("Row-filter values must be JSON scalar values")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("Row-filter numeric values must be finite")
        if self.tables is not None:
            if not self.tables:
                raise ValueError("A protected-table set cannot be empty")
            for table in self.tables:
                _normalize_table_name(table)


def _parse_identifier(value: str, label: str) -> tuple[str, bool]:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe {label}: {value!r}")
    quoted = value[0] in {'"', "`", "["}
    return (value[1:-1] if quoted else value, quoted)


def _split_table_name(value: str) -> tuple[str, ...]:
    if not isinstance(value, str):
        raise ValueError(f"Unsafe protected table: {value!r}")
    parts: list[str] = []
    current: list[str] = []
    closing_quote: str | None = None
    for character in value:
        if closing_quote is not None:
            current.append(character)
            if character == closing_quote:
                closing_quote = None
            continue
        if character in {'"', "`", "["}:
            closing_quote = "]" if character == "[" else character
            current.append(character)
        elif character == ".":
            parts.append("".join(current))
            current = []
        else:
            current.append(character)
    if closing_quote is not None:
        raise ValueError(f"Unsafe protected table: {value!r}")
    parts.append("".join(current))
    if not 1 <= len(parts) <= 3:
        raise ValueError(f"Unsafe protected table: {value!r}")
    return tuple(parts)


def _canonical_identifier(value: str, *, quoted: bool) -> str:
    if not value or any(ord(character) < 32 for character in value):
        raise ValueError(f"Unsafe protected table identifier: {value!r}")
    # Quoting a lower-case identifier does not change its physical identity in
    # SQL dialects such as PostgreSQL. Preserve only case-distinct quoted names.
    return f"q:{value}" if quoted and value != value.lower() else f"u:{value.lower()}"


def _normalize_table_name(value: str) -> str:
    normalized: list[str] = []
    for part in _split_table_name(value):
        name, quoted = _parse_identifier(part, "protected table")
        normalized.append(_canonical_identifier(name, quoted=quoted))
    return _TABLE_PART_SEPARATOR.join(normalized)


def _expression_identifier_key(value: exp.Expression | str) -> str:
    if isinstance(value, exp.Identifier):
        return _canonical_identifier(
            value.name,
            quoted=bool(value.args.get("quoted")),
        )
    return _canonical_identifier(str(value), quoted=False)


def _table_names(table: exp.Table) -> tuple[str, set[str]]:
    table_identifier = table.args.get("this")
    if not isinstance(table_identifier, exp.Identifier) or not table_identifier.name:
        raise ValueError(f"Cannot resolve protected source: {table.sql()!r}")
    name = _expression_identifier_key(table_identifier)
    catalog_identifier = table.args.get("catalog")
    db_identifier = table.args.get("db")
    parts = [
        _expression_identifier_key(part)
        for part in (catalog_identifier, db_identifier, table_identifier)
        if isinstance(part, exp.Expression)
    ]
    qualified = _TABLE_PART_SEPARATOR.join(parts)
    names = {name, qualified}
    if isinstance(db_identifier, exp.Expression):
        names.add(
            _TABLE_PART_SEPARATOR.join(
                (_expression_identifier_key(db_identifier), name)
            )
        )
    return qualified, names


def _nearest_select(expression: exp.Expression) -> Optional[exp.Select]:
    current = expression.parent
    while current is not None:
        if isinstance(current, exp.Select):
            return current
        current = current.parent
    return None


def _direct_sources(select: exp.Select) -> list[exp.Expression]:
    sources: list[exp.Expression] = []
    from_expression = select.args.get("from_")
    if isinstance(from_expression, exp.From) and from_expression.this is not None:
        sources.append(from_expression.this)
    for join in select.args.get("joins") or []:
        if isinstance(join, exp.Join) and join.this is not None:
            sources.append(join.this)
    return sources


def _direct_tables(select: exp.Select) -> list[exp.Table]:
    return [
        source for source in _direct_sources(select) if isinstance(source, exp.Table)
    ]


def _prealias_qualified_sources(tree: exp.Expression) -> None:
    """Give qualified sources unique aliases before SQLGlot scope resolution."""
    used_aliases = {
        table.alias_or_name.lower()
        for table in tree.find_all(exp.Table)
        if table.alias_or_name
    }
    alias_counter = 0
    selects = list(tree.find_all(exp.Select))
    for select in reversed(selects):
        alias_counts = Counter(
            source.alias_or_name.lower()
            for source in _direct_sources(select)
            if source.alias_or_name
        )
        duplicate_aliases = {
            alias for alias, count in alias_counts.items() if count > 1
        }
        duplicate_table_counts = Counter(
            _table_names(table)[0]
            for table in _direct_tables(select)
            if table.args.get("alias") is None
        )
        duplicate_tables = {
            table_name
            for table_name, count in duplicate_table_counts.items()
            if count > 1
        }
        if duplicate_tables:
            names = ", ".join(sorted(duplicate_tables))
            raise ValueError(
                f"Ambiguous duplicate physical source for row filtering: {names}"
            )
        for column in select.find_all(exp.Column):
            if (
                column.table.lower() in duplicate_aliases
                and not column.db
                and not column.catalog
                and _nearest_select(column) is select
            ):
                raise ValueError(
                    f"Ambiguous qualified column for row filtering: {column.sql()!r}"
                )
        for table in _direct_tables(select):
            if (
                table.args.get("alias") is not None
                or not (table.db or table.catalog)
                or alias_counts[table.alias_or_name.lower()] < 2
            ):
                continue

            while True:
                alias_counter += 1
                candidate = f"_vanna_rls_source_{alias_counter}"
                if candidate.lower() not in used_aliases:
                    used_aliases.add(candidate.lower())
                    alias_identifier = exp.to_identifier(candidate)
                    break

            table_name = table.name.lower()
            database = table.db.lower()
            catalog = table.catalog.lower()
            for column in select.find_all(exp.Column):
                if column.table.lower() != table_name:
                    continue
                is_exact_qualified = (
                    bool(column.db or column.catalog)
                    and column.db.lower() == database
                    and column.catalog.lower() == catalog
                )
                if is_exact_qualified:
                    column.set("table", alias_identifier.copy())
                    column.set("db", None)
                    column.set("catalog", None)

            table.set("alias", exp.TableAlias(this=alias_identifier.copy()))


def _query_scopes(
    tree: exp.Expression,
) -> tuple[list[Scope], list[tuple[Scope, exp.Table]]]:
    scopes: list[Scope] = []
    tables: list[tuple[Scope, exp.Table]] = []
    seen: set[int] = set()
    try:
        scopes = list(traverse_scope(tree))
        for scope in scopes:
            for _, (_, source) in scope.selected_sources.items():
                if isinstance(source, exp.Table) and id(source) not in seen:
                    seen.add(id(source))
                    tables.append((scope, source))
    except Exception as exc:
        raise ValueError("Cannot resolve SQL sources for row filtering") from exc
    return scopes, tables


def _policy_matches(policy: RowFilterPolicy, table_names: set[str]) -> Collection[str]:
    if policy.tables is None:
        return {"*"}
    normalized = {_normalize_table_name(table) for table in policy.tables}
    return normalized & table_names


def _column_expression(column: str) -> exp.Column:
    name, quoted = _parse_identifier(column, "filter column")
    return exp.Column(this=exp.Identifier(this=name, quoted=quoted))


def _predicate(policy: RowFilterPolicy) -> exp.Condition:
    return exp.EQ(
        this=_column_expression(policy.column),
        expression=exp.convert(policy.value),
    )


def _resolve_column_source(scope: Scope, column: exp.Column) -> Optional[exp.Table]:
    qualifier = column.table.lower()
    if not qualifier:
        return None

    current: Optional[Scope] = scope
    while current is not None:
        for alias, (_, source) in current.selected_sources.items():
            if alias.lower() != qualifier:
                continue
            if not isinstance(source, exp.Table):
                return None
            if column.db and column.db.lower() != source.db.lower():
                continue
            if column.catalog and column.catalog.lower() != source.catalog.lower():
                continue
            return source
        current = current.parent
    return None


def _columns_by_source(scopes: Iterable[Scope]) -> dict[int, list[exp.Column]]:
    columns: dict[int, list[exp.Column]] = {}
    seen: set[int] = set()
    for scope in scopes:
        for expression in (*scope.columns, *scope.stars):
            if not isinstance(expression, exp.Column):
                continue
            column = expression
            if id(column) in seen:
                continue
            seen.add(id(column))
            source = _resolve_column_source(scope, column)
            if source is not None:
                columns.setdefault(id(source), []).append(column)
    return columns


def _retarget_columns(
    columns: Iterable[exp.Column], alias_identifier: exp.Identifier
) -> None:
    for column in columns:
        column.set("table", alias_identifier.copy())
        column.set("db", None)
        column.set("catalog", None)


def apply_row_policies(
    sql: str,
    policies: Iterable[RowFilterPolicy],
    *,
    dialect: Optional[str] = None,
    allowed_unfiltered_tables: Iterable[str] = (),
) -> str:
    """Wrap every matching physical source in a pre-filtered subquery.

    Wrapping each table rather than modifying an outer ``WHERE`` preserves
    outer-join behavior and secures physical sources in nested scopes, CTEs,
    derived tables, correlated subqueries, and each set-operation arm.
    """
    policy_list = list(policies)
    if not policy_list:
        raise ValueError("At least one row-filter policy is required")
    allowed_unfiltered = {
        _normalize_table_name(table) for table in allowed_unfiltered_tables
    }

    try:
        statements = [statement for statement in parse(sql, read=dialect) if statement]
    except ParseError as exc:
        raise ValueError("Cannot parse SQL for row filtering") from exc
    if len(statements) != 1:
        raise ValueError("Row filtering requires exactly one SQL statement")

    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.SetOperation)):
        raise ValueError("Row filtering only supports read-only query expressions")

    _prealias_qualified_sources(tree)
    scopes, physical_sources = _query_scopes(tree)
    columns_by_source = _columns_by_source(scopes)
    qualified_by_base: dict[str, set[str]] = {}
    table_details: list[tuple[Scope, exp.Table, str, set[str]]] = []
    for scope, table in physical_sources:
        qualified, names = _table_names(table)
        table_details.append((scope, table, qualified, names))
        table_identifier = table.args.get("this")
        if not isinstance(table_identifier, exp.Identifier):
            raise ValueError(f"Cannot resolve protected source: {table.sql()!r}")
        qualified_by_base.setdefault(
            _expression_identifier_key(table_identifier), set()
        ).add(qualified)

    for policy in policy_list:
        if policy.tables is None:
            continue
        for target in policy.tables:
            normalized = _normalize_table_name(target)
            if (
                _TABLE_PART_SEPARATOR not in normalized
                and len(qualified_by_base.get(normalized, set())) > 1
            ):
                raise ValueError(f"Ambiguous protected table: {target!r}")

    used_aliases = {
        alias.lower() for scope in scopes for alias in scope.selected_sources
    }
    alias_counter = 0
    replacements = 0
    for _, table, qualified, names in table_details:
        matching_policies: list[RowFilterPolicy] = []
        for policy in policy_list:
            matches = _policy_matches(policy, names)
            if not matches:
                continue
            matching_policies.append(policy)

        if not matching_policies:
            # Public tables must use the exact physical identity. An unqualified
            # allowlist entry cannot make a same-named table in another schema public.
            if qualified in allowed_unfiltered:
                continue
            raise ValueError(
                "Physical SQL source has no row policy or public allowlist: "
                f"{table.sql(dialect=dialect)}"
            )

        predicate: exp.Condition = _predicate(matching_policies[0])
        for policy in matching_policies[1:]:
            predicate = exp.and_(predicate, _predicate(policy))

        source = table.copy()
        source.set("alias", None)
        original_alias = table.args.get("alias")
        if original_alias is not None:
            table_alias = original_alias.copy()
            alias_identifier = table_alias.this
        elif table.db or table.catalog:
            while True:
                alias_counter += 1
                candidate = f"_vanna_rls_{alias_counter}"
                if candidate.lower() not in used_aliases:
                    used_aliases.add(candidate.lower())
                    alias_identifier = exp.to_identifier(candidate)
                    break
            table_alias = exp.TableAlias(this=alias_identifier.copy())
        else:
            alias = table.alias_or_name
            if not alias:
                raise ValueError(f"Cannot alias protected source: {table.sql()!r}")
            alias_identifier = (
                table.this.copy()
                if isinstance(table.this, exp.Identifier)
                else exp.to_identifier(alias)
            )
            table_alias = exp.TableAlias(this=alias_identifier.copy())
        if not isinstance(alias_identifier, exp.Identifier):
            raise ValueError(f"Cannot alias protected source: {table.sql()!r}")

        _retarget_columns(columns_by_source.get(id(table), []), alias_identifier)
        filtered = exp.select("*").from_(source).where(predicate).subquery()
        filtered.set("alias", table_alias)
        table.replace(filtered)
        replacements += 1

    rendered = tree.sql(dialect=dialect)
    try:
        reparsed = [
            statement for statement in parse(rendered, read=dialect) if statement
        ]
    except ParseError as exc:
        raise ValueError("Generated row-filtered SQL is invalid") from exc
    if len(reparsed) != 1:
        raise ValueError("Generated row-filtered SQL is invalid")
    return rendered


def apply_row_filter(
    sql: str,
    column: str,
    value: str | int | float | bool | None,
    *,
    protected_tables: Optional[Iterable[str]] = None,
    allowed_unfiltered_tables: Iterable[str] = (),
    dialect: Optional[str] = None,
) -> str:
    """Backward-compatible single-policy wrapper over ``apply_row_policies``.

    Omitting ``protected_tables`` preserves the original convenience API but
    now protects every physical source. Production callers should pass the
    catalogued protected tables explicitly. Public dimensions require an
    explicit ``allowed_unfiltered_tables`` entry; every other source fails
    closed.
    """
    tables = frozenset(protected_tables) if protected_tables is not None else None
    return apply_row_policies(
        sql,
        [RowFilterPolicy(column=column, value=value, tables=tables)],
        dialect=dialect,
        allowed_unfiltered_tables=allowed_unfiltered_tables,
    )
