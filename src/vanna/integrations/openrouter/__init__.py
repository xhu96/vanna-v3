"""OpenRouter integration.

OpenRouter is an OpenAI-compatible gateway. This integration configures the
OpenAI SDK to talk to OpenRouter's API endpoint with the recommended headers.

Environment variables:
  - OPENROUTER_API_KEY
  - OPENROUTER_MODEL (e.g. "openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet")
  - OPENROUTER_BASE_URL (defaults to https://openrouter.ai/api/v1)
  - OPENROUTER_HTTP_REFERER (optional; recommended)
  - OPENROUTER_APP_TITLE (optional; recommended)
"""

from .llm import OpenRouterLlmService

__all__ = ["OpenRouterLlmService"]
