"""Trusted-identity rate-limit integration for server routes."""

from __future__ import annotations

import hashlib
import inspect
import json
import threading
import time
from collections import defaultdict, deque
from typing import (
    Any,
    Awaitable,
    Callable,
    Deque,
    Dict,
    Optional,
    Protocol,
    Union,
    cast,
)

from ...core.user import RequestContext, User, principal_scope_for_user
from .authorization import (
    RESOLVED_USER_METADATA_KEY,
    attach_resolved_user,
    trusted_resolved_user,
)
from .errors import InternalServerError, PublicServerError, RateLimitExceededError

RateLimitDecision = Union[bool, None, Awaitable[Optional[bool]]]


class RateLimiter(Protocol):
    """A route rate limiter keyed from trusted resolved request state."""

    def check(self, user: User, context: RequestContext) -> RateLimitDecision:
        """Allow with ``True``/``None`` or reject with ``False``/an exception."""


async def enforce_rate_limit(
    rate_limiter: Optional[Union[RateLimiter, Callable[..., Any]]],
    user: User,
    context: RequestContext,
) -> None:
    """Invoke an injectable limiter and normalize rejection to HTTP 429."""

    if rate_limiter is None:
        return

    check = cast(
        Callable[[User, RequestContext], Any],
        getattr(rate_limiter, "check", rate_limiter),
    )
    try:
        result = check(user, context)
        if inspect.isawaitable(result):
            result = await result
    except RateLimitExceededError:
        raise
    except PermissionError as exc:
        raise RateLimitExceededError() from exc
    except PublicServerError:
        raise
    except Exception as exc:
        status_code = getattr(exc, "status_code", getattr(exc, "code", None))
        if status_code == 429:
            raise RateLimitExceededError() from exc
        raise InternalServerError() from exc

    if result is False:
        raise RateLimitExceededError()


class FixedWindowRateLimiter:
    """Small in-process limiter for examples and single-process deployments."""

    def __init__(self, requests_per_minute: int = 120) -> None:
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        self.requests_per_minute = requests_per_minute
        self._buckets: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @staticmethod
    def _identity(user: Optional[User], context: RequestContext) -> str:
        if user is not None and user.authenticated:
            scope = principal_scope_for_user(user)
            canonical = json.dumps(scope, ensure_ascii=False, separators=(",", ":"))
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            return f"principal:{digest}"
        return f"peer:{context.remote_addr or 'unknown'}"

    def check(self, user: User, context: RequestContext) -> None:
        self._check_identity(self._identity(user, context))

    def __call__(self, chat_request: Any, context: RequestContext) -> None:
        """Retain compatibility with the existing ``request_guard`` hook."""

        del chat_request
        user = trusted_resolved_user(context)
        self._check_identity(self._identity(user, context))

    def _check_identity(self, identity: str) -> None:
        now = time.monotonic()
        window_start = now - 60.0
        with self._lock:
            queue = self._buckets[identity]
            while queue and queue[0] < window_start:
                queue.popleft()
            if len(queue) >= self.requests_per_minute:
                raise RateLimitExceededError(retry_after=60)
            queue.append(now)


def make_fixed_window_rate_limiter(
    requests_per_minute: int = 120,
) -> FixedWindowRateLimiter:
    """Create a limiter usable as ``rate_limiter`` or legacy ``request_guard``."""

    return FixedWindowRateLimiter(requests_per_minute=requests_per_minute)


def configured_rate_limiter(
    config: Dict[str, Any], *, security_mode: str
) -> Optional[Union[RateLimiter, Callable[..., Any]]]:
    """Return an injected limiter or the bounded production default."""

    configured = config.get("rate_limiter")
    if configured is not None:
        if not callable(configured) and not callable(
            getattr(configured, "check", None)
        ):
            raise ValueError("rate_limiter must be callable or implement check()")
        return cast(Union[RateLimiter, Callable[..., Any]], configured)
    if security_mode == "production":
        raw_limit = config.get("rate_limit_requests_per_minute", 120)
        if isinstance(raw_limit, bool) or not isinstance(raw_limit, int):
            raise ValueError("rate_limit_requests_per_minute must be an integer")
        return FixedWindowRateLimiter(requests_per_minute=raw_limit)
    return None
