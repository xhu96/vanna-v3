"""Tests for the dbt deploy tool."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vanna.exceptions import ToolExecutionError
from vanna.core.tool import ToolContext
from vanna.tools.dbt_deploy import (
    DbtDeployArgs,
    DbtDeployTool,
    _append_or_create_schema,
    _render_model_sql,
    _render_schema_yml,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def dbt_project(tmp_path: Path) -> Path:
    """Minimal dbt project directory."""
    (tmp_path / "dbt_project.yml").write_text("name: test_project\nversion: '1.0.0'\n")
    return tmp_path


@pytest.fixture()
def tool(dbt_project: Path) -> DbtDeployTool:
    return DbtDeployTool(project_path=str(dbt_project), run_tests=False)


@pytest.fixture()
def mock_context() -> ToolContext:
    ctx = MagicMock(spec=ToolContext)
    ctx.user = MagicMock()
    ctx.user.id = "user_1"
    ctx.conversation_id = "conv_1"
    return ctx


@pytest.fixture()
def valid_args() -> DbtDeployArgs:
    return DbtDeployArgs(
        sql="SELECT id, amount FROM orders",
        model_name="daily_orders",
        description="Daily order aggregation",
    )


# ---------------------------------------------------------------------------
# DbtDeployArgs validation
# ---------------------------------------------------------------------------


def test_valid_model_name_accepted():
    args = DbtDeployArgs(sql="SELECT 1", model_name="my_model_v2")
    assert args.model_name == "my_model_v2"


@pytest.mark.parametrize(
    "bad_name",
    ["MyModel", "123_model", "model name", "model-name", "", "  "],
)
def test_invalid_model_name_rejected(bad_name: str):
    with pytest.raises(Exception):
        DbtDeployArgs(sql="SELECT 1", model_name=bad_name)


def test_materialization_default():
    args = DbtDeployArgs(sql="SELECT 1", model_name="m")
    assert args.materialization == "table"


# ---------------------------------------------------------------------------
# DbtDeployTool constructor validation
# ---------------------------------------------------------------------------


def test_constructor_rejects_nonexistent_path():
    with pytest.raises(ValueError, match="does not exist"):
        DbtDeployTool(project_path="/no/such/path/at/all")


def test_access_groups_restricted(tool: DbtDeployTool):
    assert set(tool.access_groups) == {"data_engineer", "admin"}


# ---------------------------------------------------------------------------
# File rendering helpers
# ---------------------------------------------------------------------------


def test_render_model_sql_includes_config():
    args = DbtDeployArgs(sql="SELECT 1 AS val", model_name="m", materialization="view")
    rendered = _render_model_sql(args)
    assert "config(materialized='view')" in rendered
    assert "SELECT 1 AS val" in rendered


def test_render_schema_yml_uses_description():
    args = DbtDeployArgs(sql="SELECT 1", model_name="rev_model", description="Revenue")
    yml = _render_schema_yml(args)
    assert "rev_model" in yml
    assert "Revenue" in yml


def test_append_or_create_schema_creates_new_file(tmp_path: Path):
    schema = tmp_path / "schema.yml"
    _append_or_create_schema(schema, "- name: my_model\n  description: test\n  columns: []\n")
    content = schema.read_text()
    assert "version: 2" in content
    assert "my_model" in content


def test_append_or_create_schema_appends_to_existing(tmp_path: Path):
    schema = tmp_path / "schema.yml"
    schema.write_text("version: 2\n\nmodels:\n- name: existing\n  columns: []\n")
    _append_or_create_schema(schema, "- name: new_model\n  columns: []\n")
    content = schema.read_text()
    assert "existing" in content
    assert "new_model" in content


def test_append_or_create_schema_does_not_duplicate(tmp_path: Path):
    schema = tmp_path / "schema.yml"
    entry = "- name: my_model\n  columns: []\n"
    schema.write_text(f"version: 2\n\nmodels:\n{entry}")
    _append_or_create_schema(schema, entry)
    # Should not have a second copy
    assert schema.read_text().count("name: my_model") == 1


# ---------------------------------------------------------------------------
# execute() — happy path with mocked dbt subprocess
# ---------------------------------------------------------------------------


async def test_execute_happy_path(
    tool: DbtDeployTool,
    mock_context: ToolContext,
    valid_args: DbtDeployArgs,
):
    with patch("vanna.tools.dbt_deploy._run_dbt", new_callable=AsyncMock) as mock_dbt:
        mock_dbt.return_value = ("Compiled successfully.", True)
        result = await tool.execute(mock_context, valid_args)

    assert result.success is True
    assert "daily_orders" in result.result_for_llm
    assert result.metadata["model_name"] == "daily_orders"

    # Files should have been written
    written = result.metadata["written_files"]
    assert any("daily_orders.sql" in f for f in written)
    assert any("schema.yml" in f for f in written)
    for path in written:
        assert Path(path).exists()


async def test_execute_dbt_compile_failure_returns_error(
    tool: DbtDeployTool,
    mock_context: ToolContext,
    valid_args: DbtDeployArgs,
):
    with patch("vanna.tools.dbt_deploy._run_dbt", new_callable=AsyncMock) as mock_dbt:
        mock_dbt.return_value = ("Error: model not found.", False)
        result = await tool.execute(mock_context, valid_args)

    assert result.success is False
    assert "compile failed" in result.result_for_llm


async def test_execute_rejects_duplicate_without_overwrite(
    dbt_project: Path,
    mock_context: ToolContext,
    valid_args: DbtDeployArgs,
):
    # Pre-create the file
    models_dir = dbt_project / "models" / "marts"
    models_dir.mkdir(parents=True)
    (models_dir / "daily_orders.sql").write_text("SELECT 1")

    tool = DbtDeployTool(project_path=str(dbt_project), run_tests=False)
    result = await tool.execute(mock_context, valid_args)

    assert result.success is False
    assert "already exists" in result.result_for_llm


async def test_execute_overwrite_flag_replaces_file(
    dbt_project: Path,
    mock_context: ToolContext,
):
    models_dir = dbt_project / "models" / "marts"
    models_dir.mkdir(parents=True)
    (models_dir / "daily_orders.sql").write_text("SELECT 0")

    tool = DbtDeployTool(project_path=str(dbt_project), run_tests=False)
    args = DbtDeployArgs(
        sql="SELECT id FROM orders", model_name="daily_orders", overwrite=True
    )

    with patch("vanna.tools.dbt_deploy._run_dbt", new_callable=AsyncMock) as mock_dbt:
        mock_dbt.return_value = ("OK", True)
        result = await tool.execute(mock_context, args)

    assert result.success is True
    sql_content = (models_dir / "daily_orders.sql").read_text()
    assert "SELECT id FROM orders" in sql_content


# ---------------------------------------------------------------------------
# dbt CLI not installed
# ---------------------------------------------------------------------------


async def test_execute_raises_when_dbt_not_found(
    tool: DbtDeployTool,
    mock_context: ToolContext,
    valid_args: DbtDeployArgs,
):
    # ToolExecutionError propagates — the agent loop will surface it.
    # The tool should not silently swallow it.
    with pytest.raises(ToolExecutionError, match="dbt CLI not found"):
        with patch(
            "vanna.tools.dbt_deploy._run_dbt",
            side_effect=ToolExecutionError("dbt CLI not found"),
        ):
            await tool.execute(mock_context, valid_args)


# ---------------------------------------------------------------------------
# PR URL surfaced in result when provided
# ---------------------------------------------------------------------------


async def test_pr_url_included_in_result(
    dbt_project: Path,
    mock_context: ToolContext,
    valid_args: DbtDeployArgs,
):
    tool = DbtDeployTool(
        project_path=str(dbt_project),
        run_tests=False,
        github_token="tok",
        github_repo="owner/repo",
    )

    with (
        patch("vanna.tools.dbt_deploy._run_dbt", new_callable=AsyncMock) as mock_dbt,
        patch(
            "vanna.tools.dbt_deploy._create_github_pr",
            new_callable=AsyncMock,
            return_value="https://github.com/owner/repo/pull/42",
        ),
    ):
        mock_dbt.return_value = ("OK", True)
        result = await tool.execute(mock_context, valid_args)

    assert result.success is True
    assert "https://github.com/owner/repo/pull/42" in result.result_for_llm
    assert result.metadata["pr_url"] == "https://github.com/owner/repo/pull/42"
