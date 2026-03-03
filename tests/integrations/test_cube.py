import pytest
import pandas as pd
from unittest.mock import AsyncMock, patch, MagicMock

from vanna.capabilities.sql_runner.models import RunSqlToolArgs
from vanna.integrations.cube.cube_runner import CubeRunner

@pytest.fixture
def cube_runner():
    return CubeRunner(cube_api_url="http://mock-cube:4000", security_context_token="mock-token")

@pytest.fixture
def mock_context():
    context = MagicMock()
    context.user = MagicMock()
    context.user.id = "test_user"
    return context

@pytest.mark.asyncio
async def test_cube_runner_initialization(cube_runner):
    assert cube_runner.cube_api_url == "http://mock-cube:4000"
    assert cube_runner.security_context_token == "mock-token"
    assert cube_runner.headers["Authorization"] == "Bearer mock-token"

@pytest.mark.asyncio
@patch("vanna.integrations.cube.cube_runner.httpx.AsyncClient.post")
async def test_run_sql_success(mock_post, cube_runner, mock_context):
    args = RunSqlToolArgs(sql="SELECT * FROM Orders")
    
    # Mock response
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={
        "data": [
            {"Orders.id": 1, "Orders.status": "shipped"},
            {"Orders.id": 2, "Orders.status": "processing"}
        ]
    })
    mock_post.return_value = mock_response

    df = await cube_runner.run_sql(args, mock_context)
    
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert "Orders.id" in df.columns
    assert df.iloc[0]["Orders.status"] == "shipped"

@pytest.mark.asyncio
@patch("vanna.integrations.cube.cube_runner.httpx.AsyncClient.post")
async def test_run_sql_empty_results(mock_post, cube_runner, mock_context):
    args = RunSqlToolArgs(sql="SELECT * FROM EmptyTable")
    
    # Mock response
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={
        "data": []
    })
    mock_post.return_value = mock_response

    df = await cube_runner.run_sql(args, mock_context)
    
    assert isinstance(df, pd.DataFrame)
    assert df.empty

@pytest.mark.asyncio
@patch("vanna.integrations.cube.cube_runner.httpx.AsyncClient.post")
async def test_run_sql_error_response(mock_post, cube_runner, mock_context):
    args = RunSqlToolArgs(sql="INVALID SQL")
    
    # Mock response
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={
        "error": "Syntax error in SQL"
    })
    mock_post.return_value = mock_response

    with pytest.raises(ValueError, match="Cube.dev Error: Syntax error in SQL"):
        await cube_runner.run_sql(args, mock_context)

@pytest.mark.asyncio
@patch("vanna.integrations.cube.cube_runner.httpx.AsyncClient.post")
async def test_run_sql_http_exception(mock_post, cube_runner, mock_context):
    args = RunSqlToolArgs(sql="SELECT * FROM Orders")
    
    # Mock exception
    mock_post.side_effect = Exception("Connection Refused")
    
    with pytest.raises(Exception, match="Failed to execute semantic query against Cube: Connection Refused"):
        await cube_runner.run_sql(args, mock_context)
