"""Portable catalog ingestion and policy-boundary regressions."""

from __future__ import annotations

import sqlite3
from typing import Optional

import pandas as pd
import pytest

from vanna.capabilities.sql_runner import RunSqlToolArgs, SqlRunner
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.schema_catalog import (
    InformationSchemaCatalogAdapter,
    SqliteCatalogAdapter,
)
from vanna.integrations.sqlite import SqliteRunner
from vanna.security.sql_policy import SqlPolicyViolation


def context(
    *,
    tenant_id: str = "tenant-a",
    schemas: tuple[str, ...] = ("public",),
    tables: tuple[str, ...] = ("odd table",),
) -> ToolContext:
    return ToolContext(
        user=User(
            id="catalog-user",
            metadata={
                "tenant_id": tenant_id,
                "schema_catalog_schemas": schemas,
                "schema_catalog_tables": tables,
            },
            group_memberships=["admin"],
        ),
        conversation_id="catalog-conversation",
        request_id="catalog-request",
        agent_memory=DemoAgentMemory(),
        metadata={"sql_row_policies": "untrusted request metadata"},
    )


class InformationSchemaRunner(SqlRunner):
    dialect = "postgres"
    native_read_only = True

    def __init__(
        self,
        dataframe: Optional[pd.DataFrame] = None,
        failure: Optional[Exception] = None,
    ) -> None:
        self.dataframe = dataframe if dataframe is not None else pd.DataFrame()
        self.failure = failure
        self.calls: list[str] = []

    async def run_sql(self, args: RunSqlToolArgs, context: ToolContext) -> pd.DataFrame:
        del context
        self.calls.append(args.sql)
        if self.failure is not None:
            raise self.failure
        return self.dataframe


@pytest.mark.asyncio
async def test_information_schema_ingestion_normalizes_catalog_rows() -> None:
    runner = InformationSchemaRunner(
        pd.DataFrame(
            [
                {
                    "schema_name": "public",
                    "table_name": "orders",
                    "column_name": "id",
                    "data_type": "INTEGER",
                    "is_nullable": "NO",
                    "ordinal_position": 1,
                },
                {
                    "schema_name": "public",
                    "table_name": "orders",
                    "column_name": "status",
                    "data_type": "TEXT",
                    "is_nullable": "YES",
                    "ordinal_position": 2,
                },
            ]
        )
    )
    adapter = InformationSchemaCatalogAdapter(runner, dialect="postgres")

    columns = await adapter.fetch_columns(context())

    assert [(item.column_name, item.data_type) for item in columns] == [
        ("id", "integer"),
        ("status", "text"),
    ]
    assert [item.is_nullable for item in columns] == [False, True]
    assert len(runner.calls) == 1
    assert "information_schema.columns" in runner.calls[0]
    assert "table_schema IN ('public')" in runner.calls[0]


@pytest.mark.asyncio
async def test_catalog_scope_is_required_and_tenant_queries_are_disjoint() -> None:
    runner = InformationSchemaRunner()
    adapter = InformationSchemaCatalogAdapter(runner, dialect="postgres")
    unscoped = context(schemas=())

    with pytest.raises(SqlPolicyViolation, match="schema allowlist"):
        await adapter.fetch_columns(unscoped)
    assert runner.calls == []

    await adapter.fetch_columns(context(tenant_id="a", schemas=("tenant_a",)))
    await adapter.fetch_columns(context(tenant_id="b", schemas=("tenant_b",)))
    assert "'tenant_a'" in runner.calls[0]
    assert "'tenant_b'" in runner.calls[1]
    assert runner.calls[0] != runner.calls[1]


@pytest.mark.asyncio
async def test_information_schema_failure_is_not_hidden_by_dialect_fallback() -> None:
    runner = InformationSchemaRunner(failure=RuntimeError("catalog unavailable"))
    adapter = InformationSchemaCatalogAdapter(runner, dialect="postgres")

    with pytest.raises(RuntimeError, match="catalog unavailable"):
        await adapter.fetch_columns(context())

    assert len(runner.calls) == 1
    assert "sqlite" not in runner.calls[0].casefold()


def test_catalog_requires_native_read_only_runner() -> None:
    runner = InformationSchemaRunner()
    runner.native_read_only = False

    with pytest.raises(SqlPolicyViolation, match="native read-only"):
        InformationSchemaCatalogAdapter(runner, dialect="postgres")

    InformationSchemaCatalogAdapter(
        runner,
        dialect="postgres",
        require_native_read_only=False,
    )


@pytest.mark.asyncio
async def test_information_schema_rejects_malformed_and_unbounded_results() -> None:
    malformed = InformationSchemaRunner(pd.DataFrame([{"table_name": "orders"}]))
    with pytest.raises(ValueError, match="missing required columns"):
        await InformationSchemaCatalogAdapter(
            malformed, dialect="postgres"
        ).fetch_columns(context())

    oversized = InformationSchemaRunner(
        pd.DataFrame(
            [
                {
                    "schema_name": "public",
                    "table_name": "orders",
                    "column_name": f"c{index}",
                    "data_type": "integer",
                    "is_nullable": "NO",
                    "ordinal_position": index + 1,
                }
                for index in range(2)
            ]
        )
    )
    with pytest.raises(ValueError, match="column limit"):
        await InformationSchemaCatalogAdapter(
            oversized,
            dialect="postgres",
            max_columns=1,
        ).fetch_columns(context())


@pytest.mark.asyncio
async def test_sqlite_ingestion_handles_quoted_names_through_safe_pragmas(
    tmp_path,
) -> None:
    database = tmp_path / "catalog.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            'CREATE TABLE "odd table" ("id" INTEGER NOT NULL, "quoted""column" TEXT)'
        )
        connection.commit()
    finally:
        connection.close()

    adapter = SqliteCatalogAdapter(
        SqliteRunner(database_path=str(database), read_only=True)
    )
    columns = await adapter.fetch_columns(context())

    assert [item.table_name for item in columns] == ["odd table", "odd table"]
    assert [item.column_name for item in columns] == ["id", 'quoted"column']
    assert [item.ordinal_position for item in columns] == [1, 2]
    assert [item.is_nullable for item in columns] == [False, True]
