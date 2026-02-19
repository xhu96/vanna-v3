"""Smoke test: public Postgres + OpenRouter + ad-hoc skill generation.

This script is meant to be run from your own machine/CI runner that has
outbound access to your DB.

Env vars:
  DATABASE_URL             Postgres connection string
  OPENROUTER_API_KEY       OpenRouter key
  OPENROUTER_MODEL         Optional, e.g. openai/gpt-4o-mini
  OPENROUTER_HTTP_REFERER  Optional, recommended by OpenRouter
  OPENROUTER_APP_TITLE     Optional, recommended by OpenRouter

Optional:
  QUESTIONS                JSON list of questions (string) to override defaults

Examples:
  # Using a Neon sample DB (Chinook)
  export DATABASE_URL='postgresql://user:pass@host:5432/chinook'
  export OPENROUTER_API_KEY='...'
  python scripts/public_db_skill_adhoc_smoke.py

  # Using RNAcentral public DB (read-only)
  export DATABASE_URL='postgresql://reader:NWDMCE5xdipIjRrp@hh-pgsql-public.ebi.ac.uk:5432/pfmegrnargs'
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import List

from vanna.core import Agent, ToolRegistry, User
from vanna.core.user.request_context import RequestContext

from vanna.agents.basic import SimpleUserResolver, SimpleAgentMemory

from vanna.integrations.openrouter.llm import OpenRouterLlmService
from vanna.integrations.postgres.sql_runner import PostgresRunner
from vanna.integrations.sqlite.sql_runner import SqliteRunner

from vanna.tools.run_sql import RunSqlTool
from vanna.services.schema_sync import PortableSchemaCatalogService

from vanna.skills.enricher import SkillAdHocContextEnricher, SkillAdHocConfig
from vanna.skills.registry import SkillRegistry
from vanna.skills.stores import InMemorySkillRegistryStore


def _default_questions(database_url: str) -> List[str]:
    url = (database_url or "").lower()
    if "chinook" in url:
        return [
            "Which 10 artists have the most tracks sold? Include total quantity.",
            "What is total revenue by country? Show top 10.",
            "What are the top 5 genres by revenue?",
            "Show monthly revenue trend for 2012 (month, revenue).",
            "Which customers contributed the top 20% of total revenue?",
        ]
    if "dvdrental" in url or "pagila" in url or "sakila" in url:
        return [
            "Who are the top 5 customers by total payment amount?",
            "What are the top 10 film categories by rental count?",
            "Show monthly rental counts for 2005.",
            "Which stores have higher total revenue?",
            "Which actors appear in the most films?",
        ]

    # Generic questions that work on most schemas.
    return [
        "List 10 tables in the database.",
        "For the largest table, show its row count and the top 5 columns by non-null count.",
        "Pick a transactional table and summarize row counts by month if there is a date column.",
    ]


async def _run_one(agent: Agent, question: str) -> str:
    req = RequestContext(request_id=str(uuid.uuid4()), user_id="default", tenant_id=None)
    chunks: List[str] = []

    async for ui in agent.send_message(req, question):
        # Prefer simple text if present.
        sc = getattr(ui, "simple_component", None)
        if sc is not None and hasattr(sc, "text") and isinstance(sc.text, str):
            chunks.append(sc.text)

    return "\n\n".join(chunks[-3:]) if chunks else "(no text output)"


async def main() -> None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise SystemExit("Missing DATABASE_URL")

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("Missing OPENROUTER_API_KEY")

    model = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")

    llm = OpenRouterLlmService(
        api_key=api_key,
        model=model,
        http_referer=os.environ.get("OPENROUTER_HTTP_REFERER"),
        app_title=os.environ.get("OPENROUTER_APP_TITLE"),
    )

    # DB runner + tool
    if db_url.startswith("sqlite://"):
        runner = SqliteRunner(database_path=db_url.replace("sqlite://", ""))
        dialect = "sqlite"
    else:
        runner = PostgresRunner(connection_string=db_url)
        dialect = "postgres"
    run_sql_tool = RunSqlTool(sql_runner=runner, read_only=True)

    tool_registry = ToolRegistry()
    tool_registry.register_local_tool(run_sql_tool, access_groups=[])

    # Schema catalog + ad-hoc skill registry
    schema_catalog = PortableSchemaCatalogService(
        sql_runner=runner,
        persist_path=".vanna/publicdb_schema_snapshot.json",
        dialect=dialect,
    )

    skill_registry = SkillRegistry(InMemorySkillRegistryStore())
    skill_enricher = SkillAdHocContextEnricher(
        registry=skill_registry,
        schema_catalog=schema_catalog,
        llm_service=llm,  # LLM-assisted skill generation
        config=SkillAdHocConfig(enable_ad_hoc_generation=True),
    )

    from vanna.core.agent.config import AgentConfig

    max_tokens_env = os.environ.get("MAX_TOKENS")
    agent_config = AgentConfig(max_tokens=int(max_tokens_env)) if max_tokens_env else AgentConfig()

    # Minimal user / agent
    user = User(id="default", username="default", email="default@example.com", group_memberships=[])
    agent = Agent(
        config=agent_config,
        llm_service=llm,
        tool_registry=tool_registry,
        user_resolver=SimpleUserResolver(default_user=user),
        agent_memory=SimpleAgentMemory(),
        context_enrichers=[skill_enricher],
    )

    # Questions
    questions_env = os.environ.get("QUESTIONS")
    if questions_env:
        questions = json.loads(questions_env)
        if not isinstance(questions, list) or not all(isinstance(q, str) for q in questions):
            raise SystemExit("QUESTIONS must be a JSON list of strings")
    else:
        questions = _default_questions(db_url)

    print(f"Model: {model}")
    print(f"Questions: {len(questions)}")

    for i, q in enumerate(questions, 1):
        before = await skill_registry.list_skills(enabled_only=True)
        out = await _run_one(agent, q)
        after = await skill_registry.list_skills(enabled_only=True)

        created = len(after) - len(before)
        print("\n" + "=" * 88)
        print(f"Q{i}: {q}")
        print(f"Ad-hoc skills created this turn: {created}")
        if created > 0:
            print(f"Total skills now: {len(after)}")
            # Print the last created skill name
            last = after[-1]
            print(f"Last skill name: {last.skill_spec.name}")
        print("\n--- Output (tail) ---\n")
        print(out[:4000])


if __name__ == "__main__":
    asyncio.run(main())
