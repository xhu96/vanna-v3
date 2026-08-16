"""Framework-neutral public server errors."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional


class PublicServerError(Exception):
    """An error with a stable, redacted representation safe for clients."""

    status_code = 500
    code = "internal_error"
    public_message = "An unexpected error occurred."
    retryable = False

    def __init__(
        self,
        *,
        correlation_id: Optional[str] = None,
        retry_after: Optional[int] = None,
    ) -> None:
        super().__init__(self.code)
        self.correlation_id = correlation_id or f"err_{uuid.uuid4().hex}"
        self.retry_after = retry_after


class InvalidRequestError(PublicServerError):
    status_code = 400
    code = "invalid_request"
    public_message = "The request is invalid."


class AuthenticationRequiredError(PublicServerError):
    status_code = 401
    code = "authentication_required"
    public_message = "Authentication is required."


class RouteAccessDeniedError(PublicServerError):
    status_code = 403
    code = "route_access_denied"
    public_message = "Access to this route is denied."


class ConversationRouteAccessDeniedError(RouteAccessDeniedError):
    code = "conversation_access_denied"
    public_message = "Access to this conversation is denied."


class ResourceNotFoundError(PublicServerError):
    status_code = 404
    code = "resource_not_found"
    public_message = "The requested resource was not found."


class RequestConflictError(PublicServerError):
    status_code = 409
    code = "request_conflict"
    public_message = "The request conflicts with current resource state."


class MethodNotAllowedError(PublicServerError):
    status_code = 405
    code = "method_not_allowed"
    public_message = "The request method is not allowed."


class RateLimitExceededError(PublicServerError):
    status_code = 429
    code = "rate_limit_exceeded"
    public_message = "The request rate limit was exceeded."
    retryable = True


class InternalServerError(PublicServerError):
    pass


class ServiceNotConfiguredError(PublicServerError):
    status_code = 501
    code = "service_not_configured"
    public_message = "This capability is not configured."


def public_error_payload(error: PublicServerError) -> Dict[str, Any]:
    """Serialize a public error without internal exception details."""

    return {
        "error": {
            "code": error.code,
            "message": error.public_message,
            "correlation_id": error.correlation_id,
            "retryable": error.retryable,
        }
    }


def public_error_for_status(status_code: int) -> PublicServerError:
    """Map framework HTTP errors to stable public errors."""

    errors = {
        400: InvalidRequestError,
        401: AuthenticationRequiredError,
        403: RouteAccessDeniedError,
        404: ResourceNotFoundError,
        409: RequestConflictError,
        405: MethodNotAllowedError,
        429: RateLimitExceededError,
        501: ServiceNotConfiguredError,
    }
    error_type = errors.get(status_code, InternalServerError)
    return error_type()
