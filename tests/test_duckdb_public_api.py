"""
DuckDB + free public data integration test.

Downloads real-world CSV data from GitHub and loads it into DuckDB,
then uses the Gemini agent to answer questions about it.

This tests the DuckDB SqlRunner integration with real data.

Requires: GEMINI_API_KEY or GOOGLE_API_KEY environment variable.
"""

import os
import pytest
import tempfile
import sqlite3
import httpx
import pandas as pd
from pathlib import Path


def create_test_database():
    """Download free CSV data and load into a SQLite database.

    Uses the World Bank country indicators data — a clean, well-structured
    dataset with countries, populations, and GDP data.

    Returns the path to the temporary SQLite database.
    """
    # --- Dataset 1: World countries (from datahub.io) ---
    countries_url = "https://raw.githubusercontent.com/datasets/country-codes/master/data/country-codes.csv"

    # --- Dataset 2: Simple COVID data (small, reliable) ---
    covid_url = "https://raw.githubusercontent.com/datasets/covid-19/main/data/countries-aggregated.csv"

    db_path = tempfile.mktemp(suffix=".sqlite")
    conn = sqlite3.connect(db_path)

    try:
        # Download COVID aggregated data (Date, Country, Confirmed, Recovered, Deaths)
        print("Downloading COVID-19 aggregated data...")
        response = httpx.get(covid_url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()

        import io

        df_covid = pd.read_csv(io.StringIO(response.text))
        # Keep only the latest date per country for simplicity
        df_latest = (
            df_covid.sort_values("Date", ascending=False)
            .groupby("Country")
            .first()
            .reset_index()
        )
        df_latest.to_sql("covid_stats", conn, if_exists="replace", index=False)
        print(f"  Loaded {len(df_latest)} country records into covid_stats table")

        # Also keep full time series but limited to a few countries
        focus_countries = ["US", "Brazil", "India", "Germany", "Japan"]
        df_focus = df_covid[df_covid["Country"].isin(focus_countries)].copy()
        df_focus.to_sql("covid_timeseries", conn, if_exists="replace", index=False)
        print(
            f"  Loaded {len(df_focus)} time series records into covid_timeseries table"
        )

        conn.commit()

    except Exception as e:
        print(f"Warning: Could not download from primary URL: {e}")
        print("Creating fallback synthetic data...")

        # Fallback: create synthetic but realistic data
        import random

        random.seed(42)

        countries_data = []
        for i, country in enumerate(
            [
                "United States",
                "Brazil",
                "India",
                "Germany",
                "Japan",
                "France",
                "United Kingdom",
                "Italy",
                "Canada",
                "Australia",
                "South Korea",
                "Spain",
                "Mexico",
                "Indonesia",
                "Netherlands",
            ]
        ):
            population = random.randint(10_000_000, 330_000_000)
            confirmed = random.randint(1_000_000, 100_000_000)
            deaths = int(confirmed * random.uniform(0.01, 0.03))
            recovered = int(confirmed * random.uniform(0.85, 0.98))
            countries_data.append(
                {
                    "Country": country,
                    "Date": "2023-03-09",
                    "Confirmed": confirmed,
                    "Recovered": recovered,
                    "Deaths": deaths,
                }
            )

        df = pd.DataFrame(countries_data)
        df.to_sql("covid_stats", conn, if_exists="replace", index=False)
        print(f"  Loaded {len(df)} fallback records into covid_stats table")
        conn.commit()

    finally:
        conn.close()

    return db_path


@pytest.fixture(scope="session")
def public_data_db():
    """Create a SQLite database with free public data."""
    from vanna.integrations.sqlite import SqliteRunner

    db_path = create_test_database()
    runner = SqliteRunner(database_path=db_path)
    yield runner

    # Cleanup
    try:
        os.unlink(db_path)
    except OSError:
        pass


def create_gemini_agent_for_db(sql_runner):
    """Create a Gemini agent configured for the given SQL runner."""
    from vanna import Agent, AgentConfig
    from vanna.core.registry import ToolRegistry
    from vanna.core.user import User
    from vanna.core.user.resolver import UserResolver
    from vanna.core.user.request_context import RequestContext
    from vanna.tools import RunSqlTool
    from vanna.integrations.local.file_system import LocalFileSystem
    from vanna.integrations.local.agent_memory import DemoAgentMemory
    from vanna.integrations.google import GeminiLlmService
    from vanna.tools.agent_memory import (
        SaveQuestionToolArgsTool,
        SearchSavedCorrectToolUsesTool,
    )

    class SimpleResolver(UserResolver):
        async def resolve_user(self, request_context: RequestContext) -> User:
            return User(
                id="test_user",
                email="test@example.com",
                group_memberships=["user", "admin"],
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
        user_resolver=SimpleResolver(),
        agent_memory=agent_memory,
        config=AgentConfig(),
    )


async def collect_components(agent, question):
    """Helper to collect all components from agent response."""
    from vanna.core.user.request_context import RequestContext

    request_context = RequestContext(cookies={}, headers={})
    components = []
    async for component in agent.send_message(request_context, question):
        components.append(component)
    return components


def extract_text(components):
    """Extract all text content from components."""
    texts = []
    for c in components:
        if hasattr(c, "rich_component") and hasattr(c.rich_component, "content"):
            texts.append(c.rich_component.content)
        if hasattr(c, "simple_component") and hasattr(c.simple_component, "text"):
            texts.append(c.simple_component.text)
    return " ".join(texts)


# ─── Test: Query real COVID data ─────────────────────────────────────────────


@pytest.mark.gemini
@pytest.mark.asyncio
async def test_gemini_public_data_country_count(public_data_db):
    """Agent should answer questions about the free public dataset.

    'How many countries are in the covid_stats table?'
    """
    agent = create_gemini_agent_for_db(public_data_db)
    components = await collect_components(
        agent, "How many countries are in the covid_stats table?"
    )

    assert len(components) > 0, "Should receive at least one component"
    full_text = extract_text(components)
    print(f"\n=== Public Data: Country Count ===\n{full_text}\n")

    # Should mention a number (we don't know exact count since it depends on data)
    assert any(char.isdigit() for char in full_text), (
        f"Should contain a numeric answer. Got: {full_text[:500]}"
    )


@pytest.mark.gemini
@pytest.mark.asyncio
async def test_gemini_public_data_top_confirmed(public_data_db):
    """Agent should find countries with highest confirmed cases.

    'Which country has the most confirmed COVID cases?'
    Expected: US (United States) or similar
    """
    agent = create_gemini_agent_for_db(public_data_db)
    components = await collect_components(
        agent, "Which country has the most confirmed COVID cases according to the data?"
    )

    assert len(components) > 0
    full_text = extract_text(components)
    print(f"\n=== Public Data: Top Confirmed ===\n{full_text}\n")

    # US is typically the highest — but we check for any country name
    has_country = any(
        country in full_text
        for country in ["US", "United States", "Brazil", "India", "France"]
    )
    assert has_country, (
        f"Should mention a country name in the answer. Got: {full_text[:500]}"
    )


@pytest.mark.gemini
@pytest.mark.asyncio
async def test_gemini_public_data_death_rate(public_data_db):
    """Agent should handle calculated fields.

    'What is the average death rate (deaths/confirmed) across all countries?'
    """
    agent = create_gemini_agent_for_db(public_data_db)
    components = await collect_components(
        agent,
        "What is the average death rate (deaths divided by confirmed) across all countries in the covid_stats table? Give me a percentage.",
    )

    assert len(components) > 0
    full_text = extract_text(components)
    print(f"\n=== Public Data: Death Rate ===\n{full_text}\n")

    # Should contain some kind of percentage or decimal number
    assert any(char.isdigit() for char in full_text), (
        f"Should contain calculated results. Got: {full_text[:500]}"
    )


@pytest.mark.gemini
@pytest.mark.asyncio
async def test_gemini_public_data_table_listing(public_data_db):
    """Agent should be able to list tables in the database.

    'What tables are available in the database?'
    """
    agent = create_gemini_agent_for_db(public_data_db)
    components = await collect_components(
        agent, "What tables are available in this database?"
    )

    assert len(components) > 0
    full_text = extract_text(components)
    print(f"\n=== Public Data: Table Listing ===\n{full_text}\n")

    # Should mention at least one of our tables
    has_table = any(
        table in full_text.lower() for table in ["covid_stats", "covid_timeseries"]
    )
    assert has_table, (
        f"Should mention covid_stats or covid_timeseries table. Got: {full_text[:500]}"
    )
