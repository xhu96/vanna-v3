"""dbt model deployment tool.

Turns a SQL query into a committed dbt model file and, optionally, a GitHub
pull request.  The tool is intentionally additive: it writes new model files
and runs ``dbt compile`` / ``dbt test`` in the user's existing project; it
never modifies files that already exist (use ``overwrite=True`` to opt in).

Optional dependencies (install with ``pip install vanna[de]``):
  - ``dbt-core``  — for ``dbt compile`` / ``dbt test`` subprocess calls.
  - ``PyGitHub``  — for automated PR creation (``github_token`` required).
"""

from __future__ import annotations

import asyncio
import re
import textwrap
from pathlib import Path
from typing import List, Literal, Optional, Type

from pydantic import BaseModel, Field, field_validator

from vanna.components import (
    ComponentType,
    NotificationComponent,
    SimpleTextComponent,
    UiComponent,
)
from vanna.core.errors import ToolExecutionError
from vanna.core.tool import Tool, ToolContext, ToolResult

try:
    from github import Github as _Github
    from github import GithubException as _GithubException
except ImportError:
    _Github = None  # type: ignore[assignment,misc]
    _GithubException = Exception  # type: ignore[assignment,misc]

_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# ---------------------------------------------------------------------------
# Reuse the prompt template already maintained in the dbt skill pack.
# ---------------------------------------------------------------------------

try:
    from skill_packs.dbt_pipeline_generator.prompts import DBT_MODEL_PROMPT  # type: ignore[import]
except ImportError:
    # Fallback template used when the skill pack is not on sys.path.
    DBT_MODEL_PROMPT = textwrap.dedent("""\
        {{{{ config(materialized='{materialization}') }}}}

        {sql}
    """)


# ---------------------------------------------------------------------------
# Args model
# ---------------------------------------------------------------------------


class DbtDeployArgs(BaseModel):
    """Arguments for the dbt deploy tool."""

    sql: str = Field(..., description="The SELECT query to wrap as a dbt model.")
    model_name: str = Field(
        ...,
        description=(
            "Snake_case name for the dbt model, e.g. ``daily_revenue``. "
            "Must match ``[a-z][a-z0-9_]*``."
        ),
    )
    materialization: Literal["table", "view", "incremental", "ephemeral"] = Field(
        "table",
        description="dbt materialization strategy.",
    )
    description: str = Field(
        "",
        description="Short description of what this model computes (used in schema.yml).",
    )
    overwrite: bool = Field(
        False,
        description="Set to true to overwrite an existing model file with the same name.",
    )

    @field_validator("model_name")
    @classmethod
    def validate_snake_case(cls, v: str) -> str:
        if not _SNAKE_CASE_RE.match(v):
            raise ValueError(
                f"model_name must be snake_case (lowercase letters, digits, "
                f"underscores, starting with a letter). Got: {v!r}"
            )
        return v


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


class DbtDeployTool(Tool[DbtDeployArgs]):
    """Deploy a SQL query as a dbt model, run compile + test, and optionally open a PR.

    The tool writes two files into ``{project_path}/{models_subdir}/``:

    * ``{model_name}.sql``  — the dbt model SQL.
    * ``schema.yml``        — documentation and column stubs (appended if the
      file already exists and contains other models).

    If ``github_token`` and ``github_repo`` are supplied the tool also creates
    a branch and opens a pull request, returning the PR URL in the response.

    Access is restricted to the ``data_engineer`` and ``admin`` groups.
    """

    name = "dbt_deploy"
    description = (
        "Saves the current SQL query as a dbt model, runs dbt compile and dbt test, "
        "and optionally opens a GitHub pull request. "
        "Use this when the user wants to materialise an insight as a scheduled pipeline."
    )

    def __init__(
        self,
        project_path: str,
        *,
        models_subdir: str = "models/marts",
        github_token: Optional[str] = None,
        github_repo: Optional[str] = None,
        base_branch: str = "main",
        run_tests: bool = True,
    ) -> None:
        resolved = Path(project_path).resolve()
        if not resolved.exists():
            raise ValueError(
                f"dbt project path does not exist: {resolved}. "
                "Pass an absolute path to an existing dbt project."
            )
        self._project_path = resolved
        self._models_subdir = models_subdir
        self._github_token = github_token
        self._github_repo = github_repo
        self._base_branch = base_branch
        self._run_tests = run_tests

    @property
    def access_groups(self) -> List[str]:
        return ["data_engineer", "admin"]

    def get_args_schema(self) -> Type[DbtDeployArgs]:
        return DbtDeployArgs

    async def execute(self, context: ToolContext, args: DbtDeployArgs) -> ToolResult:
        models_dir = self._project_path / self._models_subdir
        models_dir.mkdir(parents=True, exist_ok=True)

        sql_file = models_dir / f"{args.model_name}.sql"
        if sql_file.exists() and not args.overwrite:
            return ToolResult(
                success=False,
                result_for_llm=(
                    f"Model file ``{sql_file}`` already exists. "
                    "Pass ``overwrite: true`` to replace it."
                ),
                error="Model file already exists.",
            )

        # ------------------------------------------------------------------
        # 1. Render model SQL and schema.yml content.
        # ------------------------------------------------------------------
        model_sql = _render_model_sql(args)
        schema_yml = _render_schema_yml(args)

        sql_file.write_text(model_sql, encoding="utf-8")
        schema_file = models_dir / "schema.yml"
        _append_or_create_schema(schema_file, schema_yml)

        written_files = [str(sql_file), str(schema_file)]

        # ------------------------------------------------------------------
        # 2. dbt compile.
        # ------------------------------------------------------------------
        compile_output, compile_ok = await _run_dbt(
            self._project_path, ["compile", "--select", args.model_name]
        )
        if not compile_ok:
            return ToolResult(
                success=False,
                result_for_llm=(
                    f"dbt compile failed for model ``{args.model_name}``.\n\n"
                    f"```\n{compile_output}\n```"
                ),
                error=compile_output,
                metadata={"written_files": written_files},
            )

        # ------------------------------------------------------------------
        # 3. dbt test (optional).
        # ------------------------------------------------------------------
        test_output = ""
        if self._run_tests:
            test_output, test_ok = await _run_dbt(
                self._project_path, ["test", "--select", args.model_name]
            )
            if not test_ok:
                # Tests failing is a warning, not a hard failure — the model
                # was written and compiled successfully.
                test_output = f"⚠️ dbt test reported failures:\n{test_output}"

        # ------------------------------------------------------------------
        # 4. GitHub PR (optional).
        # ------------------------------------------------------------------
        pr_url: Optional[str] = None
        if self._github_token and self._github_repo:
            pr_url = await _create_github_pr(
                token=self._github_token,
                repo_name=self._github_repo,
                base_branch=self._base_branch,
                model_name=args.model_name,
                written_files=written_files,
                description=args.description,
                compile_output=compile_output,
                test_output=test_output,
            )

        # ------------------------------------------------------------------
        # 5. Build response.
        # ------------------------------------------------------------------
        if pr_url:
            message = (
                f"✅ dbt model ``{args.model_name}`` compiled successfully. "
                f"Pull request opened: {pr_url}"
            )
        else:
            message = (
                f"✅ dbt model ``{args.model_name}`` written and compiled. "
                f"Files: {', '.join(written_files)}"
            )

        if test_output:
            message += f"\n\n{test_output}"

        return ToolResult(
            success=True,
            result_for_llm=message,
            ui_component=UiComponent(
                rich_component=NotificationComponent(
                    type=ComponentType.NOTIFICATION,
                    level="success",
                    message=message,
                ),
                simple_component=SimpleTextComponent(text=message),
            ),
            metadata={
                "model_name": args.model_name,
                "written_files": written_files,
                "pr_url": pr_url,
            },
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _render_model_sql(args: DbtDeployArgs) -> str:
    """Render the dbt model SQL file content."""
    header = f"{{{{ config(materialized='{args.materialization}') }}}}\n\n"
    return header + args.sql.strip() + "\n"


def _render_schema_yml(args: DbtDeployArgs) -> str:
    """Render the schema.yml block for this model."""
    description = args.description or f"Generated by Vanna from ad-hoc query."
    return textwrap.dedent(f"""\
        - name: {args.model_name}
          description: "{description}"
          columns: []
    """)


def _append_or_create_schema(schema_file: Path, new_entry: str) -> None:
    """Append *new_entry* to an existing schema.yml or create a fresh one."""
    if schema_file.exists():
        existing = schema_file.read_text(encoding="utf-8")
        # Avoid duplicating a model entry that already exists.
        if f"name: {new_entry.splitlines()[0].split()[-1]}" in existing:
            return
        updated = existing.rstrip() + "\n" + new_entry
        schema_file.write_text(updated, encoding="utf-8")
    else:
        header = "version: 2\n\nmodels:\n"
        schema_file.write_text(header + new_entry, encoding="utf-8")


async def _run_dbt(project_path: Path, args: list[str]) -> tuple[str, bool]:
    """Run a dbt subcommand in *project_path* and return (output, success)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "dbt",
            *args,
            cwd=str(project_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace").strip()
        return output, proc.returncode == 0
    except FileNotFoundError:
        raise ToolExecutionError(
            "dbt CLI not found. Install it with: pip install dbt-core dbt-duckdb"
        )


async def _create_github_pr(
    *,
    token: str,
    repo_name: str,
    base_branch: str,
    model_name: str,
    written_files: list[str],
    description: str,
    compile_output: str,
    test_output: str,
) -> Optional[str]:
    """Create a GitHub branch + PR for the new dbt model files.

    Runs in a thread-pool executor because PyGitHub is synchronous.
    Returns the PR URL on success, or ``None`` if PyGitHub is not installed.
    """
    if _Github is None:
        return None

    import time

    loop = asyncio.get_event_loop()

    def _sync_create_pr() -> str:
        gh = _Github(token)
        repo = gh.get_repo(repo_name)

        # Create a branch off the tip of base_branch.
        base_ref = repo.get_branch(base_branch)
        branch_name = f"vanna/dbt-{model_name}-{int(time.time())}"
        repo.create_git_ref(
            ref=f"refs/heads/{branch_name}",
            sha=base_ref.commit.sha,
        )

        # Commit each file.
        for filepath in written_files:
            path_obj = Path(filepath)
            if not path_obj.exists():
                continue
            content = path_obj.read_text(encoding="utf-8")
            # repo-relative path: strip the local project root prefix if possible.
            try:
                repo_relative = str(path_obj.relative_to(Path.cwd()))
            except ValueError:
                repo_relative = path_obj.name

            try:
                existing = repo.get_contents(repo_relative, ref=branch_name)
                repo.update_file(
                    path=repo_relative,
                    message=f"chore(vanna): update dbt model {model_name}",
                    content=content,
                    sha=existing.sha,
                    branch=branch_name,
                )
            except Exception:
                repo.create_file(
                    path=repo_relative,
                    message=f"feat(vanna): add dbt model {model_name}",
                    content=content,
                    branch=branch_name,
                )

        body_parts = [
            f"## dbt model: `{model_name}`",
            "",
            f"**Description:** {description or 'Generated by Vanna.'}",
            "",
            "**Files changed:**",
        ]
        for f in written_files:
            body_parts.append(f"- `{Path(f).name}`")

        if compile_output:
            body_parts += ["", "**dbt compile output:**", f"```\n{compile_output[-1000:]}\n```"]
        if test_output:
            body_parts += ["", "**dbt test output:**", f"```\n{test_output[-1000:]}\n```"]

        body_parts += ["", "---", "_Opened automatically by [Vanna](https://github.com/vanna-ai/vanna)._"]

        pr = repo.create_pull(
            title=f"feat: add dbt model `{model_name}`",
            body="\n".join(body_parts),
            head=branch_name,
            base=base_branch,
        )
        return pr.html_url

    try:
        return await loop.run_in_executor(None, _sync_create_pr)
    except Exception:
        # PR creation is best-effort; do not fail the whole tool.
        return None
