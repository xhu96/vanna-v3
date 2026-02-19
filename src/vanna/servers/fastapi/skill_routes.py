"""
FastAPI routes for the Skill Fabric: registry, compilation, promotion, generation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

try:
    from fastapi import APIRouter, HTTPException, Request
except ImportError:
    raise ImportError(
        "FastAPI is required for skill routes. "
        "Install with: pip install 'vanna[fastapi]'"
    )

from vanna.skills.approval import ApprovalError, ApprovalWorkflow
from vanna.skills.compiler import SkillCompiler
from vanna.skills.generator import SkillGenerator
from vanna.skills.models import SkillEnvironment, SkillSpec
from vanna.skills.registry import (
    SkillAuthorizationError,
    SkillRegistry,
    SkillRegistryError,
)


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class RegisterSkillRequest(BaseModel):
    skill_spec: Dict[str, Any] = Field(description="SkillSpec as JSON")


class PromoteSkillRequest(BaseModel):
    target_environment: str = Field(description="Target environment: tested/approved/default")
    eval_results: Optional[Dict[str, Any]] = Field(
        default=None, description="Eval results: {pass_rate, average_score}"
    )


class GenerateSkillRequest(BaseModel):
    description: str = Field(description="Natural language description")
    schema_catalog: Dict[str, Any] = Field(
        default_factory=dict, description="Schema snapshot"
    )
    tenant_glossary: List[Dict[str, Any]] = Field(
        default_factory=list, description="Existing glossary entries"
    )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_skill_routes(
    app: Any,
    registry: SkillRegistry,
    compiler: SkillCompiler,
    approval_workflow: ApprovalWorkflow,
    generator: SkillGenerator,
) -> None:
    """Register Skill Fabric API routes on a FastAPI app."""
    router = APIRouter(prefix="/api/v1/skills", tags=["skills"])

    def _get_user_info(request: Request) -> Dict[str, Any]:
        user_id = request.headers.get("X-User-Id", "anonymous")
        tenant_id = request.headers.get("X-Tenant-Id", "default")
        groups = request.headers.get("X-User-Groups", "").split(",")
        groups = [g.strip() for g in groups if g.strip()]
        return {"user_id": user_id, "tenant_id": tenant_id, "groups": groups}

    @router.get("")
    async def list_skills(request: Request) -> Dict[str, Any]:
        info = _get_user_info(request)
        env_param = request.query_params.get("environment")
        env = SkillEnvironment(env_param) if env_param else None
        skills = await registry.list_skills(
            tenant_id=info["tenant_id"], environment=env
        )
        return {
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

    @router.get("/{skill_id}")
    async def get_skill(skill_id: str) -> Dict[str, Any]:
        entry = await registry.get_skill(skill_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="Skill not found")
        return {"skill": entry.model_dump(mode="json")}

    @router.post("")
    async def register_skill(
        body: RegisterSkillRequest, request: Request
    ) -> Dict[str, Any]:
        info = _get_user_info(request)
        try:
            spec = SkillSpec(**body.skill_spec)
            entry = await registry.register_skill(
                spec, actor=info["user_id"], tenant_id=info["tenant_id"]
            )
            return {
                "skill_id": entry.skill_id,
                "status": "draft",
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post("/{skill_id}/compile")
    async def compile_skill(skill_id: str) -> Dict[str, Any]:
        try:
            result = await approval_workflow.compile_skill(skill_id)
            return {
                "success": result.success,
                "errors": result.errors,
                "warnings": result.warnings,
            }
        except ApprovalError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @router.post("/{skill_id}/promote")
    async def promote_skill(
        skill_id: str, body: PromoteSkillRequest, request: Request
    ) -> Dict[str, Any]:
        info = _get_user_info(request)
        try:
            target = SkillEnvironment(body.target_environment)
            entry = await approval_workflow.promote(
                skill_id,
                target,
                actor=info["user_id"],
                actor_groups=info["groups"],
                eval_results=body.eval_results,
            )
            return {
                "skill_id": entry.skill_id,
                "environment": entry.environment.value,
            }
        except ApprovalError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except SkillAuthorizationError as e:
            raise HTTPException(status_code=403, detail=str(e))
        except SkillRegistryError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post("/{skill_id}/rollback")
    async def rollback_skill(
        skill_id: str, body: PromoteSkillRequest, request: Request
    ) -> Dict[str, Any]:
        info = _get_user_info(request)
        try:
            target = SkillEnvironment(body.target_environment)
            entry = await registry.rollback_skill(
                skill_id,
                target,
                actor=info["user_id"],
                actor_groups=info["groups"],
            )
            return {
                "skill_id": entry.skill_id,
                "environment": entry.environment.value,
            }
        except SkillAuthorizationError as e:
            raise HTTPException(status_code=403, detail=str(e))
        except SkillRegistryError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.put("/{skill_id}/enable")
    async def enable_skill(skill_id: str, request: Request) -> Dict[str, Any]:
        info = _get_user_info(request)
        try:
            entry = await registry.enable_skill(
                skill_id, actor=info["user_id"]
            )
            return {"skill_id": entry.skill_id, "enabled": True}
        except SkillRegistryError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @router.put("/{skill_id}/disable")
    async def disable_skill(skill_id: str, request: Request) -> Dict[str, Any]:
        info = _get_user_info(request)
        try:
            entry = await registry.disable_skill(
                skill_id, actor=info["user_id"]
            )
            return {"skill_id": entry.skill_id, "enabled": False}
        except SkillRegistryError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @router.delete("/{skill_id}")
    async def delete_skill(skill_id: str, request: Request) -> Dict[str, Any]:
        info = _get_user_info(request)
        try:
            deleted = await registry.delete_skill(
                skill_id,
                actor=info["user_id"],
                actor_groups=info["groups"],
            )
            return {"deleted": deleted}
        except SkillAuthorizationError as e:
            raise HTTPException(status_code=403, detail=str(e))

    @router.get("/{skill_id}/audit")
    async def get_audit_log(skill_id: str) -> Dict[str, Any]:
        log = await registry.get_audit_log(skill_id)
        return {
            "audit_log": [e.model_dump(mode="json") for e in log]
        }

    @router.post("/generate")
    async def generate_skill(
        body: GenerateSkillRequest, request: Request
    ) -> Dict[str, Any]:
        info = _get_user_info(request)
        output = await generator.generate(
            schema_catalog=body.schema_catalog,
            tenant_glossary=body.tenant_glossary,
            description=body.description,
            tenant_id=info["tenant_id"],
            author=info["user_id"],
        )
        return {
            "skill_spec": output.skill_spec.model_dump(mode="json"),
            "eval_dataset": [e.model_dump() for e in output.eval_dataset],
            "risk_checklist": [
                {"category": r.category, "description": r.description, "severity": r.severity}
                for r in output.risk_checklist
            ],
            "compilation": {
                "success": output.compilation_result.success if output.compilation_result else None,
                "errors": output.compilation_result.errors if output.compilation_result else [],
            },
            "warnings": output.warnings,
        }

    app.include_router(router)
