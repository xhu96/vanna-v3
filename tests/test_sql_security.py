"""Security tests for read-only SQL enforcement."""

import pandas as pd
import pytest

from vanna.capabilities.sql_runner import RunSqlToolArgs, SqlRunner
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.tools.run_sql import RunSqlTool


class DummySqlRunner(SqlRunner):
    async def run_sql(
        self, args: RunSqlToolArgs, context: ToolContext
    ) -> pd.DataFrame:
        return pd.DataFrame([{"ok": 1}])


@pytest.fixture
def tool_context():
    return ToolContext(
        user=User(id="u1", group_memberships=["user"]),
        conversation_id="conv1",
        request_id="req1",
        agent_memory=DemoAgentMemory(),
    )


@pytest.mark.asyncio
async def test_run_sql_blocks_write_statement_by_default(tool_context):
    tool = RunSqlTool(sql_runner=DummySqlRunner())
    result = await tool.execute(tool_context, RunSqlToolArgs(sql="DELETE FROM users"))
    assert result.success is False
    assert "read-only SQL policy" in result.result_for_llm


@pytest.mark.asyncio
async def test_run_sql_blocks_multi_statement_by_default(tool_context):
    tool = RunSqlTool(sql_runner=DummySqlRunner())
    result = await tool.execute(
        tool_context, RunSqlToolArgs(sql="SELECT 1; SELECT 2;")
    )
    assert result.success is False
    assert "Multiple SQL statements are blocked" in result.result_for_llm


@pytest.mark.asyncio
async def test_run_sql_allows_select_in_read_only_mode(tool_context):
    tool = RunSqlTool(sql_runner=DummySqlRunner())
    result = await tool.execute(tool_context, RunSqlToolArgs(sql="SELECT 1"))
    assert result.success is True
