"""Semantic integration adapters.

``DbtSemanticLayerAdapter`` is the golden production adapter. It uses injected
HTTP and token providers for dbt Semantic Layer GraphQL. ``FileSemanticAdapter``
loads a local YAML metric model and runs SQL through an injected ``SqlRunner``.
``MockSemanticAdapter`` is a deterministic in-memory fixture retained for
tests/demos only.
"""

from .file_adapter import FileSemanticAdapter
from .dbt_adapter import DbtSemanticLayerAdapter, DbtSemanticLayerError
from .mock_adapter import (
    MockSemanticAdapter,
)  # retained for back-compat; demo/test only

__all__ = [
    "DbtSemanticLayerAdapter",
    "DbtSemanticLayerError",
    "FileSemanticAdapter",
    "MockSemanticAdapter",
]
