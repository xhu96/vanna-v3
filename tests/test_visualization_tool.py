"""Tests for declarative visualization tool output."""

import pytest

from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.tools.file_system import FileSystem, FileSearchMatch, CommandResult
from vanna.tools.visualize_data import VisualizeDataTool, VisualizeDataArgs


class StubFileSystem(FileSystem):
    async def list_files(self, directory: str, context: ToolContext):
        return []

    async def read_file(self, filename: str, context: ToolContext) -> str:
        return "category,value\nA,10\nB,20\n"

    async def write_file(
        self, filename: str, content: str, context: ToolContext, overwrite: bool = False
    ) -> None:
        return None

    async def exists(self, path: str, context: ToolContext) -> bool:
        return True

    async def is_directory(self, path: str, context: ToolContext) -> bool:
        return False

    async def search_files(
        self,
        query: str,
        context: ToolContext,
        *,
        max_results: int = 20,
        include_content: bool = False,
    ):
        return [FileSearchMatch(path="stub.csv")]

    async def run_bash(
        self,
        command: str,
        context: ToolContext,
        *,
        timeout=None,
    ):
        return CommandResult(stdout="", stderr="", returncode=0)


@pytest.mark.asyncio
async def test_visualize_data_returns_declarative_chart_spec():
    context = ToolContext(
        user=User(id="u1", group_memberships=["user"]),
        conversation_id="c1",
        request_id="r1",
        agent_memory=DemoAgentMemory(),
    )
    tool = VisualizeDataTool(file_system=StubFileSystem())
    result = await tool.execute(context, VisualizeDataArgs(filename="test.csv"))

    assert result.success is True
    assert result.ui_component is not None
    rich = result.ui_component.rich_component
    assert rich.type.value == "chart"
    assert rich.data["format"] == "vega-lite"
    assert "spec" in rich.data
    assert "dataset" in rich.data
