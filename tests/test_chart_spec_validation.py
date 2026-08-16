"""Security and contract tests for declarative ChartSpec payloads."""

from __future__ import annotations

import json
import time
from copy import deepcopy
from datetime import date
from importlib.resources import files
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pandas as pd
import pytest
from pydantic_core import PydanticSerializationError

from vanna.core.chart_spec import (
    MAX_CHART_BYTES,
    MAX_CHART_FIELDS,
    MAX_CHART_ROWS,
    ChartSpec,
    normalize_plotly_json_spec,
)


def _vega_payload() -> dict[str, Any]:
    return {
        "format": "vega-lite",
        "schema_version": "v5-safe-1",
        "spec": {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "title": "Revenue by region",
            "mark": "bar",
            "encoding": {
                "x": {"field": "region", "type": "nominal"},
                "y": {"field": "revenue", "type": "quantitative"},
            },
        },
        "dataset": [{"region": "North", "revenue": 10}],
        "metadata": {
            "row_count": 1,
            "columns": ["region", "revenue"],
        },
    }


def _plotly_payload() -> dict[str, Any]:
    return {
        "format": "plotly-json",
        "schema_version": "plotly-safe-1",
        "spec": {
            "data": [
                {
                    "type": "bar",
                    "name": "Revenue",
                    "x": ["North"],
                    "y": [10],
                    "marker": {"color": "#15a8a8", "opacity": 0.8},
                }
            ],
            "layout": {
                "title": "Revenue by region",
                "showlegend": False,
                "xaxis": {"title": "Region", "type": "category"},
            },
        },
        "dataset": [{"region": "North", "revenue": 10}],
        "metadata": {
            "row_count": 1,
            "columns": ["region", "revenue"],
        },
    }


def test_chart_spec_accepts_safe_vega_lite_profile():
    chart = ChartSpec.model_validate(_vega_payload())

    assert chart.format == "vega-lite"
    assert chart.schema_version == "v5-safe-1"
    assert "data" not in chart.spec


def test_chart_spec_accepts_safe_plotly_profile():
    chart = ChartSpec.model_validate(_plotly_payload())

    assert chart.format == "plotly-json"
    assert chart.spec["data"][0]["type"] == "bar"


def test_chart_spec_rejects_dataset_reference_without_a_core_resolver():
    payload = _vega_payload()
    payload["dataset"] = {"reference": "ds_result_01"}
    with pytest.raises(ValueError, match="is not of type 'array'"):
        ChartSpec.model_validate(payload)


def test_packaged_chart_schema_matches_documented_contract():
    packaged = (
        files("vanna.core.schemas").joinpath("chart-spec-v1.schema.json").read_bytes()
    )
    documented = (
        Path(__file__).resolve().parents[1]
        / "docs/v3/schemas/chart-spec-v1.schema.json"
    ).read_bytes()

    assert packaged == documented


@pytest.mark.parametrize(
    ("target", "property_name"),
    [
        ("root", "unexpected"),
        ("spec", "autosize"),
        ("metadata", "source_file"),
    ],
)
def test_chart_spec_rejects_unknown_properties(target: str, property_name: str):
    payload = _vega_payload()
    target_object = payload if target == "root" else payload[target]
    target_object[property_name] = True

    with pytest.raises(ValueError, match="Invalid vega-lite chart spec"):
        ChartSpec.model_validate(payload)


@pytest.mark.parametrize(
    "property_name",
    [
        "calculate",
        "expr",
        "expression",
        "filter",
        "href",
        "script",
        "signal",
        "transform",
        "url",
    ],
)
def test_chart_spec_rejects_active_content_properties(property_name: str):
    payload = _vega_payload()
    payload["spec"][property_name] = []

    with pytest.raises(ValueError, match="blocked active-content property"):
        ChartSpec.model_validate(payload)


@pytest.mark.parametrize(
    "dangerous_title",
    [
        "https://attacker.invalid/chart.json",
        "javascript:alert(1)",
        "<script>alert(1)</script>",
        '<img src="x" onerror="alert(1)">',
        "function () { return document.cookie; }",
        "value => fetch(value)",
        "url(//attacker.invalid/image.svg)",
        "image-set(//attacker.invalid/image.png)",
        "@import 'attacker.css'",
        "//attacker.invalid/chart",
    ],
)
def test_chart_spec_rejects_active_content_in_allowed_text_fields(
    dangerous_title: str,
):
    payload = _vega_payload()
    payload["spec"]["title"] = dangerous_title

    with pytest.raises(ValueError, match="blocked URL, script, or expression"):
        ChartSpec.model_validate(payload)


def test_chart_spec_rejects_css_resource_in_color_field():
    payload = _vega_payload()
    payload["spec"]["mark"] = {
        "type": "bar",
        "color": "url(//attacker.invalid/paint.svg#gradient)",
    }

    with pytest.raises(ValueError, match="blocked URL, script, or expression"):
        ChartSpec.model_validate(payload)


def test_chart_spec_rejects_wrong_schema_version_for_format():
    payload = _vega_payload()
    payload["schema_version"] = "plotly-safe-1"

    with pytest.raises(ValueError, match="'v5-safe-1' was expected"):
        ChartSpec.model_validate(payload)


def test_chart_spec_rejects_external_dataset_reference():
    payload = _vega_payload()
    payload["dataset"] = {"reference": "https://attacker.invalid/data.json"}

    with pytest.raises(ValueError, match="is not of type 'array'"):
        ChartSpec.model_validate(payload)


def test_chart_spec_rejects_too_many_rows_before_schema_walk():
    payload = _vega_payload()
    payload["dataset"] = [
        {"region": "North", "revenue": index} for index in range(MAX_CHART_ROWS + 1)
    ]
    payload["metadata"]["row_count"] = MAX_CHART_ROWS + 1

    with pytest.raises(ValueError, match=f"{MAX_CHART_ROWS}-row limit"):
        ChartSpec.model_validate(payload)


def test_chart_spec_rejects_oversized_raw_dataset_before_iteration():
    class OversizedList(list[Any]):
        def __len__(self) -> int:
            return MAX_CHART_ROWS + 1

        def __iter__(self) -> Iterator[Any]:
            raise AssertionError("oversized dataset must not be normalized")

    payload = _vega_payload()
    payload["dataset"] = OversizedList()

    with pytest.raises(ValueError, match=f"{MAX_CHART_ROWS}-row limit"):
        ChartSpec.model_validate(payload)


def test_chart_spec_rejects_too_many_fields_before_schema_walk():
    columns = [f"column_{index}" for index in range(MAX_CHART_FIELDS + 1)]
    payload = _vega_payload()
    payload["dataset"] = [{column: index for index, column in enumerate(columns)}]
    payload["metadata"]["columns"] = columns

    with pytest.raises(ValueError, match=f"{MAX_CHART_FIELDS}-field limit"):
        ChartSpec.model_validate(payload)


def test_chart_spec_rejects_payload_over_serialized_size_limit():
    payload = _vega_payload()
    payload["dataset"] = [
        {"region": "North", "revenue": 10, "note": "x" * MAX_CHART_BYTES}
    ]
    payload["metadata"]["columns"].append("note")

    with pytest.raises(ValueError, match=f"{MAX_CHART_BYTES}-byte"):
        ChartSpec.model_validate(payload)


def test_chart_spec_normalizes_dataframe_scalars_to_strict_json():
    payload = _vega_payload()
    payload["dataset"] = [
        {
            "region": np.str_("North"),
            "revenue": np.int64(10),
            "ratio": np.float64(0.5),
            "missing": np.nan,
            "reported_at": pd.Timestamp("2026-08-11T12:00:00Z"),
            "as_of": date(2026, 8, 11),
        }
    ]
    payload["metadata"]["columns"] = list(payload["dataset"][0])

    chart = ChartSpec.model_validate(payload)
    row = chart.dataset[0]

    assert row == {
        "region": "North",
        "revenue": 10,
        "ratio": 0.5,
        "missing": None,
        "reported_at": "2026-08-11T12:00:00+00:00",
        "as_of": "2026-08-11",
    }


@pytest.mark.parametrize("number", [float("inf"), float("-inf")])
def test_chart_spec_rejects_infinite_numbers(number: float):
    payload = _vega_payload()
    payload["dataset"][0]["revenue"] = number

    with pytest.raises(ValueError, match="non-finite number"):
        ChartSpec.model_validate(payload)


def test_chart_spec_rejects_recursive_inputs_without_recursion_error():
    payload = _vega_payload()
    payload["spec"]["cycle"] = payload["spec"]

    with pytest.raises(ValueError, match="recursive object"):
        ChartSpec.model_validate(payload)


def test_chart_spec_revalidates_existing_instances():
    chart = ChartSpec.model_validate(_vega_payload())
    chart.spec["transform"] = []

    with pytest.raises(ValueError, match="blocked active-content property"):
        ChartSpec.model_validate(chart)


def test_chart_spec_revalidates_mutable_data_when_serialized():
    chart = ChartSpec.model_validate(_vega_payload())
    chart.spec["transform"] = []

    with pytest.raises(
        PydanticSerializationError,
        match="blocked active-content property",
    ):
        chart.model_dump()


def test_chart_spec_validates_direct_field_assignment():
    chart = ChartSpec.model_validate(_vega_payload())
    unsafe_spec = deepcopy(chart.spec)
    unsafe_spec["transform"] = []

    with pytest.raises(ValueError, match="blocked active-content property"):
        chart.spec = unsafe_spec


def test_chart_spec_serialization_preserves_standard_include_behavior():
    chart = ChartSpec.model_validate(_vega_payload())

    assert chart.model_dump(include={"format"}) == {"format": "vega-lite"}


@pytest.mark.parametrize(
    ("row_count", "truncated", "message"),
    [
        (0, None, "cannot be smaller"),
        (2, None, "must be true"),
        (1, True, "is inconsistent"),
    ],
)
def test_chart_spec_enforces_inline_row_count_consistency(
    row_count: int,
    truncated: bool | None,
    message: str,
):
    payload = _vega_payload()
    payload["metadata"]["row_count"] = row_count
    if truncated is not None:
        payload["metadata"]["truncated"] = truncated

    with pytest.raises(ValueError, match=message):
        ChartSpec.model_validate(payload)


def test_chart_spec_rejects_dataset_fields_missing_from_metadata():
    payload = _vega_payload()
    payload["dataset"][0]["undeclared"] = "value"

    with pytest.raises(ValueError, match="missing from metadata.columns"):
        ChartSpec.model_validate(payload)


@pytest.mark.parametrize("invalid_dataset", [["not-an-object"], [{"region": []}]])
def test_chart_spec_rejects_non_object_rows_and_non_scalar_values(
    invalid_dataset: list[Any],
):
    payload = _vega_payload()
    payload["dataset"] = invalid_dataset

    with pytest.raises(ValueError, match="JSON object|JSON scalars"):
        ChartSpec.model_validate(payload)


def test_chart_spec_rejects_encoding_fields_missing_from_metadata():
    payload = _vega_payload()
    payload["spec"]["encoding"]["x"]["field"] = "undeclared"

    with pytest.raises(ValueError, match="references undeclared field"):
        ChartSpec.model_validate(payload)


def test_plotly_profile_rejects_unsupported_trace_and_config():
    trace_payload = _plotly_payload()
    trace_payload["spec"]["data"][0]["type"] = "heatmap"
    with pytest.raises(ValueError, match="is not one of"):
        ChartSpec.model_validate(trace_payload)

    config_payload = _plotly_payload()
    config_payload["spec"]["config"] = {"displaylogo": False}
    with pytest.raises(ValueError, match="Additional properties"):
        ChartSpec.model_validate(config_payload)


def test_plotly_normalizer_reduces_generator_output_to_allowlist():
    generated = deepcopy(_plotly_payload()["spec"])
    generated["data"][0]["hovertemplate"] = "internal generator field"
    generated["layout"]["title"] = {"text": "Safe title", "font": {"size": 20}}
    generated["layout"]["font"] = {"family": "Untrusted"}
    generated["config"] = {"displaylogo": False, "plotlyServerURL": "https://evil"}

    normalized = normalize_plotly_json_spec(generated)

    assert normalized == {
        "data": [
            {
                "type": "bar",
                "name": "Revenue",
                "x": ["North"],
                "y": [10],
                "marker": {"color": "#15a8a8", "opacity": 0.8},
            }
        ],
        "layout": {
            "title": "Safe title",
            "showlegend": False,
            "xaxis": {"title": "Region", "type": "category"},
        },
    }


def test_plotly_normalizer_rejects_unsupported_trace_type():
    with pytest.raises(ValueError, match="Unsupported Plotly trace type 'table'"):
        normalize_plotly_json_spec({"data": [{"type": "table"}]})


@pytest.mark.parametrize(
    ("field", "invalid_value", "message"),
    [
        ("x", [{}], "json-scalar"),
        ("labels", ["x" * 513], "label"),
        ("values", ["10"], "number"),
    ],
)
def test_plotly_bulk_array_projection_preserves_item_validation(
    field: str,
    invalid_value: list[Any],
    message: str,
):
    payload = _plotly_payload()
    payload["spec"]["data"][0][field] = invalid_value

    with pytest.raises(ValueError, match=message):
        ChartSpec.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "invalid_value", "message"),
    [
        ("color", ["x" * 129], "color"),
        ("size", [501], "size"),
    ],
)
def test_plotly_marker_projection_preserves_item_validation(
    field: str,
    invalid_value: list[Any],
    message: str,
):
    payload = _plotly_payload()
    payload["spec"]["data"][0]["marker"][field] = invalid_value

    with pytest.raises(ValueError, match=message):
        ChartSpec.model_validate(payload)


def test_plotly_projection_preserves_array_size_limit():
    payload = _plotly_payload()
    payload["spec"]["data"][0]["x"] = list(range(MAX_CHART_ROWS + 1))

    with pytest.raises(ValueError, match=f"{MAX_CHART_ROWS}-item limit"):
        ChartSpec.model_validate(payload)


def test_plotly_preflight_rejects_oversized_raw_array_before_iteration():
    class OversizedList(list[Any]):
        def __len__(self) -> int:
            return MAX_CHART_ROWS + 1

        def __iter__(self) -> Iterator[Any]:
            raise AssertionError("oversized Plotly array must not be normalized")

    payload = _plotly_payload()
    payload["spec"]["data"][0]["x"] = OversizedList()

    with pytest.raises(ValueError, match=f"{MAX_CHART_ROWS}-item limit"):
        ChartSpec.model_validate(payload)


def test_chart_spec_validation_meets_max_inline_performance_budget():
    columns = [f"c{index:02d}" for index in range(23)]
    rows = [dict.fromkeys(columns, "12345678") for _ in range(MAX_CHART_ROWS)]
    payload = {
        "format": "vega-lite",
        "schema_version": "v5-safe-1",
        "spec": {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "mark": "bar",
            "encoding": {
                "x": {"field": columns[0], "type": "nominal"},
                "y": {"field": columns[1], "type": "quantitative"},
            },
        },
        "dataset": rows,
        "metadata": {"row_count": len(rows), "columns": columns},
    }
    payload_size = len(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    assert int(MAX_CHART_BYTES * 0.9) < payload_size < MAX_CHART_BYTES

    ChartSpec.model_validate(payload)
    samples = []
    for _ in range(20):
        started = time.perf_counter()
        ChartSpec.model_validate(payload)
        samples.append((time.perf_counter() - started) * 1000)

    p95_ms = sorted(samples)[18]
    assert p95_ms < 200, f"ChartSpec validation p95 was {p95_ms:.2f} ms"
