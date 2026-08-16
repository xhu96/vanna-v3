"""Run test modules from the checked-in ownership inventory."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parents[1]
INVENTORY_PATH = ROOT / "tests" / "test_inventory.toml"


def load_modules() -> list[dict[str, Any]]:
    """Load inventory entries after basic shape validation."""
    payload = tomllib.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    modules = payload.get("modules")
    if payload.get("version") != 1 or not isinstance(modules, list):
        raise ValueError("Unsupported or malformed test inventory")
    return modules


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lane", required=True)
    args, pytest_args = parser.parse_known_args()
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]

    selected = [entry["path"] for entry in load_modules() if entry["lane"] == args.lane]
    if not selected:
        raise SystemExit(f"No test modules are assigned to lane {args.lane!r}")

    command = [sys.executable, "-m", "pytest", *selected, *pytest_args]
    return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
