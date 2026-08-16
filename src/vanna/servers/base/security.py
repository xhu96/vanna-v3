"""Shared validation for secure server factory configuration."""

from __future__ import annotations

import ipaddress
from typing import Any, Dict, Iterable, Union, cast
from urllib.parse import urlsplit

from ...core import Agent
from ...core.tool import (
    ARBITRARY_CODE_EXECUTION_CAPABILITY,
    PRIVILEGED_SQL_WRITE_CAPABILITY,
)
from ...core.storage import ConversationStore
from .authorization import DefaultRouteAuthorizer, RouteAuthorizer

PRODUCTION = "production"
DEVELOPMENT = "development"
VALID_SECURITY_MODES = frozenset({PRODUCTION, DEVELOPMENT})


def security_mode(config: Dict[str, Any]) -> str:
    """Read and validate the explicit server security mode."""

    mode = config.get("security_mode", PRODUCTION)
    if mode not in VALID_SECURITY_MODES:
        raise ValueError("security_mode must be 'production' or 'development'")
    return str(mode)


def route_authorizer(
    config: Dict[str, Any], *, mode: str, default_ui_enabled: bool
) -> RouteAuthorizer:
    """Return the configured authorizer or the secure default policy."""

    configured = config.get("route_authorizer")
    if configured is None:
        return DefaultRouteAuthorizer(
            security_mode=mode, default_ui_enabled=default_ui_enabled
        )
    if not callable(getattr(configured, "authorize", None)):
        raise ValueError(
            "route_authorizer must implement authorize(action, user, context)"
        )
    return cast(RouteAuthorizer, configured)


def validate_conversation_store(agent: Agent, *, mode: str) -> None:
    """Reject legacy non-atomic stores at the production server boundary."""

    if mode != PRODUCTION:
        return
    store = getattr(agent, "conversation_store", None)
    claim_method = getattr(type(store), "claim_conversation", None)
    if (
        getattr(store, "supports_atomic_ownership", False) is not True
        or getattr(store, "supports_atomic_updates", False) is not True
        or claim_method is None
        or claim_method is ConversationStore.claim_conversation
    ):
        raise ValueError(
            "Production mode requires a conversation store with "
            "supports_atomic_ownership=True, supports_atomic_updates=True, "
            "and atomic claim/update methods"
        )


def validate_agent_memory(agent: Agent, *, mode: str) -> None:
    """Reject memory backends without enforced tenant isolation in production."""

    if mode != PRODUCTION:
        return
    memory = getattr(agent, "agent_memory", None)
    if getattr(memory, "supports_tenant_isolation", False) is not True:
        raise ValueError(
            "Production mode requires agent memory with supports_tenant_isolation=True"
        )


def validate_tool_capabilities(agent: Agent, *, mode: str) -> None:
    """Reject model-reachable arbitrary execution tools in production."""

    if mode != PRODUCTION:
        return
    registry = getattr(agent, "tool_registry", None)
    if registry is None:
        return
    get_registered_tools = getattr(registry, "get_registered_tools", None)
    if not callable(get_registered_tools):
        raise ValueError("Production mode requires an introspectable tool registry")
    try:
        registered_tools = tuple(get_registered_tools())
        registered_capabilities = tuple(tool.capabilities for tool in registered_tools)
    except Exception as exc:
        raise ValueError(
            "Production mode could not validate registered tool capabilities"
        ) from exc
    if any(
        ARBITRARY_CODE_EXECUTION_CAPABILITY in capabilities
        for capabilities in registered_capabilities
    ):
        raise ValueError(
            "Production mode rejects tools with arbitrary code execution capability"
        )
    if any(
        PRIVILEGED_SQL_WRITE_CAPABILITY in capabilities
        for capabilities in registered_capabilities
    ):
        raise ValueError(
            "Production mode rejects tools with privileged SQL write capability"
        )


def validate_cors_configuration(
    cors_config: Dict[str, Any], *, origins_key: str, credentials_key: str
) -> None:
    """Reject credentialed wildcard CORS policies."""

    if not cors_config.get("enabled", False):
        return
    origins = cors_config.get(origins_key, [])
    origin_regex = cors_config.get("allow_origin_regex")
    wildcard_regex = _is_wildcard_origin(origin_regex)
    if cors_config.get(credentials_key, False) and (
        _contains_wildcard(origins)
        or wildcard_regex
        or origin_regex is not None
        or not _all_exact_http_origins(origins)
    ):
        raise ValueError(
            "Credentialed CORS requires explicit origins; origin regexes and "
            "wildcards are not allowed"
        )


def _contains_wildcard(origins: Union[str, Iterable[Any]]) -> bool:
    if isinstance(origins, str):
        return _is_wildcard_origin(origins)
    return any(_is_wildcard_origin(origin) for origin in origins)


def _all_exact_http_origins(origins: Union[str, Iterable[Any]]) -> bool:
    values = [origins] if isinstance(origins, str) else list(origins)
    if not values:
        return False
    for value in values:
        if not isinstance(value, str):
            return False
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError:
            return False
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or any(char in parsed.hostname for char in "*?[](){}|\\^")
            or (port is not None and not 1 <= port <= 65535)
        ):
            return False
    return True


def _is_wildcard_origin(origin: Any) -> bool:
    pattern = getattr(origin, "pattern", origin)
    return isinstance(pattern, str) and pattern.strip() in {"*", ".*", "^.*$"}


def validate_development_host(host: str) -> None:
    """Require loopback-only binding in explicit development mode."""

    normalized = host.strip().lower()
    if normalized == "localhost":
        return
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = normalized[1:-1]
    if "%" in normalized:
        normalized = normalized.split("%", 1)[0]
    try:
        if ipaddress.ip_address(normalized).is_loopback:
            return
    except ValueError:
        pass
    raise ValueError("Development mode must bind to a loopback host")
