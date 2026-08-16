"""Authentication and route-level authorization contracts."""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from typing import Awaitable, Optional, Union

from ...core.user import RequestContext, User, UserResolver, principal_scope_for_user
from .errors import (
    AuthenticationRequiredError,
    InternalServerError,
    PublicServerError,
    RouteAccessDeniedError,
)

CHAT_EXECUTE = "chat:execute"
FEEDBACK_CREATE = "feedback:create"
FEEDBACK_EXPORT = "feedback:export"
FEEDBACK_REVIEW = "feedback:review"
HEALTH_READ = "health:read"
SCHEMA_READ = "schema:read"
SCHEMA_SYNC = "schema:sync"
UI_READ = "ui:read"

RESOLVED_USER_METADATA_KEY = "_vanna_resolved_user"
_RESOLVED_USER_MARKER_KEY = "_vanna_resolved_user_marker"
_RESOLVED_USER_MARKER = object()

SENSITIVE_ACTIONS = frozenset(
    {
        CHAT_EXECUTE,
        FEEDBACK_CREATE,
        FEEDBACK_EXPORT,
        FEEDBACK_REVIEW,
        SCHEMA_READ,
        SCHEMA_SYNC,
        UI_READ,
    }
)
ADMIN_ACTIONS = frozenset({FEEDBACK_EXPORT, FEEDBACK_REVIEW, SCHEMA_READ, SCHEMA_SYNC})

AuthorizationDecision = Union[bool, None, Awaitable[Optional[bool]]]


class RouteAuthorizer(ABC):
    """Authorize a resolved user for a named server action."""

    @abstractmethod
    def authorize(
        self, action: str, user: User, context: RequestContext
    ) -> AuthorizationDecision:
        """Allow with ``True``/``None`` or deny with ``False``/an exception."""


class DefaultRouteAuthorizer(RouteAuthorizer):
    """Default authenticated-user and admin-group route policy."""

    def __init__(
        self, *, security_mode: str = "production", default_ui_enabled: bool = False
    ) -> None:
        self.security_mode = security_mode
        self.default_ui_enabled = default_ui_enabled

    def authorize(
        self, action: str, user: User, context: RequestContext
    ) -> Optional[bool]:
        del context

        if action == HEALTH_READ:
            return True
        if action not in SENSITIVE_ACTIONS:
            raise RouteAccessDeniedError()
        if not user.authenticated:
            raise AuthenticationRequiredError()
        try:
            principal_scope_for_user(user)
        except (TypeError, ValueError):
            raise AuthenticationRequiredError() from None
        if self.security_mode == "production" and not authentication_was_explicit(user):
            raise AuthenticationRequiredError()
        if action == UI_READ:
            if self.default_ui_enabled:
                return True
            raise RouteAccessDeniedError()
        if action in ADMIN_ACTIONS and "admin" not in user.group_memberships:
            raise RouteAccessDeniedError()
        return True


class RequestBoundUserResolver(UserResolver):
    """Reuse the route-authorized user when the Agent resolves the same context."""

    def __init__(self, delegate: UserResolver) -> None:
        self.delegate = delegate

    @classmethod
    def wrap(cls, resolver: UserResolver) -> UserResolver:
        if isinstance(resolver, cls):
            return resolver
        return cls(resolver)

    async def resolve_user(self, request_context: RequestContext) -> User:
        cached = trusted_resolved_user(request_context)
        if cached is not None:
            return cached
        return await self.delegate.resolve_user(request_context)


def attach_resolved_user(context: RequestContext, user: User) -> None:
    """Attach a user with an in-process marker that network input cannot forge."""

    context.metadata[RESOLVED_USER_METADATA_KEY] = user
    context.metadata[_RESOLVED_USER_MARKER_KEY] = _RESOLVED_USER_MARKER


def trusted_resolved_user(context: RequestContext) -> Optional[User]:
    """Read a user only when the server attached the matching private marker."""

    if context.metadata.get(_RESOLVED_USER_MARKER_KEY) is not _RESOLVED_USER_MARKER:
        return None
    candidate = context.metadata.get(RESOLVED_USER_METADATA_KEY)
    return candidate if isinstance(candidate, User) else None


def authentication_was_explicit(user: User) -> bool:
    """Return whether the resolver explicitly supplied the authentication claim."""

    return "authenticated" in user.model_fields_set


async def resolve_and_authorize(
    *,
    action: str,
    resolver: UserResolver,
    authorizer: RouteAuthorizer,
    context: RequestContext,
    security_mode: str,
) -> User:
    """Resolve one user and enforce production plus injectable route policy."""

    try:
        user = await resolver.resolve_user(context)
    except PublicServerError:
        raise
    except Exception as exc:
        raise AuthenticationRequiredError() from exc

    if not isinstance(user, User):
        raise AuthenticationRequiredError()

    if security_mode == "production" and action in SENSITIVE_ACTIONS:
        if not user.authenticated or not authentication_was_explicit(user):
            raise AuthenticationRequiredError()
        try:
            principal_scope_for_user(user)
        except (TypeError, ValueError):
            raise AuthenticationRequiredError() from None

    try:
        result = authorizer.authorize(action, user, context)
        if inspect.isawaitable(result):
            result = await result
    except PublicServerError:
        raise
    except PermissionError as exc:
        raise RouteAccessDeniedError() from exc
    except Exception as exc:
        status_code = getattr(exc, "status_code", getattr(exc, "code", None))
        if status_code == 401:
            raise AuthenticationRequiredError() from exc
        if status_code == 403:
            raise RouteAccessDeniedError() from exc
        raise InternalServerError() from exc

    if result is False or (result is not True and result is not None):
        raise RouteAccessDeniedError()
    return user
