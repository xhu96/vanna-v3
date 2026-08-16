"""Tests for safe, declarative visualization tool output."""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from pydantic import ValidationError

import vanna.tools.visualize_data as visualization_module
from vanna.core.chart_spec import MAX_CHART_FIELDS, MAX_CHART_ROWS
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.tools.file_system import CommandResult, FileSearchMatch, FileSystem
from vanna.tools.visualize_data import VisualizeDataArgs, VisualizeDataTool


class StubFileSystem(FileSystem):
    def __init__(self, content: str = "category,value\nA,10\nB,20\n") -> None:
        self.content = content
        self.read_calls: list[str] = []
        self.run_bash_called = False

    async def list_files(self, directory: str, context: ToolContext):
        return []

    async def read_file(self, filename: str, context: ToolContext) -> str:
        self.read_calls.append(filename)
        return self.content

    async def write_file(
        self,
        filename: str,
        content: str,
        context: ToolContext,
        overwrite: bool = False,
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
    ) -> CommandResult:
        self.run_bash_called = True
        raise AssertionError("visualization must not execute shell or Python commands")


class StubPlotlyGenerator:
    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.payload = payload or {
            "data": [
                {
                    "type": "bar",
                    "x": ["A", "B"],
                    "y": [10, 20],
                    "hovertemplate": "generator-only field",
                }
            ],
            "layout": {
                "title": {"text": "Safe chart", "font": {"size": 24}},
                "font": {"family": "Generator default"},
            },
            "config": {"displaylogo": False},
        }
        self.error = error

    def generate_chart(self, dataframe: Any, title: str) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        return self.payload


def _context() -> ToolContext:
    return ToolContext(
        user=User(id="u1", group_memberships=["user"]),
        conversation_id="c1",
        request_id="r1",
        agent_memory=DemoAgentMemory(),
    )


@pytest.mark.asyncio
async def test_visualize_data_returns_safe_vega_lite_chart_spec():
    file_system = StubFileSystem()
    tool = VisualizeDataTool(file_system=file_system)

    result = await tool.execute(_context(), VisualizeDataArgs(filename="test.csv"))

    assert result.success is True
    assert result.ui_component is not None
    rich = result.ui_component.rich_component
    assert rich.type.value == "chart"
    assert rich.chart_type == "declarative"
    assert rich.data["format"] == "vega-lite"
    assert rich.data["schema_version"] == "v5-safe-1"
    assert "data" not in rich.data["spec"]
    assert rich.data["dataset"] == [
        {"category": "A", "value": 10},
        {"category": "B", "value": 20},
    ]
    assert rich.data["metadata"] == {
        "row_count": 2,
        "columns": ["category", "value"],
    }
    assert "source_file" not in rich.data["metadata"]
    assert file_system.read_calls == ["test.csv"]
    assert file_system.run_bash_called is False


@pytest.mark.asyncio
async def test_visualize_data_reduces_plotly_output_to_safe_profile():
    tool = VisualizeDataTool(
        file_system=StubFileSystem(),
        plotly_generator=StubPlotlyGenerator(),
    )

    result = await tool.execute(
        _context(),
        VisualizeDataArgs(filename="test.csv", format="plotly-json"),
    )

    assert result.success is True
    chart = result.ui_component.rich_component.data
    assert chart["schema_version"] == "plotly-safe-1"
    assert chart["spec"] == {
        "data": [{"type": "bar", "x": ["A", "B"], "y": [10, 20]}],
        "layout": {"title": "Safe chart"},
    }
    assert "config" not in chart["spec"]
    assert "hovertemplate" not in chart["spec"]["data"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("trace_type", ["table", "heatmap", "histogram"])
async def test_visualize_data_fails_closed_for_unsupported_plotly_traces(
    trace_type: str,
):
    generator = StubPlotlyGenerator(payload={"data": [{"type": trace_type}]})
    tool = VisualizeDataTool(
        file_system=StubFileSystem(),
        plotly_generator=generator,
    )

    result = await tool.execute(
        _context(),
        VisualizeDataArgs(filename="test.csv", format="plotly-json"),
    )

    assert result.success is False
    assert result.metadata["error_type"] == "visualization_error"
    assert result.metadata["correlation_id"].startswith("tool_")
    assert "Correlation ID: tool_" in result.result_for_llm


@pytest.mark.asyncio
async def test_visualize_data_truncates_inline_data_at_safe_row_limit():
    csv_content = "category,value\n" + "".join(
        f"row-{index},{index}\n" for index in range(MAX_CHART_ROWS + 1)
    )
    tool = VisualizeDataTool(file_system=StubFileSystem(csv_content))

    result = await tool.execute(_context(), VisualizeDataArgs(filename="large.csv"))

    assert result.success is True
    chart = result.ui_component.rich_component.data
    assert len(chart["dataset"]) == MAX_CHART_ROWS
    assert chart["metadata"] == {
        "row_count": MAX_CHART_ROWS + 1,
        "columns": ["category", "value"],
        "truncated": True,
    }


@pytest.mark.asyncio
async def test_visualize_data_rejects_more_than_safe_field_limit():
    columns = [f"column_{index}" for index in range(MAX_CHART_FIELDS + 1)]
    csv_content = ",".join(columns) + "\n" + ",".join("1" for _ in columns)
    tool = VisualizeDataTool(file_system=StubFileSystem(csv_content))

    result = await tool.execute(_context(), VisualizeDataArgs(filename="wide.csv"))

    assert result.success is False
    assert result.metadata["error_type"] == "visualization_error"
    assert result.metadata["correlation_id"].startswith("tool_")


@pytest.mark.asyncio
async def test_visualize_data_rejects_active_chart_title():
    tool = VisualizeDataTool(file_system=StubFileSystem())

    result = await tool.execute(
        _context(),
        VisualizeDataArgs(
            filename="test.csv",
            title='<img src="x" onerror="alert(1)">',
        ),
    )

    assert result.success is False
    assert result.metadata["error_type"] == "visualization_error"
    assert result.metadata["correlation_id"].startswith("tool_")
    assert "<img" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_visualize_data_redacts_unexpected_generator_errors():
    secret = "Authorization: Bearer should-not-leak"
    tool = VisualizeDataTool(
        file_system=StubFileSystem(),
        plotly_generator=StubPlotlyGenerator(error=RuntimeError(secret)),
    )

    result = await tool.execute(
        _context(),
        VisualizeDataArgs(filename="test.csv", format="plotly-json"),
    )

    assert result.success is False
    assert result.metadata["error_type"] == "general_error"
    assert result.metadata["correlation_id"].startswith("tool_")
    assert "Correlation ID: tool_" in result.result_for_llm
    assert result.error == result.result_for_llm
    assert secret not in result.result_for_llm
    assert secret not in result.error


def test_visualize_data_format_is_a_closed_allowlist():
    with pytest.raises(ValidationError, match="vega-lite"):
        VisualizeDataArgs(filename="test.csv", format="html")


def test_visualization_module_has_no_python_execution_path():
    source = inspect.getsource(visualization_module)

    assert "RunPythonFileTool" not in source
    assert "create_python_tools" not in source
    assert "run_bash(" not in source
    assert "exec(" not in source
    assert "eval(" not in source
