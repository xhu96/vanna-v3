"""Offline training gate that blocks promotion when evals regress."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_metrics(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "pass_rate": float(data.get("pass_rate", 0.0)),
        "avg_score": float(data.get("average_score", 0.0)),
    }


def gate(baseline: dict, candidate: dict, min_score_delta: float = 0.0) -> bool:
    if candidate["pass_rate"] < baseline["pass_rate"]:
        return False
    if candidate["avg_score"] < (baseline["avg_score"] + min_score_delta):
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--min-score-delta", type=float, default=0.0)
    args = parser.parse_args()

    baseline = load_metrics(args.baseline)
    candidate = load_metrics(args.candidate)
    passed = gate(
        baseline=baseline,
        candidate=candidate,
        min_score_delta=args.min_score_delta,
    )
    print(
        json.dumps(
            {
                "baseline": baseline,
                "candidate": candidate,
                "gate_passed": passed,
            }
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

