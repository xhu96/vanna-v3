"""Regression gates for complete test-module ownership."""

from __future__ import annotations

import re
from pathlib import Path

from run_inventory import load_modules


ROOT = Path(__file__).parents[1]
VALID_LANES = {
    "offline",
    "optional-package",
    "external-service",
    "postgres",
    "manual-harness",
}
IGNORED_DISCOVERY_PARTS = {
    ".git",
    ".tox",
    ".venv",
    "dist",
    "node_modules",
    "storybook-static",
}


def _discovered_modules() -> set[str]:
    return {
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("test_*.py")
        if not (set(path.relative_to(ROOT).parts) & IGNORED_DISCOVERY_PARTS)
    }


def test_every_test_module_has_exactly_one_inventory_entry() -> None:
    entries = load_modules()
    paths = [entry["path"] for entry in entries]

    assert len(paths) == len(set(paths)), "test inventory contains duplicate paths"
    assert set(paths) == _discovered_modules()


def test_inventory_entries_have_explicit_lane_owner_and_reason() -> None:
    for entry in load_modules():
        assert entry["lane"] in VALID_LANES
        assert entry["reason"].strip()
        assert entry["owners"]
        if entry["lane"] == "offline":
            assert "tox:py311-offline" in entry["owners"]
        if entry["lane"] == "external-service":
            assert any(owner.startswith("manual:") for owner in entry["owners"])


def test_declared_tox_and_workflow_owners_exist() -> None:
    tox_config = (ROOT / "tox.ini").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8"
    )

    for entry in load_modules():
        for owner in entry["owners"]:
            kind, name = owner.split(":", 1)
            if kind == "tox":
                assert f"[testenv:{name}]" in tox_config, (
                    f"{entry['path']} names missing tox owner {name}"
                )
            elif kind == "workflow":
                assert re.search(
                    rf"^  {re.escape(name)}:\s*$", workflow, re.MULTILINE
                ), f"{entry['path']} names missing workflow owner {name}"
            else:
                assert kind == "manual"


def test_default_tox_envlist_is_hermetic() -> None:
    tox_config = (ROOT / "tox.ini").read_text(encoding="utf-8")
    envlist_match = re.search(
        r"(?ms)^envlist\s*=\s*\n(?P<body>.*?)(?=^\s*\n|^\[)", tox_config
    )
    assert envlist_match is not None

    default_envs = {
        line.strip()
        for line in envlist_match.group("body").splitlines()
        if line.strip() and not line.lstrip().startswith(("#", ";"))
    }
    assert default_envs == {
        "ruff",
        "mypy",
        "py311-test-inventory",
        "py311-offline",
    }
