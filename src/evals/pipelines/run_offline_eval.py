"""Run the deterministic offline eval and emit candidate metrics JSON.

This mirrors the construction in ``src/evals/benchmarks/llm_comparison.py`` (an
``AgentVariant`` evaluated by an ``EvaluationRunner`` via ``compare_agents``),
but injects a deterministic ``ScriptedLlmService`` so the real Agent +
evaluators run end-to-end and produce reproducible metrics. It is an honest
offline regression gate, not a model-quality benchmark.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from vanna import Agent, AgentConfig
from vanna.core.evaluation import (
    AgentVariant,
    EfficiencyEvaluator,
    EvaluationDataset,
    EvaluationRunner,
    OutputEvaluator,
)
from vanna.core.registry import ToolRegistry
from vanna.core.user import User
from vanna.core.user.request_context import RequestContext
from vanna.core.user.resolver import UserResolver
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.mock.scripted_llm import ScriptedLlmService

DEFAULT_DATASET = "src/evals/datasets/sql_generation/offline_smoke.yaml"

# Scripted answers keyed to substrings of the dataset messages.
SCRIPTED = {
    "total sales by region": "SELECT region, SUM(amount) AS total FROM sales GROUP BY region",
    "revenue by month": "SELECT month, SUM(amount) AS revenue FROM sales GROUP BY month",
    "orders per day": "SELECT day, COUNT(*) AS orders FROM orders_tbl GROUP BY day",
}


class _EvalUserResolver(UserResolver):
    """Always resolves the deterministic evaluation user."""

    async def resolve_user(self, request_context: RequestContext) -> User:
        return User(
            id="eval_user",
            username="evaluator",
            email="eval@example.com",
            group_memberships=["user", "analyst"],
        )


def build_variant() -> AgentVariant:
    """Build the scripted agent variant (mirrors llm_comparison.py shape)."""
    agent = Agent(
        llm_service=ScriptedLlmService(SCRIPTED),
        tool_registry=ToolRegistry(),
        user_resolver=_EvalUserResolver(),
        agent_memory=DemoAgentMemory(),
        config=AgentConfig(),
    )
    return AgentVariant(
        name="scripted-offline",
        agent=agent,
        metadata={"provider": "scripted", "mode": "offline"},
    )


async def run_offline_eval(dataset_path: str = DEFAULT_DATASET) -> dict:
    dataset = EvaluationDataset.from_yaml(dataset_path)
    runner = EvaluationRunner(
        evaluators=[OutputEvaluator(), EfficiencyEvaluator()],
        max_concurrency=2,
    )
    report = await runner.compare_agents([build_variant()], dataset.test_cases)
    variant_report = list(report.reports.values())[0]
    return {
        "pass_rate": variant_report.pass_rate(),
        "average_score": variant_report.average_score(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    metrics = asyncio.run(run_offline_eval(args.dataset))
    args.out.write_text(json.dumps(metrics), encoding="utf-8")
    print(json.dumps(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
