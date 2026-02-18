"""Golden path: FastAPI + JWT middleware + Postgres + v3 endpoints."""

from vanna import Agent, AgentConfig
from vanna.core.registry import ToolRegistry
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.postgres import PostgresRunner
from vanna.integrations.mock import MockLlmService
from vanna.servers.fastapi import VannaFastAPIServer
from vanna.servers.base import (
    make_fastapi_bearer_auth_middleware,
    make_fixed_window_rate_limiter,
)
from vanna.services import PortableSchemaCatalogService, FeedbackService
from vanna.tools import RunSqlTool
from vanna.core.user.resolver import UserResolver
from vanna.core.user import User
from vanna.core.user.request_context import RequestContext


class DemoUserResolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        return User(id="demo-user", group_memberships=["user"])


def token_validator(token: str) -> bool:
    return token == "dev-token"


def main() -> None:
    sql_runner = PostgresRunner(
        connection_string="postgresql://postgres:postgres@localhost:5432/postgres"
    )
    tools = ToolRegistry()
    tools.register_local_tool(RunSqlTool(sql_runner=sql_runner, read_only=True), ["user"])

    agent = Agent(
        llm_service=MockLlmService(),
        tool_registry=tools,
        user_resolver=DemoUserResolver(),
        agent_memory=DemoAgentMemory(),
        config=AgentConfig(),
    )

    schema_sync = PortableSchemaCatalogService(sql_runner=sql_runner)
    feedback_service = FeedbackService()

    server = VannaFastAPIServer(
        agent=agent,
        config={
            "enable_default_ui_route": False,
            "middleware_hooks": [make_fastapi_bearer_auth_middleware(token_validator)],
            "request_guard": make_fixed_window_rate_limiter(120),
            "schema_sync_service": schema_sync,
            "feedback_service": feedback_service,
            "cors": {
                "enabled": True,
                "allow_origins": ["http://localhost:3000"],
            },
        },
    )
    server.run(port=8000)


if __name__ == "__main__":
    main()

