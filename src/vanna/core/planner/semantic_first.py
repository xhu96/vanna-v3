"""Semantic-first planner helper."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from vanna.capabilities.semantic import SemanticAdapter, SemanticPlanHint
from vanna.core.tool import ToolSchema, ToolContext


@dataclass
class PlannerDecision:
    route: str
    message: str
    semantic_hint: SemanticPlanHint | None = None


class SemanticFirstPlanner:
    """Decides whether to prefer semantic query route before SQL."""

    def __init__(self, semantic_adapter: SemanticAdapter):
        self.semantic_adapter = semantic_adapter

    async def decide(
        self, message: str, tool_schemas: List[ToolSchema], context: ToolContext
    ) -> PlannerDecision:
        tool_names = {tool.name for tool in tool_schemas}
        if "semantic_query" not in tool_names:
            return PlannerDecision(
                route="sql_fallback",
                message="Semantic tool unavailable; using SQL path.",
                semantic_hint=None,
            )

        hint = await self.semantic_adapter.plan(message, context)
        if hint.coverage in ("full", "partial"):
            return PlannerDecision(
                route="semantic_preferred",
                message=(
                    "Semantic coverage available. Prefer semantic_query before run_sql."
                ),
                semantic_hint=hint,
            )

        return PlannerDecision(
            route="sql_fallback",
            message="Semantic coverage missing; fallback to SQL generation.",
            semantic_hint=hint,
        )

