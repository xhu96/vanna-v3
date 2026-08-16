"""SQLite catalog ingestion through read-only sqlite_schema and PRAGMA queries."""

from __future__ import annotations

from typing import Any, List, Optional

import pandas as pd

from vanna.capabilities.schema_catalog import SchemaCatalogAdapter, SchemaColumn
from vanna.capabilities.sql_runner import RunSqlToolArgs, SqlRunner
from vanna.core.tool import ToolContext
from vanna.security.sql_policy import SqlPolicyViolation, SqlQueryPolicy

from .scope import CatalogScopeSource, resolve_catalog_scope, scope_select_query

_TABLES_QUERY = """
    SELECT name
    FROM sqlite_schema
    WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'
    ORDER BY name
"""


def _quote_identifier(value: str) -> str:
    if not value or len(value) > 256 or any(ord(character) < 32 for character in value):
        raise ValueError("SQLite catalog returned an invalid table identifier")
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"SQLite catalog returned invalid {label}")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"SQLite catalog returned invalid {label}") from None
    if isinstance(value, float) and value != parsed:
        raise ValueError(f"SQLite catalog returned invalid {label}")
    return parsed


class SqliteCatalogAdapter(SchemaCatalogAdapter):
    """Read canonical descriptors from SQLite without writable operations."""

    dialect = "sqlite"

    def __init__(
        self,
        sql_runner: SqlRunner,
        *,
        query_policy: Optional[SqlQueryPolicy] = None,
        catalog_tables: Optional[CatalogScopeSource] = None,
        require_catalog_scope: bool = True,
        max_tables: int = 100_000,
        max_columns: int = 500_000,
        require_native_read_only: bool = True,
    ) -> None:
        self.sql_runner = sql_runner
        if require_native_read_only and sql_runner.native_read_only is not True:
            raise SqlPolicyViolation(
                "Schema catalog execution requires a native read-only runner boundary."
            )
        if not 1 <= max_tables <= 100_000:
            raise ValueError("max_tables must be between 1 and 100000")
        if not 1 <= max_columns <= 1_000_000:
            raise ValueError("max_columns must be between 1 and 1000000")
        self.max_tables = max_tables
        self.max_columns = max_columns
        self.catalog_tables = catalog_tables
        self.require_catalog_scope = require_catalog_scope
        self.query_policy = query_policy or SqlQueryPolicy(
            self.dialect,
            row_policies=(),
            require_row_policies=False,
        )
        if self.query_policy.dialect != self.dialect:
            raise ValueError("SQLite catalog query policy dialect does not match")

    async def fetch_columns(self, context: ToolContext) -> List[SchemaColumn]:
        table_scope = resolve_catalog_scope(
            context,
            self.catalog_tables,
            metadata_key="schema_catalog_tables",
            label="table",
            required=self.require_catalog_scope,
        )
        scoped_query = scope_select_query(
            _TABLES_QUERY,
            column="name",
            values=table_scope,
            dialect=self.dialect,
        )
        prepared = self.query_policy.prepare(scoped_query, context)
        tables = await self.sql_runner.run_sql(RunSqlToolArgs(sql=prepared), context)
        if tables.empty:
            return []
        if "name" not in tables.columns:
            raise ValueError("SQLite catalog result is missing table names")
        if len(tables) > self.max_tables:
            raise ValueError("SQLite catalog exceeds the configured table limit")

        columns: List[SchemaColumn] = []
        for raw_name in tables["name"].tolist():
            if not isinstance(raw_name, str):
                raise ValueError("SQLite catalog returned a non-string table name")
            table_name = raw_name.strip()
            pragma_sql = f"PRAGMA main.table_xinfo({_quote_identifier(table_name)})"
            prepared_pragma = self.query_policy.prepare(pragma_sql, context)
            table_columns = await self.sql_runner.run_sql(
                RunSqlToolArgs(sql=prepared_pragma),
                context,
            )
            if table_columns.empty:
                continue
            required = {"cid", "name", "type", "notnull"}
            if not required.issubset(table_columns.columns):
                raise ValueError("SQLite table_xinfo result is missing required fields")
            for row in table_columns.to_dict("records"):
                column_name = row.get("name")
                if not isinstance(column_name, str) or not column_name.strip():
                    raise ValueError("SQLite catalog returned an invalid column name")
                data_type = row.get("type")
                normalized_type = (
                    str(data_type).strip().casefold()
                    if data_type is not None and not bool(pd.isna(data_type))
                    else ""
                )
                cid = _integer(row.get("cid"), "column position")
                not_null = _integer(row.get("notnull"), "nullability")
                if cid < 0 or not_null not in {0, 1}:
                    raise ValueError("SQLite catalog returned invalid column metadata")
                columns.append(
                    SchemaColumn(
                        schema_name="main",
                        table_name=table_name,
                        column_name=column_name.strip(),
                        data_type=normalized_type or "unknown",
                        is_nullable=not bool(not_null),
                        ordinal_position=cid + 1,
                    )
                )
                if len(columns) > self.max_columns:
                    raise ValueError(
                        "SQLite catalog exceeds the configured column limit"
                    )
        return columns


__all__ = ["SqliteCatalogAdapter"]
