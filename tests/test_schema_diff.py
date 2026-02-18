"""Tests for schema snapshot diff and sync behavior."""

import pandas as pd
import pytest

from vanna.capabilities.sql_runner import RunSqlToolArgs, SqlRunner
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.services.schema_sync import PortableSchemaCatalogService


class EvolvingSqlRunner(SqlRunner):
    def __init__(self):
        self.version = 0

    async def run_sql(self, args: RunSqlToolArgs, context: ToolContext) -> pd.DataFrame:
        if "information_schema.columns" in args.sql:
            if self.version == 0:
                return pd.DataFrame(
                    [
                        {
                            "schema_name": "public",
                            "table_name": "orders",
                            "column_name": "id",
                            "data_type": "integer",
                            "is_nullable": 0,
                        }
                    ]
                )
            return pd.DataFrame(
                [
                    {
                        "schema_name": "public",
                        "table_name": "orders",
                        "column_name": "id",
                        "data_type": "integer",
                        "is_nullable": 0,
                    },
                    {
                        "schema_name": "public",
                        "table_name": "orders",
                        "column_name": "status",
                        "data_type": "text",
                        "is_nullable": 1,
                    },
                ]
            )
        raise ValueError("Unexpected SQL")


@pytest.mark.asyncio
async def test_schema_sync_detects_drift_and_patches_memory(tmp_path):
    runner = EvolvingSqlRunner()
    service = PortableSchemaCatalogService(
        runner, persist_path=str(tmp_path / "schema.json")
    )
    memory = DemoAgentMemory()
    context = ToolContext(
        user=User(id="u1", group_memberships=["admin"]),
        conversation_id="c1",
        request_id="r1",
        agent_memory=memory,
    )

    first = await service.sync(context)
    assert first.diff.has_drift is True  # first snapshot compared with empty baseline

    runner.version = 1
    second = await service.sync(context)
    assert second.diff.has_drift is True
    assert len(second.diff.added_columns) == 1
    assert second.diff.added_columns[0].column_name == "status"

    recent_text = await memory.get_recent_text_memories(context, limit=5)
    assert any("Schema drift detected" in m.content for m in recent_text)
