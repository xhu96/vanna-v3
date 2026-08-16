"""Semantic-first planner helper."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from vanna.capabilities.semantic import SemanticAdapter, SemanticPlanHint
from vanna.core.tool import ToolSchema, ToolContext


@dataclass
class PlannerDecision:
    route: str
    message: str
    semantic_hint: SemanticPlanHint | None = None
    warning_code: Optional[str] = None
    blocked_tools: tuple[str, ...] = ()
    blocked_capabilities: tuple[str, ...] = ()


class SemanticPlanningError(RuntimeError):
    """Raised when semantic coverage cannot be determined safely."""


class SemanticFirstPlanner:
    """Decides whether to prefer semantic query route before SQL."""

    def __init__(
        self,
        semantic_adapter: SemanticAdapter,
        *,
        fallback_on_service_error: bool = False,
    ):
        self.semantic_adapter = semantic_adapter
        self.fallback_on_service_error = fallback_on_service_error

    async def decide(
        self, message: str, tool_schemas: List[ToolSchema], context: ToolContext
    ) -> PlannerDecision:
        tool_names = {tool.name for tool in tool_schemas}
        if "semantic_query" not in tool_names:
            return PlannerDecision(
                route="sql_fallback",
                message="Semantic tool unavailable; using SQL path.",
                semantic_hint=None,
                warning_code="semantic_tool_unavailable",
            )

        try:
            hint = await self.semantic_adapter.plan(message, context)
        except Exception as exc:
            if self.fallback_on_service_error:
                return PlannerDecision(
                    route="sql_fallback",
                    message="Semantic service unavailable; using configured SQL fallback.",
                    warning_code="semantic_service_unavailable",
                )
            raise SemanticPlanningError(
                "Semantic service failed; SQL fallback is disabled by default."
            ) from None

        if hint.coverage == "full":
            return PlannerDecision(
                route="semantic_preferred",
                message="Full semantic coverage available; SQL is disabled for this turn.",
                semantic_hint=hint,
                blocked_tools=("run_sql",),
                blocked_capabilities=("sql",),
            )

        if hint.coverage == "partial":
            return PlannerDecision(
                route="sql_fallback",
                message="Semantic coverage is partial; SQL fallback is available.",
                semantic_hint=hint,
                warning_code="semantic_partial_coverage",
            )

        return PlannerDecision(
            route="sql_fallback",
            message="Semantic coverage missing; fallback to SQL generation.",
            semantic_hint=hint,
            warning_code="semantic_coverage_missing",
        )
