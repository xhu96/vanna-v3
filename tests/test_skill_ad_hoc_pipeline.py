import asyncio
import sqlite3
from pathlib import Path

import pytest

from vanna.core import (
    Agent,
    ToolRegistry,
    LlmRequest,
    LlmResponse,
    LlmStreamChunk,
    ToolCall,
    ToolSchema,
    LlmService,
)
from vanna.core.user.request_context import RequestContext
from vanna.agents.basic import SimpleUserResolver, SimpleAgentMemory
from vanna.integrations.sqlite import SqliteRunner
from vanna.services.schema_sync import PortableSchemaCatalogService
from vanna.tools import RunSqlTool

from vanna.skills import InMemorySkillRegistryStore
from vanna.skills.registry import SkillRegistry
from vanna.skills.enricher import SkillAdHocContextEnricher, SkillAdHocConfig


class DeterministicSqlAnalysisLlm(LlmService):
    """A deterministic tool-calling LLM used for end-to-end pipeline tests.

    This LLM:
      - calls run_sql with a fixed query on the first turn
      - returns a short analysis once the tool result is available
    """

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        last = request.messages[-1] if request.messages else None
        if last and last.role == "tool":
            # Tool results are provided as text/CSV. Keep analysis simple.
            return LlmResponse(
                content=(
                    "I queried the database and computed total revenue by region. "
                    "If you want, I can also break it down by product or by month."
                ),
                finish_reason="stop",
                usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            )

        tool_call = ToolCall(
            id="call_test",
            name="run_sql",
            arguments={
                "sql": (
                    "SELECT region, SUM(revenue) AS total_revenue "
                    "FROM sales GROUP BY region ORDER BY total_revenue DESC LIMIT 10"
                )
            },
        )
        return LlmResponse(
            content="Let me query the database.",
            tool_calls=[tool_call],
            finish_reason="tool_calls",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        )

    async def stream_request(self, request: LlmRequest):
        # Not used in this test.
        resp = await self.send_request(request)
        if resp.tool_calls:
            yield LlmStreamChunk(tool_calls=resp.tool_calls)
        if resp.content:
            yield LlmStreamChunk(content=resp.content, finish_reason=resp.finish_reason)
        else:
            yield LlmStreamChunk(finish_reason=resp.finish_reason)

    async def validate_tools(self, tools: list[ToolSchema]) -> list[str]:
        return []


def _create_demo_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE sales (
            id INTEGER PRIMARY KEY,
            sale_date TEXT NOT NULL,
            region TEXT NOT NULL,
            product TEXT NOT NULL,
            revenue REAL NOT NULL
        );
        """
    )
    cur.executemany(
        "INSERT INTO sales (sale_date, region, product, revenue) VALUES (?, ?, ?, ?)",
        [
            ("2025-01-10", "EMEA", "Widget", 120.0),
            ("2025-01-11", "EMEA", "Widget", 180.0),
            ("2025-01-12", "NA", "Widget", 250.0),
            ("2025-01-12", "NA", "Gadget", 320.0),
            ("2025-01-13", "APAC", "Gadget", 90.0),
            ("2025-01-14", "EMEA", "Gadget", 75.0),
        ],
    )
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_ad_hoc_skill_creation_and_analysis(tmp_path: Path) -> None:
    db_path = tmp_path / "demo.sqlite"
    _create_demo_db(db_path)

    tool_registry = ToolRegistry()
    sql_tool = RunSqlTool(sql_runner=SqliteRunner(database_path=str(db_path)))
    tool_registry.register(sql_tool)

    schema_catalog = PortableSchemaCatalogService(
        SqliteRunner(database_path=str(db_path)),
        persist_path=str(tmp_path / "schema.json"),
        dialect="sqlite",
    )

    registry = SkillRegistry(InMemorySkillRegistryStore())
    skill_enricher = SkillAdHocContextEnricher(
        registry=registry,
        schema_catalog=schema_catalog,
        config=SkillAdHocConfig(enable_ad_hoc_generation=True),
    )

    agent = Agent(
        llm_service=DeterministicSqlAnalysisLlm(),
        tool_registry=tool_registry,
        user_resolver=SimpleUserResolver(),
        agent_memory=SimpleAgentMemory(),
        context_enrichers=[skill_enricher],
    )

    rc = RequestContext(metadata={})
    message = "Which region has the highest revenue?"

    rendered_text = ""
    async for component in agent.send_message(rc, message, conversation_id="c1"):
        if component.simple_component and getattr(component.simple_component, "text", None):
            rendered_text += component.simple_component.text + "\n"

    # Ensure analysis text produced
    assert "total revenue" in rendered_text.lower() or "revenue" in rendered_text.lower()

    # Ensure an ad-hoc skill was created and is discoverable (compiled_skill attached)
    skills = await registry.list_skills(tenant_id=None, enabled_only=True)
    assert len(skills) == 1
    assert skills[0].compiled_skill is not None
