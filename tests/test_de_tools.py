import pytest
import pandas as pd
from unittest.mock import AsyncMock
from vanna.infrastructure.sql_runner import SqlRunner
from vanna.core.tool import ToolContext
from vanna.tools.statistical_analysis import TTestTool, CorrelationTool, TTestToolArgs, CorrelationToolArgs
from vanna.tools.export_data import ExportToCSVTool, ExportToCSVToolArgs
from vanna.infrastructure.file_system import FileSystem

class MockSqlRunner(SqlRunner):
    def __init__(self, data=None):
        self.data = data or []
    
    async def run_sql(self, args, context=None):
        return pd.DataFrame(self.data)

@pytest.mark.asyncio
async def test_ttest_tool():
    data = [
        {"group": "A", "val": 10},
        {"group": "A", "val": 12},
        {"group": "A", "val": 11},
        {"group": "B", "val": 20},
        {"group": "B", "val": 22},
        {"group": "B", "val": 21},
    ]
    runner = MockSqlRunner(data)
    tool = TTestTool(sql_runner=runner)
    
    args = TTestToolArgs(
        sql="SELECT * FROM test",
        group_column="group",
        value_column="val",
        group_a_name="A",
        group_b_name="B"
    )
    context = AsyncMock(spec=ToolContext)
    
    result = await tool.execute(context, args)
    
    assert result.success is True
    assert "T-Test Results:" in result.result_for_llm
    assert result.metadata["p_value"] < 0.05
    assert result.metadata["group_a_mean"] == 11.0
    assert result.metadata["group_b_mean"] == 21.0

@pytest.mark.asyncio
async def test_correlation_tool():
    data = [
        {"a": 1, "b": 2, "c": "ignore"},
        {"a": 2, "b": 4, "c": "ignore"},
        {"a": 3, "b": 6, "c": "ignore"},
    ]
    runner = MockSqlRunner(data)
    tool = CorrelationTool(sql_runner=runner)
    
    args = CorrelationToolArgs(sql="SELECT * FROM test")
    context = AsyncMock(spec=ToolContext)
    
    result = await tool.execute(context, args)
    
    assert result.success is True
    assert "Correlation Matrix:" in result.result_for_llm
    assert "1" in result.result_for_llm

@pytest.mark.asyncio
async def test_export_to_csv_tool():
    data = [
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob"},
    ]
    runner = MockSqlRunner(data)
    fs = AsyncMock(spec=FileSystem)
    tool = ExportToCSVTool(sql_runner=runner, file_system=fs)
    
    args = ExportToCSVToolArgs(sql="SELECT * FROM test", filename="test_output.csv")
    context = AsyncMock(spec=ToolContext)
    
    result = await tool.execute(context, args)
    
    assert result.success is True
    assert "Successfully exported" in result.result_for_llm
    fs.write_file.assert_called_once()
