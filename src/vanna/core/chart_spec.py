"""Strict declarative ChartSpec models, normalization, and validation."""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from importlib.resources import files
from typing import Any, Dict, List, Literal, Optional, Tuple, Union, cast

import numpy as np
import pandas as pd
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import best_match  # type: ignore[import-untyped]
from pydantic import (
    BaseModel,
    ConfigDict,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

MAX_CHART_ROWS = 5000
MAX_CHART_FIELDS = 100
MAX_CHART_BYTES = 2 * 1024 * 1024
MAX_CHART_DEPTH = 32
MAX_PLOTLY_TRACES = 20

_VEGA_LITE_SCHEMA_URL = "https://vega.github.io/schema/vega-lite/v5.json"
_SCHEMA_RESOURCE = files("vanna.core.schemas").joinpath("chart-spec-v1.schema.json")
_CHART_SPEC_SCHEMA = json.loads(_SCHEMA_RESOURCE.read_text(encoding="utf-8"))
Draft202012Validator.check_schema(_CHART_SPEC_SCHEMA)
_CHART_SPEC_VALIDATOR = Draft202012Validator(_CHART_SPEC_SCHEMA)

_BLOCKED_SPEC_KEYS = frozenset(
    {
        "calculate",
        "expr",
        "expression",
        "expressions",
        "filter",
        "href",
        "script",
        "scripts",
        "signal",
        "signals",
        "transform",
        "transforms",
        "url",
        "urls",
    }
)
_BLOCKED_SPEC_TEXT = re.compile(
    r"(?:https?://|(?<!:)//[a-z0-9]|ftp://|file://|javascript\s*:|"
    r"vbscript\s*:|data\s*:|\burl\s*\(|\bimage-set\s*\(|@import\b|"
    r"<\s*/?\s*(?:script|iframe|object|embed|svg)\b|"
    r"\bon(?:error|load)\s*=|\beval\s*\(|\bfunction\s*\(|=>)",
    flags=re.IGNORECASE,
)
_SAFE_PLOTLY_TRACE_TYPES = frozenset({"bar", "scatter", "pie"})

JsonObject = Dict[str, Any]
Dataset = List[JsonObject]


def _path_text(path: Tuple[Union[str, int], ...]) -> str:
    result = "$"
    for part in path:
        if isinstance(part, int):
            result += f"[{part}]"
        else:
            result += f"[{part!r}]"
    return result


def _normalize_json_value(
    value: Any,
    path: Tuple[Union[str, int], ...] = (),
    *,
    _active_container_ids: Optional[set[int]] = None,
    _depth: int = 0,
) -> Any:
    """Convert known dataframe values into strict, finite JSON values."""
    if _depth > MAX_CHART_DEPTH:
        raise ValueError(
            f"ChartSpec exceeds the {MAX_CHART_DEPTH}-level nesting limit "
            f"at {_path_text(path)}."
        )

    active_container_ids = (
        set() if _active_container_ids is None else _active_container_ids
    )

    if value is pd.NA or value is pd.NaT:
        return None

    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.isoformat()

    if isinstance(value, np.datetime64):
        if np.isnat(value):
            return None
        return pd.Timestamp(value).isoformat()

    if isinstance(value, np.ndarray):
        return _normalize_json_value(
            value.tolist(),
            path,
            _active_container_ids=active_container_ids,
            _depth=_depth,
        )

    if isinstance(value, np.generic):
        return _normalize_json_value(
            value.item(),
            path,
            _active_container_ids=active_container_ids,
            _depth=_depth,
        )

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, date):
        return value.isoformat()

    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        if math.isnan(value):
            return None
        if not math.isfinite(value):
            raise ValueError(
                f"ChartSpec contains a non-finite number at {_path_text(path)}."
            )
        return value

    if isinstance(value, dict):
        container_id = id(value)
        if container_id in active_container_ids:
            raise ValueError(
                f"ChartSpec contains a recursive object at {_path_text(path)}."
            )
        active_container_ids.add(container_id)
        try:
            normalized: JsonObject = {}
            for key, child in value.items():
                if not isinstance(key, str):
                    raise ValueError(
                        f"ChartSpec object keys must be strings at {_path_text(path)}."
                    )
                normalized[key] = _normalize_json_value(
                    child,
                    (*path, key),
                    _active_container_ids=active_container_ids,
                    _depth=_depth + 1,
                )
            return normalized
        finally:
            active_container_ids.remove(container_id)

    if isinstance(value, list):
        container_id = id(value)
        if container_id in active_container_ids:
            raise ValueError(
                f"ChartSpec contains a recursive array at {_path_text(path)}."
            )
        active_container_ids.add(container_id)
        try:
            return [
                _normalize_json_value(
                    child,
                    (*path, index),
                    _active_container_ids=active_container_ids,
                    _depth=_depth + 1,
                )
                for index, child in enumerate(value)
            ]
        finally:
            active_container_ids.remove(container_id)

    raise ValueError(
        "ChartSpec contains a non-JSON value "
        f"of type {type(value).__name__} at {_path_text(path)}."
    )


def _assert_safe_spec_content(
    value: Any, path: Tuple[Union[str, int], ...] = ()
) -> None:
    """Reject active-content channels even when they appear as text."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key.casefold() in _BLOCKED_SPEC_KEYS:
                raise ValueError(
                    "Chart spec contains blocked active-content property "
                    f"{key!r} at {_path_text((*path, key))}."
                )
            _assert_safe_spec_content(child, (*path, key))
        return

    if isinstance(value, list):
        for index, child in enumerate(value):
            _assert_safe_spec_content(child, (*path, index))
        return

    if not isinstance(value, str):
        return

    if path == ("$schema",) and value == _VEGA_LITE_SCHEMA_URL:
        return

    if _BLOCKED_SPEC_TEXT.search(value):
        raise ValueError(
            "Chart spec contains blocked URL, script, or expression content "
            f"at {_path_text(path)}."
        )


def _validation_error(payload: JsonObject, message: str) -> ValueError:
    chart_format = payload.get("format")
    prefix = (
        f"Invalid {chart_format} chart spec"
        if isinstance(chart_format, str)
        else "Invalid ChartSpec"
    )
    return ValueError(f"{prefix}: {message}")


def _serialize_payload(payload: JsonObject) -> bytes:
    try:
        return json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise _validation_error(payload, "payload is not finite JSON.") from exc


def _bulk_length(value: Any) -> Optional[int]:
    if not isinstance(value, (list, np.ndarray)):
        return None
    try:
        return len(value)
    except TypeError:
        return None


def _preflight_bulk_limits(value: Any) -> None:
    """Reject oversized raw containers before normalization copies them."""
    if not isinstance(value, dict):
        return
    payload = cast(JsonObject, value)

    dataset = value.get("dataset")
    dataset_length = _bulk_length(dataset)
    if dataset_length is not None and dataset_length > MAX_CHART_ROWS:
        raise _validation_error(
            payload,
            f"dataset exceeds the {MAX_CHART_ROWS}-row limit.",
        )
    if isinstance(dataset, list):
        for index, row in enumerate(dataset):
            if isinstance(row, dict) and len(row) > MAX_CHART_FIELDS:
                raise _validation_error(
                    payload,
                    f"dataset row {index} exceeds the {MAX_CHART_FIELDS}-field limit.",
                )

    metadata = value.get("metadata")
    if isinstance(metadata, dict):
        column_count = _bulk_length(metadata.get("columns"))
        if column_count is not None and column_count > MAX_CHART_FIELDS:
            raise _validation_error(
                payload,
                f"metadata.columns exceeds the {MAX_CHART_FIELDS}-field limit.",
            )

    if value.get("format") != "plotly-json":
        return
    spec = value.get("spec")
    if not isinstance(spec, dict):
        return
    traces = spec.get("data")
    trace_count = _bulk_length(traces)
    if trace_count is not None and trace_count > MAX_PLOTLY_TRACES:
        raise _validation_error(
            payload,
            f"Plotly spec exceeds the {MAX_PLOTLY_TRACES}-trace limit.",
        )
    if not isinstance(traces, list):
        return

    for trace_index, trace in enumerate(traces):
        if not isinstance(trace, dict):
            continue
        for name in ("x", "y", "labels", "values"):
            item_count = _bulk_length(trace.get(name))
            if item_count is not None and item_count > MAX_CHART_ROWS:
                raise _validation_error(
                    payload,
                    f"Plotly array exceeds the {MAX_CHART_ROWS}-item limit "
                    f"at {_path_text(('spec', 'data', trace_index, name))}.",
                )
        marker = trace.get("marker")
        if isinstance(marker, dict):
            for name in ("color", "size"):
                item_count = _bulk_length(marker.get(name))
                if item_count is not None and item_count > MAX_CHART_ROWS:
                    raise _validation_error(
                        payload,
                        f"Plotly array exceeds the {MAX_CHART_ROWS}-item limit "
                        "at "
                        f"{_path_text(('spec', 'data', trace_index, 'marker', name))}.",
                    )


def _enforce_structural_limits(payload: JsonObject) -> None:
    """Reject oversized inputs before the recursive JSON Schema walk."""
    dataset = payload.get("dataset")
    if isinstance(dataset, list):
        if len(dataset) > MAX_CHART_ROWS:
            raise _validation_error(
                payload,
                f"dataset exceeds the {MAX_CHART_ROWS}-row limit.",
            )
        for index, row in enumerate(dataset):
            if isinstance(row, dict) and len(row) > MAX_CHART_FIELDS:
                raise _validation_error(
                    payload,
                    f"dataset row {index} exceeds the {MAX_CHART_FIELDS}-field limit.",
                )

    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        columns = metadata.get("columns")
        if isinstance(columns, list) and len(columns) > MAX_CHART_FIELDS:
            raise _validation_error(
                payload,
                f"metadata.columns exceeds the {MAX_CHART_FIELDS}-field limit.",
            )

    if len(_serialize_payload(payload)) > MAX_CHART_BYTES:
        raise _validation_error(
            payload,
            f"payload exceeds the {MAX_CHART_BYTES}-byte serialized limit.",
        )


def _is_json_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, bool, int, float))


def _validate_inline_dataset(payload: JsonObject, dataset: List[Any]) -> None:
    """Validate bulk dataset items before omitting them from the schema walk."""
    for row_index, row in enumerate(dataset):
        if not isinstance(row, dict):
            raise _validation_error(
                payload,
                "dataset rows must be JSON objects "
                f"at {_path_text(('dataset', row_index))}.",
            )
        for field, value in row.items():
            if not _is_json_scalar(value):
                raise _validation_error(
                    payload,
                    "dataset values must be JSON scalars "
                    f"at {_path_text(('dataset', row_index, field))}.",
                )


def _project_plotly_array(
    payload: JsonObject,
    value: Any,
    path: Tuple[Union[str, int], ...],
    kind: Literal["json-scalar", "label", "number", "color", "size"],
) -> Any:
    """Validate a bounded Plotly array and return an empty schema projection."""
    if not isinstance(value, list):
        return value
    if len(value) > MAX_CHART_ROWS:
        raise _validation_error(
            payload,
            f"Plotly array exceeds the {MAX_CHART_ROWS}-item limit "
            f"at {_path_text(path)}.",
        )

    for index, item in enumerate(value):
        valid = False
        if kind == "json-scalar":
            valid = _is_json_scalar(item)
        elif kind == "label":
            valid = isinstance(item, str) and len(item) <= 512
        elif kind == "number":
            valid = isinstance(item, (int, float)) and not isinstance(item, bool)
        elif kind == "color":
            valid = isinstance(item, str) and len(item) <= 128
        elif kind == "size":
            valid = (
                isinstance(item, (int, float))
                and not isinstance(item, bool)
                and 0 <= item <= 500
            )

        if not valid:
            raise _validation_error(
                payload,
                f"invalid Plotly {kind} value at {_path_text((*path, index))}.",
            )

    return []


def _schema_validation_projection(payload: JsonObject) -> JsonObject:
    """Remove manually validated bulk arrays from the JSON Schema traversal.

    The Draft 2020-12 validator still checks every object, property allowlist,
    required field, enum, and bounded scalar. Dataset and Plotly arrays are
    checked against the same item and size constraints above, then represented
    as empty arrays to avoid an otherwise linear, duplicate Python walk.
    """
    projected = dict(payload)
    dataset = payload.get("dataset")
    if isinstance(dataset, list):
        _validate_inline_dataset(payload, dataset)
        projected["dataset"] = []

    if payload.get("format") != "plotly-json":
        return projected

    spec = payload.get("spec")
    if not isinstance(spec, dict):
        return projected
    traces = spec.get("data")
    if not isinstance(traces, list):
        return projected

    projected_traces: List[Any] = []
    for trace_index, trace in enumerate(traces):
        if not isinstance(trace, dict):
            projected_traces.append(trace)
            continue

        projected_trace = dict(trace)
        for name, kind in (
            ("x", "json-scalar"),
            ("y", "json-scalar"),
            ("labels", "label"),
            ("values", "number"),
        ):
            if name in trace:
                projected_trace[name] = _project_plotly_array(
                    payload,
                    trace[name],
                    ("spec", "data", trace_index, name),
                    cast(
                        Literal["json-scalar", "label", "number", "color", "size"],
                        kind,
                    ),
                )

        marker = trace.get("marker")
        if isinstance(marker, dict):
            projected_marker = dict(marker)
            if "color" in marker:
                projected_marker["color"] = _project_plotly_array(
                    payload,
                    marker["color"],
                    ("spec", "data", trace_index, "marker", "color"),
                    "color",
                )
            if "size" in marker:
                projected_marker["size"] = _project_plotly_array(
                    payload,
                    marker["size"],
                    ("spec", "data", trace_index, "marker", "size"),
                    "size",
                )
            projected_trace["marker"] = projected_marker

        projected_traces.append(projected_trace)

    projected_spec = dict(spec)
    projected_spec["data"] = projected_traces
    projected["spec"] = projected_spec
    return projected


def _validate_semantics(payload: JsonObject) -> None:
    dataset = payload["dataset"]
    metadata = cast(JsonObject, payload["metadata"])
    columns = cast(List[str], metadata["columns"])

    if isinstance(dataset, list):
        inline_row_count = len(dataset)
        source_row_count = cast(int, metadata["row_count"])
        truncated = metadata.get("truncated", False)

        if source_row_count < inline_row_count:
            raise _validation_error(
                payload,
                "metadata.row_count cannot be smaller than the inline dataset.",
            )

        if source_row_count > inline_row_count and truncated is not True:
            raise _validation_error(
                payload,
                "metadata.truncated must be true when inline rows are omitted.",
            )

        if truncated is True and source_row_count <= inline_row_count:
            raise _validation_error(
                payload,
                "metadata.truncated is inconsistent with metadata.row_count.",
            )

        declared_columns = set(columns)
        dataset_columns = {field for row in dataset for field in cast(JsonObject, row)}
        unknown_columns = dataset_columns - declared_columns
        if unknown_columns:
            field = min(unknown_columns)
            raise _validation_error(
                payload,
                f"dataset field {field!r} is missing from metadata.columns.",
            )

        if len(dataset_columns) > MAX_CHART_FIELDS:
            raise _validation_error(
                payload,
                f"dataset exceeds the {MAX_CHART_FIELDS}-field limit.",
            )

    if payload["format"] == "vega-lite":
        encoding = cast(JsonObject, cast(JsonObject, payload["spec"])["encoding"])
        declared_columns = set(columns)
        for channel, definition in encoding.items():
            definitions = definition if isinstance(definition, list) else [definition]
            for field_definition in definitions:
                field = cast(JsonObject, field_definition)["field"]
                if field not in declared_columns:
                    raise _validation_error(
                        payload,
                        f"encoding {channel!r} references undeclared field {field!r}.",
                    )


def _validate_chart_spec_payload(payload: JsonObject) -> None:
    _enforce_structural_limits(payload)

    spec = payload.get("spec")
    if isinstance(spec, (dict, list)):
        _assert_safe_spec_content(spec)

    validation_payload = _schema_validation_projection(payload)
    errors = list(_CHART_SPEC_VALIDATOR.iter_errors(validation_payload))
    if errors:
        error = best_match(errors)
        path = tuple(error.absolute_path)
        raise _validation_error(
            payload,
            f"{error.message} at {_path_text(path)}.",
        )

    _validate_semantics(payload)


class ChartSpec(BaseModel):
    """A validated chart payload restricted to the versioned safe profiles."""

    model_config = ConfigDict(
        extra="forbid",
        revalidate_instances="always",
        validate_assignment=True,
    )

    format: Literal["vega-lite", "plotly-json"]
    schema_version: Literal["v5-safe-1", "plotly-safe-1"]
    spec: JsonObject
    dataset: Dataset
    metadata: JsonObject

    @model_validator(mode="before")
    @classmethod
    def normalize_and_validate(cls, value: Any) -> Any:
        if isinstance(value, cls):
            value = {
                "format": value.format,
                "schema_version": value.schema_version,
                "spec": value.spec,
                "dataset": value.dataset,
                "metadata": value.metadata,
            }

        _preflight_bulk_limits(value)
        normalized = _normalize_json_value(value)
        if not isinstance(normalized, dict):
            raise ValueError("ChartSpec must be a JSON object.")

        _validate_chart_spec_payload(normalized)
        return normalized

    @model_serializer(mode="wrap")
    def serialize_validated(self, handler: SerializerFunctionWrapHandler) -> Any:
        """Recheck mutable nested data at every Pydantic serialization boundary."""
        _validate_chart_spec_payload(
            {
                "format": self.format,
                "schema_version": self.schema_version,
                "spec": self.spec,
                "dataset": self.dataset,
                "metadata": self.metadata,
            }
        )
        return handler(self)


def _copy_plotly_axis(axis: Any) -> JsonObject:
    if not isinstance(axis, dict):
        return {}

    result: JsonObject = {}
    title = axis.get("title")
    if isinstance(title, str):
        result["title"] = title
    elif isinstance(title, dict) and isinstance(title.get("text"), str):
        result["title"] = title["text"]

    for key in ("type", "autorange", "showgrid"):
        if key in axis:
            result[key] = axis[key]
    return result


def _copy_plotly_marker(marker: Any) -> JsonObject:
    if not isinstance(marker, dict):
        return {}
    return {key: marker[key] for key in ("color", "opacity", "size") if key in marker}


def normalize_plotly_json_spec(value: Any) -> JsonObject:
    """Reduce trusted Plotly generator output to the safe Plotly profile."""
    normalized = _normalize_json_value(value)
    if not isinstance(normalized, dict) or not isinstance(normalized.get("data"), list):
        raise ValueError("Plotly generator returned an invalid data array.")

    traces: List[JsonObject] = []
    for index, raw_trace in enumerate(normalized["data"]):
        if not isinstance(raw_trace, dict):
            raise ValueError(f"Plotly trace {index} is not an object.")

        trace_type = raw_trace.get("type")
        if trace_type not in _SAFE_PLOTLY_TRACE_TYPES:
            raise ValueError(
                f"Unsupported Plotly trace type {trace_type!r}; "
                "safe charts allow only bar, scatter, and pie."
            )

        trace: JsonObject = {"type": trace_type}
        for key in (
            "name",
            "mode",
            "x",
            "y",
            "labels",
            "values",
            "orientation",
        ):
            if key in raw_trace:
                trace[key] = raw_trace[key]

        marker = _copy_plotly_marker(raw_trace.get("marker"))
        if marker:
            trace["marker"] = marker
        traces.append(trace)

    raw_layout = normalized.get("layout")
    layout: JsonObject = {}
    if isinstance(raw_layout, dict):
        title = raw_layout.get("title")
        if isinstance(title, str):
            layout["title"] = title
        elif isinstance(title, dict) and isinstance(title.get("text"), str):
            layout["title"] = title["text"]

        for axis_name in ("xaxis", "yaxis"):
            axis = _copy_plotly_axis(raw_layout.get(axis_name))
            if axis:
                layout[axis_name] = axis

        for key in ("showlegend", "barmode", "width", "height"):
            if key in raw_layout:
                layout[key] = raw_layout[key]

    return {"data": traces, "layout": layout}


def dataframe_to_vega_lite_spec(
    rows: List[JsonObject],
    columns: List[str],
    column_types: Dict[str, str],
    title: str,
    *,
    row_count: Optional[int] = None,
) -> ChartSpec:
    """Generate a simple, validated Vega-Lite spec for tabular rows."""
    if not columns:
        raise ValueError("Cannot visualize a dataset without columns.")

    temporal_columns = [c for c in columns if column_types.get(c) == "temporal"]
    quantitative_columns = [c for c in columns if column_types.get(c) == "quantitative"]
    nominal_columns = [c for c in columns if column_types.get(c) == "nominal"]

    x_field: str
    y_field: str
    mark: Any = "bar"

    if temporal_columns and quantitative_columns:
        x_field = temporal_columns[0]
        y_field = quantitative_columns[0]
        mark = {"type": "line", "point": True}
    elif nominal_columns and quantitative_columns:
        x_field = nominal_columns[0]
        y_field = quantitative_columns[0]
    elif len(quantitative_columns) >= 2:
        x_field = quantitative_columns[0]
        y_field = quantitative_columns[1]
        mark = "point"
    else:
        x_field = columns[0]
        y_field = columns[1] if len(columns) > 1 else columns[0]

    encoding = {
        "x": {
            "field": x_field,
            "type": column_types.get(x_field, "nominal"),
        },
        "y": {
            "field": y_field,
            "type": column_types.get(y_field, "quantitative"),
        },
    }

    spec = {
        "$schema": _VEGA_LITE_SCHEMA_URL,
        "title": title,
        "mark": mark,
        "encoding": encoding,
    }

    source_row_count = len(rows) if row_count is None else row_count
    metadata: JsonObject = {
        "row_count": source_row_count,
        "columns": columns,
    }
    if source_row_count > len(rows):
        metadata["truncated"] = True

    return ChartSpec(
        format="vega-lite",
        schema_version="v5-safe-1",
        spec=spec,
        dataset=rows,
        metadata=metadata,
    )
