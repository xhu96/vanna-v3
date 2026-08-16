"""Portable INFORMATION_SCHEMA column ingestion."""

from __future__ import annotations

import math
from typing import Any, List, Optional

import pandas as pd

from vanna.capabilities.schema_catalog import SchemaCatalogAdapter, SchemaColumn
from vanna.capabilities.sql_runner import RunSqlToolArgs, SqlRunner
from vanna.core.tool import ToolContext
from vanna.security.sql_policy import (
    SqlPolicyViolation,
    SqlQueryPolicy,
    normalize_sql_dialect,
)

from .scope import CatalogScopeSource, resolve_catalog_scope, scope_select_query

_INFORMATION_SCHEMA_COLUMNS = """
    SELECT
        table_schema AS schema_name,
        table_name,
        column_name,
        data_type,
        is_nullable,
        ordinal_position
    FROM information_schema.columns
    WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
    ORDER BY table_schema, table_name, ordinal_position
"""


def _missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _required_text(value: Any, label: str, *, fallback: Optional[str] = None) -> str:
    if _missing(value):
        if fallback is not None:
            return fallback
        raise ValueError(f"INFORMATION_SCHEMA returned an empty {label}")
    normalized = str(value).strip()
    if not normalized:
        if fallback is not None:
            return fallback
        raise ValueError(f"INFORMATION_SCHEMA returned an empty {label}")
    return normalized


def _nullable(value: Any) -> Optional[bool]:
    if _missing(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("INFORMATION_SCHEMA returned invalid nullability")
        if value in {0, 1}:
            return bool(value)
    normalized = str(value).strip().casefold()
    if normalized in {"yes", "y", "true", "1"}:
        return True
    if normalized in {"no", "n", "false", "0"}:
        return False
    raise ValueError("INFORMATION_SCHEMA returned invalid nullability")


def _ordinal(value: Any) -> Optional[int]:
    if _missing(value):
        return None
    if isinstance(value, bool):
        raise ValueError("INFORMATION_SCHEMA returned invalid ordinal position")
    try:
        ordinal = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(
            "INFORMATION_SCHEMA returned invalid ordinal position"
        ) from None
    if ordinal < 1 or (isinstance(value, float) and value != ordinal):
        raise ValueError("INFORMATION_SCHEMA returned invalid ordinal position")
    return ordinal


class InformationSchemaCatalogAdapter(SchemaCatalogAdapter):
    """Read a canonical snapshot using the SQL-standard columns catalog."""

    def __init__(
        self,
        sql_runner: SqlRunner,
        *,
        dialect: str,
        query_policy: Optional[SqlQueryPolicy] = None,
        catalog_schemas: Optional[CatalogScopeSource] = None,
        require_catalog_scope: bool = True,
        max_columns: int = 500_000,
        require_native_read_only: bool = True,
    ) -> None:
        self.sql_runner = sql_runner
        if require_native_read_only and sql_runner.native_read_only is not True:
            raise SqlPolicyViolation(
                "Schema catalog execution requires a native read-only runner boundary."
            )
        self.dialect = normalize_sql_dialect(dialect)
        if self.dialect == "unknown":
            raise ValueError("Schema catalog ingestion requires an explicit dialect")
        if not 1 <= max_columns <= 1_000_000:
            raise ValueError("max_columns must be between 1 and 1000000")
        self.max_columns = max_columns
        self.catalog_schemas = catalog_schemas
        self.require_catalog_scope = require_catalog_scope
        self.query_policy = query_policy or SqlQueryPolicy(
            self.dialect,
            row_policies=(),
            require_row_policies=False,
        )
        if self.query_policy.dialect != self.dialect:
            raise ValueError("Schema catalog query policy dialect does not match")

    async def fetch_columns(self, context: ToolContext) -> List[SchemaColumn]:
        schemas = resolve_catalog_scope(
            context,
            self.catalog_schemas,
            metadata_key="schema_catalog_schemas",
            label="schema",
            required=self.require_catalog_scope,
        )
        scoped_query = scope_select_query(
            _INFORMATION_SCHEMA_COLUMNS,
            column="table_schema",
            values=schemas,
            dialect=self.dialect,
        )
        prepared = self.query_policy.prepare(scoped_query, context)
        dataframe = await self.sql_runner.run_sql(
            RunSqlToolArgs(sql=prepared),
            context,
        )
        if dataframe.empty:
            return []
        required = {
            "schema_name",
            "table_name",
            "column_name",
            "data_type",
            "is_nullable",
            "ordinal_position",
        }
        if not required.issubset(dataframe.columns):
            raise ValueError("INFORMATION_SCHEMA result is missing required columns")
        if len(dataframe) > self.max_columns:
            raise ValueError("Schema catalog exceeds the configured column limit")

        columns: List[SchemaColumn] = []
        for row in dataframe.to_dict("records"):
            schema_value = row.get("schema_name")
            schema_name = (
                None
                if _missing(schema_value)
                else _required_text(schema_value, "schema name")
            )
            columns.append(
                SchemaColumn(
                    schema_name=schema_name,
                    table_name=_required_text(row.get("table_name"), "table name"),
                    column_name=_required_text(row.get("column_name"), "column name"),
                    data_type=_required_text(
                        row.get("data_type"), "data type", fallback="unknown"
                    ).casefold(),
                    is_nullable=_nullable(row.get("is_nullable")),
                    ordinal_position=_ordinal(row.get("ordinal_position")),
                )
            )
        return columns


__all__ = ["InformationSchemaCatalogAdapter"]
