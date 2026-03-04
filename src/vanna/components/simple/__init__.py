"""Simple UI components for basic rendering."""

# Import from core
from vanna.components.simple_component import SimpleComponent, SimpleComponentType
from .text import SimpleTextComponent
from .image import SimpleImageComponent
from .link import SimpleLinkComponent

__all__ = [
    "SimpleComponent",
    "SimpleComponentType",
    "SimpleTextComponent",
    "SimpleImageComponent",
    "SimpleLinkComponent",
]
