"""Integration test: run_sql + schema sync against real Postgres."""

import os
import uuid

import pytest

from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.postgres import PostgresRunner
from vanna.services.schema_sync import PortableSchemaCatalogService
from vanna.tools.run_sql import RunSqlTool
from vanna.capabilities.sql_runner import RunSqlToolArgs


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_postgres_runner_and_schema_sync(tmp_path):
    dsn = os.getenv("VANNA_POSTGRES_TEST_DSN")
    if not dsn:
        pytest.skip("VANNA_POSTGRES_TEST_DSN not set")

    runner = PostgresRunner(connection_string=dsn)
    context = ToolContext(
        user=User(id="pg-user", group_memberships=["user"]),
        conversation_id="pg-conv",
        request_id="pg-req",
        agent_memory=DemoAgentMemory(),
    )

    table_name = f"vanna_v3_test_{uuid.uuid4().hex[:8]}"
    # Setup test table with direct runner calls.
    await runner.run_sql(RunSqlToolArgs(sql=f"CREATE TABLE {table_name} (id INT, value TEXT)"), context)
    await runner.run_sql(
        RunSqlToolArgs(sql=f"INSERT INTO {table_name} (id, value) VALUES (1, 'ok')"),
        context,
    )

    try:
        sql_tool = RunSqlTool(sql_runner=runner, read_only=True)
        result = await sql_tool.execute(
            context, RunSqlToolArgs(sql=f"SELECT id, value FROM {table_name}")
        )
        assert result.success is True
        assert result.metadata["row_count"] == 1

        schema_service = PortableSchemaCatalogService(
            sql_runner=runner,
            persist_path=str(tmp_path / "schema_pg.json"),
            dialect="postgres",
        )
        sync_result = await schema_service.sync(context)
        assert sync_result.snapshot.schema_hash
        assert any(c.table_name == table_name for c in sync_result.snapshot.columns)
    finally:
        await runner.run_sql(RunSqlToolArgs(sql=f"DROP TABLE IF EXISTS {table_name}"), context)
