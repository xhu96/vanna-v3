"""Tests for richer schema memories emitted during sync."""

import pandas as pd
import pytest

from vanna.infrastructure.sql_runner import RunSqlToolArgs, SqlRunner
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.services.schema_sync import PortableSchemaCatalogService


class EvolvingSqlRunner(SqlRunner):
    def __init__(self):
        self.version = 0

    async def run_sql(self, args: RunSqlToolArgs, context: ToolContext) -> pd.DataFrame:
        if "information_schema.columns" not in args.sql:
            raise ValueError("Unexpected SQL")

        rows = [
            {
                "schema_name": "public",
                "table_name": "orders",
                "column_name": "id",
                "data_type": "integer",
                "is_nullable": 0,
            }
        ]
        if self.version > 0:
            rows.append(
                {
                    "schema_name": "public",
                    "table_name": "orders",
                    "column_name": "status",
                    "data_type": "text",
                    "is_nullable": 1,
                }
            )
        return pd.DataFrame(rows)


@pytest.mark.asyncio
async def test_schema_sync_publishes_table_level_text_memories(tmp_path):
    runner = EvolvingSqlRunner()
    service = PortableSchemaCatalogService(
        runner,
        persist_path=str(tmp_path / "schema.json"),
        dialect="postgres",
    )
    memory = DemoAgentMemory()
    context = ToolContext(
        user=User(id="u1", group_memberships=["admin"]),
        conversation_id="c1",
        request_id="r1",
        agent_memory=memory,
    )

    await service.sync(context)

    recent_text = await memory.get_recent_text_memories(context, limit=10)
    contents = [memory.content for memory in recent_text]

    assert any("Schema snapshot synced." in content for content in contents)
    assert any("Schema tables available: public.orders." in content for content in contents)
    assert any("Schema table: public.orders." in content for content in contents)

    runner.version = 1
    await service.sync(context)

    recent_text = await memory.get_recent_text_memories(context, limit=10)
    contents = [memory.content for memory in recent_text]
    assert any("status text nullable" in content for content in contents)
