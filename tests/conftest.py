"""
Pytest configuration and shared fixtures for Vanna v2 test suite.
"""

import os
import pytest
import sqlite3
from pathlib import Path
import importlib.util

# Configure pytest-asyncio
pytest_plugins = ["pytest_asyncio"]


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "anthropic: marks tests requiring Anthropic API key"
    )
    config.addinivalue_line("markers", "openai: marks tests requiring OpenAI API key")
    config.addinivalue_line(
        "markers", "openrouter: marks tests requiring OpenRouter API key"
    )
    config.addinivalue_line(
        "markers", "azureopenai: marks tests requiring Azure OpenAI API key"
    )
    config.addinivalue_line("markers", "gemini: marks tests requiring Google API key")
    config.addinivalue_line("markers", "ollama: marks tests requiring Ollama")
    config.addinivalue_line("markers", "chromadb: marks tests requiring ChromaDB")
    config.addinivalue_line("markers", "legacy: marks tests for LegacyVannaAdapter")


def pytest_collection_modifyitems(config, items):
    """Automatically skip tests if required API keys are missing."""
    for item in items:
        # Skip Anthropic tests if no API key
        if "anthropic" in item.keywords:
            if not os.getenv("ANTHROPIC_API_KEY"):
                item.add_marker(
                    pytest.mark.skip(
                        reason="ANTHROPIC_API_KEY environment variable not set"
                    )
                )

        # Skip OpenAI tests if no API key
        if "openai" in item.keywords:
            if not os.getenv("OPENAI_API_KEY"):
                item.add_marker(
                    pytest.mark.skip(
                        reason="OPENAI_API_KEY environment variable not set"
                    )
                )

        # Skip OpenRouter tests if no API key
        if "openrouter" in item.keywords:
            if not os.getenv("OPENROUTER_API_KEY"):
                item.add_marker(
                    pytest.mark.skip(
                        reason="OPENROUTER_API_KEY environment variable not set"
                    )
                )

        # Skip Azure OpenAI tests if no API key
        if "azureopenai" in item.keywords:
            if not os.getenv("AZURE_OPENAI_API_KEY"):
                item.add_marker(
                    pytest.mark.skip(
                        reason="AZURE_OPENAI_API_KEY environment variable not set"
                    )
                )

        # Skip Gemini tests if no API key
        if "gemini" in item.keywords:
            if not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
                item.add_marker(
                    pytest.mark.skip(
                        reason="GOOGLE_API_KEY or GEMINI_API_KEY environment variable not set"
                    )
                )

        # Skip Ollama tests unless explicitly enabled.
        # These tests require the optional `ollama` Python package AND a reachable Ollama server.
        if "ollama" in item.keywords:
            if os.getenv("RUN_OLLAMA_TESTS") not in {"1", "true", "TRUE", "yes", "YES"}:
                item.add_marker(
                    pytest.mark.skip(
                        reason="Ollama tests are disabled by default. Set RUN_OLLAMA_TESTS=1 to enable."
                    )
                )
            elif importlib.util.find_spec("ollama") is None:
                item.add_marker(
                    pytest.mark.skip(
                        reason="ollama package not installed (install with: pip install 'vanna[ollama]' or pip install ollama)"
                    )
                )

        # Skip ChromaDB tests unless explicitly enabled.
        if "chromadb" in item.keywords:
            if os.getenv("RUN_CHROMADB_TESTS") not in {"1", "true", "TRUE", "yes", "YES"}:
                item.add_marker(
                    pytest.mark.skip(
                        reason="ChromaDB tests are disabled by default. Set RUN_CHROMADB_TESTS=1 to enable."
                    )
                )
            elif importlib.util.find_spec("chromadb") is None:
                item.add_marker(
                    pytest.mark.skip(
                        reason="chromadb package not installed (install with: pip install chromadb)"
                    )
                )

        # Legacy adapter tests typically require chromadb.
        if "legacy" in item.keywords and importlib.util.find_spec("chromadb") is None:
            item.add_marker(
                pytest.mark.skip(
                    reason="Legacy adapter tests require chromadb (install with: pip install chromadb)"
                )
            )


@pytest.fixture(scope="session")
def chinook_db(tmp_path_factory):
    """
    Downloads the Chinook SQLite database and returns a SqliteRunner.

    Uses session scope so the database is only downloaded once per test session.
    """
    import httpx
    from vanna.integrations.sqlite import SqliteRunner

    tmp_path = tmp_path_factory.mktemp("data")
    db_path = tmp_path / "Chinook.sqlite"

    # Download the database. In CI/offline environments this may be blocked;
    # in that case, skip the tests that depend on this fixture.
    url = os.getenv("VANNA_TEST_CHINOOK_URL", "https://vanna.ai/Chinook.sqlite")
    try:
        response = httpx.get(url, timeout=30.0)
        response.raise_for_status()
        db_path.write_bytes(response.content)
    except Exception as e:
        pytest.skip(f"Unable to download Chinook SQLite database from {url}: {e}")

    return SqliteRunner(database_path=str(db_path))
