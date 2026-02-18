"""Golden path: multi-tenant query isolation with query-layer enforcement."""

from typing import Union

from vanna import Agent
from vanna.capabilities.sql_runner import RunSqlToolArgs
from vanna.core.registry import ToolRegistry
from vanna.core.tool import ToolRejection, ToolContext, Tool
from vanna.core.user import User
from vanna.core.user.resolver import UserResolver
from vanna.core.user.request_context import RequestContext
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.mock import MockLlmService
from vanna.integrations.sqlite import SqliteRunner
from vanna.tools import RunSqlTool


class TenantAwareRegistry(ToolRegistry):
    async def transform_args(
        self,
        tool: Tool,
        args: RunSqlToolArgs,
        user: User,
        context: ToolContext,
    ) -> Union[RunSqlToolArgs, ToolRejection]:
        if tool.name != "run_sql":
            return args

        tenant_id = user.metadata.get("tenant_id")
        if tenant_id is None:
            return ToolRejection(reason="Missing tenant context.")

        sql = args.sql.strip().rstrip(";")
        if " where " in sql.lower():
            sql = f"{sql} AND tenant_id = '{tenant_id}'"
        else:
            sql = f"{sql} WHERE tenant_id = '{tenant_id}'"
        return RunSqlToolArgs(sql=sql)


class TenantResolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        tenant_id = request_context.headers.get("x-tenant-id", "tenant-a")
        return User(id="tenant-user", group_memberships=["user"], metadata={"tenant_id": tenant_id})


def build_agent() -> Agent:
    registry = TenantAwareRegistry()
    sql_tool = RunSqlTool(sql_runner=SqliteRunner(database_path="tenant.db"), read_only=True)
    registry.register_local_tool(sql_tool, ["user"])

    return Agent(
        llm_service=MockLlmService(),
        tool_registry=registry,
        user_resolver=TenantResolver(),
        agent_memory=DemoAgentMemory(),
    )

