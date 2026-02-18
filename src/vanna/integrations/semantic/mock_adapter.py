"""Mock semantic adapter used as a golden reference implementation."""

from __future__ import annotations

from typing import Any, Dict, List

from vanna.capabilities.semantic import (
    SemanticAdapter,
    SemanticPlanHint,
    SemanticQueryRequest,
    SemanticQueryResult,
)
from vanna.core.tool import ToolContext


class MockSemanticAdapter(SemanticAdapter):
    """Simple semantic adapter with deterministic keyword routing."""

    def __init__(
        self,
        catalog: Dict[str, List[Dict[str, Any]]] | None = None,
    ):
        self.catalog = catalog or {
            "revenue": [
                {"month": "2025-01", "revenue": 1000},
                {"month": "2025-02", "revenue": 1200},
            ],
            "orders": [
                {"day": "2025-01-01", "orders": 10},
                {"day": "2025-01-02", "orders": 12},
            ],
        }

    async def plan(self, message: str, context: ToolContext) -> SemanticPlanHint:
        lowered = message.lower()
        for metric in self.catalog.keys():
            if metric in lowered:
                return SemanticPlanHint(
                    coverage="full",
                    reason=f"Matched metric '{metric}' in semantic catalog.",
                    request=SemanticQueryRequest(metric=metric),
                )

        return SemanticPlanHint(
            coverage="missing",
            reason="No semantic metric match found; fallback to SQL generation.",
            request=None,
        )

    async def execute(
        self, request: SemanticQueryRequest, context: ToolContext
    ) -> SemanticQueryResult:
        rows = self.catalog.get(request.metric, [])
        return SemanticQueryResult(
            rows=rows,
            row_count=len(rows),
            metadata={
                "semantic_metric": request.metric,
                "source": "mock_semantic_adapter",
            },
        )
