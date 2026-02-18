"""Tests for declarative ChartSpec validation."""

import pytest

from vanna.core.chart_spec import ChartSpec


def test_chart_spec_accepts_valid_vega_lite_spec():
    chart = ChartSpec(
        format="vega-lite",
        schema_version="v5",
        spec={
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "mark": "bar",
            "encoding": {
                "x": {"field": "category", "type": "nominal"},
                "y": {"field": "value", "type": "quantitative"},
            },
            "data": {"name": "dataset"},
        },
        dataset=[{"category": "A", "value": 10}],
    )
    assert chart.format == "vega-lite"


def test_chart_spec_rejects_invalid_shape():
    with pytest.raises(ValueError, match="Invalid vega-lite chart spec"):
        ChartSpec(
            format="vega-lite",
            schema_version="v5",
            spec={"encoding": {}},
            dataset=[],
        )


def test_chart_spec_rejects_executable_tokens():
    with pytest.raises(ValueError, match="blocked executable token"):
        ChartSpec(
            format="vega-lite",
            schema_version="v5",
            spec={
                "mark": "bar",
                "encoding": {
                    "x": {"field": "a", "type": "nominal"},
                    "y": {"field": "b", "type": "quantitative"},
                },
                "transform": [{"calculate": "javascript:alert(1)", "as": "x"}],
            },
            dataset=[],
        )
