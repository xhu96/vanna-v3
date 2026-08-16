"""Run portable schema synchronization from an application worker or cron.

The service derives tenant scope from the authenticated user object. Request
body metadata is intentionally not part of the scope decision.
"""

from __future__ import annotations

from collections.abc import Sequence

from vanna.capabilities.agent_memory import AgentMemory
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.sqlite import SqliteRunner
from vanna.services import PortableSchemaCatalogService


async def sync_once(
    *,
    database_path: str,
    store_path: str,
    tenant_id: str,
    agent_memory: AgentMemory,
    catalog_tables: Sequence[str],
) -> None:
    runner = SqliteRunner(database_path=database_path, read_only=True)
    service = PortableSchemaCatalogService(
        runner,
        persist_path=store_path,
        catalog_tables=catalog_tables,
    )
    context = ToolContext(
        user=User(
            id="schema-worker",
            authenticated=True,
            metadata={"tenant_id": tenant_id},
            group_memberships=["admin"],
        ),
        conversation_id="schema-worker",
        request_id="schema-worker",
        agent_memory=agent_memory,
    )
    result = await service.sync(context)
    print(result.model_dump_json())


if __name__ == "__main__":
    raise SystemExit(
        "Import sync_once() from the application worker so it receives the same "
        "durable AgentMemory used by the agent. For a standalone catalog-only "
        "job, run: python -m vanna.services.schema_sync_cli --tenant TENANT --once "
        "--include-table TABLE. "
        "The catalog-only command leaves memory patches pending for an application "
        "worker rather than acknowledging them against ephemeral memory."
    )
