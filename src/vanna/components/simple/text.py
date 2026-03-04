"""Simple text component."""

from pydantic import Field
from vanna.components.simple_component import SimpleComponent, SimpleComponentType


class SimpleTextComponent(SimpleComponent):
    """A simple text component."""

    type: SimpleComponentType = SimpleComponentType.TEXT
    text: str = Field(..., description="The text content to display.")
