import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from vanna.models.user import User
from vanna.integrations.datahub.sync import DataHubContextEnhancer

@pytest.fixture
def mock_user():
    return User(id="test_user", group_memberships=["admin"])

@pytest.fixture
def enhancer():
    return DataHubContextEnhancer(datahub_url="http://mock-datahub:8080", token="mock-token")

@pytest.mark.asyncio
async def test_datahub_enhancer_initialization(enhancer):
    assert enhancer.datahub_url == "http://mock-datahub:8080"
    assert enhancer.token == "mock-token"
    assert enhancer.headers["Authorization"] == "Bearer mock-token"

@pytest.mark.asyncio
@patch("vanna.integrations.datahub.sync.httpx.AsyncClient.post")
async def test_fetch_glossary_terms_success(mock_post, enhancer):
    # Mock response
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={
        "data": {
            "search": {
                "searchResults": [
                    {
                        "entity": {
                            "urn": "urn:li:glossaryTerm:active_users",
                            "name": "Active Users",
                            "properties": {
                                "description": "Users who have logged in within the last 30 days."
                            }
                        }
                    },
                    {
                        "entity": {
                            "urn": "urn:li:glossaryTerm:arr",
                            "name": "ARR",
                            "properties": {
                                "description": "Annual Recurring Revenue."
                            }
                        }
                    }
                ]
            }
        }
    })
    mock_post.return_value = mock_response

    terms = await enhancer._fetch_glossary_terms("What is ARR and active users?")
    
    assert len(terms) == 2
    assert terms[0]["name"] == "Active Users"
    assert terms[0]["description"] == "Users who have logged in within the last 30 days."
    assert terms[1]["name"] == "ARR"
    assert terms[1]["description"] == "Annual Recurring Revenue."

@pytest.mark.asyncio
@patch("vanna.integrations.datahub.sync.httpx.AsyncClient.post")
async def test_enhance_system_prompt_with_terms(mock_post, enhancer, mock_user):
    # Mock response
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={
        "data": {
            "search": {
                "searchResults": [
                    {
                        "entity": {
                            "name": "ARR",
                            "properties": {
                                "description": "Annual Recurring Revenue."
                            }
                        }
                    }
                ]
            }
        }
    })
    mock_post.return_value = mock_response

    original_prompt = "You are an AI sql generator."
    enhanced_prompt = await enhancer.enhance_system_prompt(original_prompt, "Show me ARR", mock_user)
    
    assert "You are an AI sql generator." in enhanced_prompt
    assert "Enterprise Glossary Context (from DataHub):" in enhanced_prompt
    assert "- **ARR**: Annual Recurring Revenue." in enhanced_prompt

@pytest.mark.asyncio
@patch("vanna.integrations.datahub.sync.httpx.AsyncClient.post")
async def test_enhance_system_prompt_empty_results(mock_post, enhancer, mock_user):
    # Mock response
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={
        "data": {
            "search": {
                "searchResults": []
            }
        }
    })
    mock_post.return_value = mock_response

    original_prompt = "You are an AI sql generator."
    enhanced_prompt = await enhancer.enhance_system_prompt(original_prompt, "Show me nothing", mock_user)
    
    assert enhanced_prompt == original_prompt

@pytest.mark.asyncio
@patch("vanna.integrations.datahub.sync.httpx.AsyncClient.post")
async def test_enhance_system_prompt_api_error(mock_post, enhancer, mock_user):
    # Mock API error
    mock_post.side_effect = Exception("API Server down")

    original_prompt = "You are an AI sql generator."
    enhanced_prompt = await enhancer.enhance_system_prompt(original_prompt, "Show me something", mock_user)
    
    # Should safely return original prompt and not crash
    assert enhanced_prompt == original_prompt
