"""Semantic integration adapters.

``FileSemanticAdapter`` is the production adapter: it loads a YAML metric
model and runs metric SQL through an injected ``SqlRunner``.
``MockSemanticAdapter`` is a deterministic in-memory fixture retained for
tests/demos only.
"""

from .file_adapter import FileSemanticAdapter
from .mock_adapter import (
    MockSemanticAdapter,
)  # retained for back-compat; demo/test only

__all__ = ["FileSemanticAdapter", "MockSemanticAdapter"]
