"""Execute a supplied candidate agent stack against a fixed offline dataset."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from vanna.evals.offline import (
    DEFAULT_DATASET,
    _EvalUserResolver,
    build_reference_variant,
    load_candidate_factory,
    load_training_manifest,
    run_offline_eval,
)
from vanna.evals.training_data import load_training_export

# These names remain importable for existing local evaluation integrations.
__all__ = [
    "DEFAULT_DATASET",
    "_EvalUserResolver",
    "build_reference_variant",
    "load_candidate_factory",
    "load_training_export",
    "load_training_manifest",
    "run_offline_eval",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--candidate-factory", required=True)
    parser.add_argument("--approved-feedback-manifest", type=Path)
    parser.add_argument("--approved-feedback", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    candidate = load_candidate_factory(args.candidate_factory)
    if bool(args.approved_feedback_manifest) != bool(args.approved_feedback):
        parser.error(
            "--approved-feedback-manifest and --approved-feedback must be supplied together"
        )
    training_manifest = None
    if args.approved_feedback_manifest and args.approved_feedback:
        training_manifest = load_training_export(
            args.approved_feedback_manifest,
            args.approved_feedback,
        )
    metrics = asyncio.run(
        run_offline_eval(
            args.dataset,
            candidate=candidate,
            training_manifest=training_manifest,
        )
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(metrics, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(metrics, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
