import pytest
import pandas as pd
from unittest.mock import AsyncMock, patch, MagicMock

from vanna.infrastructure.sql_runner.models import RunSqlToolArgs
from vanna.integrations.flink.flink_runner import FlinkRunner

@pytest.fixture
def flink_runner():
    return FlinkRunner(flink_sql_gateway_url="http://mock-flink:8083")

@pytest.fixture
def mock_context():
    context = MagicMock()
    return context

@pytest.mark.asyncio
async def test_flink_runner_initialization(flink_runner):
    assert flink_runner.flink_sql_gateway_url == "http://mock-flink:8083"
    assert flink_runner.session_id is None

@pytest.mark.asyncio
@patch("vanna.integrations.flink.flink_runner.httpx.AsyncClient.post")
@patch("vanna.integrations.flink.flink_runner.httpx.AsyncClient.get")
async def test_run_sql_success(mock_get, mock_post, flink_runner, mock_context):
    args = RunSqlToolArgs(sql="SELECT * FROM StreamSales")
    
    # Mock POST for Create Session
    mock_session_resp = AsyncMock()
    mock_session_resp.raise_for_status = MagicMock()
    mock_session_resp.json = MagicMock(return_value={"sessionHandle": "session-123"})
    
    # Mock POST for Execute Statement
    mock_exec_resp = AsyncMock()
    mock_exec_resp.raise_for_status = MagicMock()
    mock_exec_resp.json = MagicMock(return_value={"operationHandle": "op-456"})
    
    mock_post.side_effect = [mock_session_resp, mock_exec_resp]
    
    # Mock GET for Fetch Results
    mock_fetch_resp = AsyncMock()
    mock_fetch_resp.raise_for_status = MagicMock()
    mock_fetch_resp.json = MagicMock(return_value={
        "results": {
            "columns": [{"name": "product"}, {"name": "amount"}],
            "data": [
                {"kind": "INSERT", "fields": ["Laptop", 1200]},
                {"kind": "+I", "fields": ["Mouse", 25]}
            ]
        }
    })
    mock_get.return_value = mock_fetch_resp

    df = await flink_runner.run_sql(args, mock_context)
    
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert "product" in df.columns
    assert "amount" in df.columns
    assert df.iloc[0]["product"] == "Laptop"
    assert df.iloc[1]["amount"] == 25
    assert flink_runner.session_id == "session-123"

@pytest.mark.asyncio
@patch("vanna.integrations.flink.flink_runner.httpx.AsyncClient.post")
@patch("vanna.integrations.flink.flink_runner.httpx.AsyncClient.get")
async def test_run_sql_empty_results(mock_get, mock_post, flink_runner, mock_context):
    args = RunSqlToolArgs(sql="SELECT * FROM EmptyStream")
    
    mock_session_resp = AsyncMock()
    mock_session_resp.raise_for_status = MagicMock()
    mock_session_resp.json = MagicMock(return_value={"sessionHandle": "session-123"})
    
    mock_exec_resp = AsyncMock()
    mock_exec_resp.raise_for_status = MagicMock()
    mock_exec_resp.json = MagicMock(return_value={"operationHandle": "op-456"})
    
    mock_post.side_effect = [mock_session_resp, mock_exec_resp]
    
    mock_fetch_resp = AsyncMock()
    mock_fetch_resp.raise_for_status = MagicMock()
    mock_fetch_resp.json = MagicMock(return_value={
        "results": {
            "columns": [{"name": "product"}],
            "data": []
        }
    })
    mock_get.return_value = mock_fetch_resp

    df = await flink_runner.run_sql(args, mock_context)
    
    assert isinstance(df, pd.DataFrame)
    assert df.empty

@pytest.mark.asyncio
@patch("vanna.integrations.flink.flink_runner.httpx.AsyncClient.post")
async def test_run_sql_error_response(mock_post, flink_runner, mock_context):
    args = RunSqlToolArgs(sql="INVALID SQL")
    
    # Mock session create success, but execute fail
    mock_session_resp = AsyncMock()
    mock_session_resp.raise_for_status = MagicMock()
    mock_session_resp.json = MagicMock(return_value={"sessionHandle": "session-123"})
    
    # Mock exec error HTTP exception
    mock_post.side_effect = [mock_session_resp, Exception("Flink execution failed")]
    
    with pytest.raises(Exception, match="Failed to execute streaming query against Flink"):
        await flink_runner.run_sql(args, mock_context)
