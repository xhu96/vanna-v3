import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from vanna.integrations.great_expectations.quality_gate import GreatExpectationsQualityGate

@pytest.fixture
def quality_gate():
    return GreatExpectationsQualityGate(gx_api_url="http://mock-gx:8000", gx_token="gx-token", strict=True)

@pytest.fixture
def non_strict_quality_gate():
    return GreatExpectationsQualityGate(gx_api_url="http://mock-gx:8000", gx_token="gx-token", strict=False)

@pytest.fixture
def mock_tool():
    tool = MagicMock()
    tool.name = "run_sql"
    return tool

@pytest.fixture
def mock_context():
    context = MagicMock()
    context.tool_args = MagicMock()
    context.tool_args.sql = "SELECT * FROM sales"
    context.evidence = []
    return context

@pytest.mark.asyncio
async def test_gx_initialization(quality_gate):
    assert quality_gate.gx_api_url == "http://mock-gx:8000"
    assert quality_gate.gx_token == "gx-token"
    assert quality_gate.headers["Authorization"] == "Bearer gx-token"

@pytest.mark.asyncio
@patch("vanna.integrations.great_expectations.quality_gate.httpx.AsyncClient.get")
async def test_before_tool_passing(mock_get, quality_gate, mock_tool, mock_context):
    # Mock response
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"status": "passing"})
    mock_get.return_value = mock_response

    # Should not raise any exception
    await quality_gate.before_tool(mock_tool, mock_context)
    assert len(mock_context.evidence) == 0

@pytest.mark.asyncio
@patch("vanna.integrations.great_expectations.quality_gate.httpx.AsyncClient.get")
async def test_before_tool_failing_strict(mock_get, quality_gate, mock_tool, mock_context):
    # Mock response
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"status": "failing"})
    mock_get.return_value = mock_response

    # Should raise Exception because strict is True
    with pytest.raises(Exception, match="Strict Quality Gate: Data Quality Gate Intersect: The 'sales' table recently failed Great Expectations validation. Data might be stale or incorrect."):
        await quality_gate.before_tool(mock_tool, mock_context)

@pytest.mark.asyncio
@patch("vanna.integrations.great_expectations.quality_gate.httpx.AsyncClient.get")
async def test_before_tool_failing_non_strict(mock_get, non_strict_quality_gate, mock_tool, mock_context):
    # Mock response
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"status": "failing"})
    mock_get.return_value = mock_response

    # Should not raise exception, but should append to evidence
    await non_strict_quality_gate.before_tool(mock_tool, mock_context)
    
    assert len(mock_context.evidence) == 1
    assert mock_context.evidence[0]["type"] == "warning"
    assert "Data Quality Gate Intersect" in mock_context.evidence[0]["message"]
