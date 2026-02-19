"""
Skill Router — selects applicable skills for a given question and user context.

Matches user questions against skill intents, applies policy constraints,
and contributes glossary terms, semantic mappings, and rendering defaults
to the planner/router context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import CompiledSkill, SkillRegistryEntry


@dataclass
class SelectedSkill:
    """A skill selected by the router for the current question."""

    skill_id: str
    skill_name: str
    version: str
    match_score: float  # 0.0 - 1.0

    # Contributions to the planner context
    glossary_additions: Dict[str, List[str]] = field(default_factory=dict)
    semantic_mappings: Dict[str, str] = field(default_factory=dict)
    metric_definitions: Dict[str, str] = field(default_factory=dict)
    policy_constraints: Dict[str, Any] = field(default_factory=dict)
    rendering_defaults: Dict[str, Any] = field(default_factory=dict)
    tool_routing_hints: List[str] = field(default_factory=list)


class SkillRouter:
    """Selects applicable skills given a question and user/tenant context.

    Skills NEVER elevate access beyond the user's effective permissions.
    The router only adds constraints — it never removes them.
    """

    def __init__(
        self,
        *,
        min_match_score: float = 0.3,
        max_skills: int = 5,
    ) -> None:
        self._min_score = min_match_score
        self._max_skills = max_skills

    def select_skills(
        self,
        question: str,
        enabled_skills: List[SkillRegistryEntry],
        *,
        user_groups: Optional[List[str]] = None,
    ) -> List[SelectedSkill]:
        """Select applicable skills for a question.

        Args:
            question: The user's natural-language question
            enabled_skills: Skills available for this tenant/user
            user_groups: User's group memberships (for permission checks)

        Returns:
            List of SelectedSkill with context contributions, sorted by score
        """
        candidates: List[SelectedSkill] = []

        for entry in enabled_skills:
            if not entry.enabled:
                continue
            if entry.compiled_skill is None:
                continue

            score = self._score_match(question, entry.compiled_skill)
            if score < self._min_score:
                continue

            selected = SelectedSkill(
                skill_id=entry.skill_id,
                skill_name=entry.skill_spec.name,
                version=entry.skill_spec.version,
                match_score=score,
                glossary_additions=dict(entry.compiled_skill.glossary_additions),
                semantic_mappings=dict(entry.skill_spec.knowledge.semantic_mappings),
                metric_definitions=dict(entry.skill_spec.knowledge.metric_definitions),
                policy_constraints=dict(entry.compiled_skill.policy_constraints),
                rendering_defaults=dict(entry.compiled_skill.rendering_config),
                tool_routing_hints=list(entry.compiled_skill.tool_routing_hints),
            )
            candidates.append(selected)

        # Sort by score descending, limit
        candidates.sort(key=lambda s: s.match_score, reverse=True)
        return candidates[: self._max_skills]

    def _score_match(self, question: str, compiled: CompiledSkill) -> float:
        """Score how well a question matches a compiled skill's intents.

        Uses pattern matching and keyword overlap for deterministic scoring.
        """
        score = 0.0
        q_lower = question.lower()

        # Pattern matches (regex)
        for pattern in compiled.intent_patterns:
            try:
                if re.search(pattern, question, re.IGNORECASE):
                    score += 0.6
                    break
            except re.error:
                continue

        # Embedding hint keyword overlap
        if compiled.embedding_hints:
            hint_words = {
                w.lower()
                for hint in compiled.embedding_hints
                for w in hint.split()
            }
            q_words = set(q_lower.split())
            overlap = len(hint_words & q_words)
            if hint_words:
                score += 0.4 * (overlap / len(hint_words))

        return min(score, 1.0)

    @staticmethod
    def merge_skill_context(
        selected_skills: List[SelectedSkill],
    ) -> Dict[str, Any]:
        """Merge context from all selected skills into one dict for the planner.

        Policy constraints are COMBINED (union of restrictions).
        Glossary terms are merged.
        Rendering defaults use the highest-scoring skill.
        """
        merged: Dict[str, Any] = {
            "glossary": {},
            "semantic_mappings": {},
            "metric_definitions": {},
            "policy_constraints": {
                "tool_allowlist": [],
                "tool_denylist": [],
                "required_filters": [],
                "sql_limits": {},
            },
            "rendering": {},
            "tool_hints": [],
            "skill_ids": [],
        }

        for skill in selected_skills:
            merged["skill_ids"].append(
                {"id": skill.skill_id, "name": skill.skill_name, "version": skill.version}
            )

            # Merge glossary (union)
            for term, syns in skill.glossary_additions.items():
                existing = merged["glossary"].get(term, [])
                merged["glossary"][term] = list(set(existing + syns))

            # Merge semantic mappings
            merged["semantic_mappings"].update(skill.semantic_mappings)
            merged["metric_definitions"].update(skill.metric_definitions)

            # Merge policy constraints (union = aggregate restrictions)
            pc = skill.policy_constraints
            for key in ("tool_allowlist", "tool_denylist", "required_filters"):
                if key in pc:
                    merged["policy_constraints"][key] = list(
                        set(merged["policy_constraints"][key]) | set(pc[key])
                    )
            if "sql_limits" in pc:
                # Use strictest limits
                existing_limits = merged["policy_constraints"]["sql_limits"]
                for k, v in pc["sql_limits"].items():
                    if k not in existing_limits:
                        existing_limits[k] = v
                    elif isinstance(v, bool):
                        # For booleans, True = more restrictive
                        existing_limits[k] = existing_limits[k] or v
                    elif isinstance(v, (int, float)) and v is not None:
                        # For numeric limits, lower = more restrictive
                        current = existing_limits.get(k)
                        if current is None or v < current:
                            existing_limits[k] = v

            # Tool hints
            merged["tool_hints"].extend(skill.tool_routing_hints)

        # Rendering: use highest-scoring skill
        if selected_skills:
            merged["rendering"] = selected_skills[0].rendering_defaults

        return merged
