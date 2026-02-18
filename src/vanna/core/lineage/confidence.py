"""Rule-based confidence scoring for lineage evidence."""

from __future__ import annotations

from .models import LineageEvidence


class ConfidenceScorer:
    """Assign confidence tier using explicit runtime signals."""

    @staticmethod
    def score(evidence: LineageEvidence) -> str:
        successful_tools = [t for t in evidence.tool_calls if t.success]
        has_semantic = any(t.tool_name == "semantic_query" and t.success for t in successful_tools)
        has_sql = len(evidence.sql_executions) > 0
        has_memory_support = len(evidence.retrieved_memories) > 0
        has_validation = len(evidence.validation_checks) > 0
        has_errors = any(not t.success for t in evidence.tool_calls)

        if has_semantic and has_validation and not has_errors:
            return "High"
        if (has_sql or has_memory_support) and not has_errors:
            return "Medium"
        return "Low"

