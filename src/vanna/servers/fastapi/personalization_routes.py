"""
FastAPI routes for personalization: profile CRUD, glossary, consent, export/delete.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

try:
    from fastapi import APIRouter, Depends, HTTPException, Request
except ImportError:
    raise ImportError(
        "FastAPI is required for personalization routes. "
        "Install with: pip install 'vanna[fastapi]'"
    )

from vanna.personalization.models import (
    GlossaryEntry,
    TenantProfile,
    UserProfile,
)
from vanna.personalization.services import (
    AuthorizationError,
    ConsentManager,
    GlossaryService,
    ProfileService,
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class UpdateProfileRequest(BaseModel):
    locale: Optional[str] = None
    currency: Optional[str] = None
    fiscal_year_start_month: Optional[int] = None
    date_format: Optional[str] = None
    number_format: Optional[str] = None
    department_tags: List[str] = Field(default_factory=list)
    role_tags: List[str] = Field(default_factory=list)
    preferred_chart_type: Optional[str] = None
    preferred_table_style: Optional[str] = None


class UpdateTenantProfileRequest(BaseModel):
    default_locale: Optional[str] = None
    default_currency: Optional[str] = None
    fiscal_year_start_month: Optional[int] = None
    default_date_format: Optional[str] = None
    default_number_format: Optional[str] = None
    personalization_enabled: bool = False
    session_memory_retention_days: int = 7


class CreateGlossaryRequest(BaseModel):
    term: str
    synonyms: List[str] = Field(default_factory=list)
    definition: str
    category: Optional[str] = None


class UpdateGlossaryRequest(BaseModel):
    term: Optional[str] = None
    synonyms: Optional[List[str]] = None
    definition: Optional[str] = None
    category: Optional[str] = None


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_personalization_routes(
    app: Any,
    profile_service: ProfileService,
    glossary_service: GlossaryService,
    consent_manager: ConsentManager,
    *,
    user_resolver: Any = None,
) -> None:
    """Register personalization API routes on a FastAPI app.

    Args:
        app: FastAPI application
        profile_service: Instantiated ProfileService
        glossary_service: Instantiated GlossaryService
        consent_manager: Instantiated ConsentManager
        user_resolver: Optional callable to resolve user from request
    """
    router = APIRouter(prefix="/api/v1", tags=["personalization"])

    def _get_user_info(request: Request) -> Dict[str, Any]:
        """Extract user info from request (simplified; real impl uses UserResolver)."""
        user_id = request.headers.get("X-User-Id", "anonymous")
        tenant_id = request.headers.get("X-Tenant-Id", "default")
        groups = request.headers.get("X-User-Groups", "").split(",")
        groups = [g.strip() for g in groups if g.strip()]
        return {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "groups": groups,
        }

    # --- Profile endpoints ---

    @router.get("/profile")
    async def get_profile(request: Request) -> Dict[str, Any]:
        info = _get_user_info(request)
        try:
            profile = await profile_service.get_user_profile(
                info["user_id"],
                info["tenant_id"],
                requesting_user_id=info["user_id"],
                requesting_user_groups=info["groups"],
            )
            if profile is None:
                return {"profile": None}
            return {"profile": profile.model_dump(mode="json")}
        except AuthorizationError as e:
            raise HTTPException(status_code=403, detail=str(e))

    @router.put("/profile")
    async def update_profile(
        body: UpdateProfileRequest, request: Request
    ) -> Dict[str, Any]:
        info = _get_user_info(request)
        profile = UserProfile(
            user_id=info["user_id"],
            tenant_id=info["tenant_id"],
            **body.model_dump(),
        )
        try:
            result = await profile_service.upsert_user_profile(
                profile,
                requesting_user_id=info["user_id"],
                requesting_user_groups=info["groups"],
            )
            return {"profile": result.model_dump(mode="json")}
        except AuthorizationError as e:
            raise HTTPException(status_code=403, detail=str(e))

    @router.delete("/profile")
    async def delete_profile(request: Request) -> Dict[str, Any]:
        info = _get_user_info(request)
        try:
            deleted = await profile_service.delete_user_profile(
                info["user_id"],
                info["tenant_id"],
                requesting_user_id=info["user_id"],
                requesting_user_groups=info["groups"],
            )
            return {"deleted": deleted}
        except AuthorizationError as e:
            raise HTTPException(status_code=403, detail=str(e))

    @router.get("/profile/export")
    async def export_profile(request: Request) -> Dict[str, Any]:
        info = _get_user_info(request)
        try:
            data = await profile_service.export_user_profile(
                info["user_id"],
                info["tenant_id"],
                requesting_user_id=info["user_id"],
                requesting_user_groups=info["groups"],
            )
            return {"export": data}
        except AuthorizationError as e:
            raise HTTPException(status_code=403, detail=str(e))

    # --- Tenant profile endpoints (admin) ---

    @router.put("/tenant/profile")
    async def update_tenant_profile(
        body: UpdateTenantProfileRequest, request: Request
    ) -> Dict[str, Any]:
        info = _get_user_info(request)
        profile = TenantProfile(
            tenant_id=info["tenant_id"], **body.model_dump()
        )
        try:
            result = await profile_service.upsert_tenant_profile(
                profile, requesting_user_groups=info["groups"]
            )
            return {"profile": result.model_dump(mode="json")}
        except AuthorizationError as e:
            raise HTTPException(status_code=403, detail=str(e))

    # --- Glossary endpoints ---

    @router.get("/glossary")
    async def list_glossary(request: Request) -> Dict[str, Any]:
        info = _get_user_info(request)
        entries = await glossary_service.list_entries(info["tenant_id"])
        return {
            "entries": [e.model_dump(mode="json") for e in entries]
        }

    @router.post("/glossary")
    async def create_glossary_entry(
        body: CreateGlossaryRequest, request: Request
    ) -> Dict[str, Any]:
        info = _get_user_info(request)
        entry = GlossaryEntry(
            tenant_id=info["tenant_id"],
            **body.model_dump(),
        )
        result = await glossary_service.create_entry(
            entry,
            requesting_user_id=info["user_id"],
            requesting_user_groups=info["groups"],
        )
        return {"entry": result.model_dump(mode="json")}

    @router.put("/glossary/{entry_id}")
    async def update_glossary_entry(
        entry_id: str, body: UpdateGlossaryRequest, request: Request
    ) -> Dict[str, Any]:
        info = _get_user_info(request)
        existing = await glossary_service.get_entry(entry_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Entry not found")
        update_data = body.model_dump(exclude_none=True)
        for k, v in update_data.items():
            setattr(existing, k, v)
        try:
            result = await glossary_service.update_entry(
                existing,
                requesting_user_id=info["user_id"],
                requesting_user_groups=info["groups"],
            )
            return {"entry": result.model_dump(mode="json")}
        except AuthorizationError as e:
            raise HTTPException(status_code=403, detail=str(e))

    @router.delete("/glossary/{entry_id}")
    async def delete_glossary_entry(
        entry_id: str, request: Request
    ) -> Dict[str, Any]:
        info = _get_user_info(request)
        try:
            deleted = await glossary_service.delete_entry(
                entry_id,
                requesting_user_id=info["user_id"],
                requesting_user_groups=info["groups"],
            )
            return {"deleted": deleted}
        except AuthorizationError as e:
            raise HTTPException(status_code=403, detail=str(e))

    # --- Consent endpoints ---

    @router.post("/consent/enable")
    async def enable_consent(request: Request) -> Dict[str, Any]:
        info = _get_user_info(request)
        profile = await consent_manager.enable_personalization(
            info["user_id"], info["tenant_id"]
        )
        return {"enabled": True, "profile": profile.model_dump(mode="json")}

    @router.post("/consent/disable")
    async def disable_consent(request: Request) -> Dict[str, Any]:
        info = _get_user_info(request)
        profile = await consent_manager.disable_personalization(
            info["user_id"], info["tenant_id"]
        )
        return {"enabled": False, "profile": profile.model_dump(mode="json")}

    app.include_router(router)
