"""Schema catalog provider and portable ingestion interfaces."""

from __future__ import annotations

import inspect
import warnings
from abc import ABC, abstractmethod
from typing import Any, List, Optional, Protocol, cast

from vanna.core.tool import ToolContext

from .models import SchemaColumn, SchemaSnapshot, SchemaSyncResult


class SchemaSnapshotMetadata(Protocol):
    """Minimum metadata exposed by V2 and V3 schema snapshot providers."""

    schema_hash: str
    snapshot_id: str


class SchemaCatalogAdapter(ABC):
    """Read canonical descriptors from one database catalog dialect."""

    @abstractmethod
    async def fetch_columns(self, context: ToolContext) -> List[SchemaColumn]:
        """Return bounded, canonical column descriptors."""


class SchemaCatalog(ABC):
    """Capture, persist, and diff tenant-scoped schema snapshots."""

    @abstractmethod
    async def capture_snapshot(self, context: ToolContext) -> SchemaSnapshot:
        """Capture a schema snapshot from the configured database."""

    @abstractmethod
    async def sync(self, context: ToolContext) -> SchemaSyncResult:
        """Persist changed state and patch schema memory."""

    @abstractmethod
    async def get_latest_snapshot(
        self, context: ToolContext
    ) -> Optional[SchemaSnapshot]:
        """Return the latest snapshot in the authenticated tenant scope."""


async def get_latest_snapshot_compat(
    service: Any,
    context: ToolContext,
) -> Optional[SchemaSnapshotMetadata]:
    """Call context-aware catalogs while preserving the V2 no-argument hook."""

    method = getattr(service, "get_latest_snapshot", None)
    if not callable(method):
        raise TypeError("schema_sync_service must define get_latest_snapshot")
    try:
        parameters = tuple(inspect.signature(method).parameters.values())
    except (TypeError, ValueError):
        parameters = ()

    accepts_argument = any(
        parameter.kind
        in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        }
        for parameter in parameters
    )
    if accepts_argument:
        result = method(context)
    else:
        warnings.warn(
            "A no-argument schema get_latest_snapshot() hook is deprecated; "
            "accept ToolContext for tenant-scoped V3 lineage.",
            DeprecationWarning,
            stacklevel=2,
        )
        result = method()
    if inspect.isawaitable(result):
        result = await result
    if result is None:
        return None
    schema_hash = getattr(result, "schema_hash", None)
    snapshot_id = getattr(result, "snapshot_id", None)
    if not isinstance(schema_hash, str) or not isinstance(snapshot_id, str):
        raise TypeError(
            "schema snapshot metadata must expose string schema_hash and snapshot_id"
        )
    return cast(SchemaSnapshotMetadata, result)
