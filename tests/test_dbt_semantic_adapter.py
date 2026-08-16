"""Offline contract tests for the dbt Semantic Layer GraphQL adapter."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from vanna.capabilities.semantic import SemanticQueryRequest
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.semantic import (
    DbtSemanticLayerAdapter,
    DbtSemanticLayerError,
)


METADATA_PAGE_ONE = {
    "data": {
        "metrics": {
            "edges": [
                {
                    "node": {
                        "name": "revenue",
                        "description": "Recognized revenue",
                        "synonyms": ["sales"],
                        "dimensions": [
                            {
                                "name": "tenant_id",
                                "label": "Tenant",
                                "type": "categorical",
                                "operators": ["equals"],
                            },
                            {
                                "name": "region",
                                "label": "Region",
                                "type": "categorical",
                                "operators": ["equals", "in"],
                            },
                            {
                                "name": "order_date",
                                "label": "Order date",
                                "type": "time",
                                "operators": [
                                    "equals",
                                    "greater_or_equal",
                                    "less_than",
                                ],
                                "queryableGranularities": [
                                    "day",
                                    "month",
                                    "quarter",
                                    "year",
                                ],
                            },
                        ],
                    }
                }
            ],
            "pageInfo": {"hasNextPage": True, "endCursor": "metric-cursor-1"},
        }
    }
}

METADATA_PAGE_TWO = {
    "data": {
        "metrics": {
            "edges": [
                {
                    "node": {
                        "name": "orders",
                        "description": "Order count",
                        "synonyms": ["order count"],
                        "dimensions": [
                            {
                                "name": "tenant_id",
                                "label": "Tenant",
                                "type": "categorical",
                                "operators": ["equals"],
                            },
                            {
                                "name": "inventory_status",
                                "label": "Inventory status",
                                "type": "categorical",
                                "operators": ["equals", "not_equals"],
                            },
                        ],
                    }
                }
            ],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        }
    }
}


class FakeDbtGraphqlService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.authorization_headers: list[str] = []
        self.poll_count = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append(body)
        self.authorization_headers.append(request.headers["authorization"])
        operation = body["operationName"]
        variables = body["variables"]

        if operation == "GetSemanticCatalog":
            payload = (
                METADATA_PAGE_ONE
                if variables.get("after") is None
                else METADATA_PAGE_TWO
            )
            return httpx.Response(200, json=payload)
        if operation == "CreateSemanticQuery":
            return httpx.Response(
                200, json={"data": {"createQuery": {"queryId": "query-1"}}}
            )
        if operation == "GetSemanticQueryStatus":
            self.poll_count += 1
            status = "RUNNING" if self.poll_count == 1 else "SUCCESSFUL"
            return httpx.Response(
                200,
                json={"data": {"query": {"queryId": "query-1", "status": status}}},
            )
        if operation == "GetSemanticQueryResults":
            if variables.get("after") is None:
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "queryResult": {
                                "rows": [
                                    {
                                        "region": "EMEA",
                                        "order_date__month": "2026-01-01",
                                        "revenue": 100,
                                    }
                                ],
                                "pageInfo": {
                                    "hasNextPage": True,
                                    "endCursor": "result-cursor-1",
                                },
                            }
                        }
                    },
                )
            return httpx.Response(
                200,
                json={
                    "data": {
                        "queryResult": {
                            "rows": [
                                {
                                    "region": "EMEA",
                                    "order_date__month": "2026-02-01",
                                    "revenue": 120,
                                }
                            ],
                            "pageInfo": {
                                "hasNextPage": False,
                                "endCursor": None,
                            },
                        }
                    }
                },
            )
        raise AssertionError(f"Unexpected operation {operation}")


class FakeClock:
    def __init__(self) -> None:
        self.current = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.current

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.current += delay


@pytest.fixture
def tool_context() -> ToolContext:
    return ToolContext(
        user=User(id="user-a", metadata={"tenant_id": "tenant-a"}),
        conversation_id="conversation-a",
        request_id="request-a",
        agent_memory=DemoAgentMemory(),
    )


async def _no_sleep(delay: float) -> None:
    del delay


def _build_adapter(
    handler: Any,
    **kwargs: Any,
) -> tuple[DbtSemanticLayerAdapter, httpx.AsyncClient]:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        trust_env=False,
    )
    adapter = DbtSemanticLayerAdapter(
        endpoint="https://semantic-layer.example.test/api/graphql",
        environment_id="12345",
        token_provider=lambda context: f"dbt-test-token-{context.user.id}",
        http_client=client,
        sleep=kwargs.pop("sleep", _no_sleep),
        **kwargs,
    )
    return adapter, client


def _operations(service: FakeDbtGraphqlService) -> list[str]:
    return [call["operationName"] for call in service.calls]


@pytest.mark.asyncio
async def test_catalog_pagination_and_full_coverage_plan(tool_context: ToolContext):
    service = FakeDbtGraphqlService()
    adapter, client = _build_adapter(service)
    try:
        hint = await adapter.plan(
            "Show monthly sales by region",
            tool_context,
        )
        second_hint = await adapter.plan("Show revenue by region", tool_context)
    finally:
        await client.aclose()

    assert hint.coverage == "full"
    assert hint.request is not None
    assert hint.request.metric == "revenue"
    assert hint.request.metrics == ["revenue"]
    assert hint.request.dimensions == ["region", "order_date"]
    assert hint.request.time_grain == "month"
    assert second_hint.coverage == "full"
    assert _operations(service) == ["GetSemanticCatalog", "GetSemanticCatalog"]
    assert service.calls[0]["variables"] == {
        "environmentId": "12345",
        "first": 100,
        "after": None,
    }
    assert service.calls[1]["variables"]["after"] == "metric-cursor-1"
    assert set(service.authorization_headers) == {"Bearer dbt-test-token-user-a"}
    assert "dbt-test-token" not in json.dumps(service.calls)


@pytest.mark.asyncio
async def test_plan_reports_partial_and_missing_coverage(tool_context: ToolContext):
    service = FakeDbtGraphqlService()
    adapter, client = _build_adapter(service)
    try:
        partial = await adapter.plan(
            "Show revenue by inventory status",
            tool_context,
        )
        unknown_group = await adapter.plan(
            "Show revenue by customer segment",
            tool_context,
        )
        missing = await adapter.plan("Show headcount by team", tool_context)
    finally:
        await client.aclose()

    assert partial.coverage == "partial"
    assert partial.request is None
    assert "revenue" in partial.reason
    assert unknown_group.coverage == "partial"
    assert unknown_group.request is None
    assert missing.coverage == "missing"
    assert missing.request is None


@pytest.mark.asyncio
async def test_execute_builds_typed_variables_polls_and_paginates_results(
    tool_context: ToolContext,
):
    service = FakeDbtGraphqlService()
    adapter, client = _build_adapter(service)
    request = SemanticQueryRequest(
        metrics=["revenue"],
        dimensions=["region", "order_date"],
        filters={
            "region": {"operator": "equals", "value": "EMEA"},
            "order_date": {
                "operator": "greater_or_equal",
                "value": "2026-01-01",
            },
        },
        time_grain="month",
        order_by="-revenue",
        limit=25,
    )
    try:
        result = await adapter.execute(request, tool_context)
    finally:
        await client.aclose()

    assert result.rows == [
        {
            "region": "EMEA",
            "order_date__month": "2026-01-01",
            "revenue": 100,
        },
        {
            "region": "EMEA",
            "order_date__month": "2026-02-01",
            "revenue": 120,
        },
    ]
    assert result.row_count == 2
    assert result.metadata == {
        "source": "dbt_semantic_layer",
        "semantic_metrics": ["revenue"],
        "semantic_dimensions": ["region", "order_date"],
        "query_id": "query-1",
        "status": "successful",
        "result_pages": 2,
        "validation_checks": [
            "semantic_catalog_allowlist_passed",
            "semantic_tenant_filter_passed",
            "typed_graphql_variables_passed",
        ],
    }

    create_call = next(
        call for call in service.calls if call["operationName"] == "CreateSemanticQuery"
    )
    assert create_call["variables"] == {
        "environmentId": "12345",
        "metrics": [{"name": "revenue"}],
        "groupBy": [
            {"name": "region"},
            {"name": "order_date", "grain": "MONTH"},
        ],
        "where": [
            {
                "dimension": {"name": "region"},
                "operator": "EQUALS",
                "value": "EMEA",
            },
            {
                "dimension": {"name": "order_date"},
                "operator": "GREATER_OR_EQUAL",
                "value": "2026-01-01",
            },
            {
                "dimension": {"name": "tenant_id"},
                "operator": "EQUALS",
                "value": "tenant-a",
            },
        ],
        "orderBy": [{"name": "revenue", "descending": True}],
        "limit": 25,
    }
    assert "EMEA" not in create_call["query"]
    assert "2026-01-01" not in create_call["query"]
    assert _operations(service) == [
        "GetSemanticCatalog",
        "GetSemanticCatalog",
        "CreateSemanticQuery",
        "GetSemanticQueryStatus",
        "GetSemanticQueryStatus",
        "GetSemanticQueryResults",
        "GetSemanticQueryResults",
    ]


@pytest.mark.asyncio
async def test_multi_metric_queries_intersect_dimension_capabilities(
    tool_context: ToolContext,
):
    service = FakeDbtGraphqlService()
    shared_metadata = {
        "data": {
            "metrics": {
                "edges": [
                    {
                        "node": {
                            "name": "revenue",
                            "dimensions": [
                                {
                                    "name": "tenant_id",
                                    "type": "categorical",
                                    "operators": ["equals"],
                                },
                                {
                                    "name": "region",
                                    "type": "categorical",
                                    "operators": ["equals", "in"],
                                },
                                {
                                    "name": "order_date",
                                    "type": "time",
                                    "queryableGranularities": ["day", "month"],
                                },
                            ],
                        }
                    },
                    {
                        "node": {
                            "name": "orders",
                            "dimensions": [
                                {
                                    "name": "tenant_id",
                                    "type": "categorical",
                                    "operators": ["equals"],
                                },
                                {
                                    "name": "region",
                                    "type": "categorical",
                                    "operators": ["equals"],
                                },
                                {
                                    "name": "order_date",
                                    "type": "time",
                                    "queryableGranularities": ["day"],
                                },
                            ],
                        }
                    },
                ],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        }
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["operationName"] == "GetSemanticCatalog":
            return httpx.Response(200, json=shared_metadata)
        return await service(request)

    adapter, client = _build_adapter(handler)
    try:
        with pytest.raises(DbtSemanticLayerError) as operator_error:
            await adapter.execute(
                SemanticQueryRequest(
                    metrics=["revenue", "orders"],
                    filters={
                        "region": {
                            "operator": "in",
                            "value": ["EMEA", "APAC"],
                        }
                    },
                ),
                tool_context,
            )
        with pytest.raises(DbtSemanticLayerError) as grain_error:
            await adapter.execute(
                SemanticQueryRequest(
                    metrics=["revenue", "orders"],
                    time_grain="month",
                ),
                tool_context,
            )
        result = await adapter.execute(
            SemanticQueryRequest(
                metrics=["revenue", "orders"],
                dimensions=["region"],
                filters={"region": "EMEA"},
                limit=1,
            ),
            tool_context,
        )
    finally:
        await client.aclose()

    assert operator_error.value.code == "invalid_semantic_request"
    assert grain_error.value.code == "invalid_semantic_request"
    assert result.row_count == 1
    assert result.metadata["result_pages"] == 1
    create_call = next(
        call for call in service.calls if call["operationName"] == "CreateSemanticQuery"
    )
    assert create_call["variables"]["metrics"] == [
        {"name": "revenue"},
        {"name": "orders"},
    ]
    assert create_call["variables"]["where"] == [
        {
            "dimension": {"name": "region"},
            "operator": "EQUALS",
            "value": "EMEA",
        },
        {
            "dimension": {"name": "tenant_id"},
            "operator": "EQUALS",
            "value": "tenant-a",
        },
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "semantic_request",
    [
        SemanticQueryRequest(metric="revenue", filters={"where": "1 = 1"}),
        SemanticQueryRequest(metric="revenue", filters={"unknown": "value"}),
        SemanticQueryRequest(
            metric="revenue",
            filters={"region": {"operator": "raw", "value": "1 = 1"}},
        ),
        SemanticQueryRequest(metric="revenue", order_by="revenue; DROP TABLE x"),
        SemanticQueryRequest(metric="revenue", time_grain="century"),
    ],
)
async def test_execute_rejects_non_catalogued_or_raw_query_inputs(
    semantic_request: SemanticQueryRequest,
    tool_context: ToolContext,
):
    service = FakeDbtGraphqlService()
    adapter, client = _build_adapter(service)
    try:
        with pytest.raises(DbtSemanticLayerError) as exc_info:
            await adapter.execute(semantic_request, tool_context)
    finally:
        await client.aclose()

    assert exc_info.value.code == "invalid_semantic_request"
    assert "DROP TABLE" not in str(exc_info.value)
    assert "1 = 1" not in str(exc_info.value)
    assert "CreateSemanticQuery" not in _operations(service)


@pytest.mark.asyncio
async def test_query_polling_timeout_is_bounded_and_deterministic(
    tool_context: ToolContext,
):
    clock = FakeClock()

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        operation = body["operationName"]
        if operation == "GetSemanticCatalog":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "metrics": {
                            "edges": METADATA_PAGE_ONE["data"]["metrics"]["edges"],
                            "pageInfo": {
                                "hasNextPage": False,
                                "endCursor": None,
                            },
                        }
                    }
                },
            )
        if operation == "CreateSemanticQuery":
            return httpx.Response(
                200, json={"data": {"createQuery": {"queryId": "query-timeout"}}}
            )
        if operation == "GetSemanticQueryStatus":
            return httpx.Response(
                200,
                json={"data": {"query": {"status": "RUNNING"}}},
            )
        raise AssertionError(operation)

    adapter, client = _build_adapter(
        handler,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        query_timeout_seconds=0.5,
        poll_initial_seconds=0.25,
        poll_max_seconds=0.25,
        max_poll_attempts=10,
    )
    try:
        with pytest.raises(DbtSemanticLayerError) as exc_info:
            await adapter.execute(SemanticQueryRequest(metric="revenue"), tool_context)
    finally:
        await client.aclose()

    assert exc_info.value.code == "semantic_query_timeout"
    assert clock.sleeps == [0.25, 0.25]
    assert "query-timeout" not in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_kind", ["graphql", "http", "transport"])
async def test_upstream_failures_are_redacted(
    failure_kind: str,
    tool_context: ToolContext,
):
    secret = "dbt-secret-TOP-SECRET"

    async def handler(request: httpx.Request) -> httpx.Response:
        if failure_kind == "graphql":
            return httpx.Response(200, json={"errors": [{"message": secret}]})
        if failure_kind == "http":
            return httpx.Response(401, text=secret)
        raise httpx.ConnectError(secret, request=request)

    adapter, client = _build_adapter(handler)
    try:
        with pytest.raises(DbtSemanticLayerError) as exc_info:
            await adapter.plan("show revenue", tool_context)
    finally:
        await client.aclose()

    assert secret not in str(exc_info.value)
    assert "request-a" in str(exc_info.value)
    assert exc_info.value.code in {
        "semantic_graphql_error",
        "semantic_http_error",
        "semantic_transport_error",
    }


@pytest.mark.asyncio
async def test_catalog_pagination_fails_closed_when_cursor_does_not_advance(
    tool_context: ToolContext,
):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=METADATA_PAGE_ONE)

    adapter, client = _build_adapter(handler)
    try:
        with pytest.raises(DbtSemanticLayerError) as exc_info:
            await adapter.plan("show revenue", tool_context)
    finally:
        await client.aclose()

    assert exc_info.value.code == "semantic_pagination_error"


def test_semantic_request_supports_plural_metrics_with_v2_singular_alias():
    plural = SemanticQueryRequest(metrics=["revenue", "orders"])
    singular = SemanticQueryRequest(metric="revenue")

    assert plural.metric == "revenue"
    assert plural.metrics == ["revenue", "orders"]
    assert singular.metric == "revenue"
    assert singular.metrics == ["revenue"]


def test_semantic_request_rejects_unbounded_and_unknown_fields():
    with pytest.raises(ValidationError):
        SemanticQueryRequest(metric="revenue", limit=5001)
    with pytest.raises(ValidationError):
        SemanticQueryRequest(metric="revenue", raw_where="1 = 1")
    with pytest.raises(ValidationError):
        SemanticQueryRequest(metric="revenue; DROP TABLE x")


@pytest.mark.asyncio
async def test_concurrent_plans_share_one_catalog_refresh(tool_context: ToolContext):
    service = FakeDbtGraphqlService()
    adapter, client = _build_adapter(service)
    try:
        hints = await asyncio.gather(
            adapter.plan("show revenue", tool_context),
            adapter.plan("show orders", tool_context),
        )
    finally:
        await client.aclose()

    assert [hint.coverage for hint in hints] == ["full", "full"]
    assert _operations(service) == ["GetSemanticCatalog", "GetSemanticCatalog"]


@pytest.mark.asyncio
async def test_credentials_environment_and_catalog_cache_are_context_bound() -> None:
    calls: list[tuple[str, str]] = []
    token_contexts: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        environment_id = body["variables"]["environmentId"]
        authorization = request.headers["authorization"]
        calls.append((environment_id, authorization))
        metric = "revenue" if environment_id == "100" else "orders"
        return httpx.Response(
            200,
            json={
                "data": {
                    "metrics": {
                        "edges": [
                            {
                                "node": {
                                    "name": metric,
                                    "dimensions": [
                                        {
                                            "name": "tenant_id",
                                            "type": "categorical",
                                            "operators": ["equals"],
                                        }
                                    ],
                                }
                            }
                        ],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            },
        )

    async def token_provider(context: ToolContext) -> str:
        tenant = str(context.user.metadata["tenant_id"])
        token_contexts.append((tenant, context.user.id))
        return f"token-{tenant}"

    def environment_provider(context: ToolContext) -> str:
        return "100" if context.user.metadata["tenant_id"] == "tenant-a" else "200"

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        trust_env=False,
    )
    adapter = DbtSemanticLayerAdapter(
        endpoint="https://semantic-layer.example.test/api/graphql",
        environment_id_provider=environment_provider,
        token_provider=token_provider,
        http_client=client,
    )
    context_a = ToolContext(
        user=User(id="shared", metadata={"tenant_id": "tenant-a"}),
        conversation_id="conversation-a",
        request_id="request-a",
        agent_memory=DemoAgentMemory(),
    )
    context_b = ToolContext(
        user=User(id="shared", metadata={"tenant_id": "tenant-b"}),
        conversation_id="conversation-b",
        request_id="request-b",
        agent_memory=DemoAgentMemory(),
    )
    try:
        first_a = await adapter.plan("show revenue", context_a)
        tenant_b = await adapter.plan("show revenue", context_b)
        cached_a = await adapter.plan("show revenue", context_a)
    finally:
        await client.aclose()

    assert first_a.coverage == "full"
    assert tenant_b.coverage == "missing"
    assert cached_a.coverage == "full"
    assert calls == [
        ("100", "Bearer token-tenant-a"),
        ("200", "Bearer token-tenant-b"),
    ]
    assert token_contexts == [("tenant-a", "shared"), ("tenant-b", "shared")]


@pytest.mark.asyncio
async def test_tenant_filter_is_mandatory_and_cannot_be_overridden(
    tool_context: ToolContext,
) -> None:
    service = FakeDbtGraphqlService()
    adapter, client = _build_adapter(service)
    try:
        with pytest.raises(DbtSemanticLayerError) as exc_info:
            await adapter.execute(
                SemanticQueryRequest(
                    metric="revenue",
                    filters={"tenant_id": "tenant-b"},
                ),
                tool_context,
            )
    finally:
        await client.aclose()

    assert exc_info.value.code == "semantic_policy_denied"
    assert "CreateSemanticQuery" not in _operations(service)


@pytest.mark.asyncio
async def test_missing_tenant_or_protected_dimension_fails_closed() -> None:
    service = FakeDbtGraphqlService()
    adapter, client = _build_adapter(service)
    missing_tenant = ToolContext(
        user=User(id="user-without-tenant"),
        conversation_id="conversation-a",
        request_id="request-a",
        agent_memory=DemoAgentMemory(),
    )
    try:
        with pytest.raises(DbtSemanticLayerError) as tenant_error:
            await adapter.plan("show revenue", missing_tenant)
    finally:
        await client.aclose()

    assert tenant_error.value.code == "semantic_policy_denied"
    assert service.calls == []

    async def unprotected_catalog(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "data": {
                    "metrics": {
                        "edges": [{"node": {"name": "revenue", "dimensions": []}}],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            },
        )

    unprotected, unprotected_client = _build_adapter(unprotected_catalog)
    protected_context = ToolContext(
        user=User(id="user-a", metadata={"tenant_id": "tenant-a"}),
        conversation_id="conversation-a",
        request_id="request-a",
        agent_memory=DemoAgentMemory(),
    )
    try:
        with pytest.raises(DbtSemanticLayerError) as dimension_error:
            await unprotected.plan("show revenue", protected_context)
    finally:
        await unprotected_client.aclose()

    assert dimension_error.value.code == "semantic_policy_denied"


@pytest.mark.asyncio
async def test_poll_attempt_bound_does_not_sleep_after_final_attempt(
    tool_context: ToolContext,
):
    clock = FakeClock()

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        operation = body["operationName"]
        if operation == "GetSemanticCatalog":
            page = json.loads(json.dumps(METADATA_PAGE_ONE))
            page["data"]["metrics"]["pageInfo"] = {
                "hasNextPage": False,
                "endCursor": None,
            }
            return httpx.Response(200, json=page)
        if operation == "CreateSemanticQuery":
            return httpx.Response(
                200, json={"data": {"createQuery": {"queryId": "bounded-query"}}}
            )
        if operation == "GetSemanticQueryStatus":
            return httpx.Response(200, json={"data": {"query": {"status": "RUNNING"}}})
        raise AssertionError(operation)

    adapter, client = _build_adapter(
        handler,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        max_poll_attempts=1,
    )
    try:
        with pytest.raises(DbtSemanticLayerError) as exc_info:
            await adapter.execute(SemanticQueryRequest(metric="revenue"), tool_context)
    finally:
        await client.aclose()

    assert exc_info.value.code == "semantic_query_timeout"
    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_oversized_and_invalid_auth_responses_fail_before_parsing(
    tool_context: ToolContext,
):
    request_count = 0
    chunks_seen = 0

    class OversizedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal chunks_seen
            for chunk in (b"x" * 600, b"y" * 600, b"z" * 4096):
                chunks_seen += 1
                yield chunk

    async def oversized_handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, stream=OversizedStream())

    oversized, oversized_client = _build_adapter(
        oversized_handler,
        max_response_bytes=1024,
    )
    try:
        with pytest.raises(DbtSemanticLayerError) as oversized_error:
            await oversized.plan("show revenue", tool_context)
    finally:
        await oversized_client.aclose()
    assert oversized_error.value.code == "semantic_response_too_large"

    invalid_token_client = httpx.AsyncClient(
        transport=httpx.MockTransport(oversized_handler), trust_env=False
    )
    invalid_token = DbtSemanticLayerAdapter(
        endpoint="https://semantic-layer.example.test/api/graphql",
        environment_id="12345",
        token_provider=lambda context: "secret-token\n",
        http_client=invalid_token_client,
    )
    try:
        with pytest.raises(DbtSemanticLayerError) as auth_error:
            await invalid_token.plan("show revenue", tool_context)
    finally:
        await invalid_token_client.aclose()

    assert auth_error.value.code == "semantic_auth_error"
    assert "secret-token" not in str(auth_error.value)
    assert request_count == 1
    assert chunks_seen == 2


@pytest.mark.asyncio
async def test_redirect_is_rejected_before_graphql_body_replay(
    tool_context: ToolContext,
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host != "semantic-layer.example.test":
            raise AssertionError("GraphQL body crossed the configured trust boundary")
        return httpx.Response(
            307,
            headers={"Location": "https://attacker.invalid/collect"},
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        trust_env=False,
        follow_redirects=True,
    )
    adapter = DbtSemanticLayerAdapter(
        endpoint="https://semantic-layer.example.test/api/graphql",
        environment_id="12345",
        token_provider=lambda context: f"secret-{context.user.id}",
        http_client=client,
    )
    try:
        with pytest.raises(DbtSemanticLayerError) as exc_info:
            await adapter.plan("show revenue", tool_context)
    finally:
        await client.aclose()

    assert exc_info.value.code == "semantic_http_error"
    assert len(requests) == 1
    assert requests[0].url == httpx.URL(
        "https://semantic-layer.example.test/api/graphql"
    )


@pytest.mark.asyncio
async def test_adapter_requires_https_endpoint_and_numeric_environment():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: None))
    try:
        with pytest.raises(ValueError, match="HTTPS"):
            DbtSemanticLayerAdapter(
                endpoint="http://semantic-layer.example.test/api/graphql",
                environment_id="12345",
                token_provider=lambda context: "token",
                http_client=client,
            )
        with pytest.raises(ValueError, match="numeric"):
            DbtSemanticLayerAdapter(
                endpoint="https://semantic-layer.example.test/api/graphql",
                environment_id="production",
                token_provider=lambda context: "token",
                http_client=client,
            )
        with pytest.raises(ValueError, match="exactly one"):
            DbtSemanticLayerAdapter(
                endpoint="https://semantic-layer.example.test/api/graphql",
                environment_id="12345",
                environment_id_provider=lambda context: "67890",
                token_provider=lambda context: "token",
                http_client=client,
            )
    finally:
        await client.aclose()
