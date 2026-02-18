"""Tests for semantic-first planning and routing helpers."""

import pytest

from vanna.core.planner import SemanticFirstPlanner
from vanna.core.tool import ToolContext, ToolSchema
from vanna.core.user import User
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.semantic import MockSemanticAdapter
from vanna.tools.semantic_query import SemanticQueryTool, SemanticQueryToolArgs


@pytest.fixture
def tool_context():
    return ToolContext(
        user=User(id="u1", group_memberships=["user"]),
        conversation_id="c1",
        request_id="r1",
        agent_memory=DemoAgentMemory(),
    )


@pytest.mark.asyncio
async def test_semantic_planner_prefers_semantic_route_when_covered(tool_context):
    planner = SemanticFirstPlanner(semantic_adapter=MockSemanticAdapter())
    decision = await planner.decide(
        message="Show revenue by month",
        tool_schemas=[
            ToolSchema(name="semantic_query", description="", parameters={}),
            ToolSchema(name="run_sql", description="", parameters={}),
        ],
        context=tool_context,
    )
    assert decision.route == "semantic_preferred"
    assert decision.semantic_hint is not None
    assert decision.semantic_hint.coverage == "full"


@pytest.mark.asyncio
async def test_semantic_planner_falls_back_when_no_coverage(tool_context):
    planner = SemanticFirstPlanner(semantic_adapter=MockSemanticAdapter())
    decision = await planner.decide(
        message="Show employee attrition reasons by manager hierarchy",
        tool_schemas=[
            ToolSchema(name="semantic_query", description="", parameters={}),
            ToolSchema(name="run_sql", description="", parameters={}),
        ],
        context=tool_context,
    )
    assert decision.route == "sql_fallback"
    assert decision.semantic_hint is not None
    assert decision.semantic_hint.coverage == "missing"


@pytest.mark.asyncio
async def test_semantic_query_tool_executes_with_mock_adapter(tool_context):
    tool = SemanticQueryTool(adapter=MockSemanticAdapter())
    result = await tool.execute(tool_context, SemanticQueryToolArgs(metric="revenue"))
    assert result.success is True
    assert "semantic query" in result.result_for_llm.lower()
    assert result.metadata["semantic_result"]["row_count"] > 0
