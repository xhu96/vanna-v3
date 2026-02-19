"""
Approval Workflow — gate-based skill promotion with RBAC and eval checks.

Manages the state machine: draft → tested → approved → default
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .compiler import SkillCompiler
from .models import CompilationResult, SkillEnvironment, SkillRegistryEntry
from .registry import SkillRegistry, SkillAuthorizationError, SkillRegistryError


class ApprovalError(Exception):
    """Raised when a promotion fails validation."""


class ApprovalWorkflow:
    """Gate-based skill promotion workflow.

    Promotion requirements:
      1. Compiler must succeed
      2. Eval suite must pass thresholds (if skill_eval_required)
      3. Actor must have appropriate role
    """

    def __init__(
        self,
        registry: SkillRegistry,
        compiler: SkillCompiler,
        *,
        eval_required: bool = True,
        publish_roles: Optional[List[str]] = None,
    ) -> None:
        self._registry = registry
        self._compiler = compiler
        self._eval_required = eval_required
        self._publish_roles = publish_roles or ["admin"]

    async def promote(
        self,
        skill_id: str,
        target_env: SkillEnvironment,
        *,
        actor: str,
        actor_groups: Optional[List[str]] = None,
        eval_results: Optional[Dict[str, Any]] = None,
    ) -> SkillRegistryEntry:
        """Promote a skill with validation gates.

        Args:
            skill_id: Skill to promote
            target_env: Target environment
            actor: Who is performing the action
            actor_groups: Actor's role memberships
            eval_results: Eval suite results (pass_rate, average_score)

        Returns:
            Updated SkillRegistryEntry

        Raises:
            ApprovalError: If validation gates fail
            SkillAuthorizationError: If actor lacks required role
            SkillRegistryError: If transition is invalid
        """
        entry = await self._registry.get_skill(skill_id)
        if entry is None:
            raise ApprovalError(f"Skill {skill_id} not found")

        # Gate 1: Compiler must succeed
        compilation = self._compiler.compile(entry.skill_spec)
        if not compilation.success:
            raise ApprovalError(
                f"Compilation failed: {'; '.join(compilation.errors)}"
            )

        # Store compiled artifact
        entry.compiled_skill = compilation.compiled_skill
        from .stores import SkillRegistryStore  # avoid circular
        # We update via registry which handles audit

        # Gate 2: Eval suite must pass (for tested → approved and beyond)
        if self._eval_required and target_env in (
            SkillEnvironment.APPROVED,
            SkillEnvironment.DEFAULT,
        ):
            if eval_results is None:
                raise ApprovalError(
                    "Eval results required for promotion to "
                    f"{target_env.value}. Run eval suite first."
                )
            pass_rate = eval_results.get("pass_rate", 0.0)
            avg_score = eval_results.get("average_score", 0.0)
            thresholds = entry.skill_spec.eval_suite

            if pass_rate < thresholds.pass_rate_threshold:
                raise ApprovalError(
                    f"Eval pass rate {pass_rate:.2%} below threshold "
                    f"{thresholds.pass_rate_threshold:.2%}"
                )
            if avg_score < thresholds.min_score:
                raise ApprovalError(
                    f"Eval average score {avg_score:.2f} below threshold "
                    f"{thresholds.min_score:.2f}"
                )

        # Gate 3: Promote via registry (handles RBAC + audit)
        return await self._registry.promote_skill(
            skill_id,
            target_env,
            actor=actor,
            actor_groups=actor_groups,
        )

    async def compile_skill(
        self, skill_id: str
    ) -> CompilationResult:
        """Compile a skill without promoting it. Useful for validation."""
        entry = await self._registry.get_skill(skill_id)
        if entry is None:
            raise ApprovalError(f"Skill {skill_id} not found")
        result = self._compiler.compile(entry.skill_spec)
        if result.success and result.compiled_skill is not None:
            entry.compiled_skill = result.compiled_skill
            # Update in store to persist compiled artifact
        return result
