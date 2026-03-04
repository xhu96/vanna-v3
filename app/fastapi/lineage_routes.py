"""
FastAPI routes for lineage evidence retrieval.
"""

from __future__ import annotations

from typing import Any, Dict

try:
    from fastapi import APIRouter, Query
except ImportError:
    raise ImportError(
        "FastAPI is required for lineage routes. "
        "Install with: pip install 'vanna[fastapi]'"
    )

from app.base import ChatHandler


def register_lineage_routes(
    app: Any,
    chat_handler: ChatHandler,
) -> None:
    """Register lineage retrieval routes on a FastAPI app.

    These endpoints expose the lineage evidence collected during chat
    requests.  Lineage is scoped per conversation to support concurrent
    and multi-user usage.
    """

    router = APIRouter(prefix="/api/v1/lineage", tags=["lineage"])

    @router.get("/latest")
    async def get_latest_lineage(
        conversation_id: str = Query(..., description="Conversation ID to retrieve lineage for"),
    ) -> Dict[str, Any]:
        evidence = chat_handler.get_lineage(conversation_id)
        if evidence is None:
            return {
                "lineage": None,
                "conversation_id": conversation_id,
                "message": "No lineage evidence available for this conversation",
            }
        return {"lineage": evidence, "conversation_id": conversation_id}

    @router.get("/latest/markdown")
    async def get_latest_lineage_markdown(
        conversation_id: str = Query(..., description="Conversation ID to retrieve lineage for"),
    ) -> Dict[str, Any]:
        markdown = chat_handler.get_lineage_markdown(conversation_id)
        if markdown is None:
            return {
                "markdown": "",
                "conversation_id": conversation_id,
                "message": "No lineage evidence available for this conversation",
            }
        return {"markdown": markdown, "conversation_id": conversation_id}

    app.include_router(router)
