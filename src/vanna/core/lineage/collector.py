"""Lineage evidence collector."""

from __future__ import annotations

from typing import Any, Dict, Iterable

from .confidence import ConfidenceScorer
from .models import LineageEvidence, MemoryEvidence, SqlEvidence, ToolLineageRecord


class LineageCollector:
    """Collects execution evidence during an agent run."""

    def __init__(self) -> None:
        self.evidence = LineageEvidence()

    def set_schema(
        self, schema_hash: str | None, schema_snapshot_id: str | None
    ) -> None:
        self.evidence.schema_hash = schema_hash
        self.evidence.schema_snapshot_id = schema_snapshot_id

    def add_validation_check(self, check: str) -> None:
        self.evidence.validation_checks.append(check)

    def add_memories(self, memories: Iterable[Dict[str, Any]]) -> None:
        for memory in memories:
            self.evidence.retrieved_memories.append(
                MemoryEvidence(
                    memory_id=memory.get("memory_id"),
                    score=memory.get("score"),
                    tool_name=memory.get("tool_name"),
                )
            )

    def record_tool_result(
        self,
        tool_name: str,
        success: bool,
        metadata: Dict[str, Any],
        error: str | None = None,
    ) -> None:
        self.evidence.tool_calls.append(
            ToolLineageRecord(
                tool_name=tool_name,
                success=success,
                execution_time_ms=metadata.get("execution_time_ms"),
                metadata=metadata,
                error=error,
            )
        )

        sql_text = metadata.get("executed_sql")
        if sql_text:
            self.evidence.sql_executions.append(
                SqlEvidence(
                    sql=sql_text,
                    row_count=metadata.get("row_count"),
                    execution_time_ms=metadata.get("execution_time_ms"),
                )
            )

        retrieved = metadata.get("retrieved_memories")
        if isinstance(retrieved, list):
            self.add_memories(retrieved)

        checks = metadata.get("validation_checks")
        if isinstance(checks, list):
            for check in checks:
                if isinstance(check, str):
                    self.add_validation_check(check)

    def finalize(self) -> LineageEvidence:
        self.evidence.confidence = ConfidenceScorer.score(self.evidence)
        return self.evidence

    def to_markdown(self) -> str:
        """Render a compact lineage panel suitable for card markdown."""
        evidence = self.finalize()
        lines = ["## Evidence and Lineage"]
        lines.append(
            f"- Schema: `{evidence.schema_snapshot_id or 'n/a'}` / `{evidence.schema_hash or 'n/a'}`"
        )
        lines.append(
            f"- Confidence: **{evidence.confidence}** "
            "(derived from semantic usage, retrieval support, tool success, and checks)"
        )
        lines.append(f"- Tool calls: {len(evidence.tool_calls)}")
        for tool in evidence.tool_calls:
            state = "ok" if tool.success else "error"
            lines.append(f"  - `{tool.tool_name}`: {state}")

        if evidence.sql_executions:
            lines.append(f"- SQL executions: {len(evidence.sql_executions)}")
            for sql in evidence.sql_executions[:3]:
                normalized = " ".join(sql.sql.split())
                lines.append(
                    f"  - `{normalized[:160]}` rows={sql.row_count} runtime_ms={sql.execution_time_ms}"
                )
        else:
            lines.append("- SQL executions: 0")

        lines.append(f"- Retrieved memories/docs: {len(evidence.retrieved_memories)}")
        lines.append(
            f"- Validation checks: {', '.join(evidence.validation_checks) if evidence.validation_checks else 'none'}"
        )
        return "\n".join(lines)
