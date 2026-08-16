"""Fail-closed aggregate and per-slice candidate promotion gate."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from pathlib import Path
from typing import Any, Literal, Optional

from vanna.evals.training_data import (
    TrainingDataValidationError,
    validate_training_export_bytes,
    validate_training_manifest,
)
from vanna.evals.offline import (
    DEFAULT_DATASET,
    load_candidate_factory,
    run_offline_eval,
)

SCHEMA_VERSION = "vanna-eval-metrics-v1"
QUALITY_METRICS = ("pass_rate", "average_score")
GateMode = Literal["check", "promote"]


class MetricsValidationError(ValueError):
    """Raised when a metrics artifact cannot be trusted."""


def _finite_score(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MetricsValidationError(f"{label} must be numeric")
    score = float(value)
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise MetricsValidationError(f"{label} must be finite and in [0, 1]")
    return score


def _case_count(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MetricsValidationError(f"{label} must be a positive integer")
    return value


def _metric_group(value: Any, label: str) -> dict[str, float | int]:
    if not isinstance(value, dict):
        raise MetricsValidationError(f"{label} must be an object")
    return {
        "case_count": _case_count(value.get("case_count"), f"{label}.case_count"),
        **{
            metric: _finite_score(value.get(metric), f"{label}.{metric}")
            for metric in QUALITY_METRICS
        },
    }


def _training_data(value: Any) -> dict[str, Any]:
    try:
        return validate_training_manifest(value)
    except TrainingDataValidationError as error:
        raise MetricsValidationError(str(error)) from error


def _candidate(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"name", "metadata"}:
        raise MetricsValidationError("candidate metadata has an invalid shape")
    name = value.get("name")
    metadata = value.get("metadata")
    if not isinstance(name, str) or not name or len(name) > 160:
        raise MetricsValidationError("candidate.name must be a bounded string")
    if not isinstance(metadata, dict) or any(
        not isinstance(key, str) or not key or len(key) > 160 for key in metadata
    ):
        raise MetricsValidationError("candidate.metadata must use bounded string keys")
    try:
        encoded = json.dumps(metadata, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise MetricsValidationError(
            "candidate.metadata must be finite JSON"
        ) from error
    if len(encoded.encode("utf-8")) > 65_536:
        raise MetricsValidationError("candidate.metadata exceeds the size limit")
    return {"name": name, "metadata": json.loads(encoded)}


def validate_metrics(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise MetricsValidationError("metrics schema_version is missing or unsupported")
    candidate = _candidate(value.get("candidate"))
    dataset = value.get("dataset")
    if not isinstance(dataset, dict):
        raise MetricsValidationError("dataset metadata is missing")
    name = dataset.get("name")
    digest = dataset.get("sha256")
    if not isinstance(name, str) or not name:
        raise MetricsValidationError("dataset.name must be non-empty")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise MetricsValidationError("dataset.sha256 must be a lowercase SHA-256")
    normalized_dataset = {
        "name": name,
        "sha256": digest,
        "case_count": _case_count(dataset.get("case_count"), "dataset.case_count"),
    }
    aggregate = _metric_group(value.get("aggregate"), "aggregate")
    if aggregate["case_count"] != normalized_dataset["case_count"]:
        raise MetricsValidationError("aggregate case count does not match the dataset")

    raw_slices = value.get("slices")
    if not isinstance(raw_slices, dict) or not raw_slices:
        raise MetricsValidationError("at least one metrics slice is required")
    slices: dict[str, dict[str, float | int]] = {}
    for slice_name, metrics in raw_slices.items():
        if not isinstance(slice_name, str) or not slice_name or len(slice_name) > 160:
            raise MetricsValidationError("slice names must be bounded strings")
        slices[slice_name] = _metric_group(metrics, f"slices.{slice_name}")
    if sum(int(metrics["case_count"]) for metrics in slices.values()) != int(
        aggregate["case_count"]
    ):
        raise MetricsValidationError("slice counts must partition the aggregate")
    total_cases = int(aggregate["case_count"])
    for metric in QUALITY_METRICS:
        weighted = (
            sum(
                float(metrics[metric]) * int(metrics["case_count"])
                for metrics in slices.values()
            )
            / total_cases
        )
        if not math.isclose(
            weighted,
            float(aggregate[metric]),
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise MetricsValidationError(
                f"aggregate.{metric} does not match weighted slice metrics"
            )

    normalized = {
        "schema_version": SCHEMA_VERSION,
        "candidate": candidate,
        "dataset": normalized_dataset,
        "aggregate": aggregate,
        "slices": slices,
    }
    if "training_data" in value:
        normalized["training_data"] = _training_data(value["training_data"])
    return normalized


def load_metrics(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MetricsValidationError(f"cannot load metrics artifact: {path}") from exc
    return validate_metrics(value)


def evaluate_gate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    mode: GateMode = "promote",
    minimum_improvement: float = 0.0,
    approved_feedback_content: Optional[bytes] = None,
    expected_candidate_name: Optional[str] = None,
    recomputed_candidate: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    baseline = validate_metrics(baseline)
    candidate = validate_metrics(candidate)
    if not math.isfinite(minimum_improvement) or minimum_improvement < 0:
        raise MetricsValidationError(
            "minimum_improvement must be finite and non-negative"
        )
    reasons: list[str] = []
    improvements: list[str] = []
    if baseline["dataset"] != candidate["dataset"]:
        reasons.append("dataset_mismatch")
    if recomputed_candidate is None:
        reasons.append("missing_candidate_execution_evidence")
    elif validate_metrics(recomputed_candidate) != candidate:
        reasons.append("candidate_execution_mismatch")
    if (
        expected_candidate_name is not None
        and candidate["candidate"]["name"] != expected_candidate_name
    ):
        reasons.append("unexpected_candidate")
    if mode == "promote":
        training_data = candidate.get("training_data")
        if training_data is None or training_data["record_count"] < 1:
            reasons.append("missing_approved_training_provenance")
        elif approved_feedback_content is None:
            reasons.append("missing_approved_training_artifact")
        else:
            try:
                validate_training_export_bytes(
                    training_data,
                    approved_feedback_content,
                )
            except TrainingDataValidationError:
                reasons.append("approved_training_artifact_mismatch")
    for metric in QUALITY_METRICS:
        baseline_value = float(baseline["aggregate"][metric])
        candidate_value = float(candidate["aggregate"][metric])
        if candidate_value < baseline_value:
            reasons.append(f"aggregate_regression:{metric}")
        required_delta = minimum_improvement if minimum_improvement > 0 else 0.0
        if candidate_value > baseline_value and (
            candidate_value - baseline_value >= required_delta
        ):
            improvements.append(f"aggregate:{metric}")

    for slice_name, baseline_slice in baseline["slices"].items():
        candidate_slice = candidate["slices"].get(slice_name)
        if candidate_slice is None:
            reasons.append(f"missing_slice:{slice_name}")
            continue
        if candidate_slice["case_count"] != baseline_slice["case_count"]:
            reasons.append(f"slice_case_count_changed:{slice_name}")
        for metric in QUALITY_METRICS:
            if float(candidate_slice[metric]) < float(baseline_slice[metric]):
                reasons.append(f"slice_regression:{slice_name}:{metric}")

    if mode == "promote" and not improvements:
        reasons.append("no_quality_improvement")
    return {
        "passed": not reasons,
        "reasons": sorted(set(reasons)),
        "improvements": improvements,
    }


def gate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    min_score_delta: float = 0.0,
    approved_feedback_content: Optional[bytes] = None,
    recomputed_candidate: Optional[dict[str, Any]] = None,
) -> bool:
    """Compatibility wrapper with production promotion semantics."""

    return bool(
        evaluate_gate(
            baseline,
            candidate,
            mode="promote",
            minimum_improvement=min_score_delta,
            approved_feedback_content=approved_feedback_content,
            recomputed_candidate=recomputed_candidate,
        )["passed"]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--candidate-factory", required=True)
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--mode", choices=("check", "promote"), default="promote")
    parser.add_argument("--approved-feedback", type=Path)
    parser.add_argument("--expected-candidate")
    parser.add_argument(
        "--minimum-improvement",
        "--min-score-delta",
        dest="minimum_improvement",
        type=float,
        default=0.0,
    )
    args = parser.parse_args()

    try:
        baseline = load_metrics(args.baseline)
        candidate = load_metrics(args.candidate)
        candidate_variant = load_candidate_factory(args.candidate_factory)
        recomputed_candidate = asyncio.run(
            run_offline_eval(
                args.dataset,
                candidate=candidate_variant,
                training_manifest=candidate.get("training_data"),
            )
        )
        approved_feedback_content = (
            args.approved_feedback.read_bytes() if args.approved_feedback else None
        )
        result = evaluate_gate(
            baseline,
            candidate,
            mode=args.mode,
            minimum_improvement=args.minimum_improvement,
            approved_feedback_content=approved_feedback_content,
            expected_candidate_name=args.expected_candidate,
            recomputed_candidate=recomputed_candidate,
        )
    except (MetricsValidationError, OSError, TypeError, ValueError) as error:
        result = {
            "passed": False,
            "reasons": ["invalid_metrics_artifact"],
            "detail": str(error),
            "improvements": [],
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
