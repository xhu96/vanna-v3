"""Skill context enrichers.

This module provides ToolContextEnricher implementations that:
- select applicable skills for the current user message
- optionally generate/register a draft skill on-the-fly (ad-hoc)
- attach merged skill context to ToolContext.metadata

Design notes:
- No changes to the ToolContextEnricher interface are required.
- The current user message is expected in context.metadata['user_message'].
  The Agent sets this automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from vanna.core.enricher import ToolContextEnricher
from vanna.core.tool import ToolContext

from vanna.capabilities.schema_catalog import SchemaCatalog

from .compiler import SkillCompiler
from .generator import SkillGenerator
from .models import SkillEnvironment
from .registry import SkillRegistry
from .router import SkillRouter


def _snapshot_to_catalog_dict(snapshot: Any) -> Dict[str, Any]:
    """Convert a SchemaSnapshot into the lightweight dict format expected by SkillGenerator.

    SkillGenerator currently expects a JSON-ish schema_catalog with a top-level
    `tables` mapping. We derive that from portable SchemaColumn rows.
    """
    tables: Dict[str, Dict[str, Any]] = {}
    for col in getattr(snapshot, "columns", []) or []:
        table_name = getattr(col, "table_name", None)
        if not table_name:
            continue
        table = tables.setdefault(table_name, {"columns": []})
        table["columns"].append(
            {
                "name": getattr(col, "column_name", ""),
                "type": getattr(col, "data_type", ""),
                "nullable": bool(getattr(col, "is_nullable", True)),
                "schema": getattr(col, "schema_name", None) or "",
            }
        )
    return {"tables": tables}


@dataclass
class SkillAdHocConfig:
    """Configuration for SkillAdHocContextEnricher."""

    # Which environments are considered when selecting skills.
    # In production you typically want DEFAULT/APPROVED only.
    environments: Sequence[SkillEnvironment] = (
        SkillEnvironment.DEFAULT,
        SkillEnvironment.APPROVED,
        SkillEnvironment.TESTED,
        SkillEnvironment.DRAFT,
    )
    # Generate a draft skill when nothing matches.
    enable_ad_hoc_generation: bool = True
    # Router thresholds.
    min_match_score: float = 0.3
    max_skills: int = 5


class SkillAdHocContextEnricher(ToolContextEnricher):
    """Attach skill context to ToolContext.metadata.

    If no enabled skills match the current user message and ad-hoc generation is
    enabled, this enricher will:
      1) capture the current schema snapshot
      2) generate a DRAFT skill spec using SkillGenerator
      3) compile it and register it into the SkillRegistry
      4) re-run selection and attach merged context

    The merged skill context is stored at:
      - context.metadata['skill_context'] (dict)
      - context.metadata['system_prompt_appendix'] (string)
    """

    def __init__(
        self,
        *,
        registry: SkillRegistry,
        schema_catalog: SchemaCatalog,
        llm_service: Any = None,
        generator: Optional[SkillGenerator] = None,
        compiler: Optional[SkillCompiler] = None,
        router: Optional[SkillRouter] = None,
        config: Optional[SkillAdHocConfig] = None,
        tenant_glossary: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self._registry = registry
        self._schema_catalog = schema_catalog
        # Optional: use an LLM to generate higher-quality skill specs.
        # If unset, SkillGenerator falls back to template generation.
        self._llm_service = llm_service
        self._generator = generator or SkillGenerator()
        self._compiler = compiler or SkillCompiler()
        self._router = router or SkillRouter(
            min_match_score=(config.min_match_score if config else 0.3),
            max_skills=(config.max_skills if config else 5),
        )
        self._config = config or SkillAdHocConfig()
        self._tenant_glossary = tenant_glossary or []

    async def enrich_context(self, context: ToolContext) -> ToolContext:
        user_message = context.metadata.get("user_message")
        if not isinstance(user_message, str) or not user_message.strip():
            return context

        tenant_id = getattr(context.user, "tenant_id", None)
        enabled_skills: List[Any] = []
        for env in self._config.environments:
            enabled_skills.extend(
                await self._registry.list_skills(
                    tenant_id=tenant_id, environment=env, enabled_only=True
                )
            )

        selected = self._router.select_skills(
            user_message,
            enabled_skills,
            user_groups=getattr(context.user, "group_memberships", None),
        )

        # If nothing matches, generate a draft skill for this question.
        if not selected and self._config.enable_ad_hoc_generation:
            try:
                snapshot = await self._schema_catalog.capture_snapshot(context)
                schema_dict = _snapshot_to_catalog_dict(snapshot)
                description = (
                    "Ad-hoc skill to answer questions like: "
                    + user_message.strip()
                )
                output = await self._generator.generate(
                    schema_catalog=schema_dict,
                    tenant_glossary=self._tenant_glossary,
                    description=description,
                    llm_service=self._llm_service,
                    tenant_id=tenant_id,
                    author=getattr(context.user, "id", "anonymous"),
                )

                compiled = (
                    output.compilation_result.compiled_skill
                    if output.compilation_result and output.compilation_result.success
                    else None
                )

                if compiled is not None:
                    await self._registry.register_skill_with_compilation(
                        output.skill_spec,
                        compiled,
                        actor=getattr(context.user, "id", "anonymous"),
                        tenant_id=tenant_id,
                    )

                    # Re-list + re-select now that the skill exists.
                    enabled_skills = []
                    for env in self._config.environments:
                        enabled_skills.extend(
                            await self._registry.list_skills(
                                tenant_id=tenant_id,
                                environment=env,
                                enabled_only=True,
                            )
                        )
                    selected = self._router.select_skills(
                        user_message,
                        enabled_skills,
                        user_groups=getattr(context.user, "group_memberships", None),
                    )
            except Exception:
                # Skills must never break the core tool loop.
                return context

        if not selected:
            return context

        merged = SkillRouter.merge_skill_context(selected)
        context.metadata["skill_context"] = merged

        # Provide a prompt appendix so the LLM understands active constraints.
        skill_names = ", ".join([s.skill_name for s in selected])
        appendix_lines = [
            "## Active Skill Context",
            f"Selected skills: {skill_names}",
            "",
            "Skill constraints and helpful context:",
            f"- Tool hints: {merged.get('tool_hints', [])}",
            f"- Required SQL filters: {merged.get('policy_constraints', {}).get('required_filters', [])}",
            f"- SQL limits: {merged.get('policy_constraints', {}).get('sql_limits', {})}",
            "",
            "When generating SQL, respect required filters and row limits.",
        ]
        context.metadata["system_prompt_appendix"] = "\n".join(appendix_lines)

        return context
