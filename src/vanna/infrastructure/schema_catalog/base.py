"""Base interface for schema catalog snapshot/diff providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from vanna.core.tool import ToolContext

from .models import SchemaSnapshot, SchemaSyncResult


class SchemaCatalog(ABC):
    """Abstract schema catalog provider."""

    @abstractmethod
    async def capture_snapshot(self, context: ToolContext) -> SchemaSnapshot:
        """Capture a schema snapshot from the configured database."""
        pass

    @abstractmethod
    async def sync(self, context: ToolContext) -> SchemaSyncResult:
        """Capture current snapshot, compute drift against baseline, and persist."""
        pass

    @abstractmethod
    async def get_latest_snapshot(self) -> Optional[SchemaSnapshot]:
        """Return latest persisted snapshot if available."""
        pass
