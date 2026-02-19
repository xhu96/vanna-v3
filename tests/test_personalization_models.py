"""Tests for personalization Pydantic models."""

import pytest
from datetime import datetime
from vanna.personalization.models import (
    UserProfile,
    TenantProfile,
    GlossaryEntry,
    SessionMemoryEntry,
    Provenance,
)


class TestUserProfile:
    def test_create_minimal(self):
        p = UserProfile(user_id="u1", tenant_id="t1")
        assert p.user_id == "u1"
        assert p.tenant_id == "t1"
        assert p.personalization_enabled is False
        assert p.locale is None
        assert p.department_tags == []

    def test_create_full(self):
        p = UserProfile(
            user_id="u1",
            tenant_id="t1",
            locale="en-US",
            currency="USD",
            fiscal_year_start_month=4,
            date_format="YYYY-MM-DD",
            number_format="1,000.00",
            department_tags=["engineering"],
            role_tags=["analyst"],
            preferred_chart_type="bar",
            preferred_table_style="compact",
            personalization_enabled=True,
            provenance=Provenance(author="admin"),
        )
        assert p.locale == "en-US"
        assert p.fiscal_year_start_month == 4
        assert p.personalization_enabled is True

    def test_fiscal_month_validation(self):
        with pytest.raises(Exception):
            UserProfile(user_id="u1", tenant_id="t1", fiscal_year_start_month=13)
        with pytest.raises(Exception):
            UserProfile(user_id="u1", tenant_id="t1", fiscal_year_start_month=0)

    def test_json_roundtrip(self):
        p = UserProfile(user_id="u1", tenant_id="t1", locale="en-GB")
        data = p.model_dump(mode="json")
        p2 = UserProfile(**data)
        assert p2.user_id == p.user_id
        assert p2.locale == p.locale

    def test_json_schema_generation(self):
        schema = UserProfile.model_json_schema()
        assert "properties" in schema
        assert "user_id" in schema["properties"]
        assert "tenant_id" in schema["properties"]
        assert "personalization_enabled" in schema["properties"]


class TestTenantProfile:
    def test_create_minimal(self):
        t = TenantProfile(tenant_id="t1")
        assert t.tenant_id == "t1"
        assert t.personalization_enabled is False
        assert t.session_memory_retention_days == 7

    def test_retention_days_validation(self):
        with pytest.raises(Exception):
            TenantProfile(tenant_id="t1", session_memory_retention_days=0)


class TestGlossaryEntry:
    def test_create_tenant_level(self):
        e = GlossaryEntry(tenant_id="t1", term="GMV", definition="Gross merch value")
        assert e.tenant_id == "t1"
        assert e.user_id is None
        assert e.approved is False
        assert e.entry_id  # auto-generated

    def test_create_user_override(self):
        e = GlossaryEntry(
            tenant_id="t1",
            user_id="u1",
            term="Revenue",
            definition="Total sales",
            synonyms=["sales", "turnover"],
            category="metric",
        )
        assert e.user_id == "u1"
        assert len(e.synonyms) == 2


class TestSessionMemoryEntry:
    def test_create(self):
        exp = datetime(2099, 1, 1)
        e = SessionMemoryEntry(
            session_id="s1",
            user_id="u1",
            tenant_id="t1",
            content="test memory",
            expires_at=exp,
        )
        assert e.content == "test memory"
        assert e.expires_at == exp


class TestProvenance:
    def test_defaults(self):
        p = Provenance(author="admin")
        assert p.source == "api"
        assert isinstance(p.timestamp, datetime)
