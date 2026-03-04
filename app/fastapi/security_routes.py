"""
FastAPI admin routes for runtime security configuration.

These endpoints are restricted to users in the ``admin`` group and allow
reading and updating the ``SecurityConfig`` on the running agent instance.
Changes are in-memory only — a server restart restores defaults.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

try:
    from fastapi import APIRouter, Depends, HTTPException, Request
except ImportError:
    raise ImportError(
        "FastAPI is required for security routes. "
        "Install with: pip install 'vanna[fastapi]'"
    )

from pydantic import BaseModel, Field

from vanna.core import Agent
from vanna.config import SecurityConfig, UiFeature

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class SecurityConfigResponse(BaseModel):
    """Response schema for GET /admin/security."""

    config: Dict[str, Any]
    message: str = "Current security configuration"


class SecurityConfigUpdate(BaseModel):
    """Partial update schema for PATCH /admin/security.

    All fields are optional — only the supplied fields are merged into the
    running config.
    """

    ssrf_protection_enabled: Optional[bool] = None
    ssrf_allowed_private_ranges: Optional[list] = None
    max_redirect_hops: Optional[int] = Field(default=None, ge=0, le=10)
    fetch_url_enabled: Optional[bool] = None
    lineage_isolation_enabled: Optional[bool] = None
    lineage_max_entries: Optional[int] = Field(default=None, ge=10, le=10_000)
    api_strict_validation: Optional[bool] = None


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_security_routes(app: Any, agent: Agent) -> None:
    """Register admin security configuration routes on a FastAPI app.

    Args:
        app: The FastAPI application instance.
        agent: The running Agent whose ``config.security`` will be read/updated.
    """

    router = APIRouter(prefix="/api/v1/admin", tags=["admin", "security"])

    async def _require_admin(request: Request) -> None:
        """Verify the caller belongs to the ``admin`` group."""
        try:
            from vanna.core.user.request_context import RequestContext

            # Build request context from the incoming HTTP request
            cookies = dict(request.cookies)
            headers = dict(request.headers)
            remote_addr = request.client.host if request.client else None

            ctx = RequestContext(
                cookies=cookies,
                headers=headers,
                remote_addr=remote_addr,
            )

            user = await agent.user_resolver.resolve_user(ctx)

            # Check security-settings feature access
            has_access = agent.config.ui_features.can_user_access_feature(
                UiFeature.UI_FEATURE_SECURITY_SETTINGS, user,
            )
            if not has_access:
                raise HTTPException(
                    status_code=403,
                    detail="Only administrators can access security settings.",
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning(f"Admin auth failed: {exc}")
            raise HTTPException(
                status_code=403,
                detail="Could not verify admin access.",
            )

    @router.get("/security", response_model=SecurityConfigResponse)
    async def get_security_config(request: Request) -> SecurityConfigResponse:
        """Return the current security configuration."""
        await _require_admin(request)
        return SecurityConfigResponse(
            config=agent.config.security.model_dump(),
        )

    @router.patch("/security", response_model=SecurityConfigResponse)
    async def update_security_config(
        request: Request,
        update: SecurityConfigUpdate,
    ) -> SecurityConfigResponse:
        """Partially update the security configuration.

        Only fields present in the request body are changed. Omitted fields
        retain their current values.  Changes are in-memory only — a server
        restart restores defaults.
        """
        await _require_admin(request)

        current = agent.config.security
        update_data = update.model_dump(exclude_unset=True)

        if not update_data:
            return SecurityConfigResponse(
                config=current.model_dump(),
                message="No fields to update.",
            )

        # Merge updates into current config
        merged = current.model_dump()
        merged.update(update_data)
        agent.config.security = SecurityConfig(**merged)

        logger.info(f"Security config updated: {update_data}")

        return SecurityConfigResponse(
            config=agent.config.security.model_dump(),
            message=f"Updated {len(update_data)} security setting(s).",
        )

    app.include_router(router)
