"""Rule-based confidence scoring for lineage evidence."""

from __future__ import annotations

from typing import Any

from .models import LineageEvidence


class ConfidenceScorer:
    """Assign a heuristic confidence tier from explicit runtime signals."""

    @staticmethod
    def _signals(evidence: LineageEvidence) -> dict[str, bool]:
        successful_tools = [t for t in evidence.tool_calls if t.success]
        return {
            "has_semantic": any(
                t.tool_name == "semantic_query" and t.success for t in successful_tools
            ),
            "has_sql": len(evidence.sql_executions) > 0,
            "has_memory_support": len(evidence.retrieved_memories) > 0,
            "has_validation": len(evidence.validation_checks) > 0,
            "has_errors": any(not t.success for t in evidence.tool_calls),
        }

    @staticmethod
    def score(evidence: LineageEvidence) -> str:
        s = ConfidenceScorer._signals(evidence)
        if s["has_semantic"] and s["has_validation"] and not s["has_errors"]:
            return "High"
        if (s["has_sql"] or s["has_memory_support"]) and not s["has_errors"]:
            return "Medium"
        return "Low"

    @staticmethod
    def explain(evidence: LineageEvidence) -> dict[str, Any]:
        """Return the tier plus the boolean signals it was derived from."""
        return {
            "tier": ConfidenceScorer.score(evidence),
            "signals": ConfidenceScorer._signals(evidence),
        }
