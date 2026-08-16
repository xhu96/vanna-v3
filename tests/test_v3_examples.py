"""Security contracts for the V3 golden-path examples."""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import time
from pathlib import Path
from typing import Any

import pytest

from vanna.core.tool import ToolContext
from vanna.core.user import RequestContext, User
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.security.sql_policy import SqlPolicyViolation, SqlQueryPolicy

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples/v3"


def load_example(name: str) -> Any:
    path = EXAMPLES / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"vanna_example_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_python_example_compiles() -> None:
    for path in EXAMPLES.glob("*.py"):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_fastapi_jwt_postgres_example_has_no_demo_identity_or_owner_dsn() -> None:
    source = (EXAMPLES / "fastapi_jwt_postgres.py").read_text(encoding="utf-8")

    assert "dev-token" not in source
    assert "postgres:postgres" not in source
    assert "VANNA_POSTGRES_READ_ONLY_DSN" in source
    assert '"security_mode": "production"' in source
    assert '"cors": {"enabled": False}' in source
    assert "authenticated=True" in source
    assert 'algorithms=["RS256"]' in source


def test_fastapi_jwt_postgres_example_enforces_tenant_rls() -> None:
    module = load_example("fastapi_jwt_postgres")
    policy = SqlQueryPolicy(
        "postgres",
        row_policies=module.tenant_row_policies,
        require_row_policies=True,
    )

    def context(tenant_id: str | None) -> ToolContext:
        metadata = {"tenant_id": tenant_id} if tenant_id is not None else {}
        return ToolContext(
            user=User(
                id="analyst",
                authenticated=True,
                metadata=metadata,
            ),
            conversation_id="conversation",
            request_id=f"request-{tenant_id or 'missing'}",
            agent_memory=DemoAgentMemory(),
        )

    query = (
        "SELECT o.id, c.id AS customer_id FROM orders AS o "
        "JOIN customers AS c ON c.id = o.customer_id"
    )
    tenant_a = policy.prepare(query, context("tenant-a"))
    tenant_b = policy.prepare(query, context("tenant-b"))

    assert "FROM (SELECT * FROM orders WHERE tenant_id = 'tenant-a') AS o" in tenant_a
    assert (
        "JOIN (SELECT * FROM customers WHERE tenant_id = 'tenant-a') AS c" in tenant_a
    )
    assert "tenant-b" not in tenant_a
    assert "FROM (SELECT * FROM orders WHERE tenant_id = 'tenant-b') AS o" in tenant_b
    assert (
        "JOIN (SELECT * FROM customers WHERE tenant_id = 'tenant-b') AS c" in tenant_b
    )
    assert tenant_a != tenant_b
    with pytest.raises(SqlPolicyViolation, match="policy resolution failed"):
        policy.prepare(query, context(None))


@pytest.mark.asyncio
async def test_multi_tenant_example_derives_scope_from_verified_claims() -> None:
    module = load_example("multi_tenant_rls")
    resolver = module.TenantResolver(
        lambda token: {
            "sub": "alice",
            "tenant_id": "tenant-from-token",
            "groups": ["analyst"],
        }
    )
    context = RequestContext(
        headers={
            "Authorization": "Bearer signed-token",
            "X-Tenant-ID": "attacker-selected-tenant",
        }
    )

    user = await resolver.resolve_user(context)

    assert user.authenticated is True
    assert user.metadata["tenant_id"] == "tenant-from-token"
    assert user.group_memberships == ["analyst"]


def gateway_headers(
    module: Any,
    secret: bytes,
    *,
    timestamp: int,
) -> dict[str, str]:
    values = {
        "X-Vanna-Identity-User": "alice",
        "X-Vanna-Identity-Tenant": "acme",
        "X-Vanna-Identity-Groups": "user,analyst",
        "X-Vanna-Identity-Timestamp": str(timestamp),
        "X-Vanna-Identity-Nonce": "request-123",
    }
    canonical = module._canonical_assertion(
        values["X-Vanna-Identity-User"],
        values["X-Vanna-Identity-Tenant"],
        values["X-Vanna-Identity-Groups"],
        values["X-Vanna-Identity-Timestamp"],
        values["X-Vanna-Identity-Nonce"],
    )
    values["X-Vanna-Identity-Signature"] = hmac.new(
        secret, canonical, hashlib.sha256
    ).hexdigest()
    return values


@pytest.mark.asyncio
async def test_oauth_gateway_example_requires_trusted_peer_and_signature() -> None:
    module = load_example("trusted_oauth_gateway")
    secret = b"0123456789abcdef0123456789abcdef"
    resolver = module.TrustedOAuthGatewayResolver(
        trusted_proxy_networks=["10.20.0.0/16"],
        assertion_secret=secret,
    )
    headers = gateway_headers(module, secret, timestamp=int(time.time()))

    user = await resolver.resolve_user(
        RequestContext(headers=headers, remote_addr="10.20.3.4")
    )
    assert user.authenticated is True
    assert user.id == "alice"
    assert user.metadata["tenant_id"] == "acme"

    with pytest.raises(PermissionError, match="trusted gateway"):
        await resolver.resolve_user(
            RequestContext(headers=headers, remote_addr="203.0.113.8")
        )

    tampered = {**headers, "X-Vanna-Identity-Tenant": "other"}
    with pytest.raises(PermissionError, match="signature"):
        await resolver.resolve_user(
            RequestContext(headers=tampered, remote_addr="10.20.3.4")
        )

    stale = gateway_headers(module, secret, timestamp=int(time.time()) - 120)
    with pytest.raises(PermissionError, match="expired"):
        await resolver.resolve_user(
            RequestContext(headers=stale, remote_addr="10.20.3.4")
        )
