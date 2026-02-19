"""OpenRouter LLM service.

OpenRouter exposes an OpenAI-compatible API. We implement this as a small
wrapper around :class:`vanna.integrations.openai.OpenAILlmService` that sets:
  - base_url to OpenRouter's endpoint
  - api_key from OPENROUTER_API_KEY
  - optional OpenRouter identification headers

This module does **not** provide keys or manage credentials; it only reads
environment variables.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from vanna.integrations.openai import OpenAILlmService


class OpenRouterLlmService(OpenAILlmService):
    """OpenRouter-backed LLM service (OpenAI-compatible).

    Args:
        model: OpenRouter model id (e.g., "openai/gpt-4o-mini").
        api_key: API key; falls back to env `OPENROUTER_API_KEY`.
        base_url: Custom base URL; falls back to env `OPENROUTER_BASE_URL`.
        http_referer: Optional referer header (recommended by OpenRouter).
        app_title: Optional X-Title header (recommended by OpenRouter).
        extra_client_kwargs: Extra kwargs forwarded to `openai.OpenAI()`.
    """

    DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
    DEFAULT_MODEL = "openai/gpt-4o-mini"

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        http_referer: Optional[str] = None,
        app_title: Optional[str] = None,
        **extra_client_kwargs: Any,
    ) -> None:
        api_key = api_key or os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = base_url or os.getenv("OPENROUTER_BASE_URL") or self.DEFAULT_BASE_URL
        model = (
            model
            or os.getenv("OPENROUTER_MODEL")
            or os.getenv("OPENAI_MODEL")
            or self.DEFAULT_MODEL
        )

        http_referer = http_referer or os.getenv("OPENROUTER_HTTP_REFERER")
        app_title = app_title or os.getenv("OPENROUTER_APP_TITLE")

        # Merge in OpenRouter recommended identification headers.
        default_headers: Dict[str, str] = {}
        if http_referer:
            default_headers["HTTP-Referer"] = http_referer
        if app_title:
            default_headers["X-Title"] = app_title

        if default_headers:
            existing = extra_client_kwargs.get("default_headers")
            if isinstance(existing, dict):
                merged = {**existing, **default_headers}
                extra_client_kwargs["default_headers"] = merged
            else:
                extra_client_kwargs["default_headers"] = default_headers

        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url,
            **extra_client_kwargs,
        )
