"""Tests for lineage evidence capture."""

from vanna.core.lineage import LineageCollector


def test_lineage_collector_records_sql_and_confidence():
    collector = LineageCollector()
    collector.set_schema("hash123", "snap123")
    collector.record_tool_result(
        tool_name="run_sql",
        success=True,
        metadata={
            "executed_sql": "SELECT 1",
            "row_count": 1,
            "execution_time_ms": 12.0,
            "validation_checks": ["read_only_policy_passed"],
        },
    )
    evidence = collector.finalize()
    assert evidence.schema_hash == "hash123"
    assert len(evidence.sql_executions) == 1
    assert evidence.confidence in {"Medium", "High"}
    assert "read_only_policy_passed" in evidence.validation_checks


def test_lineage_collector_tracks_retrieved_memories():
    collector = LineageCollector()
    collector.record_tool_result(
        tool_name="search_saved_correct_tool_uses",
        success=True,
        metadata={
            "retrieved_memories": [
                {"memory_id": "m1", "score": 0.9, "tool_name": "run_sql"}
            ]
        },
    )
    evidence = collector.finalize()
    assert len(evidence.retrieved_memories) == 1
    assert evidence.retrieved_memories[0].memory_id == "m1"
