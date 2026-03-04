"""
Flask routes for the Skill Fabric: registry, compilation, promotion, generation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

try:
    from flask import Blueprint, Flask, jsonify, request
except ImportError:
    raise ImportError(
        "Flask is required for skill routes. "
        "Install with: pip install 'vanna[flask]'"
    )

from vanna.core.user.request_context import RequestContext
from vanna.skills.approval import ApprovalError, ApprovalWorkflow
from vanna.skills.compiler import SkillCompiler
from vanna.skills.generator import SkillGenerator
from vanna.skills.models import SkillEnvironment, SkillSpec
from vanna.skills.registry import (
    SkillAuthorizationError,
    SkillRegistry,
    SkillRegistryError,
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


def register_skill_routes(
    app: Flask,
    registry: SkillRegistry,
    compiler: SkillCompiler,
    approval_workflow: ApprovalWorkflow,
    generator: SkillGenerator,
    *,
    user_resolver: Any = None,
) -> None:
    """Register Skill Fabric API routes on a Flask app."""
    if user_resolver is None:
        logger.warning(
            "skill_routes: user_resolver is not configured; user identity "
            "will be read from unverified X-User-Id/X-Tenant-Id/X-User-Groups headers. "
            "Provide a UserResolver or deploy behind a trusted auth proxy."
        )

    bp = Blueprint("skills", __name__, url_prefix="/api/v1/skills")

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
        return {"user_id": user_id, "tenant_id": tenant_id, "groups": groups}

    @bp.route("", methods=["GET"])
    def list_skills():  # type: ignore[no-untyped-def]
        info = _get_user_info()
        env_param = request.args.get("environment")
        env = SkillEnvironment(env_param) if env_param else None
        skills = _run_async(
            registry.list_skills(tenant_id=info["tenant_id"], environment=env)
        )
        return jsonify(
            {
                "skills": [
                    {
                        "skill_id": s.skill_id,
                        "name": s.skill_spec.name,
                        "version": s.skill_spec.version,
                        "environment": s.environment.value,
                        "enabled": s.enabled,
                    }
                    for s in skills
                ]
            }
        )

    @bp.route("/<skill_id>", methods=["GET"])
    def get_skill(skill_id: str):  # type: ignore[no-untyped-def]
        entry = _run_async(registry.get_skill(skill_id))
        if entry is None:
            return jsonify({"error": "Skill not found"}), 404
        return jsonify({"skill": entry.model_dump(mode="json")})

    @bp.route("", methods=["POST"])
    def register_skill():  # type: ignore[no-untyped-def]
        info = _get_user_info()
        body = request.get_json(force=True)
        try:
            spec = SkillSpec(**body.get("skill_spec", {}))
            entry = _run_async(
                registry.register_skill(
                    spec, actor=info["user_id"], tenant_id=info["tenant_id"]
                )
            )
            return jsonify({"skill_id": entry.skill_id, "status": "draft"})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @bp.route("/<skill_id>/compile", methods=["POST"])
    def compile_skill(skill_id: str):  # type: ignore[no-untyped-def]
        try:
            result = _run_async(approval_workflow.compile_skill(skill_id))
            return jsonify(
                {
                    "success": result.success,
                    "errors": result.errors,
                    "warnings": result.warnings,
                }
            )
        except ApprovalError as e:
            return jsonify({"error": str(e)}), 404

    @bp.route("/<skill_id>/promote", methods=["POST"])
    def promote_skill(skill_id: str):  # type: ignore[no-untyped-def]
        info = _get_user_info()
        body = request.get_json(force=True)
        try:
            target = SkillEnvironment(body["target_environment"])
            entry = _run_async(
                approval_workflow.promote(
                    skill_id,
                    target,
                    actor=info["user_id"],
                    actor_groups=info["groups"],
                    eval_results=body.get("eval_results"),
                )
            )
            return jsonify(
                {
                    "skill_id": entry.skill_id,
                    "environment": entry.environment.value,
                }
            )
        except ApprovalError as e:
            return jsonify({"error": str(e)}), 400
        except SkillAuthorizationError as e:
            return jsonify({"error": str(e)}), 403
        except SkillRegistryError as e:
            return jsonify({"error": str(e)}), 400

    @bp.route("/<skill_id>/rollback", methods=["POST"])
    def rollback_skill(skill_id: str):  # type: ignore[no-untyped-def]
        info = _get_user_info()
        body = request.get_json(force=True)
        try:
            target = SkillEnvironment(body["target_environment"])
            entry = _run_async(
                registry.rollback_skill(
                    skill_id,
                    target,
                    actor=info["user_id"],
                    actor_groups=info["groups"],
                )
            )
            return jsonify(
                {
                    "skill_id": entry.skill_id,
                    "environment": entry.environment.value,
                }
            )
        except SkillAuthorizationError as e:
            return jsonify({"error": str(e)}), 403
        except SkillRegistryError as e:
            return jsonify({"error": str(e)}), 400

    @bp.route("/<skill_id>/enable", methods=["PUT"])
    def enable_skill(skill_id: str):  # type: ignore[no-untyped-def]
        info = _get_user_info()
        try:
            entry = _run_async(
                registry.enable_skill(skill_id, actor=info["user_id"])
            )
            return jsonify({"skill_id": entry.skill_id, "enabled": True})
        except SkillRegistryError as e:
            return jsonify({"error": str(e)}), 404

    @bp.route("/<skill_id>/disable", methods=["PUT"])
    def disable_skill(skill_id: str):  # type: ignore[no-untyped-def]
        info = _get_user_info()
        try:
            entry = _run_async(
                registry.disable_skill(skill_id, actor=info["user_id"])
            )
            return jsonify({"skill_id": entry.skill_id, "enabled": False})
        except SkillRegistryError as e:
            return jsonify({"error": str(e)}), 404

    @bp.route("/<skill_id>", methods=["DELETE"])
    def delete_skill(skill_id: str):  # type: ignore[no-untyped-def]
        info = _get_user_info()
        try:
            deleted = _run_async(
                registry.delete_skill(
                    skill_id,
                    actor=info["user_id"],
                    actor_groups=info["groups"],
                )
            )
            return jsonify({"deleted": deleted})
        except SkillAuthorizationError as e:
            return jsonify({"error": str(e)}), 403

    @bp.route("/<skill_id>/audit", methods=["GET"])
    def get_audit_log(skill_id: str):  # type: ignore[no-untyped-def]
        log = _run_async(registry.get_audit_log(skill_id))
        return jsonify(
            {"audit_log": [e.model_dump(mode="json") for e in log]}
        )

    @bp.route("/generate", methods=["POST"])
    def generate_skill():  # type: ignore[no-untyped-def]
        info = _get_user_info()
        body = request.get_json(force=True)
        output = _run_async(
            generator.generate(
                schema_catalog=body.get("schema_catalog", {}),
                tenant_glossary=body.get("tenant_glossary", []),
                description=body["description"],
                tenant_id=info["tenant_id"],
                author=info["user_id"],
            )
        )
        return jsonify(
            {
                "skill_spec": output.skill_spec.model_dump(mode="json"),
                "eval_dataset": [e.model_dump() for e in output.eval_dataset],
                "risk_checklist": [
                    {
                        "category": r.category,
                        "description": r.description,
                        "severity": r.severity,
                    }
                    for r in output.risk_checklist
                ],
                "compilation": {
                    "success": (
                        output.compilation_result.success
                        if output.compilation_result
                        else None
                    ),
                    "errors": (
                        output.compilation_result.errors
                        if output.compilation_result
                        else []
                    ),
                },
                "warnings": output.warnings,
            }
        )

    app.register_blueprint(bp)
