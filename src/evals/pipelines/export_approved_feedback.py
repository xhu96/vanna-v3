"""Export tenant-approved feedback for an offline candidate pipeline."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.services.feedback import FeedbackService
from vanna.services.feedback_store import SqliteFeedbackStore


def export_approved_feedback(
    *,
    database: Path,
    tenant_id: str,
    output: Path,
    reviewer_id: str = "offline-export",
) -> dict[str, object]:
    """Write approved-only JSONL and return the signed-by-content manifest."""

    if not tenant_id.strip():
        raise ValueError("tenant_id must be non-empty")
    context = ToolContext(
        user=User(
            id=reviewer_id,
            authenticated=True,
            group_memberships=["admin"],
            metadata={"tenant_id": tenant_id},
        ),
        conversation_id="offline-feedback-export",
        request_id="offline-feedback-export",
        agent_memory=DemoAgentMemory(),
    )
    service = FeedbackService(store=SqliteFeedbackStore(str(database)))
    exported = asyncio.run(service.write_approved_export(context, str(output)))
    return exported.manifest.model_dump(mode="json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--reviewer-id", default="offline-export")
    args = parser.parse_args()

    manifest = export_approved_feedback(
        database=args.database,
        tenant_id=args.tenant_id,
        output=args.out,
        reviewer_id=args.reviewer_id,
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
