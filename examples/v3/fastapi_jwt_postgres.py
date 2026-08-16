"""Golden path: FastAPI, verified JWT identity, and read-only PostgreSQL.

Install ``vanna[fastapi,postgres,jwt]``. Configure a PostgreSQL role that has
only CONNECT/USAGE/SELECT and set ``VANNA_POSTGRES_READ_ONLY_DSN``. Never use a
database owner or migration role for this process.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

from vanna import Agent, AgentConfig
from vanna.core.registry import ToolRegistry
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.core.user.request_context import RequestContext
from vanna.core.user.resolver import UserResolver
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.mock import MockLlmService
from vanna.integrations.postgres import PostgresRunner
from vanna.security.rls import RowFilterPolicy
from vanna.security.sql_policy import SqlQueryPolicy
from vanna.servers.base import (
    make_fastapi_bearer_auth_middleware,
    make_fixed_window_rate_limiter,
)
from vanna.servers.fastapi import VannaFastAPIServer
from vanna.services import FeedbackService, PortableSchemaCatalogService
from vanna.tools import RunSqlTool

TENANT_SCOPED_TABLES = frozenset({"orders", "customers", "invoices"})


def tenant_row_policies(context: ToolContext) -> list[RowFilterPolicy]:
    tenant_id = context.user.metadata.get("tenant_id")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise PermissionError("Verified tenant context is required")
    return [
        RowFilterPolicy(
            column="tenant_id",
            value=tenant_id,
            tables=TENANT_SCOPED_TABLES,
        )
    ]


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable is not set: {name}")
    return value


class JwtVerifier:
    """Verify RS256 tokens against a cached issuer JWKS."""

    def __init__(self, *, issuer: str, audience: str, jwks_url: str) -> None:
        try:
            import jwt
        except ImportError as exc:  # pragma: no cover - deployment guard
            raise RuntimeError("Install the 'vanna[jwt]' extra") from exc
        self.jwt = jwt
        self.issuer = issuer
        self.audience = audience
        self.jwks = jwt.PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=300)

    def verify(self, token: str) -> Mapping[str, Any]:
        signing_key = self.jwks.get_signing_key_from_jwt(token)
        return self.jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=self.audience,
            issuer=self.issuer,
            options={"require": ["exp", "sub"]},
        )

    def is_valid(self, token: str) -> bool:
        try:
            self.verify(token)
        except Exception:
            return False
        return True


class JwtUserResolver(UserResolver):
    def __init__(self, verifier: JwtVerifier) -> None:
        self.verifier = verifier

    async def resolve_user(self, request_context: RequestContext) -> User:
        authorization = request_context.get_header("Authorization", "") or ""
        scheme, separator, token = authorization.partition(" ")
        if scheme != "Bearer" or not separator or not token:
            raise PermissionError("Bearer authentication is required")
        claims = self.verifier.verify(token)
        subject = claims.get("sub")
        tenant_id = claims.get("tenant_id")
        raw_groups = claims.get("groups", [])
        if not isinstance(subject, str) or not subject:
            raise PermissionError("JWT subject is missing")
        if not isinstance(tenant_id, str) or not tenant_id:
            raise PermissionError("JWT tenant claim is missing")
        if not isinstance(raw_groups, list) or any(
            not isinstance(group, str) for group in raw_groups
        ):
            raise PermissionError("JWT groups claim is invalid")
        groups = [
            group for group in raw_groups if group in {"user", "analyst", "admin"}
        ]
        return User(
            id=subject,
            authenticated=True,
            group_memberships=groups,
            metadata={"tenant_id": tenant_id},
        )


def build_server() -> VannaFastAPIServer:
    verifier = JwtVerifier(
        issuer=required_environment("VANNA_JWT_ISSUER"),
        audience=required_environment("VANNA_JWT_AUDIENCE"),
        jwks_url=required_environment("VANNA_JWT_JWKS_URL"),
    )
    sql_runner = PostgresRunner(
        connection_string=required_environment("VANNA_POSTGRES_READ_ONLY_DSN"),
        read_only=True,
    )
    query_policy = SqlQueryPolicy(
        "postgres",
        row_policies=tenant_row_policies,
        require_row_policies=True,
    )
    tools = ToolRegistry()
    tools.register_local_tool(
        RunSqlTool(
            sql_runner=sql_runner,
            read_only=True,
            query_policy=query_policy,
        ),
        ["user", "analyst", "admin"],
    )
    agent = Agent(
        llm_service=MockLlmService(),  # Inject the deployment's LLM service.
        tool_registry=tools,
        user_resolver=JwtUserResolver(verifier),
        agent_memory=DemoAgentMemory(),  # Inject a durable store in production.
        config=AgentConfig(),
    )
    return VannaFastAPIServer(
        agent=agent,
        config={
            "security_mode": "production",
            "enable_default_ui_route": False,
            "middleware_hooks": [
                make_fastapi_bearer_auth_middleware(verifier.is_valid)
            ],
            "rate_limiter": make_fixed_window_rate_limiter(120),
            "schema_sync_service": PortableSchemaCatalogService(
                sql_runner=sql_runner,
                catalog_schemas=["public"],
            ),
            "feedback_service": FeedbackService(query_policy=query_policy),
            "cors": {"enabled": False},
        },
    )


if __name__ == "__main__":
    build_server().run(host="0.0.0.0", port=8000)
