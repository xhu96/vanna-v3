"""Tests for semantic-first planning and routing helpers."""

from typing import AsyncGenerator, FrozenSet, Type

import pytest
from pydantic import BaseModel

from vanna.agents.basic import SimpleAgentMemory, SimpleUserResolver
from vanna.capabilities.semantic import SemanticPlanHint
from vanna.core.agent import Agent
from vanna.core.agent.config import AgentConfig
from vanna.core.lifecycle import LifecycleHook
from vanna.core.llm import LlmRequest, LlmResponse, LlmService, LlmStreamChunk
from vanna.core.planner import SemanticFirstPlanner, SemanticPlanningError
from vanna.core.registry import ToolRegistry
from vanna.core.tool import Tool, ToolCall, ToolContext, ToolResult, ToolSchema
from vanna.core.user import User
from vanna.core.user.request_context import RequestContext
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.local.storage import MemoryConversationStore
from support.semantic_fixtures import MockSemanticAdapter
from vanna.tools.semantic_query import SemanticQueryTool, SemanticQueryToolArgs


class PartialSemanticAdapter(MockSemanticAdapter):
    async def plan(self, message, context):
        del message, context
        return SemanticPlanHint(coverage="partial", reason="Only one dimension matched")


class FailingSemanticAdapter(MockSemanticAdapter):
    async def plan(self, message, context):
        del message, context
        raise RuntimeError("dbt token TOP_SECRET expired")


class EmptyArgs(BaseModel):
    pass


class SchemaOnlyTool(Tool[EmptyArgs]):
    def __init__(
        self,
        name: str,
        capabilities: FrozenSet[str] = frozenset(),
    ) -> None:
        self._name = name
        self._capabilities = capabilities
        self.executions = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._name

    @property
    def capabilities(self) -> FrozenSet[str]:
        return self._capabilities

    def get_args_schema(self) -> Type[EmptyArgs]:
        return EmptyArgs

    async def execute(self, context: ToolContext, args: EmptyArgs) -> ToolResult:
        del context, args
        self.executions += 1
        return ToolResult(success=True, result_for_llm="unused")


class CapturingLlmService(LlmService):
    def __init__(self) -> None:
        self.request: LlmRequest | None = None

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        self.request = request
        return LlmResponse(content="semantic answer", finish_reason="stop")

    async def stream_request(
        self, request: LlmRequest
    ) -> AsyncGenerator[LlmStreamChunk, None]:
        self.request = request
        yield LlmStreamChunk(content="semantic answer", finish_reason="stop")

    async def validate_tools(self, tools):
        del tools
        return []


class InjectingLlmService(CapturingLlmService):
    def __init__(self, tool_name: str) -> None:
        super().__init__()
        self.tool_name = tool_name
        self.calls = 0

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        self.request = request
        self.calls += 1
        if self.calls == 1:
            return LlmResponse(
                tool_calls=[
                    ToolCall(id="injected-call", name=self.tool_name, arguments={})
                ],
                finish_reason="tool_calls",
            )
        return LlmResponse(content="safe answer", finish_reason="stop")


class RecordingToolHook(LifecycleHook):
    def __init__(self) -> None:
        self.before_calls = 0
        self.after_calls = 0

    async def before_tool(self, tool, context) -> None:
        del tool, context
        self.before_calls += 1

    async def after_tool(self, result):
        del result
        self.after_calls += 1
        return None


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
    assert decision.blocked_tools == ("run_sql",)
    assert decision.blocked_capabilities == ("sql",)
    assert decision.warning_code is None


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
    assert decision.warning_code == "semantic_coverage_missing"


@pytest.mark.asyncio
async def test_partial_coverage_keeps_sql_with_typed_warning(tool_context):
    planner = SemanticFirstPlanner(semantic_adapter=PartialSemanticAdapter())
    decision = await planner.decide(
        message="Show partially covered metric",
        tool_schemas=[
            ToolSchema(name="semantic_query", description="", parameters={}),
            ToolSchema(name="run_sql", description="", parameters={}),
        ],
        context=tool_context,
    )

    assert decision.route == "sql_fallback"
    assert decision.warning_code == "semantic_partial_coverage"
    assert decision.blocked_tools == ()
    assert decision.blocked_capabilities == ()


@pytest.mark.asyncio
async def test_semantic_service_failure_does_not_silently_fallback(tool_context):
    planner = SemanticFirstPlanner(semantic_adapter=FailingSemanticAdapter())
    with pytest.raises(SemanticPlanningError) as exc_info:
        await planner.decide(
            message="Show revenue",
            tool_schemas=[
                ToolSchema(name="semantic_query", description="", parameters={}),
                ToolSchema(name="run_sql", description="", parameters={}),
            ],
            context=tool_context,
        )
    assert "TOP_SECRET" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_semantic_service_failure_fallback_is_explicit_opt_in(tool_context):
    planner = SemanticFirstPlanner(
        semantic_adapter=FailingSemanticAdapter(), fallback_on_service_error=True
    )
    decision = await planner.decide(
        message="Show revenue",
        tool_schemas=[
            ToolSchema(name="semantic_query", description="", parameters={}),
            ToolSchema(name="run_sql", description="", parameters={}),
        ],
        context=tool_context,
    )
    assert decision.route == "sql_fallback"
    assert decision.warning_code == "semantic_service_unavailable"
    assert "TOP_SECRET" not in decision.message


@pytest.mark.asyncio
async def test_agent_does_not_advertise_sql_for_full_semantic_coverage():
    registry = ToolRegistry()
    registry.register_local_tool(SchemaOnlyTool("semantic_query"), access_groups=[])
    registry.register_local_tool(SchemaOnlyTool("run_sql"), access_groups=[])
    registry.register_local_tool(
        SchemaOnlyTool("warehouse_query", frozenset({"sql"})), access_groups=[]
    )
    llm_service = CapturingLlmService()
    agent = Agent(
        llm_service=llm_service,
        tool_registry=registry,
        user_resolver=SimpleUserResolver(User(id="semantic-user")),
        agent_memory=SimpleAgentMemory(),
        conversation_store=MemoryConversationStore(),
        config=AgentConfig(stream_responses=False),
        semantic_planner=SemanticFirstPlanner(MockSemanticAdapter()),
    )

    components = [
        component
        async for component in agent.send_message(
            RequestContext(), "Show revenue by month"
        )
    ]

    assert components
    assert llm_service.request is not None
    advertised = {tool.name for tool in llm_service.request.tools or []}
    assert advertised == {"semantic_query"}


@pytest.mark.asyncio
async def test_agent_blocks_injected_custom_named_sql_execution():
    registry = ToolRegistry()
    registry.register_local_tool(SchemaOnlyTool("semantic_query"), access_groups=[])
    custom_sql = SchemaOnlyTool("warehouse_query", frozenset({"sql"}))
    registry.register_local_tool(custom_sql, access_groups=[])
    llm_service = InjectingLlmService("warehouse_query")
    hook = RecordingToolHook()
    agent = Agent(
        llm_service=llm_service,
        tool_registry=registry,
        user_resolver=SimpleUserResolver(User(id="semantic-user")),
        agent_memory=SimpleAgentMemory(),
        conversation_store=MemoryConversationStore(),
        config=AgentConfig(stream_responses=False),
        semantic_planner=SemanticFirstPlanner(MockSemanticAdapter()),
        lifecycle_hooks=[hook],
    )

    components = [
        component
        async for component in agent.send_message(
            RequestContext(), "Show revenue by month"
        )
    ]

    assert components
    assert custom_sql.executions == 0
    assert hook.before_calls == 0
    assert hook.after_calls == 0
    assert llm_service.calls == 2


@pytest.mark.asyncio
async def test_agent_does_not_run_hooks_for_group_denied_injected_tool():
    registry = ToolRegistry()
    restricted = SchemaOnlyTool("admin_query")
    registry.register_local_tool(restricted, access_groups=["admin"])
    llm_service = InjectingLlmService("admin_query")
    hook = RecordingToolHook()
    agent = Agent(
        llm_service=llm_service,
        tool_registry=registry,
        user_resolver=SimpleUserResolver(
            User(id="semantic-user", group_memberships=["user"])
        ),
        agent_memory=SimpleAgentMemory(),
        conversation_store=MemoryConversationStore(),
        config=AgentConfig(stream_responses=False),
        lifecycle_hooks=[hook],
    )

    _ = [
        component
        async for component in agent.send_message(RequestContext(), "Run admin query")
    ]

    assert restricted.executions == 0
    assert hook.before_calls == 0
    assert hook.after_calls == 0


@pytest.mark.asyncio
async def test_semantic_query_tool_executes_with_mock_adapter(tool_context):
    tool = SemanticQueryTool(adapter=MockSemanticAdapter())
    result = await tool.execute(tool_context, SemanticQueryToolArgs(metric="revenue"))
    assert result.success is True
    assert "semantic query" in result.result_for_llm.lower()
    assert result.metadata["semantic_result"]["row_count"] > 0
