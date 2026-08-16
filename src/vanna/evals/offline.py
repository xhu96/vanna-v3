"""Deterministic execution of an explicitly supplied offline candidate stack."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
from typing import Any, Callable, Optional, cast

from vanna import Agent, AgentConfig
from vanna.core.evaluation import (
    AgentVariant,
    EfficiencyEvaluator,
    EvaluationDataset,
    EvaluationRunner,
    OutputEvaluator,
    ResultDataEvaluator,
    TrajectoryEvaluator,
)
from vanna.core.evaluation.report import EvaluationReport
from vanna.core.registry import ToolRegistry
from vanna.core.user import User
from vanna.core.user.request_context import RequestContext
from vanna.core.user.resolver import UserResolver
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.mock.scripted_llm import ScriptedLlmService
from vanna.evals.training_data import validate_training_manifest

DEFAULT_DATASET = "src/evals/datasets/sql_generation/offline_smoke.yaml"
METRICS_SCHEMA_VERSION = "vanna-eval-metrics-v1"

SCRIPTED = {
    "total sales by region": (
        "SELECT region, SUM(amount) AS total FROM sales GROUP BY region"
    ),
    "revenue by month": (
        "SELECT month, SUM(amount) AS revenue FROM sales GROUP BY month"
    ),
    "orders per day": ("SELECT day, COUNT(*) AS orders FROM orders_tbl GROUP BY day"),
}


class _EvalUserResolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        test_user = request_context.metadata.get("test_case_user")
        if isinstance(test_user, User):
            return test_user.model_copy(update={"authenticated": True})
        return User(
            id="eval_user",
            authenticated=True,
            group_memberships=["user", "analyst"],
        )


def build_reference_variant() -> AgentVariant:
    """Build the deterministic reference, not a hidden production candidate."""

    agent = Agent(
        llm_service=ScriptedLlmService(SCRIPTED),
        tool_registry=ToolRegistry(),
        user_resolver=_EvalUserResolver(),
        agent_memory=DemoAgentMemory(),
        config=AgentConfig(stream_responses=False, auto_save_conversations=False),
    )
    return AgentVariant(
        name="scripted-offline-reference",
        agent=agent,
        metadata={"provider": "scripted", "mode": "offline"},
    )


def load_candidate_factory(spec: str) -> AgentVariant:
    """Load an explicitly supplied local ``module:factory`` candidate stack."""

    module_name, separator, attribute = spec.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("candidate factory must use module:callable syntax")
    factory = getattr(importlib.import_module(module_name), attribute, None)
    if not callable(factory):
        raise ValueError("candidate factory is not callable")
    candidate = cast(Callable[[], Any], factory)()
    if not isinstance(candidate, AgentVariant):
        raise TypeError("candidate factory must return AgentVariant")
    return candidate


def load_training_manifest(path: Path) -> dict[str, Any]:
    """Load manifest shape for diagnostics; promotion still requires JSONL bytes."""

    value = json.loads(path.read_text(encoding="utf-8"))
    return validate_training_manifest(value)


def _quality_metrics(report: EvaluationReport) -> dict[str, float]:
    return {
        "pass_rate": report.pass_rate(),
        "average_score": report.average_score(),
    }


def _slice_metrics(report: EvaluationReport) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, list[Any]] = {}
    for result in report.results:
        slice_name = result.test_case.metadata.get("slice", "unspecified")
        if not isinstance(slice_name, str) or not slice_name:
            raise ValueError("evaluation slice names must be non-empty strings")
        grouped.setdefault(slice_name, []).append(result)

    slices: dict[str, dict[str, float | int]] = {}
    for slice_name, results in sorted(grouped.items()):
        passed = sum(1 for result in results if result.overall_passed())
        score = sum(result.overall_score() for result in results) / len(results)
        slices[slice_name] = {
            "case_count": len(results),
            "pass_rate": passed / len(results),
            "average_score": score,
        }
    return slices


async def run_offline_eval(
    dataset_path: str = DEFAULT_DATASET,
    *,
    candidate: AgentVariant,
    training_manifest: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Run the exact supplied candidate through the real evaluation runner."""

    dataset_file = Path(dataset_path)
    dataset = EvaluationDataset.from_yaml(str(dataset_file))
    runner = EvaluationRunner(
        evaluators=[
            TrajectoryEvaluator(),
            OutputEvaluator(),
            ResultDataEvaluator(),
            EfficiencyEvaluator(),
        ],
        max_concurrency=2,
    )
    comparison = await runner.compare_agents([candidate], dataset.test_cases)
    report = comparison.reports[candidate.name]
    metrics: dict[str, Any] = {
        "schema_version": METRICS_SCHEMA_VERSION,
        "candidate": {
            "name": candidate.name,
            "metadata": candidate.metadata,
        },
        "dataset": {
            "name": dataset.name,
            "sha256": hashlib.sha256(dataset_file.read_bytes()).hexdigest(),
            "case_count": len(dataset.test_cases),
        },
        "aggregate": {
            "case_count": len(report.results),
            **_quality_metrics(report),
        },
        "slices": _slice_metrics(report),
    }
    if training_manifest is not None:
        metrics["training_data"] = validate_training_manifest(training_manifest)
    return metrics


__all__ = [
    "DEFAULT_DATASET",
    "METRICS_SCHEMA_VERSION",
    "_EvalUserResolver",
    "build_reference_variant",
    "load_candidate_factory",
    "load_training_manifest",
    "run_offline_eval",
]
