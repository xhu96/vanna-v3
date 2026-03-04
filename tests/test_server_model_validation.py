"""Tests for public API model validation (ChatRequest, RequestContext)."""

import pytest
from pydantic import ValidationError

from app.base.models import ChatRequest
from vanna.core.user.request_context import RequestContext


class TestChatRequestValidation:
    """Verify that ChatRequest enforces strict field constraints."""

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            ChatRequest(message="hello", evil_field="injected")

    def test_message_max_length(self) -> None:
        with pytest.raises(ValidationError):
            ChatRequest(message="x" * 50_001)

    def test_conversation_id_pattern_valid(self) -> None:
        req = ChatRequest(message="hello", conversation_id="conv_abc123")
        assert req.conversation_id == "conv_abc123"

    def test_conversation_id_pattern_rejects_spaces(self) -> None:
        with pytest.raises(ValidationError):
            ChatRequest(message="hello", conversation_id="conv abc")

    def test_conversation_id_pattern_rejects_special_chars(self) -> None:
        with pytest.raises(ValidationError):
            ChatRequest(message="hello", conversation_id="conv/../../etc")

    def test_conversation_id_max_length(self) -> None:
        with pytest.raises(ValidationError):
            ChatRequest(message="hello", conversation_id="a" * 129)

    def test_request_id_max_length(self) -> None:
        with pytest.raises(ValidationError):
            ChatRequest(message="hello", request_id="r" * 129)

    def test_valid_request(self) -> None:
        req = ChatRequest(
            message="What are the top customers?",
            conversation_id="conv_12345678",
            request_id="req_abcdef",
        )
        assert req.message == "What are the top customers?"
        assert req.conversation_id == "conv_12345678"

    def test_valid_request_no_optional_fields(self) -> None:
        req = ChatRequest(message="hello")
        assert req.conversation_id is None
        assert req.request_id is None
        assert req.metadata == {}


class TestRequestContextValidation:
    """Verify that RequestContext enforces strict field constraints."""

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            RequestContext(evil="injected")

    def test_valid_context(self) -> None:
        ctx = RequestContext(
            cookies={"session": "abc"},
            headers={"Authorization": "Bearer token"},
            remote_addr="127.0.0.1",
        )
        assert ctx.get_cookie("session") == "abc"
        assert ctx.get_header("authorization") == "Bearer token"

    def test_valid_empty_context(self) -> None:
        ctx = RequestContext()
        assert ctx.cookies == {}
        assert ctx.headers == {}
        assert ctx.remote_addr is None
