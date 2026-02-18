"""Semantic layer adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from vanna.core.tool import ToolContext

from .models import SemanticPlanHint, SemanticQueryRequest, SemanticQueryResult


class SemanticAdapter(ABC):
    """Adapter for semantic layers (dbt semantic, MetricFlow, etc.)."""

    @abstractmethod
    async def plan(self, message: str, context: ToolContext) -> SemanticPlanHint:
        """Return whether a semantic query can answer the message."""
        pass

    @abstractmethod
    async def execute(
        self, request: SemanticQueryRequest, context: ToolContext
    ) -> SemanticQueryResult:
        """Execute semantic query request."""
        pass
