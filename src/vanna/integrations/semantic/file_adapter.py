"""File-backed semantic adapter: a real, self-contained semantic layer.

Metrics are declared in a YAML file (name, synonyms, and a read-only SQL
statement). ``plan`` matches a natural-language message to a metric by
name/synonym; ``execute`` runs the metric's SQL through an injected
``SqlRunner`` and returns the rows.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, cast

import yaml

from vanna.capabilities.semantic import (
    SemanticAdapter,
    SemanticPlanHint,
    SemanticQueryRequest,
    SemanticQueryResult,
)
from vanna.capabilities.sql_runner import RunSqlToolArgs, SqlRunner
from vanna.core.tool import ToolContext
from vanna.security.sql_policy import (
    SqlPolicyViolation,
    SqlQueryPolicy,
    normalize_sql_dialect,
)


class _Metric:
    def __init__(self, name: str, sql: str, synonyms: List[str]):
        self.name = name
        self.sql = sql
        self.synonyms = synonyms


class FileSemanticAdapter(SemanticAdapter):
    """Semantic adapter backed by a YAML metric model and a SqlRunner."""

    def __init__(
        self,
        model_path: str,
        sql_runner: SqlRunner,
        query_policy: Optional[SqlQueryPolicy] = None,
        *,
        require_native_read_only: bool = True,
    ):
        self.model_path = model_path
        self.sql_runner = sql_runner
        self.require_native_read_only = require_native_read_only
        if require_native_read_only and sql_runner.native_read_only is not True:
            raise SqlPolicyViolation(
                "Semantic SQL execution requires a native read-only runner boundary."
            )
        runner_dialect = normalize_sql_dialect(
            getattr(sql_runner, "dialect", "unknown")
        )
        if query_policy is None:
            if runner_dialect == "unknown":
                raise ValueError(
                    "FileSemanticAdapter requires a known runner dialect or an "
                    "explicit SqlQueryPolicy."
                )
            query_policy = SqlQueryPolicy(
                runner_dialect,
                require_row_policies=True,
            )
        elif runner_dialect != "unknown" and query_policy.dialect != runner_dialect:
            raise ValueError(
                "Semantic query policy dialect does not match the runner dialect."
            )
        self.query_policy = query_policy
        self._metrics: Dict[str, _Metric] = self._load_model(model_path)

    @staticmethod
    def _load_model(path: str) -> Dict[str, "_Metric"]:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        metrics: Dict[str, _Metric] = {}
        for entry in data.get("metrics", []):
            name = entry["name"]
            metrics[name] = _Metric(
                name=name,
                sql=entry["sql"],
                synonyms=[s.lower() for s in entry.get("synonyms", [])],
            )
        return metrics

    def _match(self, message: str) -> Optional[_Metric]:
        lowered = message.lower()
        for metric in self._metrics.values():
            terms = [metric.name.lower(), *metric.synonyms]
            if any(term in lowered for term in terms):
                return metric
        return None

    async def plan(self, message: str, context: ToolContext) -> SemanticPlanHint:
        metric = self._match(message)
        if metric is None:
            return SemanticPlanHint(
                coverage="missing",
                reason="No semantic metric matched; fall back to SQL generation.",
                request=None,
            )
        return SemanticPlanHint(
            coverage="full",
            reason=f"Matched semantic metric '{metric.name}'.",
            request=SemanticQueryRequest(metric=metric.name),
        )

    async def execute(
        self, request: SemanticQueryRequest, context: ToolContext
    ) -> SemanticQueryResult:
        if len(request.metrics) != 1:
            raise ValueError("FileSemanticAdapter supports exactly one metric.")
        if (
            request.dimensions
            or request.filters
            or request.time_grain
            or request.order_by
        ):
            raise ValueError(
                "FileSemanticAdapter does not support structured semantic options."
            )
        metric = self._metrics.get(request.metric)
        if metric is None:
            return SemanticQueryResult(
                rows=[],
                row_count=0,
                metadata={"semantic_metric": request.metric, "matched": False},
            )

        prepared_sql = self.query_policy.prepare(metric.sql, context)
        df = await self.sql_runner.run_sql(RunSqlToolArgs(sql=prepared_sql), context)
        rows: List[Dict[str, Any]] = (
            cast(List[Dict[str, Any]], df.to_dict("records")) if not df.empty else []
        )
        if request.limit:
            rows = rows[: request.limit]
        return SemanticQueryResult(
            rows=rows,
            row_count=len(rows),
            metadata={
                "semantic_metric": metric.name,
                "matched": True,
                "source": "file_semantic_adapter",
                "executed_sql": prepared_sql,
                "validation_checks": ["shared_sql_query_policy_passed"],
            },
        )
