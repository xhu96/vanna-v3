"""
FastAPI routes for admin-only configuration management.

Provides endpoints for audit logs, tool RBAC, connections, observability,
privacy settings — all scoped to admin role.
"""

from __future__ import annotations

from app.fastapi.deps import context_from_request
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

try:
    from fastapi import APIRouter, HTTPException, Request
except ImportError:
    raise ImportError(
        "FastAPI is required. Install with: pip install 'vanna[fastapi]'"
    )

from vanna.core import Agent
from vanna.config import UiFeature

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ToolAccessUpdate(BaseModel):
    tool_name: str
    groups: List[str]


class ConnectionsUpdate(BaseModel):
    """Partial update for connection settings."""
    llm_api_key: Optional[str] = None
    datahub_endpoint: Optional[str] = None
    warehouse_dsn: Optional[str] = None


class ObservabilityUpdate(BaseModel):
    strict_checking: Optional[bool] = None
    gx_token: Optional[str] = None


class PrivacyUpdate(BaseModel):
    enabled_entities: Optional[List[str]] = None
    custom_regex_patterns: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_admin_routes(app: Any, agent: Agent) -> None:
    """Register admin configuration routes."""
    router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
    user_resolver = getattr(agent, "user_resolver", None)

    async def _require_admin(request: Request) -> None:
        if user_resolver is None:
            return  # No auth configured
        try:

            request_context = context_from_request(request)
            user = await user_resolver.resolve_user(request_context)
            can_access = agent.config.ui_features.can_user_access_feature(
                UiFeature.UI_FEATURE_SECURITY_SETTINGS, user
            )
            if not can_access:
                raise HTTPException(status_code=403, detail="Admin access required")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("Admin auth check failed: %s", e)
            raise HTTPException(status_code=403, detail="Admin access required")

    # -------------------------------------------------------------------
    # Audit logs
    # -------------------------------------------------------------------

    @router.get("/audit")
    async def get_audit_logs(
        request: Request,
        limit: int = 50,
        event_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        await _require_admin(request)
        audit_logger = getattr(agent, "_audit_logger", None)
        if audit_logger is None:
            return {"events": [], "message": "Audit logging not configured"}

        events = []
        if hasattr(audit_logger, "get_recent_events"):
            events = await audit_logger.get_recent_events(
                limit=limit, event_type=event_type
            )
        return {"events": events, "total": len(events)}

    # -------------------------------------------------------------------
    # Tool RBAC
    # -------------------------------------------------------------------

    @router.get("/tools")
    async def get_tool_access(request: Request) -> Dict[str, Any]:
        await _require_admin(request)
        tools = {}
        registry = getattr(agent, "tool_registry", None)
        if registry is not None and hasattr(registry, "_tools"):
            for name, tool in registry._tools.items():
                group_access = getattr(tool, "group_access", [])
                tools[name] = {
                    "name": name,
                    "description": getattr(tool, "description", ""),
                    "groups": list(group_access) if group_access else [],
                    "enabled": getattr(tool, "enabled", True),
                }
        return {"tools": tools}

    @router.patch("/tools")
    async def update_tool_access(
        body: ToolAccessUpdate, request: Request
    ) -> Dict[str, Any]:
        await _require_admin(request)
        registry = getattr(agent, "tool_registry", None)
        if registry is None or not hasattr(registry, "_tools"):
            raise HTTPException(status_code=501, detail="Tool registry not available")

        tool = registry._tools.get(body.tool_name)
        if tool is None:
            raise HTTPException(status_code=404, detail=f"Tool '{body.tool_name}' not found")

        tool.group_access = body.groups
        return {
            "message": f"Updated access for '{body.tool_name}'",
            "tool": {
                "name": body.tool_name,
                "groups": body.groups,
            },
        }

    # -------------------------------------------------------------------
    # Connections
    # -------------------------------------------------------------------

    @router.get("/connections")
    async def get_connections(request: Request) -> Dict[str, Any]:
        await _require_admin(request)
        conn_config = getattr(agent, "_connection_config", {})
        return {
            "connections": {
                "llm_api_key": "***" if conn_config.get("llm_api_key") else "",
                "datahub_endpoint": conn_config.get("datahub_endpoint", ""),
                "warehouse_dsn": "***" if conn_config.get("warehouse_dsn") else "",
            }
        }

    @router.patch("/connections")
    async def update_connections(
        body: ConnectionsUpdate, request: Request
    ) -> Dict[str, Any]:
        await _require_admin(request)
        conn_config = getattr(agent, "_connection_config", None)
        if conn_config is None:
            agent._connection_config = {}
            conn_config = agent._connection_config

        updates = body.model_dump(exclude_none=True)
        conn_config.update(updates)
        return {"message": "Connection settings updated", "updated_fields": list(updates.keys())}

    # -------------------------------------------------------------------
    # Observability / Quality Gate
    # -------------------------------------------------------------------

    @router.get("/observability")
    async def get_observability(request: Request) -> Dict[str, Any]:
        await _require_admin(request)
        obs_config = getattr(agent, "_observability_config", {
            "strict_checking": True,
            "gx_token": "",
        })
        return {
            "config": {
                "strict_checking": obs_config.get("strict_checking", True),
                "gx_token": "***" if obs_config.get("gx_token") else "",
            }
        }

    @router.patch("/observability")
    async def update_observability(
        body: ObservabilityUpdate, request: Request
    ) -> Dict[str, Any]:
        await _require_admin(request)
        obs_config = getattr(agent, "_observability_config", None)
        if obs_config is None:
            agent._observability_config = {"strict_checking": True, "gx_token": ""}
            obs_config = agent._observability_config

        updates = body.model_dump(exclude_none=True)
        obs_config.update(updates)
        return {"message": "Observability settings updated", "updated_fields": list(updates.keys())}

    # -------------------------------------------------------------------
    # Privacy / PII Redaction
    # -------------------------------------------------------------------

    @router.get("/privacy")
    async def get_privacy(request: Request) -> Dict[str, Any]:
        await _require_admin(request)
        privacy_config = getattr(agent, "_privacy_config", {
            "enabled_entities": ["CREDIT_CARD", "EMAIL_ADDRESS", "US_SSN", "PERSON"],
            "custom_regex_patterns": [],
        })
        return {"config": privacy_config}

    @router.patch("/privacy")
    async def update_privacy(
        body: PrivacyUpdate, request: Request
    ) -> Dict[str, Any]:
        await _require_admin(request)
        privacy_config = getattr(agent, "_privacy_config", None)
        if privacy_config is None:
            agent._privacy_config = {
                "enabled_entities": ["CREDIT_CARD", "EMAIL_ADDRESS", "US_SSN", "PERSON"],
                "custom_regex_patterns": [],
            }
            privacy_config = agent._privacy_config

        updates = body.model_dump(exclude_none=True)
        privacy_config.update(updates)
        return {"message": "Privacy settings updated", "config": privacy_config}

    # -------------------------------------------------------------------
    # Schema status (proxy to existing route)
    # -------------------------------------------------------------------

    @router.get("/schema/status")
    async def admin_schema_status(request: Request) -> Dict[str, Any]:
        await _require_admin(request)
        schema_cap = getattr(agent, "schema_capability", None)
        if schema_cap is None:
            return {"status": "not_configured", "tables": []}
        try:
            tables = await schema_cap.get_tables() if hasattr(schema_cap, "get_tables") else []
            return {"status": "ok", "table_count": len(tables), "tables": tables[:50]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    app.include_router(router)
