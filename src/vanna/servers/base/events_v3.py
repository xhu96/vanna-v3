"""Strict V3 event payloads, sequencing, polling, and SSE framing."""

from __future__ import annotations

import asyncio
import json
import math
import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import (
    Any,
    AsyncGenerator,
    AsyncIterable,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Type,
    Union,
    cast,
)

import numpy as np
import pandas as pd
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

from vanna.core.chart_spec import ChartSpec

from .errors import InternalServerError, PublicServerError
from .models import ChatRequest, ChatStreamChunk

EventType = Literal[
    "status",
    "assistant_text",
    "table_result",
    "chart_spec",
    "component",
    "warning",
    "lineage",
    "error",
    "done",
]
NonTerminalEventType = Literal[
    "status",
    "assistant_text",
    "table_result",
    "chart_spec",
    "component",
    "warning",
    "lineage",
]
TerminalEventType = Literal["error", "done"]
StatusStage = Literal[
    "accepted",
    "planning",
    "semantic",
    "sql",
    "validating",
    "rendering",
]
JsonScalar = Union[str, int, float, bool, None]

_ID = re.compile(r"^[^\x00-\x1f\x7f]{1,160}$")
_CODE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_MAX_TABLE_ROWS = 5000
_MAX_TABLE_FIELDS = 100
_MAX_TABLE_BYTES = 2 * 1024 * 1024
_MAX_EVENTS = 100_000


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_assignment=True,
        revalidate_instances="always",
    )


class StatusPayload(_StrictModel):
    stage: StatusStage
    message: str = Field(max_length=2000)


class AssistantTextPayload(_StrictModel):
    text: str = Field(max_length=1_000_000)
    delta: bool


def _normalize_scalar(value: Any) -> JsonScalar:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, np.generic):
        return _normalize_scalar(value.item())
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("table values must be finite JSON scalars")
        return str(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if not math.isfinite(value):
            raise ValueError("table values must be finite JSON scalars")
        return value
    if isinstance(value, str):
        if len(value) > 1_000_000:
            raise ValueError("table scalar exceeds the string limit")
        return value
    raise ValueError("table values must be JSON scalars")


def _table_size(rows: List[Dict[str, JsonScalar]]) -> int:
    return len(
        json.dumps(
            rows,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _fit_table_rows(
    rows: List[Dict[str, JsonScalar]],
) -> tuple[List[Dict[str, JsonScalar]], bool]:
    if _table_size(rows) <= _MAX_TABLE_BYTES:
        return rows, False
    low = 0
    high = len(rows)
    while low < high:
        middle = (low + high + 1) // 2
        if _table_size(rows[:middle]) <= _MAX_TABLE_BYTES:
            low = middle
        else:
            high = middle - 1
    if low == 0 and rows:
        raise ValueError("one table row exceeds the event payload limit")
    return rows[:low], True


class TableResultPayload(_StrictModel):
    columns: List[str] = Field(max_length=_MAX_TABLE_FIELDS)
    rows: List[Dict[str, JsonScalar]] = Field(max_length=_MAX_TABLE_ROWS)
    row_count: int = Field(ge=0)
    truncated: bool

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, columns: List[str]) -> List[str]:
        if len(columns) != len(set(columns)):
            raise ValueError("table columns must be unique")
        for column in columns:
            if (
                not column
                or len(column) > 512
                or any(ord(char) < 32 for char in column)
            ):
                raise ValueError("table columns must be bounded identifiers")
        return columns

    @model_validator(mode="after")
    def validate_shape(self) -> "TableResultPayload":
        column_set = set(self.columns)
        for row in self.rows:
            if len(row) > _MAX_TABLE_FIELDS or not set(row).issubset(column_set):
                raise ValueError("table row fields must match declared columns")
        if self.row_count < len(self.rows):
            raise ValueError("table row_count cannot be smaller than inline rows")
        if self.row_count > len(self.rows) and not self.truncated:
            raise ValueError("truncated must report omitted inline rows")
        if _table_size(self.rows) > _MAX_TABLE_BYTES:
            raise ValueError("table event exceeds the serialized byte limit")
        return self


class ChartSpecPayload(_StrictModel):
    chart_spec: ChartSpec


class CardData(_StrictModel):
    title: str = Field(max_length=500)
    body: str = Field(max_length=100_000)


class CodeData(_StrictModel):
    language: str = Field(max_length=64)
    text: str = Field(max_length=1_000_000)


class ArtifactData(_StrictModel):
    title: Optional[str] = Field(default=None, max_length=500)
    representation: Literal["text", "sanitized_html"]
    content: str = Field(max_length=1_000_000)


class CardComponentPayload(_StrictModel):
    component_kind: Literal["card"] = "card"
    data: CardData


class CodeComponentPayload(_StrictModel):
    component_kind: Literal["code"] = "code"
    data: CodeData


class ArtifactComponentPayload(_StrictModel):
    component_kind: Literal["artifact"] = "artifact"
    data: ArtifactData


ComponentPayload = Union[
    CardComponentPayload,
    CodeComponentPayload,
    ArtifactComponentPayload,
]


class WarningPayload(_StrictModel):
    code: str
    message: str = Field(max_length=2000)
    fallback: Optional[Literal["sql", "none"]] = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        if not _CODE.fullmatch(value):
            raise ValueError("warning code is invalid")
        return value


class RetrievedSourcePayload(_StrictModel):
    id: str = Field(max_length=160)
    kind: Literal["memory", "document"]
    score: Optional[float] = Field(default=None, ge=0, le=1)


class ToolCallPayload(_StrictModel):
    name: str = Field(max_length=160)
    success: bool
    runtime_ms: Optional[float] = Field(default=None, ge=0)


class SqlExecutionPayload(_StrictModel):
    sql: Optional[str] = Field(default=None, max_length=100_000)
    dialect: Optional[str] = Field(default=None, max_length=64)
    row_count: int = Field(ge=0)
    runtime_ms: Optional[float] = Field(default=None, ge=0)


class ValidationCheckPayload(_StrictModel):
    name: str = Field(max_length=160)
    passed: bool


class ConfidencePayload(_StrictModel):
    tier: Literal["High", "Medium", "Low"]
    signals: List[str] = Field(default_factory=list, max_length=100)

    @field_validator("signals")
    @classmethod
    def validate_signals(cls, value: List[str]) -> List[str]:
        if len(value) != len(set(value)) or any(
            not signal or len(signal) > 160 for signal in value
        ):
            raise ValueError("confidence signals must be unique bounded strings")
        return value


class SemanticEvidencePayload(_StrictModel):
    coverage: Literal["full", "partial", "missing", "not_applicable"]
    metric_names: List[str] = Field(default_factory=list, max_length=100)
    fallback_reason: Optional[str] = Field(default=None, max_length=2000)


class LineageEvidencePayload(_StrictModel):
    schema_version: Optional[int] = Field(default=None, ge=1)
    schema_snapshot_id: Optional[str] = Field(default=None, max_length=160)
    schema_hash: Optional[str] = Field(default=None, max_length=160)
    schema_drifted: bool = False
    semantic: SemanticEvidencePayload
    retrieved_sources: List[RetrievedSourcePayload] = Field(
        default_factory=list,
        max_length=1000,
    )
    tool_calls: List[ToolCallPayload] = Field(default_factory=list, max_length=1000)
    sql_executions: List[SqlExecutionPayload] = Field(
        default_factory=list,
        max_length=100,
    )
    validation_checks: List[ValidationCheckPayload] = Field(
        default_factory=list,
        max_length=1000,
    )
    confidence: ConfidencePayload


class LineagePayload(_StrictModel):
    evidence: LineageEvidencePayload


class ErrorPayload(_StrictModel):
    code: str
    message: str = Field(max_length=2000)
    correlation_id: str = Field(min_length=1, max_length=160)
    retryable: bool

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        if not _CODE.fullmatch(value):
            raise ValueError("error code is invalid")
        return value


class DonePayload(_StrictModel):
    status: Literal["completed"] = "completed"
    event_count: int = Field(ge=1)


EventPayload = Union[
    StatusPayload,
    AssistantTextPayload,
    TableResultPayload,
    ChartSpecPayload,
    CardComponentPayload,
    CodeComponentPayload,
    ArtifactComponentPayload,
    WarningPayload,
    LineagePayload,
    ErrorPayload,
    DonePayload,
]

_PAYLOAD_MODELS: Dict[str, Type[BaseModel]] = {
    "status": StatusPayload,
    "assistant_text": AssistantTextPayload,
    "table_result": TableResultPayload,
    "chart_spec": ChartSpecPayload,
    "warning": WarningPayload,
    "lineage": LineagePayload,
    "error": ErrorPayload,
    "done": DonePayload,
}
_COMPONENT_MODELS: Dict[str, Type[BaseModel]] = {
    "card": CardComponentPayload,
    "code": CodeComponentPayload,
    "artifact": ArtifactComponentPayload,
}


def _payload_model(event_type: str, payload: Any) -> Type[BaseModel]:
    if event_type == "component":
        kind = (
            payload.get("component_kind")
            if isinstance(payload, dict)
            else getattr(payload, "component_kind", None)
        )
        if not isinstance(kind, str) or kind not in _COMPONENT_MODELS:
            raise ValueError("component payload kind is invalid")
        return _COMPONENT_MODELS[kind]
    model = _PAYLOAD_MODELS.get(event_type)
    if model is None:
        raise ValueError("event type is invalid")
    return model


class ChatEvent(_StrictModel):
    """One versioned event with a payload discriminated by ``event_type``."""

    event_version: Literal["v3"] = "v3"
    event_type: EventType
    event_id: str = Field(default_factory=lambda: f"evt_{uuid.uuid4().hex}")
    sequence: int = Field(default=0, ge=0)
    conversation_id: str
    request_id: str
    timestamp: datetime = Field(default_factory=utc_now)
    payload: EventPayload

    @model_validator(mode="before")
    @classmethod
    def discriminate_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        event_type = value.get("event_type")
        payload = value.get("payload")
        if isinstance(event_type, str):
            model = _payload_model(event_type, payload)
            copied = dict(value)
            copied["payload"] = model.model_validate(payload)
            return copied
        return value

    @field_validator("event_id", "conversation_id", "request_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not _ID.fullmatch(value) or value != value.strip():
            raise ValueError("event identifiers must be bounded and non-empty")
        return value

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            raise ValueError("event timestamp must be RFC 3339") from None

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event timestamp must include a UTC offset")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_payload_type(self) -> "ChatEvent":
        expected = _payload_model(self.event_type, self.payload.model_dump())
        if not isinstance(self.payload, expected):
            raise ValueError("event payload does not match event_type")
        return self

    @model_serializer(mode="plain")
    def serialize_event(self) -> Dict[str, Any]:
        model = _payload_model(self.event_type, self.payload.model_dump())
        model.model_validate(self.payload.model_dump(mode="python"))
        serialized_payload = self.payload.model_dump(
            mode="python",
            exclude_none=True,
        )
        if isinstance(self.payload, LineagePayload):
            evidence = cast(Dict[str, Any], serialized_payload["evidence"])
            evidence["schema_version"] = self.payload.evidence.schema_version
            evidence["schema_snapshot_id"] = self.payload.evidence.schema_snapshot_id
            evidence["schema_hash"] = self.payload.evidence.schema_hash
        return {
            "event_version": self.event_version,
            "event_type": self.event_type,
            "event_id": self.event_id,
            "sequence": self.sequence,
            "conversation_id": self.conversation_id,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "payload": serialized_payload,
        }

    @property
    def terminal(self) -> bool:
        return self.event_type in {"done", "error"}

    @classmethod
    def from_chunk(
        cls,
        chunk: ChatStreamChunk,
        *,
        sequence: int = 0,
        event_id: Optional[str] = None,
    ) -> "ChatEvent":
        payload, event_type = _payload_from_chunk(chunk)
        try:
            timestamp = datetime.fromtimestamp(chunk.timestamp, timezone.utc)
        except (OverflowError, OSError, ValueError):
            raise ValueError("chunk timestamp is invalid") from None
        return cls(
            event_type=event_type,
            event_id=event_id or f"evt_{uuid.uuid4().hex}",
            sequence=sequence,
            conversation_id=chunk.conversation_id,
            request_id=chunk.request_id,
            timestamp=timestamp,
            payload=payload,
        )

    @classmethod
    def done(
        cls,
        conversation_id: str,
        request_id: str,
        *,
        sequence: int = 0,
        event_id: Optional[str] = None,
    ) -> "ChatEvent":
        return cls(
            event_type="done",
            event_id=event_id or f"evt_{uuid.uuid4().hex}",
            sequence=sequence,
            conversation_id=conversation_id,
            request_id=request_id,
            payload=DonePayload(event_count=sequence + 1),
        )

    @classmethod
    def error(
        cls,
        conversation_id: str,
        request_id: str,
        error: PublicServerError,
        *,
        sequence: int = 0,
        event_id: Optional[str] = None,
    ) -> "ChatEvent":
        return cls(
            event_type="error",
            event_id=event_id or f"evt_{uuid.uuid4().hex}",
            sequence=sequence,
            conversation_id=conversation_id,
            request_id=request_id,
            payload=ErrorPayload(
                code=error.code,
                message=error.public_message,
                correlation_id=error.correlation_id,
                retryable=error.retryable,
            ),
        )

    @classmethod
    def lineage(
        cls,
        conversation_id: str,
        request_id: str,
        payload: LineagePayload,
        *,
        sequence: int = 0,
        event_id: Optional[str] = None,
    ) -> "ChatEvent":
        return cls(
            event_type="lineage",
            event_id=event_id or f"evt_{uuid.uuid4().hex}",
            sequence=sequence,
            conversation_id=conversation_id,
            request_id=request_id,
            payload=payload,
        )


def _bounded_text(value: Any, limit: int, fallback: str = "") -> str:
    text = value if isinstance(value, str) else fallback
    return text[:limit]


def _missing_lineage_payload(*, request_failed: bool) -> LineagePayload:
    signals = ["missing_agent_lineage"]
    if request_failed:
        signals.append("request_failed")
    return LineagePayload(
        evidence=LineageEvidencePayload(
            schema_version=None,
            schema_snapshot_id=None,
            schema_hash=None,
            schema_drifted=False,
            semantic=SemanticEvidencePayload(
                coverage="not_applicable",
                metric_names=[],
            ),
            validation_checks=[
                ValidationCheckPayload(
                    name="agent_lineage_emitted",
                    passed=False,
                )
            ],
            confidence=ConfidencePayload(tier="Low", signals=signals),
        )
    )


def _warning_payload(data: Dict[str, Any]) -> WarningPayload:
    raw_code = data.get("code")
    message = _bounded_text(data.get("detail") or data.get("message"), 2000)
    lowered = message.casefold()
    if isinstance(raw_code, str) and _CODE.fullmatch(raw_code):
        code = raw_code
    elif "tool" in lowered and "limit" in lowered:
        code = "tool_limit_reached"
    elif "sql" in lowered or "semantic" in lowered:
        code = "semantic_sql_fallback"
    else:
        code = "agent_warning"
    raw_fallback = data.get("fallback")
    fallback: Optional[Literal["sql", "none"]]
    if raw_fallback in {"sql", "none"}:
        fallback = cast(Literal["sql", "none"], raw_fallback)
    elif "sql" in lowered:
        fallback = "sql"
    else:
        fallback = None
    return WarningPayload(code=code, message=message, fallback=fallback)


def _table_payload(data: Dict[str, Any]) -> TableResultPayload:
    raw_rows = data.get("data", data.get("rows", []))
    if not isinstance(raw_rows, list):
        raise ValueError("dataframe component rows are invalid")
    raw_columns = data.get("columns")
    if raw_columns is None and raw_rows:
        first = raw_rows[0]
        raw_columns = list(first) if isinstance(first, dict) else None
    if not isinstance(raw_columns, list) or not all(
        isinstance(column, str) for column in raw_columns
    ):
        raise ValueError("dataframe component columns are invalid")
    columns = cast(List[str], raw_columns)
    if len(columns) > _MAX_TABLE_FIELDS:
        raise ValueError("dataframe component has too many columns")

    normalized_rows: List[Dict[str, JsonScalar]] = []
    for raw_row in raw_rows[:_MAX_TABLE_ROWS]:
        if not isinstance(raw_row, dict) or len(raw_row) > _MAX_TABLE_FIELDS:
            raise ValueError("dataframe component row is invalid")
        normalized_row: Dict[str, JsonScalar] = {}
        for key, value in raw_row.items():
            if not isinstance(key, str):
                raise ValueError("dataframe component row keys are invalid")
            normalized_row[key] = _normalize_scalar(value)
        normalized_rows.append(normalized_row)
    normalized_rows, byte_truncated = _fit_table_rows(normalized_rows)

    reported_count = data.get("row_count", len(raw_rows))
    if not isinstance(reported_count, int) or isinstance(reported_count, bool):
        raise ValueError("dataframe row_count is invalid")
    row_count = max(reported_count, len(raw_rows))
    truncated = (
        bool(data.get("truncated"))
        or row_count > len(normalized_rows)
        or len(raw_rows) > _MAX_TABLE_ROWS
        or byte_truncated
    )
    return TableResultPayload(
        columns=columns,
        rows=normalized_rows,
        row_count=row_count,
        truncated=truncated,
    )


def _chart_payload(data: Dict[str, Any]) -> ChartSpecPayload:
    chart_data = data.get("chart_spec")
    if chart_data is None:
        chart_data = {
            key: data[key]
            for key in ("format", "schema_version", "spec", "dataset", "metadata")
            if key in data
        }
    return ChartSpecPayload(chart_spec=ChartSpec.model_validate(chart_data))


def _component_payload(rich_type: str, data: Dict[str, Any]) -> ComponentPayload:
    if rich_type == "card":
        return CardComponentPayload(
            data=CardData(
                title=_bounded_text(data.get("title"), 500, "Card"),
                body=_bounded_text(data.get("content"), 100_000),
            )
        )
    if rich_type in {"code", "code_block"}:
        return CodeComponentPayload(
            data=CodeData(
                language=_bounded_text(
                    data.get("language") or data.get("code_language"),
                    64,
                    "text",
                ),
                text=_bounded_text(data.get("text") or data.get("content"), 1_000_000),
            )
        )
    if rich_type == "artifact":
        # Core V3 never labels model-provided HTML as sanitized. All legacy
        # artifact forms cross the V3 contract as inert source text.
        return ArtifactComponentPayload(
            data=ArtifactData(
                title=_bounded_text(data.get("title"), 500) or None,
                representation="text",
                content=_bounded_text(data.get("content"), 1_000_000),
            )
        )
    if rich_type == "notification":
        return CardComponentPayload(
            data=CardData(
                title=_bounded_text(data.get("title"), 500, "Notification"),
                body=_bounded_text(data.get("message"), 100_000),
            )
        )
    return CardComponentPayload(
        data=CardData(
            title=f"V2 component: {rich_type}"[:500],
            body="This component is available through the V2 protocol.",
        )
    )


def _payload_from_chunk(
    chunk: ChatStreamChunk,
) -> tuple[EventPayload, EventType]:
    rich = chunk.rich
    if not isinstance(rich, dict):
        raise ValueError("chunk rich component is invalid")
    rich_type = rich.get("type")
    data = rich.get("data", {})
    if not isinstance(rich_type, str) or not isinstance(data, dict):
        raise ValueError("chunk component shape is invalid")

    terminal_error = data.get("v3_terminal_error")
    if terminal_error is not None:
        return ErrorPayload.model_validate(terminal_error), "error"
    lineage = data.get("v3_lineage")
    if lineage is not None:
        return LineagePayload.model_validate(lineage), "lineage"

    if rich_type == "status_bar_update":
        if data.get("status") == "warning":
            return _warning_payload(data), "warning"
        status = str(data.get("status", "working")).casefold()
        stage: StatusStage = (
            "rendering" if status in {"success", "idle"} else "planning"
        )
        message = _bounded_text(data.get("message"), 2000, "Working")
        detail = _bounded_text(data.get("detail"), 2000)
        if detail:
            message = f"{message}: {detail}"[:2000]
        return StatusPayload(stage=stage, message=message), "status"
    if rich_type == "text":
        return (
            AssistantTextPayload(
                text=_bounded_text(data.get("content"), 1_000_000),
                delta=False,
            ),
            "assistant_text",
        )
    if rich_type == "dataframe":
        return _table_payload(data), "table_result"
    if rich_type == "chart":
        return _chart_payload(data), "chart_spec"
    return _component_payload(rich_type, data), "component"


class V3EventSequence:
    """Enforce contiguous IDs, one lineage event, and one terminal event."""

    def __init__(
        self,
        conversation_id: str,
        request_id: str,
        *,
        event_id_factory: Callable[[], str] = lambda: f"evt_{uuid.uuid4().hex}",
    ) -> None:
        self.conversation_id = _validate_request_id(conversation_id, "conversation_id")
        self.request_id = _validate_request_id(request_id, "request_id")
        self.event_id_factory = event_id_factory
        self.sequence = 0
        self.terminated = False
        self.lineage_emitted = False

    def from_chunk(self, chunk: ChatStreamChunk) -> ChatEvent:
        if self.terminated:
            raise RuntimeError("cannot emit after a terminal V3 event")
        if (
            chunk.conversation_id != self.conversation_id
            or chunk.request_id != self.request_id
        ):
            raise ValueError("chunk identifiers changed during one request")
        event = ChatEvent.from_chunk(
            chunk,
            sequence=self.sequence,
            event_id=self.event_id_factory(),
        )
        if event.event_type == "lineage":
            if self.lineage_emitted:
                raise ValueError("V3 sequence contains more than one lineage event")
            self.lineage_emitted = True
        elif self.lineage_emitted and not event.terminal:
            raise ValueError("V3 lineage must be the final non-terminal event")
        elif event.terminal and not self.lineage_emitted:
            raise ValueError("V3 terminal event requires preceding lineage")
        self.sequence += 1
        if self.sequence > _MAX_EVENTS:
            raise ValueError("V3 event count exceeds the request limit")
        if event.terminal:
            self.terminated = True
        return event

    def lineage(self, payload: LineagePayload) -> ChatEvent:
        if self.terminated:
            raise RuntimeError("cannot emit after a terminal V3 event")
        if self.lineage_emitted:
            raise RuntimeError("V3 sequence already contains lineage")
        event = ChatEvent.lineage(
            self.conversation_id,
            self.request_id,
            payload,
            sequence=self.sequence,
            event_id=self.event_id_factory(),
        )
        self.sequence += 1
        self.lineage_emitted = True
        return event

    def missing_lineage(self, *, request_failed: bool) -> ChatEvent:
        return self.lineage(_missing_lineage_payload(request_failed=request_failed))

    def done(self) -> ChatEvent:
        if self.terminated:
            raise RuntimeError("V3 sequence already terminated")
        if not self.lineage_emitted:
            raise RuntimeError("V3 terminal event requires preceding lineage")
        event = ChatEvent.done(
            self.conversation_id,
            self.request_id,
            sequence=self.sequence,
            event_id=self.event_id_factory(),
        )
        self.sequence += 1
        self.terminated = True
        return event

    def error(self, error: PublicServerError) -> ChatEvent:
        if self.terminated:
            raise RuntimeError("V3 sequence already terminated")
        if not self.lineage_emitted:
            raise RuntimeError("V3 terminal event requires preceding lineage")
        event = ChatEvent.error(
            self.conversation_id,
            self.request_id,
            error,
            sequence=self.sequence,
            event_id=self.event_id_factory(),
        )
        self.sequence += 1
        self.terminated = True
        return event


class ChatPollResponse(_StrictModel):
    event_version: Literal["v3"] = "v3"
    conversation_id: str
    request_id: str
    events: List[ChatEvent] = Field(default_factory=list, max_length=_MAX_EVENTS)
    terminal_event: ChatEvent

    @model_validator(mode="after")
    def validate_sequence(self) -> "ChatPollResponse":
        all_events = [*self.events, self.terminal_event]
        if not all_events:
            raise ValueError("poll response requires a terminal event")
        if any(event.terminal for event in self.events):
            raise ValueError("poll non-terminal events contain a terminal event")
        if not self.terminal_event.terminal:
            raise ValueError("poll terminal_event is not terminal")
        lineage_events = [
            event for event in self.events if event.event_type == "lineage"
        ]
        if len(lineage_events) != 1:
            raise ValueError("poll response requires exactly one lineage event")
        if not self.events or self.events[-1].event_type != "lineage":
            raise ValueError("poll lineage must be the final non-terminal event")
        event_ids = [event.event_id for event in all_events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("poll event IDs must be unique")
        if (
            self.terminal_event.event_type == "done"
            and isinstance(self.terminal_event.payload, DonePayload)
            and self.terminal_event.payload.event_count != len(all_events)
        ):
            raise ValueError("poll done event_count does not match the event sequence")
        for sequence, event in enumerate(all_events):
            if (
                event.sequence != sequence
                or event.conversation_id != self.conversation_id
                or event.request_id != self.request_id
            ):
                raise ValueError("poll event sequence or identifiers are invalid")
        return self


def _validate_request_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value) or value != value.strip():
        raise ValueError(f"{label} must be a bounded non-empty identifier")
    return value


def prepare_v3_request(request: ChatRequest) -> None:
    """Assign and validate canonical IDs before V3 execution starts."""

    if (
        not isinstance(request.message, str)
        or not 1 <= len(request.message) <= 1_000_000
    ):
        raise ValueError("V3 message must contain between 1 and 1000000 characters")
    conversation_id = (
        f"conv_{uuid.uuid4().hex}"
        if request.conversation_id is None
        else request.conversation_id
    )
    request_id = (
        f"req_{uuid.uuid4().hex}" if request.request_id is None else request.request_id
    )
    request.conversation_id = _validate_request_id(conversation_id, "conversation_id")
    request.request_id = _validate_request_id(request_id, "request_id")


async def iter_v3_events(
    chunks: AsyncIterable[ChatStreamChunk],
    *,
    conversation_id: str,
    request_id: str,
    internal_error_factory: Callable[[], PublicServerError] = InternalServerError,
) -> AsyncGenerator[ChatEvent, None]:
    """Convert a chunk stream into exactly one terminal V3 sequence."""

    sequence = V3EventSequence(conversation_id, request_id)
    try:
        async for chunk in chunks:
            rich = chunk.rich
            data = rich.get("data") if isinstance(rich, dict) else None
            if (
                isinstance(data, dict)
                and data.get("v3_terminal_error") is not None
                and not sequence.lineage_emitted
            ):
                yield sequence.missing_lineage(request_failed=True)
            event = sequence.from_chunk(chunk)
            yield event
            if event.terminal:
                return
    except asyncio.CancelledError:
        raise
    except PublicServerError as error:
        if not sequence.lineage_emitted:
            yield sequence.missing_lineage(request_failed=True)
        yield sequence.error(error)
    except Exception:
        try:
            public_error = internal_error_factory()
        except Exception:
            public_error = InternalServerError()
        if not sequence.lineage_emitted:
            yield sequence.missing_lineage(request_failed=True)
        yield sequence.error(public_error)
    else:
        if not sequence.lineage_emitted:
            yield sequence.missing_lineage(request_failed=False)
        yield sequence.done()


async def collect_v3_poll(
    chunks: AsyncIterable[ChatStreamChunk],
    *,
    conversation_id: str,
    request_id: str,
    internal_error_factory: Callable[[], PublicServerError] = InternalServerError,
) -> ChatPollResponse:
    events: List[ChatEvent] = []
    terminal: Optional[ChatEvent] = None
    async for event in iter_v3_events(
        chunks,
        conversation_id=conversation_id,
        request_id=request_id,
        internal_error_factory=internal_error_factory,
    ):
        if event.terminal:
            terminal = event
        else:
            events.append(event)
    if terminal is None:
        raise RuntimeError("V3 event collector did not produce a terminal event")
    return ChatPollResponse(
        conversation_id=conversation_id,
        request_id=request_id,
        events=events,
        terminal_event=terminal,
    )


def format_sse_event(event: ChatEvent) -> str:
    """Serialize one complete WHATWG SSE frame."""

    return (
        f"id: {event.event_id}\n"
        f"event: {event.event_type}\n"
        f"data: {event.model_dump_json()}\n\n"
    )


__all__ = [
    "ArtifactComponentPayload",
    "AssistantTextPayload",
    "CardComponentPayload",
    "ChartSpecPayload",
    "ChatEvent",
    "ChatPollResponse",
    "CodeComponentPayload",
    "DonePayload",
    "ErrorPayload",
    "EventType",
    "LineageEvidencePayload",
    "LineagePayload",
    "StatusPayload",
    "TableResultPayload",
    "V3EventSequence",
    "WarningPayload",
    "collect_v3_poll",
    "format_sse_event",
    "iter_v3_events",
    "prepare_v3_request",
]
