"""Offline evaluation execution and fail-closed promotion gates."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import sys
import types
from pathlib import Path
from typing import Any

import pytest

import vanna.evals.candidates.sqlite_policy as sqlite_policy_candidate

from vanna import Agent, AgentConfig
from vanna.core import LlmMessage, LlmRequest
from vanna.core.evaluation import (
    AgentResult,
    AgentVariant,
    LLMAsJudgeEvaluator,
    TestCase as EvaluationTestCase,
)
from vanna.capabilities.sql_runner import RunSqlToolArgs
from vanna.core.recovery import ErrorRecoveryStrategy
from vanna.core.registry import ToolRegistry
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.local import LocalFileSystem
from vanna.integrations.mock.scripted_llm import ScriptedLlmService
from vanna.integrations.sqlite import SqliteRunner
from vanna.evals.candidates.sqlite_policy import (
    _SqlToolDriver,
    _create_fixture,
    _query_policy,
    build_variant,
)
from vanna.security.sql_policy import SqlPolicyViolation, SqlQueryPolicy
from vanna.tools import RunSqlTool

ROOT = Path(__file__).parents[1]
DATASET = ROOT / "src/evals/datasets/sql_generation/offline_smoke.yaml"


def load_script(name: str, relative_path: str) -> Any:
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def runner_module() -> Any:
    return load_script(
        "vanna_offline_eval",
        "src/evals/pipelines/run_offline_eval.py",
    )


@pytest.fixture
def gate_module() -> Any:
    return load_script(
        "vanna_offline_gate",
        "src/evals/pipelines/offline_training_gate.py",
    )


def bad_variant(runner_module: Any) -> AgentVariant:
    agent = Agent(
        llm_service=ScriptedLlmService({}, default="This answer has no query"),
        tool_registry=ToolRegistry(),
        user_resolver=runner_module._EvalUserResolver(),
        agent_memory=DemoAgentMemory(),
        config=AgentConfig(stream_responses=False, auto_save_conversations=False),
    )
    return AgentVariant(name="supplied-bad-candidate", agent=agent)


def valid_metrics() -> dict[str, Any]:
    return {
        "schema_version": "vanna-eval-metrics-v1",
        "candidate": {"name": "candidate-under-test", "metadata": {}},
        "dataset": {
            "name": "fixed",
            "sha256": "a" * 64,
            "case_count": 2,
        },
        "aggregate": {
            "case_count": 2,
            "pass_rate": 0.5,
            "average_score": 0.6,
        },
        "slices": {
            "a": {"case_count": 1, "pass_rate": 1.0, "average_score": 0.8},
            "b": {"case_count": 1, "pass_rate": 0.0, "average_score": 0.4},
        },
    }


def evaluated_gate(
    gate_module: Any,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Supply metrics produced by the test's simulated fresh candidate run."""

    kwargs.setdefault("recomputed_candidate", copy.deepcopy(candidate))
    return gate_module.evaluate_gate(baseline, candidate, **kwargs)


def approved_training_content() -> bytes:
    record = {
        "feedback_id": "fb_approved",
        "tenant_scope": "tenant:acme",
        "user_id": "analyst-1",
        "rating": "down",
        "question": "Show revenue",
        "corrected_sql": "SELECT SUM(amount) FROM sales",
        "correction_validated": True,
        "conversation_id": "conversation-1",
        "request_id": "request-1",
        "created_at": "2026-08-11T11:00:00Z",
        "memory_patch_status": "applied",
        "review_status": "approved",
        "reviewer_id": "reviewer-1",
        "reviewed_at": "2026-08-11T12:00:00Z",
    }
    return (json.dumps(record, sort_keys=True) + "\n").encode()


def approved_training_manifest(content: bytes | None = None) -> dict[str, Any]:
    content = content if content is not None else approved_training_content()
    return {
        "schema_version": "vanna-feedback-export-v1",
        "tenant_scope": "tenant:acme",
        "generated_at": "2026-08-11T12:00:00Z",
        "record_count": 1,
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "feedback_ids": ["fb_approved"],
    }


@pytest.mark.asyncio
async def test_scripted_llm_returns_mapped_answer() -> None:
    llm = ScriptedLlmService(
        responses={
            "total sales by region": "SELECT region, SUM(amount) FROM sales GROUP BY region"
        },
        default="SELECT 1",
    )
    request = LlmRequest(
        user=User(id="u1", group_memberships=["user"]),
        messages=[LlmMessage(role="user", content="show me total sales by region")],
    )

    response = await llm.send_request(request)

    assert "SELECT" in response.content and "region" in response.content


@pytest.mark.asyncio
async def test_eval_and_default_recovery_redact_exception_values() -> None:
    secret = "postgresql://admin:secret@db/internal"

    class ExplodingJudge(ScriptedLlmService):
        async def send_request(self, request: LlmRequest):  # type: ignore[no-untyped-def]
            del request
            raise RuntimeError(secret)

    user = User(id="u1", authenticated=True)
    test_case = EvaluationTestCase(id="redaction", user=user, message="question")
    result = await LLMAsJudgeEvaluator(ExplodingJudge({}), "be correct").evaluate(
        test_case,
        AgentResult(test_case_id="redaction", components=[]),
    )
    context = ToolContext(
        user=user,
        conversation_id="conversation",
        request_id="request",
        agent_memory=DemoAgentMemory(),
    )
    strategy = ErrorRecoveryStrategy()
    tool_recovery = await strategy.handle_tool_error(RuntimeError(secret), context)
    llm_recovery = await strategy.handle_llm_error(
        RuntimeError(secret),
        LlmRequest(user=user, messages=[]),
    )

    assert secret not in result.reasoning
    assert secret not in tool_recovery.message
    assert secret not in llm_recovery.message


@pytest.mark.asyncio
async def test_runner_executes_the_supplied_candidate(runner_module: Any) -> None:
    reference = await runner_module.run_offline_eval(
        str(DATASET),
        candidate=runner_module.build_reference_variant(),
    )
    candidate = await runner_module.run_offline_eval(
        str(DATASET),
        candidate=bad_variant(runner_module),
    )

    assert candidate["candidate"]["name"] == "supplied-bad-candidate"
    assert candidate["dataset"] == reference["dataset"]
    assert candidate["aggregate"]["pass_rate"] == 0.0
    assert candidate["aggregate"]["average_score"] < 1.0
    assert (
        candidate["aggregate"]["average_score"]
        < reference["aggregate"]["average_score"]
    )
    assert set(candidate["slices"]) == {"aggregation", "counting", "time_series"}


@pytest.mark.asyncio
async def test_checked_candidate_executes_real_sql_tool_trajectory(
    runner_module: Any,
) -> None:
    metrics = await runner_module.run_offline_eval(
        str(DATASET),
        candidate=build_variant(),
    )

    assert metrics["candidate"]["name"] == "v3-sqlite-policy-stack"
    assert metrics["candidate"]["metadata"]["native_read_only"] is True
    assert metrics["aggregate"] == {
        "case_count": 6,
        "pass_rate": 1.0,
        "average_score": 1.0,
    }


@pytest.mark.asyncio
async def test_checked_candidate_generalizes_and_executes_tenant_scoped_sql(
    tmp_path: Path,
) -> None:
    request = LlmRequest(
        user=User(id="eval", authenticated=True),
        messages=[
            LlmMessage(
                role="user",
                content="Please compare revenue across territories",
            )
        ],
    )
    generated = _SqlToolDriver._query_for(request)
    probes = {
        "Provide the sum of transaction values grouped by area": "GROUP BY region",
        "List turnover for each geographic zone": "GROUP BY region",
        "How many purchases were placed on each calendar date?": "GROUP BY day",
    }
    for prompt, expected_sql in probes.items():
        request = LlmRequest(
            user=User(id="eval", authenticated=True),
            messages=[LlmMessage(role="user", content=prompt)],
        )
        assert expected_sql in _SqlToolDriver._query_for(request)

    generated = _SqlToolDriver._query_for(
        LlmRequest(
            user=User(id="eval", authenticated=True),
            messages=[
                LlmMessage(
                    role="user",
                    content="Please compare revenue across territories",
                )
            ],
        )
    )
    assert "GROUP BY region" in generated

    database = tmp_path / "eval.sqlite3"
    _create_fixture(database)
    context = ToolContext(
        user=User(
            id="eval",
            authenticated=True,
            metadata={"tenant_id": "offline-eval"},
            group_memberships=["analyst"],
        ),
        conversation_id="eval-conversation",
        request_id="eval-request",
        agent_memory=DemoAgentMemory(),
    )
    policy = _query_policy()
    prepared = policy.prepare(generated, context)
    assert "tenant_id = 'offline-eval'" in prepared

    tool = RunSqlTool(
        sql_runner=SqliteRunner(str(database), read_only=True),
        file_system=LocalFileSystem(str(tmp_path / "artifacts")),
        query_policy=policy,
    )
    result = await tool.execute(context, RunSqlToolArgs(sql=generated))

    assert result.success is True
    assert result.metadata["results"] == [
        {"region": "north", "total": 40.0},
        {"region": "south", "total": 20.0},
    ]
    assert "10000" not in str(result.metadata["results"])
    assert "tenant_id = 'offline-eval'" in result.metadata["executed_sql"]

    missing_tenant = context.model_copy(
        update={"user": context.user.model_copy(update={"metadata": {}})}
    )
    with pytest.raises(SqlPolicyViolation, match="trusted tenant"):
        policy.prepare(generated, missing_tenant)


@pytest.mark.asyncio
async def test_offline_eval_fails_when_tenant_rls_is_removed(
    runner_module: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sqlite_policy_candidate,
        "_query_policy",
        lambda: SqlQueryPolicy(
            "sqlite",
            row_policies=(),
            require_row_policies=False,
        ),
    )

    metrics = await runner_module.run_offline_eval(
        str(DATASET),
        candidate=sqlite_policy_candidate.build_variant(),
    )

    assert metrics["aggregate"]["pass_rate"] == 0.0
    assert metrics["aggregate"]["average_score"] < 1.0
    assert all(item["pass_rate"] == 0.0 for item in metrics["slices"].values())


def test_candidate_factory_loads_exact_variant(
    runner_module: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = bad_variant(runner_module)
    module = types.ModuleType("local_eval_candidate")
    module.build = lambda: expected
    monkeypatch.setitem(sys.modules, module.__name__, module)

    assert (
        runner_module.load_candidate_factory("local_eval_candidate:build") is expected
    )

    module.build = lambda: object()
    with pytest.raises(TypeError, match="AgentVariant"):
        runner_module.load_candidate_factory("local_eval_candidate:build")
    with pytest.raises(ValueError, match="module:callable"):
        runner_module.load_candidate_factory("invalid")


def test_training_manifest_loader_rejects_unapproved_shape(
    runner_module: Any,
    tmp_path: Path,
) -> None:
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(approved_training_manifest()))
    assert runner_module.load_training_manifest(valid) == approved_training_manifest()

    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"schema_version": "vanna-feedback-export-v1"}')
    with pytest.raises(ValueError, match="shape"):
        runner_module.load_training_manifest(malformed)


def test_training_export_is_bound_to_exact_approved_jsonl(
    runner_module: Any,
    tmp_path: Path,
) -> None:
    content = approved_training_content()
    manifest = tmp_path / "approved.manifest.json"
    records = tmp_path / "approved.jsonl"
    manifest.write_text(json.dumps(approved_training_manifest(content)))
    records.write_bytes(content)

    assert runner_module.load_training_export(manifest, records) == (
        approved_training_manifest(content)
    )

    records.write_bytes(content.replace(b"tenant:acme", b"tenant:evil"))
    with pytest.raises(ValueError, match="digest"):
        runner_module.load_training_export(manifest, records)


def test_ci_promotion_fixture_is_approved_and_content_bound(
    runner_module: Any,
) -> None:
    fixture = ROOT / "src/evals/fixtures"

    manifest = runner_module.load_training_export(
        fixture / "approved_feedback.manifest.json",
        fixture / "approved_feedback.jsonl",
    )

    assert manifest["record_count"] == 1
    assert manifest["feedback_ids"] == ["fb_ci_approved"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pass_rate", None),
        ("pass_rate", True),
        ("pass_rate", math.nan),
        ("average_score", math.inf),
        ("average_score", -0.01),
        ("average_score", 1.01),
    ],
)
def test_metrics_reject_missing_nonfinite_or_out_of_range_values(
    gate_module: Any,
    field: str,
    value: object,
) -> None:
    metrics = valid_metrics()
    metrics["aggregate"][field] = value

    with pytest.raises(gate_module.MetricsValidationError):
        gate_module.validate_metrics(metrics)


def test_metrics_reject_missing_slices_or_count_manipulation(gate_module: Any) -> None:
    missing = valid_metrics()
    missing["slices"] = {}
    with pytest.raises(gate_module.MetricsValidationError, match="slice"):
        gate_module.validate_metrics(missing)

    duplicated = valid_metrics()
    duplicated["slices"]["extra"] = {
        "case_count": 1,
        "pass_rate": 1.0,
        "average_score": 1.0,
    }
    with pytest.raises(gate_module.MetricsValidationError, match="partition"):
        gate_module.validate_metrics(duplicated)

    forged = valid_metrics()
    forged["aggregate"]["pass_rate"] = 1.0
    with pytest.raises(gate_module.MetricsValidationError, match="weighted"):
        gate_module.validate_metrics(forged)


def test_metrics_require_bounded_candidate_identity(gate_module: Any) -> None:
    missing = valid_metrics()
    missing.pop("candidate")
    with pytest.raises(gate_module.MetricsValidationError, match="candidate"):
        gate_module.validate_metrics(missing)

    non_finite = valid_metrics()
    non_finite["candidate"]["metadata"] = {"score": math.nan}
    with pytest.raises(gate_module.MetricsValidationError, match="finite JSON"):
        gate_module.validate_metrics(non_finite)


def test_gate_rejects_dataset_aggregate_and_slice_regressions(gate_module: Any) -> None:
    baseline = valid_metrics()

    dataset_change = copy.deepcopy(baseline)
    dataset_change["dataset"]["sha256"] = "b" * 64
    assert evaluated_gate(gate_module, baseline, dataset_change, mode="check") == {
        "passed": False,
        "reasons": ["dataset_mismatch"],
        "improvements": [],
    }

    aggregate_regression = copy.deepcopy(baseline)
    aggregate_regression["aggregate"]["average_score"] = 0.5
    aggregate_regression["slices"]["a"]["average_score"] = 0.6
    result = evaluated_gate(gate_module, baseline, aggregate_regression, mode="check")
    assert "aggregate_regression:average_score" in result["reasons"]

    slice_regression = copy.deepcopy(baseline)
    slice_regression["slices"]["a"]["average_score"] = 0.7
    slice_regression["aggregate"]["average_score"] = 0.55
    result = evaluated_gate(gate_module, baseline, slice_regression, mode="check")
    assert "slice_regression:a:average_score" in result["reasons"]


def test_gate_rejects_missing_or_recounted_baseline_slice(gate_module: Any) -> None:
    baseline = valid_metrics()
    missing = copy.deepcopy(baseline)
    missing["slices"] = {"b": {"case_count": 2, "pass_rate": 0.5, "average_score": 0.6}}
    result = evaluated_gate(gate_module, baseline, missing, mode="check")
    assert "missing_slice:a" in result["reasons"]
    assert "slice_case_count_changed:b" in result["reasons"]


def test_check_allows_equality_but_promotion_requires_improvement(
    gate_module: Any,
) -> None:
    baseline = valid_metrics()

    assert evaluated_gate(gate_module, baseline, baseline, mode="check")["passed"]
    promotion = evaluated_gate(gate_module, baseline, baseline, mode="promote")
    assert not promotion["passed"]
    assert promotion["reasons"] == [
        "missing_approved_training_provenance",
        "no_quality_improvement",
    ]


def test_promotion_requires_improvement_without_any_slice_regression(
    gate_module: Any,
) -> None:
    baseline = valid_metrics()
    candidate = copy.deepcopy(baseline)
    candidate["aggregate"]["pass_rate"] = 1.0
    candidate["slices"]["b"]["pass_rate"] = 1.0
    candidate["training_data"] = approved_training_manifest()

    result = evaluated_gate(
        gate_module,
        baseline,
        candidate,
        mode="promote",
        approved_feedback_content=approved_training_content(),
        expected_candidate_name="candidate-under-test",
    )

    assert result == {
        "passed": True,
        "reasons": [],
        "improvements": ["aggregate:pass_rate"],
    }


def test_promotion_rejects_empty_or_malformed_training_provenance(
    gate_module: Any,
) -> None:
    baseline = valid_metrics()
    candidate = copy.deepcopy(baseline)
    candidate["aggregate"]["pass_rate"] = 1.0
    candidate["slices"]["b"]["pass_rate"] = 1.0
    candidate["training_data"] = {
        **approved_training_manifest(),
        "record_count": 0,
        "feedback_ids": [],
    }
    result = evaluated_gate(gate_module, baseline, candidate, mode="promote")
    assert "missing_approved_training_provenance" in result["reasons"]

    candidate["training_data"] = {
        **approved_training_manifest(),
        "content_sha256": "not-a-hash",
    }
    with pytest.raises(gate_module.MetricsValidationError, match="content_sha256"):
        evaluated_gate(gate_module, baseline, candidate, mode="promote")


def test_promotion_rejects_missing_tampered_or_cross_tenant_export(
    gate_module: Any,
) -> None:
    baseline = valid_metrics()
    candidate = copy.deepcopy(baseline)
    candidate["aggregate"]["pass_rate"] = 1.0
    candidate["slices"]["b"]["pass_rate"] = 1.0
    candidate["training_data"] = approved_training_manifest()

    missing = evaluated_gate(gate_module, baseline, candidate, mode="promote")
    assert "missing_approved_training_artifact" in missing["reasons"]

    tampered = evaluated_gate(
        gate_module,
        baseline,
        candidate,
        mode="promote",
        approved_feedback_content=approved_training_content() + b"{}\n",
    )
    assert "approved_training_artifact_mismatch" in tampered["reasons"]

    cross_tenant_content = approved_training_content().replace(
        b"tenant:acme", b"tenant:evil"
    )
    candidate["training_data"] = approved_training_manifest(cross_tenant_content)
    cross_tenant = evaluated_gate(
        gate_module,
        baseline,
        candidate,
        mode="promote",
        approved_feedback_content=cross_tenant_content,
    )
    assert "approved_training_artifact_mismatch" in cross_tenant["reasons"]

    wrong_candidate = evaluated_gate(
        gate_module,
        baseline,
        candidate,
        mode="check",
        expected_candidate_name="required-candidate",
    )
    assert wrong_candidate["reasons"] == ["unexpected_candidate"]


def test_minimum_improvement_is_finite_and_enforced(gate_module: Any) -> None:
    baseline = valid_metrics()
    candidate = copy.deepcopy(baseline)
    candidate["aggregate"]["pass_rate"] = 0.6
    candidate["slices"]["b"]["pass_rate"] = 0.2
    candidate["training_data"] = approved_training_manifest()

    assert not evaluated_gate(
        gate_module,
        baseline,
        candidate,
        mode="promote",
        minimum_improvement=0.2,
        approved_feedback_content=approved_training_content(),
    )["passed"]
    with pytest.raises(gate_module.MetricsValidationError):
        evaluated_gate(
            gate_module,
            baseline,
            candidate,
            minimum_improvement=math.nan,
        )


def test_gate_rejects_coherent_metrics_without_matching_execution(
    gate_module: Any,
) -> None:
    baseline = valid_metrics()
    forged = copy.deepcopy(baseline)
    forged["aggregate"]["pass_rate"] = 1.0
    forged["slices"]["b"]["pass_rate"] = 1.0

    missing = gate_module.evaluate_gate(baseline, forged, mode="check")
    mismatched = gate_module.evaluate_gate(
        baseline,
        forged,
        mode="check",
        recomputed_candidate=baseline,
    )

    assert "missing_candidate_execution_evidence" in missing["reasons"]
    assert "candidate_execution_mismatch" in mismatched["reasons"]
