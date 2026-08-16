"""Golden path: verified tenant claims plus recursive query-layer RLS."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from vanna import Agent
from vanna.core.registry import ToolRegistry
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.core.user.request_context import RequestContext
from vanna.core.user.resolver import UserResolver
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.mock import MockLlmService
from vanna.integrations.sqlite import SqliteRunner
from vanna.security.rls import RowFilterPolicy
from vanna.security.sql_policy import SqlQueryPolicy
from vanna.tools import RunSqlTool

TENANT_SCOPED_TABLES = {"orders", "customers", "invoices"}
ClaimsVerifier = Callable[[str], Mapping[str, Any]]


def tenant_row_policies(context: ToolContext) -> list[RowFilterPolicy]:
    tenant_id = context.user.metadata.get("tenant_id")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise PermissionError("Verified tenant context is required")
    return [
        RowFilterPolicy(
            column="tenant_id",
            value=tenant_id,
            tables=frozenset(TENANT_SCOPED_TABLES),
        )
    ]


class TenantResolver(UserResolver):
    def __init__(self, verify_claims: ClaimsVerifier) -> None:
        self.verify_claims = verify_claims

    async def resolve_user(self, request_context: RequestContext) -> User:
        authorization = request_context.get_header("Authorization", "") or ""
        scheme, separator, token = authorization.partition(" ")
        if scheme != "Bearer" or not separator or not token:
            raise PermissionError("Bearer authentication is required")
        claims = self.verify_claims(token)
        subject = claims.get("sub")
        tenant_id = claims.get("tenant_id")
        raw_groups = claims.get("groups", [])
        if not isinstance(subject, str) or not subject:
            raise PermissionError("Verified subject is missing")
        if not isinstance(tenant_id, str) or not tenant_id:
            raise PermissionError("Verified tenant is missing")
        if not isinstance(raw_groups, list):
            raise PermissionError("Verified groups are invalid")
        groups = [
            group
            for group in raw_groups
            if isinstance(group, str) and group in {"user", "analyst", "admin"}
        ]
        return User(
            id=subject,
            authenticated=True,
            group_memberships=groups,
            metadata={"tenant_id": tenant_id},
        )


def build_agent(verify_claims: ClaimsVerifier, database_path: str) -> Agent:
    registry = ToolRegistry()
    registry.register_local_tool(
        RunSqlTool(
            sql_runner=SqliteRunner(database_path=database_path, read_only=True),
            read_only=True,
            query_policy=SqlQueryPolicy(
                "sqlite",
                row_policies=tenant_row_policies,
                require_row_policies=True,
            ),
        ),
        ["user", "analyst", "admin"],
    )
    return Agent(
        llm_service=MockLlmService(),
        tool_registry=registry,
        user_resolver=TenantResolver(verify_claims),
        agent_memory=DemoAgentMemory(),
    )


if __name__ == "__main__":
    raise SystemExit(
        "Inject the same cryptographic claims verifier used by the API gateway. "
        "Never derive tenant_id from a caller-controlled tenant header."
    )
