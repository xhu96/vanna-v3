"""Immutable package identity and build-only release policy."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).parents[1]


def project() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]


def test_python_and_frontend_share_frozen_package_identity() -> None:
    metadata = project()
    package = json.loads(
        (ROOT / "frontends/webcomponent/package.json").read_text(encoding="utf-8")
    )
    lock = json.loads(
        (ROOT / "frontends/webcomponent/package-lock.json").read_text(encoding="utf-8")
    )
    source = (ROOT / "src/vanna/__init__.py").read_text(encoding="utf-8")
    frontend_check = (
        ROOT / "frontends/webcomponent/scripts/sync-version.js"
    ).read_text(encoding="utf-8")
    source_version = re.search(r'^__version__ = "([^"]+)"$', source, re.MULTILINE)

    assert metadata["name"] == "vanna"
    assert package["name"] == "@vanna/webcomponent"
    assert source_version is not None
    assert {
        metadata["version"],
        package["version"],
        lock["packages"][""]["version"],
        source_version.group(1),
    } == {"3.3.0"}
    assert "versions.pyproject !== '3.3.0'" in frontend_check
    assert "versions.pyproject !== '3.0.0'" not in frontend_check


def test_python_floor_classifiers_license_and_fork_urls_are_consistent() -> None:
    metadata = project()

    assert metadata["requires-python"] == ">=3.11"
    for version in ("3.11", "3.12", "3.13", "3.14"):
        assert f"Programming Language :: Python :: {version}" in metadata["classifiers"]
    assert metadata["license"] == {"file": "LICENSE"}
    assert "MIT License" in (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert metadata["urls"]["Repository"] == "https://github.com/xhu96/vanna-v3"
    assert metadata["urls"]["Bug Tracker"].startswith(
        "https://github.com/xhu96/vanna-v3/"
    )
    assert metadata["urls"]["Upstream"] == "https://github.com/vanna-ai/vanna"


def test_aggregate_extras_are_direct_and_parseable() -> None:
    extras = project()["optional-dependencies"]

    for aggregate in ("servers", "all"):
        requirements = [Requirement(value) for value in extras[aggregate]]
        assert requirements
        assert all(requirement.name.lower() != "vanna" for requirement in requirements)

    server_names = {Requirement(value).name.lower() for value in extras["servers"]}
    all_names = {Requirement(value).name.lower() for value in extras["all"]}
    assert server_names <= all_names


def test_release_workflow_cannot_publish_and_verifies_artifacts() -> None:
    workflow = (ROOT / ".github/workflows/python-publish.yaml").read_text(
        encoding="utf-8"
    )
    folded = workflow.casefold()

    assert "gh-action-pypi-publish" not in folded
    assert "twine upload" not in folded
    assert "npm publish" not in folded
    assert "secrets." not in folded
    for required in (
        "python -m build --no-isolation",
        "cmp ",
        "python -m twine check",
        "sha256sum",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        "vanna-3.3.0-verified-no-publish",
        "'build==1.5.0'",
        "'twine==7.0.0'",
        "'flit_core==3.11.0'",
    ):
        assert required in workflow
    assert "runs-on: ubuntu-24.04" in workflow


def test_ci_actions_are_pinned_to_immutable_commits() -> None:
    for workflow_path in sorted((ROOT / ".github/workflows").glob("*.y*ml")):
        workflow = workflow_path.read_text(encoding="utf-8")
        action_refs = re.findall(r"uses:\s+[^\s@]+@([^\s#]+)", workflow)
        assert action_refs, workflow_path
        assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in action_refs), (
            workflow_path,
            action_refs,
        )


def test_ci_declares_supported_python_and_node_matrix() -> None:
    workflow = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")

    assert 'python-version: ["3.11", "3.12", "3.13", "3.14"]' in workflow
    assert 'node-version: "20.19.0"' in workflow
    assert "tests/test_package_metadata.py" in workflow


def test_public_version_lineage_remains_a_documented_release_blocker() -> None:
    migration = (ROOT / "docs/v3/migration-v2-to-v3.md").read_text(encoding="utf-8")

    assert "v3.1.0" in migration and "v3.2.0" in migration
    assert "3.3.0" in migration
    assert "publishing is disabled" in migration.casefold()
