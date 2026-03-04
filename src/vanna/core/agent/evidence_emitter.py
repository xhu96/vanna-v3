"""
Evidence emitter — builds the lineage/evidence panel UI component.

Extracted from agent.py to reduce its responsibility surface.
"""

import dataclasses

from vanna.components import (
    CardComponent,
    UiComponent,
)
from vanna.core.lineage import LineageCollector


class EvidenceEmitter:
    """Builds and emits the evidence/lineage panel at the end of each agent turn."""

    @staticmethod
    def emit_evidence_panel(lineage_collector: LineageCollector) -> UiComponent:
        """Create the evidence and lineage card component.

        Args:
            lineage_collector: The lineage collector with accumulated evidence.

        Returns:
            A UiComponent containing the collapsible evidence card.
        """
        lineage_markdown = lineage_collector.to_markdown()
        return UiComponent(
            rich_component=CardComponent(
                title="Evidence and Lineage",
                content=lineage_markdown,
                icon="🔎",
                status="info",
                collapsible=True,
                collapsed=True,
                markdown=True,
                data={"evidence": dataclasses.asdict(lineage_collector.evidence)},
            ),
            simple_component=None,
        )
