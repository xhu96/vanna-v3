"""
Flask routes for personalization: profile CRUD, glossary, consent, export/delete.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

try:
    from flask import Blueprint, Flask, jsonify, request
except ImportError:
    raise ImportError(
        "Flask is required for personalization routes. "
        "Install with: pip install 'vanna[flask]'"
    )

from vanna.core.user.request_context import RequestContext
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

logger = logging.getLogger(__name__)


def _run_async(coro):  # type: ignore[no-untyped-def]
    """Run an async coroutine synchronously (Flask helper)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def register_personalization_routes(
    app: Flask,
    profile_service: ProfileService,
    glossary_service: GlossaryService,
    consent_manager: ConsentManager,
    *,
    user_resolver: Any = None,
) -> None:
    """Register personalization API routes on a Flask app."""
    if user_resolver is None:
        logger.warning(
            "personalization_routes: user_resolver is not configured; user identity "
            "will be read from unverified X-User-Id/X-Tenant-Id/X-User-Groups headers. "
            "Provide a UserResolver or deploy behind a trusted auth proxy."
        )

    bp = Blueprint("personalization", __name__, url_prefix="/api/v1")

    def _get_user_info() -> Dict[str, Any]:
        """Extract verified user identity from the request."""
        if user_resolver is not None:
            request_context = RequestContext(
                cookies=dict(request.cookies),
                headers=dict(request.headers),
                remote_addr=request.remote_addr,
                query_params=dict(request.args),
                metadata={},
            )
            user = _run_async(user_resolver.resolve_user(request_context))
            return {
                "user_id": user.id,
                "tenant_id": user.tenant_id or "default",
                "groups": user.group_memberships,
            }
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

    @bp.route("/profile", methods=["GET"])
    def get_profile():  # type: ignore[no-untyped-def]
        info = _get_user_info()
        try:
            profile = _run_async(
                profile_service.get_user_profile(
                    info["user_id"],
                    info["tenant_id"],
                    requesting_user_id=info["user_id"],
                    requesting_user_groups=info["groups"],
                )
            )
            if profile is None:
                return jsonify({"profile": None})
            return jsonify({"profile": profile.model_dump(mode="json")})
        except AuthorizationError as e:
            return jsonify({"error": str(e)}), 403

    @bp.route("/profile", methods=["PUT"])
    def update_profile():  # type: ignore[no-untyped-def]
        info = _get_user_info()
        body = request.get_json(force=True)
        profile = UserProfile(
            user_id=info["user_id"],
            tenant_id=info["tenant_id"],
            **{
                k: v
                for k, v in body.items()
                if k
                in {
                    "locale",
                    "currency",
                    "fiscal_year_start_month",
                    "date_format",
                    "number_format",
                    "department_tags",
                    "role_tags",
                    "preferred_chart_type",
                    "preferred_table_style",
                }
            },
        )
        try:
            result = _run_async(
                profile_service.upsert_user_profile(
                    profile,
                    requesting_user_id=info["user_id"],
                    requesting_user_groups=info["groups"],
                )
            )
            return jsonify({"profile": result.model_dump(mode="json")})
        except AuthorizationError as e:
            return jsonify({"error": str(e)}), 403

    @bp.route("/profile", methods=["DELETE"])
    def delete_profile():  # type: ignore[no-untyped-def]
        info = _get_user_info()
        try:
            deleted = _run_async(
                profile_service.delete_user_profile(
                    info["user_id"],
                    info["tenant_id"],
                    requesting_user_id=info["user_id"],
                    requesting_user_groups=info["groups"],
                )
            )
            return jsonify({"deleted": deleted})
        except AuthorizationError as e:
            return jsonify({"error": str(e)}), 403

    @bp.route("/profile/export", methods=["GET"])
    def export_profile():  # type: ignore[no-untyped-def]
        info = _get_user_info()
        try:
            data = _run_async(
                profile_service.export_user_profile(
                    info["user_id"],
                    info["tenant_id"],
                    requesting_user_id=info["user_id"],
                    requesting_user_groups=info["groups"],
                )
            )
            return jsonify({"export": data})
        except AuthorizationError as e:
            return jsonify({"error": str(e)}), 403

    # --- Tenant profile endpoints (admin) ---

    @bp.route("/tenant/profile", methods=["PUT"])
    def update_tenant_profile():  # type: ignore[no-untyped-def]
        info = _get_user_info()
        body = request.get_json(force=True)
        profile = TenantProfile(tenant_id=info["tenant_id"], **body)
        try:
            result = _run_async(
                profile_service.upsert_tenant_profile(
                    profile, requesting_user_groups=info["groups"]
                )
            )
            return jsonify({"profile": result.model_dump(mode="json")})
        except AuthorizationError as e:
            return jsonify({"error": str(e)}), 403

    # --- Glossary endpoints ---

    @bp.route("/glossary", methods=["GET"])
    def list_glossary():  # type: ignore[no-untyped-def]
        info = _get_user_info()
        entries = _run_async(glossary_service.list_entries(info["tenant_id"]))
        return jsonify(
            {"entries": [e.model_dump(mode="json") for e in entries]}
        )

    @bp.route("/glossary", methods=["POST"])
    def create_glossary_entry():  # type: ignore[no-untyped-def]
        info = _get_user_info()
        body = request.get_json(force=True)
        entry = GlossaryEntry(tenant_id=info["tenant_id"], **body)
        result = _run_async(
            glossary_service.create_entry(
                entry,
                requesting_user_id=info["user_id"],
                requesting_user_groups=info["groups"],
            )
        )
        return jsonify({"entry": result.model_dump(mode="json")})

    @bp.route("/glossary/<entry_id>", methods=["PUT"])
    def update_glossary_entry(entry_id: str):  # type: ignore[no-untyped-def]
        info = _get_user_info()
        existing = _run_async(glossary_service.get_entry(entry_id))
        if existing is None:
            return jsonify({"error": "Entry not found"}), 404
        body = request.get_json(force=True)
        for k, v in body.items():
            if v is not None:
                setattr(existing, k, v)
        try:
            result = _run_async(
                glossary_service.update_entry(
                    existing,
                    requesting_user_id=info["user_id"],
                    requesting_user_groups=info["groups"],
                )
            )
            return jsonify({"entry": result.model_dump(mode="json")})
        except AuthorizationError as e:
            return jsonify({"error": str(e)}), 403

    @bp.route("/glossary/<entry_id>", methods=["DELETE"])
    def delete_glossary_entry(entry_id: str):  # type: ignore[no-untyped-def]
        info = _get_user_info()
        try:
            deleted = _run_async(
                glossary_service.delete_entry(
                    entry_id,
                    requesting_user_id=info["user_id"],
                    requesting_user_groups=info["groups"],
                )
            )
            return jsonify({"deleted": deleted})
        except AuthorizationError as e:
            return jsonify({"error": str(e)}), 403

    # --- Consent endpoints ---

    @bp.route("/consent/enable", methods=["POST"])
    def enable_consent():  # type: ignore[no-untyped-def]
        info = _get_user_info()
        profile = _run_async(
            consent_manager.enable_personalization(
                info["user_id"], info["tenant_id"]
            )
        )
        return jsonify(
            {"enabled": True, "profile": profile.model_dump(mode="json")}
        )

    @bp.route("/consent/disable", methods=["POST"])
    def disable_consent():  # type: ignore[no-untyped-def]
        info = _get_user_info()
        profile = _run_async(
            consent_manager.disable_personalization(
                info["user_id"], info["tenant_id"]
            )
        )
        return jsonify(
            {"enabled": False, "profile": profile.model_dump(mode="json")}
        )

    app.register_blueprint(bp)
