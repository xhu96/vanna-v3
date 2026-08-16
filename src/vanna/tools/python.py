"""Disabled V2 Python-tool compatibility shims.

Vanna v3 core never executes Python or package-manager commands. Deployments that
need code execution must provide a separately administered sandbox service rather
than exposing host execution to the model tool registry.
"""

from __future__ import annotations

from typing import Any, FrozenSet, List, Optional, Sequence, Type

from pydantic import BaseModel, Field

from vanna.components import (
    ComponentType,
    NotificationComponent,
    SimpleTextComponent,
    UiComponent,
)
from vanna.core.tool import (
    ARBITRARY_CODE_EXECUTION_CAPABILITY,
    Tool,
    ToolContext,
    ToolResult,
)

from .file_system import FileSystem, LocalFileSystem

_DISABLED_MESSAGE = (
    "Built-in Python and package execution is disabled in Vanna v3. "
    "Use a separately administered sandbox service outside the core tool registry."
)


class RunPythonFileArgs(BaseModel):
    """Arguments retained for V2 import and schema compatibility."""

    filename: str = Field(
        description="Python file to execute (relative to the workspace root)"
    )
    arguments: Sequence[str] = Field(
        default_factory=list,
        description="Optional arguments to pass to the Python script",
    )
    timeout_seconds: Optional[float] = Field(
        default=None,
        ge=0,
        description="Optional timeout for the command in seconds",
    )


class RunPythonFileTool(Tool[RunPythonFileArgs]):
    """Inert V2 compatibility shim; Vanna v3 core does not execute Python."""

    def __init__(self, file_system: Optional[FileSystem] = None):
        self.file_system = file_system or LocalFileSystem()

    @property
    def name(self) -> str:
        return "run_python_file"

    @property
    def description(self) -> str:
        return "Disabled V2 compatibility shim for Python file execution"

    @property
    def capabilities(self) -> FrozenSet[str]:
        return frozenset({ARBITRARY_CODE_EXECUTION_CAPABILITY})

    def get_args_schema(self) -> Type[RunPythonFileArgs]:
        return RunPythonFileArgs

    async def execute(
        self, context: ToolContext, args: RunPythonFileArgs
    ) -> ToolResult:
        del context, args
        return _disabled_result()


class PipInstallArgs(BaseModel):
    """Arguments retained for V2 import and schema compatibility."""

    packages: List[str] = Field(
        description="Packages (with optional specifiers) to install", min_length=1
    )
    upgrade: bool = Field(
        default=False,
        description="Whether to include --upgrade in the pip invocation",
    )
    extra_args: Sequence[str] = Field(
        default_factory=list,
        description="Additional arguments to pass to pip install",
    )
    timeout_seconds: Optional[float] = Field(
        default=None,
        ge=0,
        description="Optional timeout for the command in seconds",
    )


class PipInstallTool(Tool[PipInstallArgs]):
    """Inert V2 compatibility shim; Vanna v3 core does not install packages."""

    def __init__(self, file_system: Optional[FileSystem] = None):
        self.file_system = file_system or LocalFileSystem()

    @property
    def name(self) -> str:
        return "pip_install"

    @property
    def description(self) -> str:
        return "Disabled V2 compatibility shim for package installation"

    @property
    def capabilities(self) -> FrozenSet[str]:
        return frozenset({ARBITRARY_CODE_EXECUTION_CAPABILITY})

    def get_args_schema(self) -> Type[PipInstallArgs]:
        return PipInstallArgs

    async def execute(self, context: ToolContext, args: PipInstallArgs) -> ToolResult:
        del context, args
        return _disabled_result()


def create_python_tools(file_system: Optional[FileSystem] = None) -> List[Tool[Any]]:
    """Return inert V2 compatibility shims without any execution path."""

    fs = file_system or LocalFileSystem()
    return [RunPythonFileTool(fs), PipInstallTool(fs)]


def _disabled_result() -> ToolResult:
    return ToolResult(
        success=False,
        result_for_llm=_DISABLED_MESSAGE,
        ui_component=UiComponent(
            rich_component=NotificationComponent(
                type=ComponentType.NOTIFICATION,
                level="error",
                message=_DISABLED_MESSAGE,
            ),
            simple_component=SimpleTextComponent(text=_DISABLED_MESSAGE),
        ),
        error=_DISABLED_MESSAGE,
        metadata={"code": "code_execution_disabled"},
    )
