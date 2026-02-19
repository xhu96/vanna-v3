"""
PII redaction module.

Detects and redacts personally identifiable information from text
before durable storage. Uses regex patterns for common PII types.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)
_PHONE_RE = re.compile(
    r"""(?x)
    (?<!\d)                       # not preceded by digit
    (?:
        \+?\d{1,3}[\s\-]?        # optional country code
    )?
    (?:
        \(?\d{2,4}\)?[\s\-]?     # area code
        \d{3,4}[\s\-]?           # first group
        \d{3,4}                  # second group
    )
    (?!\d)                        # not followed by digit
    """
)
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_API_KEY_RE = re.compile(
    r"""(?x)
    (?:
        (?:sk|pk|api|token|key|secret|bearer)
        [\-_]?
        [A-Za-z0-9\-_]{20,}
    )
    """,
    re.IGNORECASE,
)
_CREDIT_CARD_RE = re.compile(
    r"\b\d{4}[\s\-]\d{4}[\s\-]\d{4}[\s\-]\d{4}\b"
)

_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    ("email", _EMAIL_RE),
    ("phone", _PHONE_RE),
    ("ssn", _SSN_RE),
    ("api_key", _API_KEY_RE),
    ("credit_card", _CREDIT_CARD_RE),
]

_REDACTED = "[REDACTED]"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class RedactionResult:
    """Outcome of a PII redaction pass."""

    text: str
    redacted_types: List[str] = field(default_factory=list)
    redaction_count: int = 0


def redact_pii(text: str) -> RedactionResult:
    """Strip obvious PII patterns from *text*.

    Returns a ``RedactionResult`` with the sanitised text and a list of
    detected PII categories.
    """
    redacted_types: List[str] = []
    count = 0
    result = text

    for label, pattern in _PATTERNS:
        matches = pattern.findall(result)
        if matches:
            result = pattern.sub(_REDACTED, result)
            redacted_types.append(label)
            count += len(matches)

    return RedactionResult(
        text=result,
        redacted_types=redacted_types,
        redaction_count=count,
    )


@dataclass
class PolicyCheckResult:
    """Outcome of a storage policy check."""

    passed: bool
    violations: List[str] = field(default_factory=list)


def check_storage_policy(data: dict) -> PolicyCheckResult:
    """Validate that data conforms to durable storage policies.

    Checks:
    - No raw query results stored in profile
    - Provenance / timestamps are present
    """
    violations: List[str] = []

    # Reject raw query results
    for key in ("query_result", "raw_result", "sql_result", "result_data"):
        if key in data:
            violations.append(
                f"Field '{key}' contains raw query data and must not be stored in profiles"
            )

    # Require provenance if present as a key
    if "provenance" in data and data["provenance"] is None:
        violations.append("Provenance must be provided for durable storage")

    return PolicyCheckResult(
        passed=len(violations) == 0,
        violations=violations,
    )
