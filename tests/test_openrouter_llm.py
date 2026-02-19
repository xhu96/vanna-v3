"""Unit tests for OpenRouter LLM service integration.

These tests validate the OpenRouter integration without making network calls.
"""

import os
from unittest.mock import patch

import pytest


@pytest.mark.openrouter
class TestOpenRouterInitialization:
    @patch.dict(
        os.environ,
        {
            "OPENROUTER_API_KEY": "test-key",
            "OPENROUTER_MODEL": "openai/gpt-4o-mini",
            "OPENROUTER_HTTP_REFERER": "https://example.test",
            "OPENROUTER_APP_TITLE": "vanna-test",
        },
        clear=False,
    )
    @patch("openai.OpenAI")
    def test_init_from_environment_sets_base_url_and_headers(self, mock_openai):
        from vanna.integrations.openrouter import OpenRouterLlmService

        service = OpenRouterLlmService()

        assert service.model == "openai/gpt-4o-mini"

        # Verify OpenAI client called with OpenRouter base URL + identification headers
        mock_openai.assert_called_once()
        call_kwargs = mock_openai.call_args[1]
        assert call_kwargs["api_key"] == "test-key"
        assert call_kwargs["base_url"] == "https://openrouter.ai/api/v1"

        headers = call_kwargs.get("default_headers")
        assert isinstance(headers, dict)
        assert headers.get("HTTP-Referer") == "https://example.test"
        assert headers.get("X-Title") == "vanna-test"

    @patch("openai.OpenAI")
    def test_init_explicit_params_override_env(self, mock_openai):
        from vanna.integrations.openrouter import OpenRouterLlmService

        service = OpenRouterLlmService(
            api_key="k",
            model="anthropic/claude-3.5-sonnet",
            base_url="https://openrouter.ai/api/v1",
            http_referer="https://r.test",
            app_title="title",
        )

        assert service.model == "anthropic/claude-3.5-sonnet"
        call_kwargs = mock_openai.call_args[1]
        assert call_kwargs["api_key"] == "k"
        assert call_kwargs["base_url"] == "https://openrouter.ai/api/v1"
        assert call_kwargs["default_headers"]["HTTP-Referer"] == "https://r.test"
        assert call_kwargs["default_headers"]["X-Title"] == "title"
