"""
Comprehensive Gemini end-to-end integration tests.

Tests the full agent pipeline: Gemini LLM → SQL generation → execution → response.
Uses the Chinook SQLite database (a music store with 11 tables).

Requires: GEMINI_API_KEY or GOOGLE_API_KEY environment variable.

Note: Free-tier Gemini API has rate limits. Tests include retry logic
and delays between requests to handle 429 errors gracefully.
"""

import asyncio
import os
import pytest
import time
from vanna.core.user import User
from vanna.core.user.resolver import UserResolver
from vanna.core.user.request_context import RequestContext


class TestUserResolver(UserResolver):
    """Simple user resolver for integration tests."""

    async def resolve_user(self, request_context: RequestContext) -> User:
        return User(
            id="test_user",
            email="test@example.com",
            group_memberships=["user", "admin"],
        )


def create_gemini_agent(sql_runner):
    """Create a fully configured Gemini agent with tools."""
    from vanna import Agent, AgentConfig
    from vanna.core.registry import ToolRegistry
    from vanna.tools import RunSqlTool
    from vanna.integrations.local.file_system import LocalFileSystem
    from vanna.integrations.local.agent_memory import DemoAgentMemory
    from vanna.integrations.google import GeminiLlmService
    from vanna.tools.agent_memory import (
        SaveQuestionToolArgsTool,
        SearchSavedCorrectToolUsesTool,
    )

    llm = GeminiLlmService(model="gemini-2.5-flash", temperature=0.0)

    tools = ToolRegistry()
    db_tool = RunSqlTool(sql_runner=sql_runner, file_system=LocalFileSystem())
    tools.register_local_tool(db_tool, access_groups=["user"])

    agent_memory = DemoAgentMemory(max_items=1000)
    tools.register_local_tool(SaveQuestionToolArgsTool(), access_groups=["user"])
    tools.register_local_tool(SearchSavedCorrectToolUsesTool(), access_groups=["user"])

    return Agent(
        llm_service=llm,
        tool_registry=tools,
        user_resolver=TestUserResolver(),
        agent_memory=agent_memory,
        config=AgentConfig(),
    )


async def collect_components_with_retry(agent, question, max_retries=3):
    """Collect agent components with retry logic for rate limits."""
    request_context = RequestContext(cookies={}, headers={})

    for attempt in range(max_retries):
        try:
            components = []
            async for component in agent.send_message(request_context, question):
                components.append(component)

            # Check if the response itself indicates a rate limit error
            full_text = extract_text(components)
            if "429" in full_text or "RESOURCE_EXHAUSTED" in full_text:
                wait_time = 30 * (attempt + 1)
                print(
                    f"  Rate limited (response), waiting {wait_time}s (attempt {attempt + 1}/{max_retries})..."
                )
                await asyncio.sleep(wait_time)
                continue

            return components

        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                wait_time = 30 * (attempt + 1)
                print(
                    f"  Rate limited (exception), waiting {wait_time}s (attempt {attempt + 1}/{max_retries})..."
                )
                await asyncio.sleep(wait_time)
                if attempt == max_retries - 1:
                    pytest.skip(
                        f"Gemini API rate limit exceeded after {max_retries} retries"
                    )
            else:
                raise

    pytest.skip("Gemini API rate limit exceeded after all retries")
    return []  # unreachable


def extract_text(components):
    """Extract all text content from components for assertion checking."""
    texts = []
    for c in components:
        if hasattr(c, "rich_component") and hasattr(c.rich_component, "content"):
            texts.append(c.rich_component.content)
        if hasattr(c, "simple_component") and hasattr(c.simple_component, "text"):
            texts.append(c.simple_component.text)
    return " ".join(texts)


# Rate-limit friendly wait between tests
INTER_TEST_DELAY = (
    45  # seconds — free tier allows ~5 req/min, agent uses ~3 per question
)


# ─── Test: Simple Count Query ────────────────────────────────────────────────


@pytest.mark.gemini
@pytest.mark.asyncio
async def test_gemini_simple_count(chinook_db):
    """Agent should answer a simple count question.

    'How many artists are there?' → SELECT COUNT(*) FROM Artist → 275
    """
    agent = create_gemini_agent(chinook_db)
    components = await collect_components_with_retry(
        agent, "How many artists are there?"
    )

    assert len(components) > 0, "Should receive at least one component"
    full_text = extract_text(components)
    print(f"\n=== Simple Count ===\n{full_text}\n")

    assert "275" in full_text, f"Should mention 275 artists. Got: {full_text[:500]}"

    # Wait before next test to avoid rate limits
    await asyncio.sleep(INTER_TEST_DELAY)


# ─── Test: JOIN + GROUP BY + LIMIT ───────────────────────────────────────────


@pytest.mark.gemini
@pytest.mark.asyncio
async def test_gemini_join_query(chinook_db):
    """Agent should answer a query requiring JOINs.

    'What are the top 5 genres by number of tracks?'
    Expected top genre: Rock (with 1297 tracks)
    """
    agent = create_gemini_agent(chinook_db)
    components = await collect_components_with_retry(
        agent, "What are the top 5 genres by number of tracks?"
    )

    assert len(components) > 0
    full_text = extract_text(components)
    print(f"\n=== JOIN Query ===\n{full_text}\n")

    assert "Rock" in full_text, (
        f"Should mention 'Rock' as top genre. Got: {full_text[:500]}"
    )

    await asyncio.sleep(INTER_TEST_DELAY)


# ─── Test: Multi-table JOIN (customers → invoices → invoice_items) ───────────


@pytest.mark.gemini
@pytest.mark.asyncio
async def test_gemini_multi_table_join(chinook_db):
    """Agent should handle multi-table JOINs.

    'Show me the top 3 customers by total spending'
    """
    agent = create_gemini_agent(chinook_db)
    components = await collect_components_with_retry(
        agent, "Show me the top 3 customers by total spending"
    )

    assert len(components) > 0
    full_text = extract_text(components)
    print(f"\n=== Multi-table JOIN ===\n{full_text}\n")

    has_customers = any(
        name in full_text
        for name in ["Helena", "Richard", "Luis", "Astrid", "Hugh", "Frank"]
    )
    assert has_customers, (
        f"Should mention at least one top customer name. Got: {full_text[:500]}"
    )

    await asyncio.sleep(INTER_TEST_DELAY)


# ─── Test: Streaming yields multiple component types ─────────────────────────


@pytest.mark.gemini
@pytest.mark.asyncio
async def test_gemini_streaming_components(chinook_db):
    """Agent should return multiple streaming components."""
    agent = create_gemini_agent(chinook_db)
    components = await collect_components_with_retry(
        agent, "How many tracks are longer than 5 minutes?"
    )

    print(f"\n=== Streaming Components ===")
    for i, c in enumerate(components):
        ctype = getattr(c, "type", "unknown")
        print(f"  Component {i + 1}: type={ctype}")

    assert len(components) >= 2, (
        f"Should receive at least 2 components, got {len(components)}"
    )

    await asyncio.sleep(INTER_TEST_DELAY)


# ─── Test: Schema awareness ─────────────────────────────────────────────────


@pytest.mark.gemini
@pytest.mark.asyncio
async def test_gemini_schema_awareness(chinook_db):
    """Agent should understand table structures."""
    agent = create_gemini_agent(chinook_db)
    components = await collect_components_with_retry(
        agent, "What columns does the Employee table have?"
    )

    assert len(components) > 0
    full_text = extract_text(components)
    print(f"\n=== Schema Awareness ===\n{full_text}\n")

    has_column_info = any(
        col in full_text
        for col in ["EmployeeId", "LastName", "FirstName", "Title", "Employee"]
    )
    assert has_column_info, (
        f"Should mention Employee table columns. Got: {full_text[:500]}"
    )

    await asyncio.sleep(INTER_TEST_DELAY)


# ─── Test: Aggregation with HAVING ───────────────────────────────────────────


@pytest.mark.gemini
@pytest.mark.asyncio
async def test_gemini_aggregation_having(chinook_db):
    """Agent should handle complex aggregation.

    'Which artists have more than 10 albums?'
    Iron Maiden has 21 albums in Chinook.
    """
    agent = create_gemini_agent(chinook_db)
    components = await collect_components_with_retry(
        agent, "Which artists have more than 10 albums?"
    )

    assert len(components) > 0
    full_text = extract_text(components)
    print(f"\n=== Aggregation HAVING ===\n{full_text}\n")

    assert "Iron Maiden" in full_text, (
        f"Should mention 'Iron Maiden' (21 albums). Got: {full_text[:500]}"
    )
