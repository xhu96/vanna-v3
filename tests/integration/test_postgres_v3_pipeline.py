"""Production-path integration against a real PostgreSQL 15 service."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Callable

import psycopg2
import pytest
from psycopg2 import sql

from vanna.capabilities.agent_memory import memory_scope_for_context
from vanna.capabilities.sql_runner import RunSqlToolArgs
from vanna.core.chart_spec import dataframe_to_vega_lite_spec
from vanna.core.lineage import LineageCollector
from vanna.core.planner import SemanticFirstPlanner
from vanna.core.registry import ToolRegistry
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local import LocalFileSystem
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.postgres import PostgresRunner
from vanna.integrations.semantic import MockSemanticAdapter
from vanna.security.rls import RowFilterPolicy
from vanna.security.sql_policy import SqlPolicyViolation, SqlQueryPolicy
from vanna.services.feedback import FeedbackRequest, FeedbackService
from vanna.services.schema_sync import PortableSchemaCatalogService
from vanna.tools.run_sql import RunSqlTool
from vanna.tools.semantic_query import SemanticQueryTool, SemanticQueryToolArgs


def _context(
    memory: DemoAgentMemory,
    *,
    tenant: str,
    user_id: str,
) -> ToolContext:
    return ToolContext(
        user=User(
            id=user_id,
            authenticated=True,
            metadata={"tenant_id": tenant},
            group_memberships=["user"],
        ),
        conversation_id=f"conversation-{tenant}",
        request_id=f"request-{tenant}",
        agent_memory=memory,
    )


def _tenant_policies(
    table_name: str,
) -> Callable[[ToolContext], tuple[RowFilterPolicy, ...]]:
    def resolve(context: ToolContext) -> tuple[RowFilterPolicy, ...]:
        tenant = context.user.metadata.get("tenant_id")
        if not isinstance(tenant, str) or not tenant:
            raise SqlPolicyViolation("Authenticated tenant scope is required")
        return (
            RowFilterPolicy(
                column="tenant_id",
                value=tenant,
                tables=frozenset({table_name}),
            ),
        )

    return resolve


def _restricted_dsn(admin_dsn: str, role_name: str, password: str) -> str:
    parameters = psycopg2.extensions.parse_dsn(admin_dsn)
    parameters.update(user=role_name, password=password)
    return psycopg2.extensions.make_dsn(**parameters)


def _create_fixture(
    admin_dsn: str, table_name: str, role_name: str, password: str
) -> None:
    with psycopg2.connect(admin_dsn) as connection:
        database_name = connection.get_dsn_parameters()["dbname"]
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "CREATE TABLE {} (id INTEGER PRIMARY KEY, tenant_id TEXT NOT NULL, "
                    "value INTEGER NOT NULL)"
                ).format(sql.Identifier(table_name))
            )
            cursor.execute(
                sql.SQL(
                    "INSERT INTO {} VALUES (1, 'tenant-a', 10), (2, 'tenant-b', 20)"
                ).format(sql.Identifier(table_name))
            )
            cursor.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD %s").format(
                    sql.Identifier(role_name)
                ),
                (password,),
            )
            cursor.execute(
                sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(
                    sql.Identifier(role_name)
                )
            )
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(database_name),
                    sql.Identifier(role_name),
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                    sql.Identifier(role_name)
                )
            )
            cursor.execute(
                sql.SQL("GRANT SELECT ON {} TO {}").format(
                    sql.Identifier(table_name),
                    sql.Identifier(role_name),
                )
            )


def _drop_fixture(admin_dsn: str, table_name: str, role_name: str) -> None:
    connection = psycopg2.connect(admin_dsn)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table_name))
            )
            cursor.execute(
                sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name))
            )
            cursor.execute(
                sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role_name))
            )
    finally:
        connection.close()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_postgres_v3_production_pipeline(tmp_path: Path) -> None:
    admin_dsn = os.getenv("VANNA_POSTGRES_TEST_DSN")
    if not admin_dsn:
        pytest.skip("VANNA_POSTGRES_TEST_DSN not set")

    suffix = uuid.uuid4().hex[:10]
    table_name = f"vanna_v3_tenant_data_{suffix}"
    role_name = f"vanna_v3_reader_{suffix}"
    password = f"vanna-v3-{uuid.uuid4().hex}"
    fixture_created = False

    try:
        _create_fixture(admin_dsn, table_name, role_name, password)
        fixture_created = True
        read_only_dsn = _restricted_dsn(admin_dsn, role_name, password)
        runner = PostgresRunner(connection_string=read_only_dsn, read_only=True)
        native_role_runner = PostgresRunner(
            connection_string=read_only_dsn,
            read_only=False,
        )
        memory = DemoAgentMemory()
        tenant_a = _context(memory, tenant="tenant-a", user_id="alice")
        tenant_b = _context(memory, tenant="tenant-b", user_id="bob")
        query_policy = SqlQueryPolicy(
            "postgres",
            row_policies=_tenant_policies(table_name),
            require_row_policies=True,
        )
        sql_tool = RunSqlTool(
            sql_runner=runner,
            file_system=LocalFileSystem(str(tmp_path / "artifacts")),
            query_policy=query_policy,
        )
        query = f"SELECT id, tenant_id, value FROM {table_name} ORDER BY id"

        result_a = await sql_tool.execute(tenant_a, RunSqlToolArgs(sql=query))
        result_b = await sql_tool.execute(tenant_b, RunSqlToolArgs(sql=query))
        assert result_a.success and result_b.success
        assert result_a.metadata["results"] == [
            {"id": 1, "tenant_id": "tenant-a", "value": 10}
        ]
        assert result_b.metadata["results"] == [
            {"id": 2, "tenant_id": "tenant-b", "value": 20}
        ]
        assert "tenant-a" in result_a.metadata["executed_sql"]
        assert "tenant-b" in result_b.metadata["executed_sql"]

        with pytest.raises(psycopg2.Error):
            await native_role_runner.run_sql(
                RunSqlToolArgs(
                    sql=f"INSERT INTO {table_name} VALUES (3, 'tenant-a', 30)"
                ),
                tenant_a,
            )

        schema_service = PortableSchemaCatalogService(
            sql_runner=runner,
            persist_path=str(tmp_path / "schema.sqlite3"),
            dialect="postgres",
            catalog_schemas=["public"],
        )
        first_snapshot = await schema_service.sync(tenant_a)
        assert first_snapshot.snapshot.schema_version == 1
        assert first_snapshot.snapshot.tenant_id == "tenant-a"
        assert any(
            column.table_name == table_name
            for column in first_snapshot.snapshot.columns
        )

        with psycopg2.connect(admin_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("ALTER TABLE {} ADD COLUMN observed_at TIMESTAMPTZ").format(
                        sql.Identifier(table_name)
                    )
                )

        drifted_snapshot = await schema_service.sync(tenant_a)
        isolated_snapshot = await schema_service.sync(tenant_b)
        assert drifted_snapshot.snapshot.schema_version == 2
        assert drifted_snapshot.diff.has_drift
        assert any(
            column.column_name == "observed_at"
            for column in drifted_snapshot.diff.added_columns
        )
        assert isolated_snapshot.snapshot.schema_version == 1
        assert isolated_snapshot.snapshot.tenant_id == "tenant-b"

        semantic_adapter = MockSemanticAdapter()
        semantic_tool = SemanticQueryTool(semantic_adapter)
        registry = ToolRegistry()
        registry.register_local_tool(sql_tool, access_groups=[])
        registry.register_local_tool(semantic_tool, access_groups=[])
        decision = await SemanticFirstPlanner(semantic_adapter).decide(
            "Show revenue by month",
            await registry.get_schemas(tenant_a.user),
            tenant_a,
        )
        assert decision.route == "semantic_preferred"
        assert decision.blocked_capabilities == ("sql",)
        semantic_result = await semantic_tool.execute(
            tenant_a,
            SemanticQueryToolArgs(metric="revenue"),
        )
        assert semantic_result.success

        chart = dataframe_to_vega_lite_spec(
            rows=result_a.metadata["results"],
            columns=["id", "tenant_id", "value"],
            column_types={
                "id": "quantitative",
                "tenant_id": "nominal",
                "value": "quantitative",
            },
            title="Tenant-scoped values",
        )
        assert chart.format == "vega-lite"
        assert chart.dataset == result_a.metadata["results"]

        lineage = LineageCollector(
            request_id=tenant_a.request_id,
            conversation_id=tenant_a.conversation_id,
        )
        lineage.set_visibility(
            show_tool_names=True,
            show_sql=True,
            show_sources=True,
        )
        lineage.set_schema(
            drifted_snapshot.snapshot.schema_hash,
            drifted_snapshot.snapshot.snapshot_id,
            schema_version=drifted_snapshot.snapshot.schema_version,
            schema_drifted=drifted_snapshot.diff.has_drift,
        )
        lineage.set_semantic("full", metric_names=("revenue",))
        lineage.record_tool_result(
            sql_tool.name,
            result_a.success,
            result_a.metadata,
        )
        lineage.record_tool_result(
            semantic_tool.name,
            semantic_result.success,
            semantic_result.metadata,
        )
        public_lineage = lineage.to_public_evidence()
        assert public_lineage["schema_version"] == 2
        assert public_lineage["schema_drifted"] is True
        assert public_lineage["semantic"]["coverage"] == "full"
        assert public_lineage["sql_executions"][0]["row_count"] == 1

        feedback = FeedbackService(
            database_path=str(tmp_path / "feedback.sqlite3"),
            query_policy=query_policy,
        )
        original_sql = f"SELECT id, tenant_id, value FROM {table_name}"
        corrected_sql = f"SELECT id, tenant_id FROM {table_name} ORDER BY id"
        await memory.save_tool_usage(
            question="Show my tenant rows",
            tool_name="run_sql",
            args={"sql": original_sql},
            context=tenant_a,
            success=True,
        )
        feedback_result = await feedback.process_feedback(
            FeedbackRequest(
                rating="down",
                conversation_id=tenant_a.conversation_id,
                request_id=tenant_a.request_id,
                question="Show my tenant rows",
                original_sql=original_sql,
                corrected_sql=corrected_sql,
                reason_codes=["wrong_columns"],
            ),
            tenant_a,
        )
        next_request_memories = await memory.search_similar_usage(
            "Show my tenant rows",
            tenant_a,
            similarity_threshold=0.1,
            tool_name_filter="run_sql",
        )
        other_tenant_memories = await memory.search_similar_usage(
            "Show my tenant rows",
            tenant_b,
            similarity_threshold=0.1,
            tool_name_filter="run_sql",
        )
        assert feedback_result.patched_memories == 2
        assert next_request_memories[0].memory.metadata is not None
        assert next_request_memories[0].memory.metadata["patch_type"] == "corrective"
        assert other_tenant_memories == []
        assert memory_scope_for_context(tenant_a) != memory_scope_for_context(tenant_b)
    finally:
        if fixture_created:
            _drop_fixture(admin_dsn, table_name, role_name)
