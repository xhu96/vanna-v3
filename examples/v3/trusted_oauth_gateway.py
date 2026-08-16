"""Trusted OAuth gateway identity-header pattern.

The gateway must authenticate OAuth, strip every ``X-Vanna-Identity-*`` header
from the client, write fresh values, sign them, and be the only network peer
allowed to reach the application. TLS/mTLS and firewall policy remain required;
the shared signature is defense in depth, not a replacement for that boundary.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import time
from typing import Iterable

from vanna.core.user import RequestContext, User
from vanna.core.user.resolver import UserResolver

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$")
_GROUP = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")


def _canonical_assertion(
    user_id: str,
    tenant_id: str,
    groups: str,
    timestamp: str,
    nonce: str,
) -> bytes:
    return "\n".join((user_id, tenant_id, groups, timestamp, nonce)).encode("utf-8")


class TrustedOAuthGatewayResolver(UserResolver):
    def __init__(
        self,
        *,
        trusted_proxy_networks: Iterable[str],
        assertion_secret: bytes,
        maximum_age_seconds: int = 30,
    ) -> None:
        if len(assertion_secret) < 32:
            raise ValueError("gateway assertion secret must contain at least 32 bytes")
        if maximum_age_seconds < 1 or maximum_age_seconds > 300:
            raise ValueError("maximum assertion age must be between 1 and 300 seconds")
        self.networks = tuple(
            ipaddress.ip_network(value, strict=True) for value in trusted_proxy_networks
        )
        if not self.networks:
            raise ValueError("at least one trusted proxy network is required")
        self.secret = assertion_secret
        self.maximum_age_seconds = maximum_age_seconds

    async def resolve_user(self, request_context: RequestContext) -> User:
        self._verify_peer(request_context.remote_addr)
        user_id = self._header(request_context, "X-Vanna-Identity-User")
        tenant_id = self._header(request_context, "X-Vanna-Identity-Tenant")
        groups_value = self._header(request_context, "X-Vanna-Identity-Groups")
        timestamp_value = self._header(request_context, "X-Vanna-Identity-Timestamp")
        nonce = self._header(request_context, "X-Vanna-Identity-Nonce")
        signature = self._header(request_context, "X-Vanna-Identity-Signature")

        if not _IDENTIFIER.fullmatch(user_id) or not _IDENTIFIER.fullmatch(tenant_id):
            raise PermissionError("gateway identity is invalid")
        if not _IDENTIFIER.fullmatch(nonce):
            raise PermissionError("gateway nonce is invalid")
        try:
            timestamp = int(timestamp_value)
        except ValueError as exc:
            raise PermissionError("gateway timestamp is invalid") from exc
        if abs(int(time.time()) - timestamp) > self.maximum_age_seconds:
            raise PermissionError("gateway assertion has expired")

        groups = groups_value.split(",") if groups_value else []
        if len(groups) > 32 or any(not _GROUP.fullmatch(group) for group in groups):
            raise PermissionError("gateway groups are invalid")
        expected = hmac.new(
            self.secret,
            _canonical_assertion(
                user_id,
                tenant_id,
                groups_value,
                timestamp_value,
                nonce,
            ),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise PermissionError("gateway signature is invalid")

        return User(
            id=user_id,
            authenticated=True,
            group_memberships=groups,
            metadata={"tenant_id": tenant_id, "identity_source": "oauth_gateway"},
        )

    def _verify_peer(self, remote_addr: str | None) -> None:
        try:
            peer = ipaddress.ip_address(remote_addr or "")
        except ValueError as exc:
            raise PermissionError("gateway peer is invalid") from exc
        if not any(peer in network for network in self.networks):
            raise PermissionError("request did not originate from a trusted gateway")

    @staticmethod
    def _header(context: RequestContext, name: str) -> str:
        value = context.get_header(name)
        if value is None or not value or len(value) > 512:
            raise PermissionError("gateway assertion is incomplete")
        return value
