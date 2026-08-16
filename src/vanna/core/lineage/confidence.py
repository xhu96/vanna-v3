"""Deterministic confidence tiers derived from explicit lineage signals."""

from __future__ import annotations

from typing import Dict

from .models import ConfidenceEvidence, ConfidenceTier, LineageEvidence


class ConfidenceScorer:
    """Assign a tier without inventing an uncalibrated numeric probability."""

    @staticmethod
    def signal_map(evidence: LineageEvidence) -> Dict[str, bool]:
        semantic_succeeded = any(
            record.tool_name == "semantic_query" and record.success
            for record in evidence.tool_calls
        )
        has_errors = any(not record.success for record in evidence.tool_calls)
        has_checks = bool(evidence.validation_checks)
        checks_passed = has_checks and all(
            check.passed for check in evidence.validation_checks
        )
        return {
            "semantic_full": evidence.semantic.coverage == "full",
            "semantic_query_succeeded": semantic_succeeded,
            "sql_executed": bool(evidence.sql_executions),
            "retrieval_support": bool(evidence.retrieved_memories),
            "post_query_checks_passed": checks_passed,
            "validation_failed": any(
                not check.passed for check in evidence.validation_checks
            ),
            "tool_error": has_errors,
            "schema_drift_detected": evidence.schema_drifted,
            "tool_limit_reached": evidence.outcome == "tool_limit",
            "request_failed": evidence.outcome == "error",
        }

    @staticmethod
    def explain(evidence: LineageEvidence) -> ConfidenceEvidence:
        signal_map = ConfidenceScorer.signal_map(evidence)
        signals = [name for name, active in signal_map.items() if active]
        unreliable = any(
            signal_map[name]
            for name in (
                "validation_failed",
                "tool_error",
                "tool_limit_reached",
                "request_failed",
            )
        )

        tier: ConfidenceTier
        if unreliable:
            tier = "Low"
        elif (
            signal_map["semantic_full"]
            and signal_map["semantic_query_succeeded"]
            and signal_map["post_query_checks_passed"]
            and not signal_map["schema_drift_detected"]
        ):
            tier = "High"
        elif (
            signal_map["semantic_query_succeeded"]
            or signal_map["sql_executed"]
            or signal_map["retrieval_support"]
        ):
            tier = "Medium"
        else:
            tier = "Low"
        return ConfidenceEvidence(tier=tier, signals=signals)

    @staticmethod
    def score(evidence: LineageEvidence) -> ConfidenceTier:
        return ConfidenceScorer.explain(evidence).tier
