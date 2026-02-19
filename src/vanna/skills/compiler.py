"""
Skill Compiler / Validator — deterministic, no LLM calls.

Validates SkillSpec schema and semantic correctness, checks policy safety,
and produces a CompiledSkill runtime artifact.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .models import (
    CompiledSkill,
    CompilationResult,
    SkillSpec,
)


class SkillCompiler:
    """Deterministic compiler that validates and compiles SkillSpecs.

    NO LLM calls. All validation is rule-based and reproducible.
    """

    def __init__(
        self,
        *,
        known_tools: Optional[List[str]] = None,
        require_tenant_predicate: bool = False,
    ) -> None:
        self._known_tools = set(known_tools or [])
        self._require_tenant_predicate = require_tenant_predicate

    def compile(self, spec: SkillSpec) -> CompilationResult:
        """Validate and compile a SkillSpec.

        Returns CompilationResult with success/failure and compiled artifact.
        """
        errors: List[str] = []
        warnings: List[str] = []

        # --- Schema validation ---
        if not spec.name or not spec.name.strip():
            errors.append("Skill name is required and cannot be empty")

        if not spec.version:
            errors.append("Skill version is required")

        # --- Policy safety checks ---
        policies = spec.policies

        # 1. Refuse specs that enable write SQL by default
        if not policies.sql_limits.read_only:
            errors.append(
                "Policy violation: sql_limits.read_only must be True. "
                "Skills cannot enable write SQL by default."
            )

        if not policies.sql_limits.forbid_ddl_dml:
            errors.append(
                "Policy violation: sql_limits.forbid_ddl_dml must be True. "
                "Skills cannot allow DDL/DML statements."
            )

        # 2. Refuse missing required tenant predicate
        if self._require_tenant_predicate and not policies.required_filters:
            errors.append(
                "Policy violation: required_filters must contain at least one "
                "tenant predicate when tenant enforcement is configured."
            )

        # 3. Validate tool references against known tools
        if self._known_tools:
            for tool_name in policies.tool_allowlist:
                if tool_name not in self._known_tools:
                    errors.append(
                        f"Unknown tool in allowlist: '{tool_name}'. "
                        f"Known tools: {sorted(self._known_tools)}"
                    )
            for tool_name in policies.tool_denylist:
                if tool_name not in self._known_tools:
                    warnings.append(
                        f"Tool in denylist not found in registry: '{tool_name}'"
                    )

        # 4. Check for conflicting allow/deny
        overlap = set(policies.tool_allowlist) & set(policies.tool_denylist)
        if overlap:
            errors.append(
                f"Tools cannot appear in both allowlist and denylist: {sorted(overlap)}"
            )

        # --- Intent validation ---
        intents = spec.intents
        if not intents.patterns and not intents.embedding_hints:
            warnings.append(
                "No intent patterns or embedding hints defined. "
                "Skill may not be discoverable by the router."
            )

        # Validate regex patterns
        for pattern in intents.patterns:
            try:
                re.compile(pattern)
            except re.error as e:
                errors.append(f"Invalid regex pattern '{pattern}': {e}")

        # --- Eval suite warnings ---
        eval_suite = spec.eval_suite
        if not eval_suite.inline_evals and not eval_suite.eval_data_path:
            warnings.append("No eval suite defined. Promotion may be blocked.")

        # --- Build compiled artifact if no errors ---
        if errors:
            return CompilationResult(
                success=False,
                errors=errors,
                warnings=warnings,
            )

        compiled = CompiledSkill(
            skill_spec_hash=CompiledSkill.compute_spec_hash(spec),
            version=spec.version,
            intent_patterns=list(intents.patterns),
            embedding_hints=list(intents.embedding_hints),
            tool_routing_hints=list(intents.tool_routing_hints),
            policy_constraints={
                "tool_allowlist": list(policies.tool_allowlist),
                "tool_denylist": list(policies.tool_denylist),
                "required_filters": list(policies.required_filters),
                "sql_limits": policies.sql_limits.model_dump(),
                "row_redaction_rules": list(policies.row_redaction_rules),
                "column_redaction_rules": list(policies.column_redaction_rules),
            },
            glossary_additions=dict(spec.knowledge.synonyms),
            rendering_config=spec.rendering.model_dump(exclude_none=True),
        )

        return CompilationResult(
            success=True,
            errors=[],
            warnings=warnings,
            compiled_skill=compiled,
        )
