"""Tenant, history, concurrency, scheduler, and outbox schema sync tests."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import pytest

from vanna.capabilities.sql_runner import RunSqlToolArgs, SqlRunner
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.sqlite import SqliteRunner
from vanna.services.schema_sync import PortableSchemaCatalogService, SchemaScopeError
from vanna.services.schema_sync_cli import run as run_schema_sync_cli


class EvolvingSqlRunner(SqlRunner):
    dialect = "postgres"
    native_read_only = True

    def __init__(self) -> None:
        self.version = 0
        self.calls = 0

    async def run_sql(self, args: RunSqlToolArgs, context: ToolContext) -> pd.DataFrame:
        del context
        assert "information_schema.columns" in args.sql
        self.calls += 1
        await asyncio.sleep(0)
        if self.version == 0:
            return dataframe(
                [
                    ("id", "integer", "NO", 1),
                    ("amount", "integer", "YES", 2),
                ]
            )
        return dataframe(
            [
                ("id", "bigint", "NO", 1),
                ("status", "text", "YES", 2),
            ]
        )


def dataframe(rows: list[tuple[str, str, str, int]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "schema_name": "public",
                "table_name": "orders",
                "column_name": name,
                "data_type": data_type,
                "is_nullable": nullable,
                "ordinal_position": ordinal,
            }
            for name, data_type, nullable, ordinal in rows
        ]
    )


def tool_context(
    tenant_id: str,
    *,
    memory: DemoAgentMemory | None = None,
    authenticated: bool = True,
    request_tenant: str | None = None,
) -> ToolContext:
    return ToolContext(
        user=User(
            id=f"user-{tenant_id}",
            authenticated=authenticated,
            metadata={"tenant_id": tenant_id},
            group_memberships=["admin"],
        ),
        conversation_id=f"conversation-{tenant_id}",
        request_id=f"request-{tenant_id}",
        agent_memory=memory or DemoAgentMemory(),
        metadata={"tenant_id": request_tenant} if request_tenant else {},
    )


class FlakyMemory(DemoAgentMemory):
    def __init__(self) -> None:
        super().__init__()
        self.failures_remaining = 1

    async def upsert_text_memory(  # type: ignore[no-untyped-def]
        self, content: str, context: ToolContext, *, memory_key: str
    ):
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("temporary memory outage")
        return await super().upsert_text_memory(
            content,
            context,
            memory_key=memory_key,
        )


class AppendOnlyMemory(DemoAgentMemory):
    supports_keyed_text_memory_upsert = False


@pytest.mark.asyncio
async def test_sync_versions_history_diff_memory_and_lineage(tmp_path) -> None:
    runner = EvolvingSqlRunner()
    memory = DemoAgentMemory()
    context = tool_context("tenant-a", memory=memory)
    service = PortableSchemaCatalogService(
        runner,
        persist_path=str(tmp_path / "schema.sqlite3"),
        catalog_schemas=["public"],
    )

    first = await service.sync(context)
    unchanged = await service.sync(context)
    runner.version = 1
    changed = await service.sync(context)

    assert first.persisted is True
    assert first.snapshot.schema_version == 1
    assert first.diff.has_drift is True
    assert unchanged.persisted is False
    assert unchanged.snapshot.snapshot_id == first.snapshot.snapshot_id
    assert unchanged.snapshot.schema_version == 1
    assert unchanged.diff.has_drift is False
    assert changed.persisted is True
    assert changed.snapshot.schema_version == 2
    assert changed.snapshot.previous_snapshot_id == first.snapshot.snapshot_id
    assert changed.diff.added_entities == ["public.orders.status"]
    assert changed.diff.removed_entities == ["public.orders.amount"]
    assert changed.diff.changed_entities == ["public.orders.id"]

    history = await service.list_snapshot_history(context)
    assert [item.schema_version for item in history] == [2, 1]
    assert (
        await service.get_snapshot(context, first.snapshot.snapshot_id)
        == first.snapshot
    )

    memories = await memory.get_recent_text_memories(context, limit=20)
    decoded = [json.loads(item.content) for item in memories]
    assert any(item["action"] == "tombstone" for item in decoded)
    assert any(item["action"] == "upsert" for item in decoded)
    assert all(item["tenant_id"] == "tenant-a" for item in decoded)
    by_entity = {item["entity_id"]: item for item in decoded}
    assert len(decoded) == len(by_entity) == 4
    assert by_entity["public.orders.amount"]["action"] == "tombstone"
    assert by_entity["public.orders.id"]["column"]["data_type"] == "bigint"
    assert not any(
        item.get("column", {}).get("data_type") == "integer"
        and item["entity_id"] == "public.orders.id"
        for item in decoded
    )

    lineage = await service.get_lineage_metadata(context)
    assert lineage == {
        "schema_hash": changed.snapshot.schema_hash,
        "schema_version": 2,
        "schema_snapshot_id": changed.snapshot.snapshot_id,
        "schema_drift_detected": True,
        "schema_captured_at": changed.snapshot.captured_at.isoformat(),
    }


@pytest.mark.asyncio
async def test_snapshots_are_tenant_isolated_and_request_metadata_is_ignored(
    tmp_path,
) -> None:
    service = PortableSchemaCatalogService(
        EvolvingSqlRunner(),
        persist_path=str(tmp_path / "schema.sqlite3"),
        catalog_schemas=["public"],
    )
    tenant_a = tool_context("tenant-a", request_tenant="tenant-b")
    tenant_b = tool_context("tenant-b")

    first = await service.sync(tenant_a)
    second = await service.sync(tenant_b)

    assert first.snapshot.tenant_id == "tenant-a"
    assert second.snapshot.tenant_id == "tenant-b"
    assert first.snapshot.snapshot_id != second.snapshot.snapshot_id
    assert await service.get_snapshot(tenant_b, first.snapshot.snapshot_id) is None
    assert len(await service.list_snapshot_history(tenant_a)) == 1
    assert len(await service.list_snapshot_history(tenant_b)) == 1


@pytest.mark.asyncio
async def test_schema_scope_fails_closed_for_anonymous_or_invalid_claims(
    tmp_path,
) -> None:
    service = PortableSchemaCatalogService(
        EvolvingSqlRunner(),
        persist_path=str(tmp_path / "schema.sqlite3"),
        catalog_schemas=["public"],
    )

    with pytest.raises(SchemaScopeError, match="authentication"):
        await service.sync(tool_context("tenant-a", authenticated=False))

    invalid = tool_context("tenant-a")
    invalid.user.metadata["tenant_id"] = "../../other-tenant"
    with pytest.raises(SchemaScopeError, match="invalid"):
        await service.sync(invalid)


@pytest.mark.asyncio
async def test_concurrent_equal_syncs_create_one_immutable_version(tmp_path) -> None:
    memory = DemoAgentMemory()
    service = PortableSchemaCatalogService(
        EvolvingSqlRunner(),
        persist_path=str(tmp_path / "schema.sqlite3"),
        catalog_schemas=["public"],
    )
    context = tool_context("tenant-a", memory=memory)

    results = await asyncio.gather(*(service.sync(context) for _ in range(12)))

    assert sum(result.persisted for result in results) == 1
    assert {result.snapshot.schema_version for result in results} == {1}
    assert len({result.snapshot.snapshot_id for result in results}) == 1
    assert len(await service.list_snapshot_history(context)) == 1
    applied_patch_ids = [
        patch_id for result in results for patch_id in result.memory_patches_applied
    ]
    assert len(applied_patch_ids) == len(set(applied_patch_ids)) == 3
    memories = await memory.get_recent_text_memories(context, limit=10)
    assert {json.loads(item.content)["patch_id"] for item in memories} == set(
        applied_patch_ids
    )


@pytest.mark.asyncio
async def test_memory_outbox_retries_after_snapshot_was_committed(tmp_path) -> None:
    memory = FlakyMemory()
    context = tool_context("tenant-a", memory=memory)
    service = PortableSchemaCatalogService(
        EvolvingSqlRunner(),
        persist_path=str(tmp_path / "schema.sqlite3"),
        catalog_schemas=["public"],
    )

    with pytest.raises(RuntimeError, match="temporary memory outage"):
        await service.sync(context)

    recovered = await service.sync(context)
    assert recovered.persisted is False
    assert recovered.memory_patches_applied
    assert len(await service.list_snapshot_history(context)) == 1


@pytest.mark.asyncio
async def test_schema_memory_sync_rejects_append_only_backend(tmp_path) -> None:
    path = str(tmp_path / "schema.sqlite3")
    service = PortableSchemaCatalogService(
        EvolvingSqlRunner(),
        persist_path=path,
        catalog_schemas=["public"],
    )

    with pytest.raises(RuntimeError, match="keyed text-memory upsert"):
        await service.sync(tool_context("tenant-a", memory=AppendOnlyMemory()))

    recovered = await PortableSchemaCatalogService(
        EvolvingSqlRunner(),
        persist_path=path,
        catalog_schemas=["public"],
    ).sync(tool_context("tenant-a", memory=DemoAgentMemory()))
    assert recovered.persisted is False
    assert recovered.memory_patches_pending == 0


@pytest.mark.asyncio
async def test_schedule_claim_is_durable_across_service_instances(tmp_path) -> None:
    store_path = str(tmp_path / "schema.sqlite3")
    runner = EvolvingSqlRunner()
    first_service = PortableSchemaCatalogService(
        runner,
        persist_path=store_path,
        cron_schedule="*/5 * * * *",
        catalog_schemas=["public"],
    )
    second_service = PortableSchemaCatalogService(
        runner,
        persist_path=store_path,
        cron_schedule="*/5 * * * *",
        catalog_schemas=["public"],
    )
    context = tool_context("tenant-a")
    due = datetime(2026, 8, 10, 12, 10, tzinfo=timezone.utc)

    first = await first_service.run_scheduled_sync_if_due(context, due)
    duplicate = await second_service.run_scheduled_sync_if_due(context, due)
    next_minute = await second_service.run_scheduled_sync_if_due(
        context,
        due.replace(minute=15),
    )

    assert first is not None
    assert duplicate is None
    assert next_minute is not None
    assert next_minute.persisted is False


def test_legacy_mutable_json_store_requires_explicit_migration(tmp_path) -> None:
    path = tmp_path / "schema.json"
    path.write_text('{"snapshot": {}}', encoding="utf-8")

    with pytest.raises(ValueError, match="legacy JSON"):
        PortableSchemaCatalogService(
            EvolvingSqlRunner(),
            persist_path=str(path),
        )


@pytest.mark.asyncio
async def test_snapshot_history_rows_are_database_immutable(tmp_path) -> None:
    path = tmp_path / "schema.sqlite3"
    service = PortableSchemaCatalogService(
        EvolvingSqlRunner(),
        persist_path=str(path),
        catalog_schemas=["public"],
    )
    await service.sync(tool_context("tenant-a"))
    assert path.stat().st_mode & 0o777 == 0o600

    connection = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE schema_snapshots SET schema_hash = ?",
                ("0" * 64,),
            )
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_one_shot_cli_is_idempotent_and_emits_bounded_metadata(
    tmp_path,
    capsys,
) -> None:
    database = tmp_path / "source.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE orders (id INTEGER NOT NULL)")
        connection.commit()
    finally:
        connection.close()
    store = tmp_path / "catalog.sqlite3"
    arguments = [
        "--tenant",
        "tenant-a",
        "--once",
        "--database-url",
        f"sqlite://{database}",
        "--store-path",
        str(store),
        "--include-table",
        "orders",
    ]

    assert await run_schema_sync_cli(arguments) == 0
    first = json.loads(capsys.readouterr().out)
    assert await run_schema_sync_cli(arguments) == 0
    second = json.loads(capsys.readouterr().out)

    assert first["status"] == "ok"
    assert first["tenant_id"] == "tenant-a"
    assert first["schema_version"] == 1
    assert first["persisted"] is True
    assert first["memory_patches_applied"] == 0
    assert first["memory_patches_pending"] > 0
    assert second["snapshot_id"] == first["snapshot_id"]
    assert second["schema_version"] == 1
    assert second["persisted"] is False
    assert second["memory_patches_pending"] == first["memory_patches_pending"]

    memory = DemoAgentMemory()
    application_service = PortableSchemaCatalogService(
        SqliteRunner(database_path=str(database), read_only=True),
        persist_path=str(store),
        catalog_tables=["orders"],
    )
    application_sync = await application_service.sync(
        tool_context("tenant-a", memory=memory)
    )
    assert application_sync.persisted is False
    assert application_sync.memory_patches_applied
    assert application_sync.memory_patches_pending == 0
    assert await memory.get_recent_text_memories(
        tool_context("tenant-a", memory=memory), limit=10
    )

    assert set(second) == {
        "drift_detected",
        "memory_patches_applied",
        "memory_patches_pending",
        "persisted",
        "schema_hash",
        "schema_version",
        "snapshot_id",
        "status",
        "tenant_id",
    }


class DottedIdentifierSqlRunner(SqlRunner):
    dialect = "postgres"
    native_read_only = True

    async def run_sql(self, args: RunSqlToolArgs, context: ToolContext) -> pd.DataFrame:
        del context
        assert "information_schema.columns" in args.sql
        return pd.DataFrame(
            [
                {
                    "schema_name": "a.b",
                    "table_name": "c",
                    "column_name": "d",
                    "data_type": "integer",
                    "is_nullable": "NO",
                    "ordinal_position": 1,
                },
                {
                    "schema_name": "a",
                    "table_name": "b.c",
                    "column_name": "d",
                    "data_type": "integer",
                    "is_nullable": "NO",
                    "ordinal_position": 1,
                },
            ]
        )


@pytest.mark.asyncio
async def test_dotted_catalog_identifiers_persist_as_distinct_memory_entities(
    tmp_path,
) -> None:
    memory = DemoAgentMemory()
    context = tool_context("tenant-a", memory=memory)
    store_path = str(tmp_path / "dotted-schema.sqlite3")
    service = PortableSchemaCatalogService(
        DottedIdentifierSqlRunner(),
        persist_path=store_path,
        catalog_schemas=["a", "a.b"],
    )

    result = await service.sync(context)
    reopened = PortableSchemaCatalogService(
        DottedIdentifierSqlRunner(),
        persist_path=store_path,
        catalog_schemas=["a", "a.b"],
    )
    persisted = await reopened.get_latest_snapshot(context)
    memories = await memory.get_recent_text_memories(context, limit=10)
    patches = [json.loads(item.content) for item in memories]
    upsert_ids = {
        patch["entity_id"] for patch in patches if patch["action"] == "upsert"
    }

    assert persisted == result.snapshot
    assert len(result.snapshot.columns) == 2
    assert upsert_ids == {"a%2Eb.c.d", "a.b%2Ec.d"}
    assert len(result.memory_patches_applied) == 3
    assert len(set(result.memory_patches_applied)) == 3
