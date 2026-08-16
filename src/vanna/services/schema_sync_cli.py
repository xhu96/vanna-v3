"""Cron-compatible one-shot schema synchronization command."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import unquote, urlsplit

from vanna.capabilities.sql_runner import SqlRunner
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.postgres import PostgresRunner
from vanna.integrations.sqlite import SqliteRunner

from .schema_sync import PortableSchemaCatalogService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture one tenant-scoped Vanna schema snapshot.",
    )
    parser.add_argument("--tenant", required=True, help="Trusted tenant scope")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one idempotent synchronization and exit",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("VANNA_SCHEMA_DATABASE_URL"),
        help="Read-only sqlite:/// or postgresql:// URL",
    )
    parser.add_argument(
        "--store-path",
        default=os.environ.get(
            "VANNA_SCHEMA_STORE_PATH", ".vanna/schema_catalog.sqlite3"
        ),
        help="Transactional local snapshot store path",
    )
    parser.add_argument(
        "--include-schema",
        action="append",
        default=None,
        help="Allowed INFORMATION_SCHEMA schema; repeat for each trusted schema",
    )
    parser.add_argument(
        "--include-table",
        action="append",
        default=None,
        help="Allowed SQLite table; repeat for each trusted table",
    )
    return parser


def _runner_from_url(database_url: str) -> SqlRunner:
    parsed = urlsplit(database_url)
    if parsed.scheme == "sqlite":
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("SQLite schema URL must not contain query or credentials")
        if parsed.netloc not in {"", "localhost"}:
            raise ValueError("SQLite schema URL host must be empty or localhost")
        decoded_path = unquote(parsed.path)
        if (
            not decoded_path
            or not Path(decoded_path).is_absolute()
            or any(ord(character) < 32 for character in decoded_path)
        ):
            raise ValueError("SQLite schema URL must contain an absolute path")
        return SqliteRunner(database_path=decoded_path, read_only=True)
    if parsed.scheme in {"postgres", "postgresql"}:
        if not parsed.hostname or parsed.fragment:
            raise ValueError("PostgreSQL schema URL is invalid")
        return PostgresRunner(connection_string=database_url, read_only=True)
    raise ValueError("Schema database URL must use sqlite or postgresql")


async def run(argv: Optional[Sequence[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.once:
        parser.error("--once is required; use system cron for scheduling")
    if not isinstance(args.database_url, str) or not args.database_url:
        parser.error("--database-url or VANNA_SCHEMA_DATABASE_URL is required")

    runner = _runner_from_url(args.database_url)
    if runner.dialect == "sqlite" and not args.include_table:
        parser.error("SQLite schema sync requires at least one --include-table")
    if runner.dialect != "sqlite" and not args.include_schema:
        parser.error("INFORMATION_SCHEMA sync requires at least one --include-schema")
    service = PortableSchemaCatalogService(
        runner,
        persist_path=args.store_path,
        apply_memory_patches=False,
        catalog_schemas=args.include_schema,
        catalog_tables=args.include_table,
    )
    context = ToolContext(
        user=User(
            id="schema-sync-cli",
            authenticated=True,
            metadata={"tenant_id": args.tenant},
            group_memberships=["admin"],
        ),
        conversation_id="schema-sync-cli",
        request_id="schema-sync-cli",
        agent_memory=DemoAgentMemory(),
        metadata={"schema_sync": True},
    )
    result = await service.sync(context)
    print(
        json.dumps(
            {
                "status": "ok",
                "tenant_id": result.snapshot.tenant_id,
                "snapshot_id": result.snapshot.snapshot_id,
                "schema_version": result.snapshot.schema_version,
                "schema_hash": result.snapshot.schema_hash,
                "drift_detected": result.diff.has_drift,
                "persisted": result.persisted,
                "memory_patches_applied": len(result.memory_patches_applied),
                "memory_patches_pending": result.memory_patches_pending,
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    try:
        return asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        print(
            json.dumps(
                {
                    "status": "error",
                    "code": "schema_sync_failed",
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
