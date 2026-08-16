"""Golden adapter wiring for dbt Semantic Layer GraphQL.

Set ``DBT_SEMANTIC_LAYER_URL``, ``DBT_ENVIRONMENT_ID``, and
``DBT_SERVICE_TOKEN`` in the process environment. In production, replace the
environment lookup with a secret-manager-backed token provider and close the
HTTP client during application shutdown.
"""

from __future__ import annotations

import os

import httpx

from vanna import Agent
from vanna.core.planner import SemanticFirstPlanner
from vanna.core.registry import ToolRegistry
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.core.user.request_context import RequestContext
from vanna.core.user.resolver import UserResolver
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.mock import MockLlmService
from vanna.integrations.semantic import DbtSemanticLayerAdapter
from vanna.tools.semantic_query import SemanticQueryTool


class Resolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        return User(
            id="semantic-user",
            authenticated=True,
            group_memberships=["user"],
            metadata={"tenant_id": "acme"},
        )


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable is not set: {name}")
    return value


def service_token(context: ToolContext) -> str:
    if context.user.metadata.get("tenant_id") != "acme":
        raise PermissionError("No dbt credentials are configured for this tenant")
    return required_environment("DBT_SERVICE_TOKEN")


def build_agent(http_client: httpx.AsyncClient) -> Agent:
    adapter = DbtSemanticLayerAdapter(
        endpoint=required_environment("DBT_SEMANTIC_LAYER_URL"),
        environment_id=required_environment("DBT_ENVIRONMENT_ID"),
        token_provider=service_token,
        tenant_filter_dimension="tenant_id",
        http_client=http_client,
        request_timeout_seconds=10,
        query_timeout_seconds=30,
        max_poll_attempts=100,
    )
    tools = ToolRegistry()
    tools.register_local_tool(SemanticQueryTool(adapter), ["user"])

    return Agent(
        llm_service=MockLlmService(),
        tool_registry=tools,
        user_resolver=Resolver(),
        agent_memory=DemoAgentMemory(),
        semantic_planner=SemanticFirstPlanner(semantic_adapter=adapter),
    )


def build_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        follow_redirects=False,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )


# Framework startup should call build_agent(build_http_client()) and retain both
# objects. Framework shutdown must close the client with ``await client.aclose()``.
