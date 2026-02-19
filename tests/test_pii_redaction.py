"""Tests for PII redaction module."""

from vanna.personalization.redaction import redact_pii, check_storage_policy


class TestRedactPii:
    def test_email_redacted(self):
        r = redact_pii("Contact john@example.com for details")
        assert "john@example.com" not in r.text
        assert "email" in r.redacted_types
        assert r.redaction_count >= 1

    def test_phone_redacted(self):
        r = redact_pii("Call 555-123-4567 or +1 555 123 4567")
        assert "555-123-4567" not in r.text
        assert "phone" in r.redacted_types

    def test_ssn_redacted(self):
        r = redact_pii("SSN is 123-45-6789")
        assert "123-45-6789" not in r.text
        assert "ssn" in r.redacted_types

    def test_api_key_redacted(self):
        r = redact_pii("Use key sk-abc123def456ghi789jkl012mno")
        assert "sk-abc123def456ghi789jkl012mno" not in r.text
        assert "api_key" in r.redacted_types

    def test_credit_card_redacted(self):
        r = redact_pii("Card: 4111-1111-1111-1111")
        assert "4111-1111-1111-1111" not in r.text
        assert r.redaction_count >= 1

    def test_clean_text_unchanged(self):
        text = "This is a normal sentence with no PII"
        r = redact_pii(text)
        assert r.text == text
        assert r.redacted_types == []
        assert r.redaction_count == 0

    def test_multiple_types(self):
        r = redact_pii("Email john@test.com and call 555-123-4567")
        assert r.redaction_count >= 2
        assert "email" in r.redacted_types
        assert "phone" in r.redacted_types


class TestStoragePolicy:
    def test_rejects_query_result(self):
        p = check_storage_policy({"query_result": [1, 2, 3]})
        assert not p.passed
        assert len(p.violations) >= 1

    def test_rejects_raw_result(self):
        p = check_storage_policy({"raw_result": "data"})
        assert not p.passed

    def test_accepts_clean_data(self):
        p = check_storage_policy({"locale": "en-US", "currency": "USD"})
        assert p.passed
        assert p.violations == []

    def test_warns_null_provenance(self):
        p = check_storage_policy({"provenance": None})
        assert not p.passed
