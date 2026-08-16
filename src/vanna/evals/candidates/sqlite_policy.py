"""Hermetic candidate that exercises the production SQL policy/tool stack."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
import weakref
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, AsyncGenerator, List, Mapping, Sequence, cast

from vanna import Agent, AgentConfig
from vanna.core.evaluation import AgentVariant
from vanna.core.llm import LlmRequest, LlmResponse, LlmService, LlmStreamChunk
from vanna.core.registry import ToolRegistry
from vanna.core.tool import ToolCall, ToolContext, ToolSchema
from vanna.core.user import User
from vanna.core.user.request_context import RequestContext
from vanna.core.user.resolver import UserResolver
from vanna.integrations.local import LocalFileSystem
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.sqlite import SqliteRunner
from vanna.security.rls import RowFilterPolicy
from vanna.security.sql_policy import SqlPolicyViolation, SqlQueryPolicy
from vanna.tools import RunSqlTool

CANDIDATE_NAME = "v3-sqlite-policy-stack"


@dataclass(frozen=True)
class _QueryIntent:
    source: str
    dimension: str
    aggregate: str
    column: str
    output_alias: str

    def to_sql(self) -> str:
        expression = (
            "COUNT(*)"
            if self.aggregate == "count" and self.column == "*"
            else f"{self.aggregate.upper()}({self.column})"
        )
        return (
            f"SELECT {self.dimension}, {expression} AS {self.output_alias} "
            f"FROM {self.source} GROUP BY {self.dimension} "
            f"ORDER BY {self.dimension}"
        )


def _catalog_bytes() -> bytes:
    return (
        files("vanna.evals.fixtures")
        .joinpath("sqlite_semantic_catalog.json")
        .read_bytes()
    )


@lru_cache(maxsize=1)
def _semantic_catalog() -> Mapping[str, Any]:
    value: object = json.loads(_catalog_bytes())
    if not isinstance(value, dict):
        raise ValueError("offline semantic catalog must be an object")
    return cast(Mapping[str, Any], value)


def _catalog_entries(name: str) -> Sequence[Mapping[str, Any]]:
    entries = _semantic_catalog().get(name)
    if not isinstance(entries, list) or not all(
        isinstance(entry, dict) for entry in entries
    ):
        raise ValueError(f"offline semantic catalog {name} are invalid")
    return cast(Sequence[Mapping[str, Any]], entries)


def _contains_alias(question: str, raw_aliases: Any) -> bool:
    if not isinstance(raw_aliases, list):
        raise ValueError("offline semantic aliases must be a list")
    normalized = " ".join(re.findall(r"[a-z0-9]+", question.casefold()))
    return any(
        isinstance(alias, str)
        and alias
        and re.search(
            rf"(?:^|\s){re.escape(' '.join(alias.casefold().split()))}(?:$|\s)",
            normalized,
        )
        is not None
        for alias in raw_aliases
    )


def _intent_for(question: str) -> _QueryIntent:
    dimensions = [
        entry
        for entry in _catalog_entries("dimensions")
        if _contains_alias(question, entry.get("aliases"))
    ]
    if len(dimensions) != 1:
        raise ValueError("offline evaluation question has ambiguous dimensions")
    dimension = dimensions[0].get("name")
    if not isinstance(dimension, str):
        raise ValueError("offline semantic dimension name is invalid")

    metrics = [
        entry
        for entry in _catalog_entries("metrics")
        if _contains_alias(question, entry.get("aliases"))
        and dimension in entry.get("dimensions", ())
    ]
    if len(metrics) != 1:
        raise ValueError("offline evaluation question has ambiguous metrics")
    metric = metrics[0]
    source = metric.get("source")
    aggregate = metric.get("aggregate")
    column = metric.get("column")
    if (
        not isinstance(source, str)
        or not source
        or not isinstance(aggregate, str)
        or not aggregate
        or not isinstance(column, str)
        or not column
    ):
        raise ValueError("offline semantic metric definition is invalid")
    output_alias = (
        "orders"
        if aggregate == "count"
        else ("revenue" if dimension == "month" else "total")
    )
    return _QueryIntent(source, dimension, aggregate, column, output_alias)


def _tenant_row_policies(context: ToolContext) -> tuple[RowFilterPolicy, ...]:
    tenant_id = context.user.metadata.get("tenant_id")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise SqlPolicyViolation("Offline evaluation requires a trusted tenant")
    return (
        RowFilterPolicy(
            column="tenant_id",
            value=tenant_id,
            tables=frozenset({"sales", "orders_tbl"}),
        ),
    )


def _query_policy() -> SqlQueryPolicy:
    return SqlQueryPolicy(
        "sqlite",
        row_policies=_tenant_row_policies,
        require_row_policies=True,
    )


class _EvalUserResolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        user = request_context.metadata.get("test_case_user")
        if not isinstance(user, User):
            raise ValueError("offline evaluation requires a typed test user")
        metadata = {**user.metadata, "tenant_id": "offline-eval"}
        return user.model_copy(update={"authenticated": True, "metadata": metadata})


class _SqlToolDriver(LlmService):
    """Resolve a catalogued intent while requiring real policy/tool execution."""

    @staticmethod
    def _query_for(request: LlmRequest) -> str:
        question = ""
        for message in request.messages:
            if message.role == "user":
                question = message.content.casefold()
        return _intent_for(question).to_sql()

    @staticmethod
    def _has_tool_result(request: LlmRequest) -> bool:
        return any(message.role == "tool" for message in request.messages)

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        sql = self._query_for(request)
        if self._has_tool_result(request):
            return LlmResponse(
                content=f"Validated SQL:\n```sql\n{sql}\n```",
                finish_reason="stop",
            )

        tool_names = {
            tool.name for tool in (request.tools or []) if isinstance(tool, ToolSchema)
        }
        if "run_sql" not in tool_names:
            raise RuntimeError("checked candidate did not expose run_sql")
        return LlmResponse(
            tool_calls=[
                ToolCall(
                    id="offline-run-sql",
                    name="run_sql",
                    arguments={"sql": sql},
                )
            ],
            finish_reason="tool_calls",
        )

    async def stream_request(
        self, request: LlmRequest
    ) -> AsyncGenerator[LlmStreamChunk, None]:
        response = await self.send_request(request)
        yield LlmStreamChunk(
            content=response.content,
            tool_calls=response.tool_calls,
            finish_reason=response.finish_reason,
        )

    async def validate_tools(self, tools: List[ToolSchema]) -> List[str]:
        return [] if any(tool.name == "run_sql" for tool in tools) else ["run_sql"]


def _create_fixture(database: Path) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            """
            CREATE TABLE sales (
                tenant_id TEXT NOT NULL,
                region TEXT NOT NULL,
                month TEXT NOT NULL,
                amount REAL NOT NULL
            );
            INSERT INTO sales(tenant_id, region, month, amount) VALUES
                ('offline-eval', 'north', '2026-01', 10.0),
                ('offline-eval', 'south', '2026-01', 20.0),
                ('offline-eval', 'north', '2026-02', 30.0),
                ('other-tenant', 'north', '2026-01', 10000.0);
            CREATE TABLE orders_tbl (
                tenant_id TEXT NOT NULL,
                day TEXT NOT NULL
            );
            INSERT INTO orders_tbl(tenant_id, day) VALUES
                ('offline-eval', '2026-01-01'),
                ('offline-eval', '2026-01-01'),
                ('offline-eval', '2026-01-02'),
                ('other-tenant', '2026-01-01');
            """
        )
        connection.commit()
    finally:
        connection.close()


def build_variant() -> AgentVariant:
    """Build the exact candidate selected by the CI regression recipe."""

    workspace = Path(tempfile.mkdtemp(prefix="vanna-v3-eval-"))
    database = workspace / "eval.sqlite3"
    _create_fixture(database)

    registry = ToolRegistry()
    registry.register_local_tool(
        RunSqlTool(
            sql_runner=SqliteRunner(str(database), read_only=True),
            file_system=LocalFileSystem(str(workspace / "artifacts")),
            query_policy=_query_policy(),
        ),
        access_groups=["analyst"],
    )
    agent = Agent(
        llm_service=_SqlToolDriver(),
        tool_registry=registry,
        user_resolver=_EvalUserResolver(),
        agent_memory=DemoAgentMemory(),
        config=AgentConfig(
            stream_responses=False,
            auto_save_conversations=False,
            max_tool_iterations=2,
        ),
    )
    weakref.finalize(agent, shutil.rmtree, workspace, True)
    return AgentVariant(
        name=CANDIDATE_NAME,
        agent=agent,
        metadata={
            "mode": "offline",
            "provider": "deterministic-catalog-driver",
            "sql_dialect": "sqlite",
            "native_read_only": True,
            "tenant_row_policy": "required",
            "semantic_catalog_sha256": hashlib.sha256(_catalog_bytes()).hexdigest(),
            "stack": [
                "Agent",
                "ToolRegistry",
                "RunSqlTool",
                "SqlQueryPolicy",
                "SqliteRunner",
            ],
        },
    )
