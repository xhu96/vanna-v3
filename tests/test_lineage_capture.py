"""Request-wide lineage, redaction, confidence, and terminal regressions."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncGenerator, FrozenSet, Sequence, Type

import pytest
from pydantic import BaseModel

from support.semantic_fixtures import MockSemanticAdapter
from vanna.agents.basic import SimpleAgentMemory, SimpleUserResolver
from vanna.capabilities.semantic import SemanticPlanHint
from vanna.core.agent import Agent
from vanna.core.agent.config import AgentConfig
from vanna.core.lineage import ConfidenceScorer, LineageCollector
from vanna.core.lineage.models import LineageEvidence, SemanticEvidence
from vanna.core.llm import LlmRequest, LlmResponse, LlmService, LlmStreamChunk
from vanna.core.observability import ObservabilityProvider, Span
from vanna.core.planner import SemanticFirstPlanner
from vanna.core.registry import ToolRegistry
from vanna.core.tool import Tool, ToolCall, ToolContext, ToolResult
from vanna.core.user import (
    RequestContext,
    TRUSTED_SCHEMA_LINEAGE_METADATA_KEY,
    User,
)
from vanna.core.workflow import WorkflowHandler, WorkflowResult
from vanna.integrations.local.storage import MemoryConversationStore
from vanna.servers.base import ChatHandler, ChatRequest
from vanna.servers.base.events_v3 import (
    LineagePayload,
    collect_v3_poll,
)
from vanna.tools.semantic_query import SemanticQueryTool


class EmptyArgs(BaseModel):
    pass


class EvidenceTool(Tool[EmptyArgs]):
    def __init__(
        self,
        name: str,
        *,
        metadata: dict[str, Any] | None = None,
        capabilities: FrozenSet[str] = frozenset(),
    ) -> None:
        self._name = name
        self._metadata = metadata or {}
        self._capabilities = capabilities

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
        return ToolResult(
            success=True,
            result_for_llm="tool complete",
            metadata=dict(self._metadata),
        )


class ScriptedLlm(LlmService):
    def __init__(self, responses: Sequence[LlmResponse]) -> None:
        self.responses = list(responses)
        self.calls = 0

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        del request
        if self.calls >= len(self.responses):
            raise AssertionError("LLM received more calls than the test allowed")
        response = self.responses[self.calls]
        self.calls += 1
        return response

    async def stream_request(
        self, request: LlmRequest
    ) -> AsyncGenerator[LlmStreamChunk, None]:
        response = await self.send_request(request)
        yield LlmStreamChunk(
            content=response.content,
            tool_calls=response.tool_calls,
            finish_reason=response.finish_reason,
        )

    async def validate_tools(self, tools: list[Any]) -> list[str]:
        del tools
        return []


class FailingLlm(ScriptedLlm):
    def __init__(self) -> None:
        super().__init__([])

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        del request
        raise RuntimeError("postgresql://user:TOP_SECRET@db.internal/app")


class PartialSemanticAdapter(MockSemanticAdapter):
    async def plan(
        self,
        message: str,
        context: ToolContext,
    ) -> SemanticPlanHint:
        del message, context
        return SemanticPlanHint(coverage="partial", reason="Partial catalog match")


class FailingStarterWorkflow(WorkflowHandler):
    def __init__(self, secret: str) -> None:
        self.secret = secret

    async def try_handle(
        self, agent: Agent, user: User, conversation: Any, message: str
    ) -> WorkflowResult:
        del agent, user, conversation, message
        return WorkflowResult(should_skip_llm=False)

    async def get_starter_ui(
        self, agent: Agent, user: User, conversation: Any
    ) -> list[Any]:
        del agent, user, conversation
        raise RuntimeError(self.secret)


class CapturingObservability(ObservabilityProvider):
    def __init__(self) -> None:
        self.spans: list[Span] = []

    async def create_span(
        self, name: str, attributes: dict[str, Any] | None = None
    ) -> Span:
        span = Span(name=name, attributes=attributes or {})
        self.spans.append(span)
        return span


def make_agent(
    llm: LlmService,
    *,
    registry: ToolRegistry | None = None,
    planner: SemanticFirstPlanner | None = None,
    max_tool_iterations: int = 10,
    groups: Sequence[str] = ("admin", "user"),
    workflow_handler: WorkflowHandler | None = None,
    observability_provider: ObservabilityProvider | None = None,
) -> Agent:
    return Agent(
        llm_service=llm,
        tool_registry=registry or ToolRegistry(),
        user_resolver=SimpleUserResolver(
            User(
                id="lineage-user",
                authenticated=True,
                group_memberships=list(groups),
            )
        ),
        agent_memory=SimpleAgentMemory(),
        conversation_store=MemoryConversationStore(),
        config=AgentConfig(
            stream_responses=False,
            auto_save_conversations=False,
            include_thinking_indicators=False,
            max_tool_iterations=max_tool_iterations,
        ),
        semantic_planner=planner,
        workflow_handler=workflow_handler,
        observability_provider=observability_provider,
    )


def marker_payload(components: Sequence[Any]) -> dict[str, Any]:
    markers = [
        component.rich_component.data["v3_lineage"]
        for component in components
        if component.rich_component.data.get("v3_lineage") is not None
    ]
    assert len(markers) == 1
    payload = markers[0]
    assert isinstance(payload, dict)
    LineagePayload.model_validate(payload)
    return payload


async def agent_components(agent: Agent, message: str) -> list[Any]:
    return [
        component
        async for component in agent.send_message(
            RequestContext(),
            message,
            conversation_id="conv_lineage",
        )
    ]


@pytest.mark.asyncio
async def test_starter_failure_logs_and_telemetry_are_redacted(caplog) -> None:
    secret = "postgresql://svc:TOP_SECRET@db.internal/app"
    observability = CapturingObservability()
    agent = make_agent(
        ScriptedLlm([]),
        workflow_handler=FailingStarterWorkflow(secret),
        observability_provider=observability,
    )

    with caplog.at_level(logging.ERROR):
        components = [
            component
            async for component in agent.send_message(
                RequestContext(metadata={"starter_ui_request": True}),
                "",
                conversation_id="starter-conversation",
            )
        ]

    assert components == []
    assert secret not in caplog.text
    starter_spans = [
        span for span in observability.spans if span.name.endswith("starter_ui")
    ]
    assert len(starter_spans) == 1
    serialized_attributes = json.dumps(starter_spans[0].attributes)
    assert secret not in serialized_attributes
    assert starter_spans[0].attributes["error_code"] == "starter_workflow_failed"
    assert starter_spans[0].attributes["error_type"] == "RuntimeError"
    assert starter_spans[0].attributes["correlation_id"].startswith("tool_")


@pytest.mark.asyncio
async def test_public_metadata_cannot_turn_a_prompt_into_a_starter_request() -> None:
    llm = ScriptedLlm([LlmResponse(content="normal answer", finish_reason="stop")])
    agent = make_agent(
        llm,
        workflow_handler=FailingStarterWorkflow("starter path must not execute"),
    )

    components = [
        component
        async for component in agent.send_message(
            RequestContext(metadata={"starter_ui_request": True}),
            "normal question",
            conversation_id="normal-conversation",
        )
    ]

    assert llm.calls == 1
    marker_payload(components)


def test_lineage_collector_records_typed_sql_schema_and_confidence() -> None:
    collector = LineageCollector(request_id="req_1", conversation_id="conv_1")
    collector.set_visibility(
        show_tool_names=True,
        show_sql=True,
        show_sources=True,
    )
    collector.set_schema(
        "hash123",
        "snap123",
        schema_version=7,
        schema_drifted=False,
    )
    collector.record_tool_result(
        tool_name="run_sql",
        success=True,
        metadata={
            "executed_sql": "SELECT 1",
            "dialect": "postgres",
            "row_count": 1,
            "execution_time_ms": 12.0,
            "validation_checks": ["read_only_policy_passed"],
            "password": "TOP_SECRET",
        },
    )

    evidence = collector.finalize()
    payload = collector.to_public_payload()

    assert evidence.schema_hash == "hash123"
    assert evidence.schema_version == 7
    assert evidence.confidence.tier == "Medium"
    assert evidence.sql_executions[0].row_count == 1
    assert payload["evidence"]["sql_executions"][0]["sql"] == "SELECT 1"
    assert "TOP_SECRET" not in json.dumps(payload)
    LineagePayload.model_validate(payload)


def test_lineage_public_serializer_enforces_existing_ui_permissions() -> None:
    collector = LineageCollector()
    collector.record_tool_result(
        tool_name="run_sql",
        success=True,
        metadata={
            "executed_sql": "SELECT secret FROM finance",
            "dialect": "postgres",
            "row_count": 2,
            "retrieved_memories": [
                {"memory_id": "mem_1", "score": 0.9, "tool_name": "run_sql"}
            ],
            "validation_checks": ["read_only_policy_passed"],
        },
    )

    public = collector.to_public_evidence()

    assert public["retrieved_sources"] == []
    assert public["tool_calls"][0]["name"] == "restricted"
    assert "sql" not in public["sql_executions"][0]
    assert public["sql_executions"][0]["row_count"] == 2
    assert collector.evidence.redactions == [
        "tool_names",
        "sql_text",
        "retrieved_sources",
    ]


@pytest.mark.parametrize(
    ("evidence", "tier", "required_signal"),
    [
        (LineageEvidence(), "Low", None),
        (
            LineageEvidence(
                sql_executions=[{"sql": "SELECT 1", "row_count": 1}],
            ),
            "Medium",
            "sql_executed",
        ),
        (
            LineageEvidence(
                semantic=SemanticEvidence(coverage="full"),
                tool_calls=[{"tool_name": "semantic_query", "success": True}],
                validation_checks=[{"name": "row_shape", "passed": True}],
            ),
            "High",
            "semantic_full",
        ),
        (
            LineageEvidence(
                semantic=SemanticEvidence(coverage="full"),
                schema_drifted=True,
                tool_calls=[{"tool_name": "semantic_query", "success": True}],
                validation_checks=[{"name": "row_shape", "passed": True}],
            ),
            "Medium",
            "schema_drift_detected",
        ),
        (
            LineageEvidence(
                outcome="tool_limit",
                sql_executions=[{"sql": "SELECT 1", "row_count": 1}],
            ),
            "Low",
            "tool_limit_reached",
        ),
    ],
)
def test_confidence_tiers_are_signal_derived(
    evidence: LineageEvidence,
    tier: str,
    required_signal: str | None,
) -> None:
    confidence = ConfidenceScorer.explain(evidence)
    assert confidence.tier == tier
    if required_signal:
        assert required_signal in confidence.signals


@pytest.mark.asyncio
async def test_normal_answer_and_workflow_shortcut_each_emit_one_lineage_panel() -> (
    None
):
    normal_llm = ScriptedLlm(
        [LlmResponse(content="normal answer", finish_reason="stop")]
    )
    normal = await agent_components(make_agent(normal_llm), "hello")

    workflow_llm = ScriptedLlm([])
    workflow = await agent_components(make_agent(workflow_llm), "/help")

    normal_payload = marker_payload(normal)["evidence"]
    workflow_payload = marker_payload(workflow)["evidence"]
    assert normal_payload["confidence"]["tier"] == "Low"
    assert workflow_llm.calls == 0
    assert workflow_payload["validation_checks"] == [
        {"name": "workflow_completed", "passed": True}
    ]


@pytest.mark.asyncio
async def test_zero_row_sql_is_reproducible_and_medium_confidence() -> None:
    registry = ToolRegistry()
    registry.register_local_tool(
        EvidenceTool(
            "run_sql",
            capabilities=frozenset({"sql"}),
            metadata={
                "executed_sql": "SELECT * FROM orders WHERE 1 = 0",
                "dialect": "postgres",
                "row_count": 0,
                "validation_checks": ["read_only_policy_passed"],
            },
        ),
        access_groups=[],
    )
    llm = ScriptedLlm(
        [
            LlmResponse(
                tool_calls=[ToolCall(id="sql_1", name="run_sql", arguments={})],
                finish_reason="tool_calls",
            ),
            LlmResponse(content="No rows matched.", finish_reason="stop"),
        ]
    )

    payload = marker_payload(
        await agent_components(make_agent(llm, registry=registry), "empty")
    )["evidence"]

    assert payload["sql_executions"] == [
        {
            "sql": "SELECT * FROM orders WHERE 1 = 0",
            "dialect": "postgres",
            "row_count": 0,
            "runtime_ms": pytest.approx(payload["sql_executions"][0]["runtime_ms"]),
        }
    ]
    assert payload["confidence"]["tier"] == "Medium"


@pytest.mark.asyncio
async def test_semantic_answer_is_high_confidence_and_sql_fallback_is_visible() -> None:
    semantic_adapter = MockSemanticAdapter()
    semantic_registry = ToolRegistry()
    semantic_registry.register_local_tool(
        SemanticQueryTool(semantic_adapter),
        access_groups=[],
    )
    semantic_registry.register_local_tool(
        EvidenceTool("run_sql", capabilities=frozenset({"sql"})),
        access_groups=[],
    )
    semantic_llm = ScriptedLlm(
        [
            LlmResponse(
                tool_calls=[
                    ToolCall(
                        id="semantic_1",
                        name="semantic_query",
                        arguments={"metric": "revenue"},
                    )
                ],
                finish_reason="tool_calls",
            ),
            LlmResponse(content="Revenue answer", finish_reason="stop"),
        ]
    )
    semantic_agent = make_agent(
        semantic_llm,
        registry=semantic_registry,
        planner=SemanticFirstPlanner(semantic_adapter),
    )

    semantic = marker_payload(await agent_components(semantic_agent, "Show revenue"))[
        "evidence"
    ]

    assert semantic["semantic"] == {
        "coverage": "full",
        "metric_names": ["revenue"],
    }
    assert semantic["sql_executions"] == []
    assert semantic["confidence"]["tier"] == "High"
    assert semantic["tool_calls"][0]["name"] == "semantic_query"

    mismatch_llm = ScriptedLlm(
        [
            LlmResponse(
                tool_calls=[
                    ToolCall(
                        id="semantic_mismatch",
                        name="semantic_query",
                        arguments={"metric": "orders"},
                    )
                ],
                finish_reason="tool_calls",
            ),
            LlmResponse(content="Orders answer", finish_reason="stop"),
        ]
    )
    mismatch_agent = make_agent(
        mismatch_llm,
        registry=semantic_registry,
        planner=SemanticFirstPlanner(semantic_adapter),
    )
    mismatch = marker_payload(await agent_components(mismatch_agent, "Show revenue"))[
        "evidence"
    ]
    assert mismatch["semantic"]["metric_names"] == ["orders"]
    assert {
        "name": "semantic_plan_execution_match",
        "passed": False,
    } in mismatch["validation_checks"]
    assert mismatch["confidence"]["tier"] == "Low"

    fallback_registry = ToolRegistry()
    fallback_registry.register_local_tool(
        SemanticQueryTool(PartialSemanticAdapter()),
        access_groups=[],
    )
    fallback_registry.register_local_tool(
        EvidenceTool("run_sql", capabilities=frozenset({"sql"})),
        access_groups=[],
    )
    fallback_llm = ScriptedLlm(
        [LlmResponse(content="fallback answer", finish_reason="stop")]
    )
    fallback_agent = make_agent(
        fallback_llm,
        registry=fallback_registry,
        planner=SemanticFirstPlanner(PartialSemanticAdapter()),
    )

    fallback_components = await agent_components(fallback_agent, "partial metric")
    fallback = marker_payload(fallback_components)["evidence"]

    assert fallback["semantic"]["coverage"] == "partial"
    assert "SQL fallback" in fallback["semantic"]["fallback_reason"]
    assert any(
        component.rich_component.type.value == "status_bar_update"
        and component.rich_component.status == "warning"
        for component in fallback_components
    )


@pytest.mark.asyncio
async def test_tool_limit_and_agent_failure_have_low_lineage_and_one_terminal() -> None:
    registry = ToolRegistry()
    registry.register_local_tool(EvidenceTool("noop"), access_groups=[])
    looping_llm = ScriptedLlm(
        [
            LlmResponse(
                tool_calls=[ToolCall(id="loop_1", name="noop", arguments={})],
                finish_reason="tool_calls",
            )
        ]
    )
    limited = marker_payload(
        await agent_components(
            make_agent(
                looping_llm,
                registry=registry,
                max_tool_iterations=1,
            ),
            "loop",
        )
    )["evidence"]
    assert limited["confidence"]["tier"] == "Low"
    assert "tool_limit_reached" in limited["confidence"]["signals"]

    handler = ChatHandler(make_agent(FailingLlm()))
    request = ChatRequest(
        message="fail",
        conversation_id="conv_failure",
        request_id="req_failure",
    )
    poll = await collect_v3_poll(
        handler.handle_stream(request),
        conversation_id="conv_failure",
        request_id="req_failure",
    )
    events = [*poll.events, poll.terminal_event]
    serialized = json.dumps([event.model_dump(mode="json") for event in events])

    assert [event.event_type for event in events[-2:]] == ["lineage", "error"]
    assert sum(event.terminal for event in events) == 1
    assert poll.terminal_event.payload.code == "agent_execution_failed"
    assert "request_failed" in events[-2].payload.evidence.confidence.signals
    assert "TOP_SECRET" not in serialized


@pytest.mark.asyncio
async def test_chat_handler_uses_one_request_id_for_chunks_and_lineage() -> None:
    handler = ChatHandler(
        make_agent(ScriptedLlm([LlmResponse(content="answer", finish_reason="stop")]))
    )
    request = ChatRequest(
        message="hello",
        conversation_id="conv_fixed",
        request_id="req_fixed",
        request_context=RequestContext(
            metadata={"_vanna_request_id": "attacker_supplied"}
        ),
    )

    chunks = [chunk async for chunk in handler.handle_stream(request)]
    lineage_chunks = [
        chunk for chunk in chunks if "v3_lineage" in chunk.rich.get("data", {})
    ]

    assert len(lineage_chunks) == 1
    assert all(chunk.conversation_id == "conv_fixed" for chunk in chunks)
    assert all(chunk.request_id == "req_fixed" for chunk in chunks)
    assert request.request_context.metadata["_vanna_request_id"] == "req_fixed"


@pytest.mark.asyncio
async def test_agent_ignores_public_schema_metadata_and_uses_trusted_envelope() -> None:
    forged_agent = make_agent(
        ScriptedLlm([LlmResponse(content="answer", finish_reason="stop")])
    )
    forged = marker_payload(
        [
            component
            async for component in forged_agent.send_message(
                RequestContext(
                    metadata={
                        "schema_hash": "forged",
                        "schema_snapshot_id": "forged-snapshot",
                        "schema_version": 999,
                    }
                ),
                "question",
                conversation_id="conv_forged",
            )
        ]
    )["evidence"]
    assert forged["schema_hash"] is None
    assert forged["schema_snapshot_id"] is None
    assert forged["schema_version"] is None

    trusted_agent = make_agent(
        ScriptedLlm([LlmResponse(content="answer", finish_reason="stop")])
    )
    trusted = marker_payload(
        [
            component
            async for component in trusted_agent.send_message(
                RequestContext(
                    metadata={
                        TRUSTED_SCHEMA_LINEAGE_METADATA_KEY: {
                            "schema_hash": "trusted-hash",
                            "schema_snapshot_id": "trusted-snapshot",
                            "schema_version": 7,
                            "schema_drift_detected": True,
                        }
                    }
                ),
                "question",
                conversation_id="conv_trusted",
            )
        ]
    )["evidence"]
    assert trusted["schema_hash"] == "trusted-hash"
    assert trusted["schema_snapshot_id"] == "trusted-snapshot"
    assert trusted["schema_version"] == 7
    assert trusted["schema_drifted"] is True


def test_lineage_finalization_for_100_tool_records_meets_budget() -> None:
    samples_ms: list[float] = []
    for _ in range(30):
        collector = LineageCollector()
        for index in range(100):
            collector.record_tool_result(
                tool_name=f"tool_{index}",
                success=True,
                metadata={
                    "execution_time_ms": 1.0,
                    "validation_checks": [f"check_{index}"],
                },
            )
        started = time.perf_counter()
        payload = collector.to_public_payload()
        json.dumps(payload, allow_nan=False)
        samples_ms.append((time.perf_counter() - started) * 1000)

    p95_ms = sorted(samples_ms)[28]
    assert p95_ms < 25, f"Lineage finalization p95 was {p95_ms:.2f} ms"
