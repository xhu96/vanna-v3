"""
FastAPI routes for lineage evidence retrieval.
"""

from __future__ import annotations

from typing import Any, Dict

try:
    from fastapi import APIRouter
except ImportError:
    raise ImportError(
        "FastAPI is required for lineage routes. "
        "Install with: pip install 'vanna[fastapi]'"
    )

from ..base import ChatHandler


def register_lineage_routes(
    app: Any,
    chat_handler: ChatHandler,
) -> None:
    """Register lineage retrieval routes on a FastAPI app.

    These endpoints expose the lineage evidence collected during the most
    recent chat request.  The ``ChatHandler`` stores a reference to the
    latest ``LineageEvidence`` after every completed chat turn.
    """

    router = APIRouter(prefix="/api/v1/lineage", tags=["lineage"])

    @router.get("/latest")
    async def get_latest_lineage() -> Dict[str, Any]:
        evidence = getattr(chat_handler, "_latest_lineage", None)
        if evidence is None:
            return {"lineage": None, "message": "No lineage evidence available yet"}
        return {"lineage": evidence}

    @router.get("/latest/markdown")
    async def get_latest_lineage_markdown() -> Dict[str, str]:
        markdown = getattr(chat_handler, "_latest_lineage_markdown", None)
        if markdown is None:
            return {"markdown": "", "message": "No lineage evidence available yet"}
        return {"markdown": markdown}

    app.include_router(router)
