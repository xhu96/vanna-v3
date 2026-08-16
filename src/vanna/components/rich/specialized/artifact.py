"""Artifact component for static sandboxed content."""

import uuid
from typing import Optional
from pydantic import Field
from ....core.rich_component import RichComponent, ComponentType


class ArtifactComponent(RichComponent):
    """Untrusted content rendered as sanitized HTML or inert source text."""

    type: ComponentType = ComponentType.ARTIFACT
    artifact_id: str = Field(default_factory=lambda: f"artifact_{uuid.uuid4().hex[:8]}")
    content: str  # Untrusted HTML or source text; never execute directly.
    artifact_type: str  # HTML is sanitized; script-like types render as source.
    title: Optional[str] = None
    description: Optional[str] = None
    editable: bool = True
    fullscreen_capable: bool = True
    external_renderable: bool = True
