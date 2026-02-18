"""Declarative ChartSpec models and validators."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator
from jsonschema import validate
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError


VEGA_LITE_SPEC_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["mark", "encoding"],
    "properties": {
        "$schema": {"type": "string"},
        "title": {"type": "string"},
        "mark": {"type": ["string", "object"]},
        "encoding": {"type": "object"},
        "data": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "values": {"type": "array"},
            },
            "additionalProperties": False,
        },
        "width": {"type": ["number", "string"]},
        "height": {"type": ["number", "string"]},
    },
    "additionalProperties": True,
}

PLOTLY_JSON_SPEC_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["data"],
    "properties": {
        "data": {"type": "array"},
        "layout": {"type": "object"},
        "config": {"type": "object"},
    },
    "additionalProperties": True,
}

_DANGEROUS_TOKENS = ("javascript:", "<script", "Function(", "eval(")


def _assert_safe_payload(value: Any) -> None:
    """Reject obvious executable payload vectors in chart specs."""
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and key.lower() == "url":
                raise ValueError("Chart specs with external URL sources are blocked.")
            _assert_safe_payload(child)
    elif isinstance(value, list):
        for child in value:
            _assert_safe_payload(child)
    elif isinstance(value, str):
        lowered = value.lower()
        for token in _DANGEROUS_TOKENS:
            if token.lower() in lowered:
                raise ValueError(
                    "Chart spec contains blocked executable token content."
                )


class ChartSpec(BaseModel):
    """Declarative chart specification exchanged with clients."""

    format: Literal["vega-lite", "plotly-json"]
    schema_version: str
    spec: Dict[str, Any]
    dataset: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_spec(self) -> "ChartSpec":
        _assert_safe_payload(self.spec)
        _assert_safe_payload(self.dataset)

        schema = (
            VEGA_LITE_SPEC_SCHEMA
            if self.format == "vega-lite"
            else PLOTLY_JSON_SPEC_SCHEMA
        )

        try:
            validate(instance=self.spec, schema=schema)
        except JsonSchemaValidationError as exc:
            raise ValueError(f"Invalid {self.format} chart spec: {exc.message}") from exc

        return self


def dataframe_to_vega_lite_spec(
    rows: List[Dict[str, Any]],
    columns: List[str],
    column_types: Dict[str, str],
    title: str,
) -> ChartSpec:
    """Generate a simple, validated Vega-Lite spec for tabular rows."""
    temporal_columns = [c for c in columns if column_types.get(c) == "temporal"]
    quantitative_columns = [c for c in columns if column_types.get(c) == "quantitative"]
    nominal_columns = [c for c in columns if column_types.get(c) == "nominal"]

    x_field: Optional[str] = None
    y_field: Optional[str] = None
    mark: Any = "bar"

    if temporal_columns and quantitative_columns:
        x_field = temporal_columns[0]
        y_field = quantitative_columns[0]
        mark = {"type": "line", "point": True}
    elif nominal_columns and quantitative_columns:
        x_field = nominal_columns[0]
        y_field = quantitative_columns[0]
        mark = "bar"
    elif len(quantitative_columns) >= 2:
        x_field = quantitative_columns[0]
        y_field = quantitative_columns[1]
        mark = "point"
    elif columns:
        x_field = columns[0]
        y_field = columns[1] if len(columns) > 1 else columns[0]
        mark = "bar"

    encoding = {
        "x": {
            "field": x_field,
            "type": column_types.get(x_field or "", "nominal"),
        },
        "y": {
            "field": y_field,
            "type": column_types.get(y_field or "", "quantitative"),
        },
    }

    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": title,
        "mark": mark,
        "encoding": encoding,
        "data": {"name": "dataset"},
    }

    return ChartSpec(
        format="vega-lite",
        schema_version="v5",
        spec=spec,
        dataset=rows,
        metadata={"row_count": len(rows), "columns": columns},
    )

