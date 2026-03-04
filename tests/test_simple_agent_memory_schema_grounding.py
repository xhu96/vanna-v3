"""Focused tests for the default in-memory agent and schema grounding flow."""

import pandas as pd
import pytest

from vanna.agents.basic import SimpleAgentMemory
from vanna.infrastructure.sql_runner import RunSqlToolArgs, SqlRunner
from vanna.core.enhancer.default import DefaultLlmContextEnhancer
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.services.schema_sync import PortableSchemaCatalogService


class StaticSchemaSqlRunner(SqlRunner):
    """Minimal runner that exposes a stable schema snapshot."""

    async def run_sql(self, args: RunSqlToolArgs, context: ToolContext) -> pd.DataFrame:
        if "information_schema.columns" not in args.sql:
            raise ValueError("Unexpected SQL")

        return pd.DataFrame(
            [
                {
                    "schema_name": "public",
                    "table_name": "Invoice",
                    "column_name": "InvoiceId",
                    "data_type": "integer",
                    "is_nullable": 0,
                },
                {
                    "schema_name": "public",
                    "table_name": "Invoice",
                    "column_name": "BillingCountry",
                    "data_type": "text",
                    "is_nullable": 1,
                },
                {
                    "schema_name": "public",
                    "table_name": "Invoice",
                    "column_name": "Total",
                    "data_type": "numeric",
                    "is_nullable": 0,
                },
                {
                    "schema_name": "public",
                    "table_name": "Customer",
                    "column_name": "CustomerId",
                    "data_type": "integer",
                    "is_nullable": 0,
                },
            ]
        )


@pytest.fixture
def simple_context() -> ToolContext:
    memory = SimpleAgentMemory()
    return ToolContext(
        user=User(id="u1", group_memberships=["admin"]),
        conversation_id="c1",
        request_id="r1",
        agent_memory=memory,
    )


@pytest.mark.asyncio
async def test_simple_agent_memory_text_search_supports_schema_like_queries(
    simple_context: ToolContext,
):
    memory = simple_context.agent_memory
    await memory.save_text_memory(
        (
            "Schema table: public.Invoice. Columns: InvoiceId integer not null; "
            "BillingCountry text nullable; Total numeric not null."
        ),
        simple_context,
    )
    await memory.save_text_memory(
        "Schema table: public.Customer. Columns: CustomerId integer not null.",
        simple_context,
    )

    results = await memory.search_text_memories(
        query="Show me total sales by country",
        context=simple_context,
        limit=3,
        similarity_threshold=0.3,
    )

    assert results
    assert "public.Invoice" in results[0].memory.content
    assert results[0].similarity_score >= 0.3


@pytest.mark.asyncio
async def test_schema_sync_and_context_enhancer_surface_relevant_table_memory(
    simple_context: ToolContext, tmp_path
):
    service = PortableSchemaCatalogService(
        StaticSchemaSqlRunner(),
        persist_path=str(tmp_path / "schema.json"),
        dialect="postgres",
    )

    await service.sync(simple_context)

    enhancer = DefaultLlmContextEnhancer(simple_context.agent_memory)
    enhanced_prompt = await enhancer.enhance_system_prompt(
        "You are a helpful analyst.",
        "Show me total sales by country",
        simple_context.user,
    )

    assert "Relevant Context from Memory" in enhanced_prompt
    assert "Schema table: public.Invoice." in enhanced_prompt
    assert "BillingCountry" in enhanced_prompt
    assert "Total" in enhanced_prompt
