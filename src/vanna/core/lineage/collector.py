"""Request-wide lineage collection and permission-filtered serialization."""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, cast

from .confidence import ConfidenceScorer
from .models import (
    LineageEvidence,
    LineageOutcome,
    RetrievedSourceEvidence,
    SemanticCoverage,
    SemanticEvidence,
    SqlEvidence,
    ToolLineageRecord,
    ValidationCheck,
)


def _bounded_string(value: Any, limit: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[:limit]


def _bounded_runtime(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    runtime = float(value)
    return runtime if math.isfinite(runtime) and runtime >= 0 else None


def _bounded_row_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


class LineageCollector:
    """Collect typed evidence and never serialize arbitrary tool metadata."""

    def __init__(
        self,
        *,
        request_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> None:
        self.evidence = LineageEvidence(
            request_id=_bounded_string(request_id, 160),
            conversation_id=_bounded_string(conversation_id, 160),
        )
        self._show_tool_names = False
        self._show_sql = False
        self._show_sources = False

    def set_visibility(
        self,
        *,
        show_tool_names: bool,
        show_sql: bool,
        show_sources: bool,
    ) -> None:
        self._show_tool_names = show_tool_names
        self._show_sql = show_sql
        self._show_sources = show_sources

    def set_schema(
        self,
        schema_hash: Optional[str],
        schema_snapshot_id: Optional[str],
        *,
        schema_version: Any = None,
        schema_drifted: Any = False,
    ) -> None:
        self.evidence.schema_hash = _bounded_string(schema_hash, 160)
        self.evidence.schema_snapshot_id = _bounded_string(schema_snapshot_id, 160)
        self.evidence.schema_version = (
            schema_version
            if isinstance(schema_version, int)
            and not isinstance(schema_version, bool)
            and schema_version >= 1
            else None
        )
        self.evidence.schema_drifted = schema_drifted is True

    def set_outcome(
        self,
        outcome: LineageOutcome,
        *,
        failure_code: Optional[str] = None,
    ) -> None:
        self.evidence.outcome = outcome
        self.evidence.failure_code = _bounded_string(failure_code, 160)

    def set_semantic(
        self,
        coverage: SemanticCoverage,
        *,
        metric_names: Sequence[str] = (),
        fallback_reason: Optional[str] = None,
    ) -> None:
        bounded_metrics: list[str] = []
        for value in metric_names:
            metric = _bounded_string(value, 256)
            if metric and metric not in bounded_metrics:
                bounded_metrics.append(metric)
            if len(bounded_metrics) == 100:
                break
        self.evidence.semantic = SemanticEvidence(
            coverage=coverage,
            metric_names=bounded_metrics,
            fallback_reason=_bounded_string(fallback_reason, 2000),
        )

    def add_validation_check(self, check: str, passed: Optional[bool] = None) -> None:
        if len(self.evidence.validation_checks) >= 1000:
            return
        name = _bounded_string(check, 160)
        if not name:
            return
        inferred_passed = not (
            name.endswith("_failed")
            or name.endswith(":failed")
            or name.endswith(":error")
        )
        record = ValidationCheck(
            name=name,
            passed=inferred_passed if passed is None else passed,
        )
        if record not in self.evidence.validation_checks:
            self.evidence.validation_checks.append(record)

    def add_memories(self, memories: Iterable[Mapping[str, Any]]) -> None:
        for memory in memories:
            if len(self.evidence.retrieved_memories) >= 1000:
                break
            source_id = _bounded_string(
                memory.get("memory_id")
                or memory.get("document_id")
                or memory.get("id"),
                160,
            )
            if not source_id:
                continue
            raw_kind = memory.get("kind", "memory")
            kind = "document" if raw_kind == "document" else "memory"
            raw_score = memory.get("score", memory.get("similarity_score"))
            score = _bounded_runtime(raw_score)
            if score is not None and score > 1:
                score = None
            source = RetrievedSourceEvidence(
                source_id=source_id,
                kind=cast(Any, kind),
                score=score,
            )
            if source not in self.evidence.retrieved_memories:
                self.evidence.retrieved_memories.append(source)

    def record_tool_result(
        self,
        tool_name: str,
        success: bool,
        metadata: Dict[str, Any],
        error: Optional[str] = None,
    ) -> None:
        del error  # Raw errors are intentionally excluded from lineage state.
        bounded_name = _bounded_string(tool_name, 160) or "unknown_tool"
        runtime = _bounded_runtime(metadata.get("execution_time_ms"))
        if len(self.evidence.tool_calls) < 1000:
            self.evidence.tool_calls.append(
                ToolLineageRecord(
                    tool_name=bounded_name,
                    success=success,
                    execution_time_ms=runtime,
                )
            )

        sql_text = _bounded_string(metadata.get("executed_sql"), 100_000)
        if sql_text and len(self.evidence.sql_executions) < 100:
            self.evidence.sql_executions.append(
                SqlEvidence(
                    sql=sql_text,
                    dialect=_bounded_string(metadata.get("dialect"), 64),
                    row_count=_bounded_row_count(metadata.get("row_count")),
                    execution_time_ms=runtime,
                )
            )

        retrieved = metadata.get("retrieved_memories")
        if isinstance(retrieved, list):
            mappings = [value for value in retrieved if isinstance(value, Mapping)]
            self.add_memories(cast(Iterable[Mapping[str, Any]], mappings))

        checks = metadata.get("validation_checks")
        if isinstance(checks, list):
            for check in checks:
                if isinstance(check, str):
                    self.add_validation_check(check)
                elif isinstance(check, Mapping):
                    name = check.get("name")
                    passed = check.get("passed")
                    if isinstance(name, str) and isinstance(passed, bool):
                        self.add_validation_check(name, passed)

        if bounded_name == "semantic_query" and success:
            planned_metrics = list(self.evidence.semantic.metric_names)
            raw_query = metadata.get("semantic_query")
            executed_metrics: list[str] = []
            if isinstance(raw_query, Mapping):
                raw_metrics = raw_query.get("metrics")
                if isinstance(raw_metrics, list):
                    for raw_metric in raw_metrics:
                        metric = _bounded_string(raw_metric, 256)
                        if metric and metric not in executed_metrics:
                            executed_metrics.append(metric)
                        if len(executed_metrics) == 100:
                            break
                if not executed_metrics:
                    metric = _bounded_string(raw_query.get("metric"), 256)
                    if metric:
                        executed_metrics.append(metric)
            self.set_semantic(
                (
                    "full"
                    if self.evidence.semantic.coverage == "not_applicable"
                    else self.evidence.semantic.coverage
                ),
                metric_names=executed_metrics,
                fallback_reason=self.evidence.semantic.fallback_reason,
            )
            self.add_validation_check(
                "semantic_execution_metadata_valid",
                bool(executed_metrics),
            )
            if planned_metrics:
                self.add_validation_check(
                    "semantic_plan_execution_match",
                    planned_metrics == executed_metrics,
                )
            self.add_validation_check("semantic_query_passed")

    def finalize(self) -> LineageEvidence:
        self.evidence.confidence = ConfidenceScorer.explain(self.evidence)
        return self.evidence.model_copy(deep=True)

    def to_public_evidence(self) -> Dict[str, Any]:
        evidence = self.finalize()
        redactions: list[str] = []
        if evidence.tool_calls and not self._show_tool_names:
            redactions.append("tool_names")
        if evidence.sql_executions and not self._show_sql:
            redactions.append("sql_text")
        if evidence.retrieved_memories and not self._show_sources:
            redactions.append("retrieved_sources")
        self.evidence.redactions = redactions

        return {
            "schema_version": evidence.schema_version,
            "schema_snapshot_id": evidence.schema_snapshot_id,
            "schema_hash": evidence.schema_hash,
            "schema_drifted": evidence.schema_drifted,
            "semantic": evidence.semantic.model_dump(exclude_none=True),
            "retrieved_sources": (
                [
                    {
                        "id": source.source_id,
                        "kind": source.kind,
                        **({"score": source.score} if source.score is not None else {}),
                    }
                    for source in evidence.retrieved_memories
                ]
                if self._show_sources
                else []
            ),
            "tool_calls": [
                {
                    "name": record.tool_name if self._show_tool_names else "restricted",
                    "success": record.success,
                    **(
                        {"runtime_ms": record.execution_time_ms}
                        if record.execution_time_ms is not None
                        else {}
                    ),
                }
                for record in evidence.tool_calls
            ],
            "sql_executions": [
                {
                    **({"sql": record.sql} if self._show_sql else {}),
                    **({"dialect": record.dialect} if record.dialect else {}),
                    "row_count": record.row_count,
                    **(
                        {"runtime_ms": record.execution_time_ms}
                        if record.execution_time_ms is not None
                        else {}
                    ),
                }
                for record in evidence.sql_executions
            ],
            "validation_checks": [
                check.model_dump() for check in evidence.validation_checks
            ],
            "confidence": evidence.confidence.model_dump(),
        }

    def to_public_payload(self) -> Dict[str, Any]:
        return {"evidence": self.to_public_evidence()}

    def to_markdown(self) -> str:
        """Render the same permission-filtered evidence shown by the V3 event."""

        public = self.to_public_evidence()
        confidence = cast(Dict[str, Any], public["confidence"])
        semantic = cast(Dict[str, Any], public["semantic"])
        lines = ["## Evidence and Lineage"]
        lines.append(
            "- Schema: "
            f"version={public['schema_version'] or 'n/a'} "
            f"snapshot=`{public['schema_snapshot_id'] or 'n/a'}` "
            f"hash=`{public['schema_hash'] or 'n/a'}` "
            f"drifted={public['schema_drifted']}"
        )
        signals = cast(list[str], confidence["signals"])
        lines.append(
            f"- Confidence: **{confidence['tier']}** "
            f"(signals: {', '.join(signals) if signals else 'none'})"
        )
        lines.append(
            f"- Semantic coverage: `{semantic['coverage']}`"
            + (
                f" ({semantic['fallback_reason']})"
                if semantic.get("fallback_reason")
                else ""
            )
        )
        lines.append(f"- Tool calls: {len(cast(list[Any], public['tool_calls']))}")
        lines.append(
            f"- SQL executions: {len(cast(list[Any], public['sql_executions']))}"
        )
        lines.append(
            "- Retrieved memories/docs: "
            f"{len(cast(list[Any], public['retrieved_sources']))}"
        )
        checks = cast(list[Dict[str, Any]], public["validation_checks"])
        lines.append(
            "- Validation checks: "
            + (
                ", ".join(
                    f"{check['name']}={'pass' if check['passed'] else 'fail'}"
                    for check in checks
                )
                if checks
                else "none"
            )
        )
        return "\n".join(lines)
