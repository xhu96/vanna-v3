"""Security tests for the fetch_url tool — SSRF protection and input validation."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import ValidationError

from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.tools.fetch_url import (
    FetchUrlTool,
    FetchUrlToolArgs,
    _validate_url_target,
)


@pytest.fixture
def tool_context():
    return ToolContext(
        user=User(id="u1", group_memberships=["user"]),
        conversation_id="conv1",
        request_id="req1",
        agent_memory=DemoAgentMemory(),
    )


@pytest.fixture
def tool():
    return FetchUrlTool()


# ---------------------------------------------------------------------------
# SSRF: private/internal IP blocking
# ---------------------------------------------------------------------------


class TestSsrfProtection:
    """Verify that requests to private, loopback, and cloud metadata IPs are blocked."""

    @pytest.mark.asyncio
    async def test_blocks_localhost(self, tool, tool_context):
        args = FetchUrlToolArgs(url="http://127.0.0.1/data")
        result = await tool.execute(tool_context, args)
        assert result.success is False
        assert "private" in result.result_for_llm.lower() or "blocked" in result.result_for_llm.lower()

    @pytest.mark.asyncio
    async def test_blocks_private_network_10(self, tool, tool_context):
        args = FetchUrlToolArgs(url="http://10.0.0.1/data")
        result = await tool.execute(tool_context, args)
        assert result.success is False
        assert "private" in result.result_for_llm.lower() or "blocked" in result.result_for_llm.lower()

    @pytest.mark.asyncio
    async def test_blocks_private_network_172(self, tool, tool_context):
        args = FetchUrlToolArgs(url="http://172.16.0.1/data")
        result = await tool.execute(tool_context, args)
        assert result.success is False
        assert "private" in result.result_for_llm.lower() or "blocked" in result.result_for_llm.lower()

    @pytest.mark.asyncio
    async def test_blocks_private_network_192(self, tool, tool_context):
        args = FetchUrlToolArgs(url="http://192.168.1.1/data")
        result = await tool.execute(tool_context, args)
        assert result.success is False
        assert "private" in result.result_for_llm.lower() or "blocked" in result.result_for_llm.lower()

    @pytest.mark.asyncio
    async def test_blocks_link_local_metadata(self, tool, tool_context):
        args = FetchUrlToolArgs(url="http://169.254.169.254/latest/meta-data/")
        result = await tool.execute(tool_context, args)
        assert result.success is False
        assert "private" in result.result_for_llm.lower() or "blocked" in result.result_for_llm.lower()

    @pytest.mark.asyncio
    async def test_blocks_metadata_google(self, tool, tool_context):
        args = FetchUrlToolArgs(url="http://metadata.google.internal/computeMetadata/v1/")
        result = await tool.execute(tool_context, args)
        assert result.success is False
        assert "blocked" in result.result_for_llm.lower()

    @pytest.mark.asyncio
    async def test_blocks_ipv6_loopback(self, tool, tool_context):
        args = FetchUrlToolArgs(url="http://[::1]/data")
        result = await tool.execute(tool_context, args)
        assert result.success is False
        assert "private" in result.result_for_llm.lower() or "blocked" in result.result_for_llm.lower()

    @pytest.mark.asyncio
    async def test_blocks_zero_address(self, tool, tool_context):
        args = FetchUrlToolArgs(url="http://0.0.0.0/data")
        result = await tool.execute(tool_context, args)
        assert result.success is False


# ---------------------------------------------------------------------------
# SSRF: redirect chain validation
# ---------------------------------------------------------------------------


class TestRedirectSsrf:
    """Verify that redirect targets are re-validated against the SSRF blocklist."""

    @pytest.mark.asyncio
    async def test_redirect_to_private_ip_blocked(self, tool, tool_context):
        """A redirect from a public URL to a private IP must be blocked."""
        # Mock the first response as a redirect to 127.0.0.1
        redirect_response = httpx.Response(
            status_code=302,
            headers={"Location": "http://127.0.0.1/internal"},
            request=httpx.Request("GET", "http://example.com/redirect"),
        )

        with patch("vanna.tools.fetch_url._validate_url_target") as mock_validate:
            # First call (original URL) passes, second call (redirect) blocks
            mock_validate.side_effect = [
                None,  # original URL is fine
                "Requests to private/internal IP addresses are not allowed: 127.0.0.1",
            ]

            with patch("httpx.AsyncClient") as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.get = AsyncMock(return_value=redirect_response)
                MockClient.return_value.__aenter__ = AsyncMock(
                    return_value=mock_client_instance
                )
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

                args = FetchUrlToolArgs(url="http://example.com/redirect")
                result = await tool.execute(tool_context, args)

                assert result.success is False
                assert "ssrf" in result.result_for_llm.lower() or "redirect" in result.result_for_llm.lower()


# ---------------------------------------------------------------------------
# Pydantic field validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Verify Pydantic field constraints on FetchUrlToolArgs."""

    def test_rejects_invalid_method(self):
        with pytest.raises(ValidationError):
            FetchUrlToolArgs(url="http://example.com", method="DELETE")

    def test_rejects_put_method(self):
        with pytest.raises(ValidationError):
            FetchUrlToolArgs(url="http://example.com", method="PUT")

    def test_url_max_length(self):
        with pytest.raises(ValidationError):
            FetchUrlToolArgs(url="http://example.com/" + "a" * 2048)

    def test_timeout_ceiling(self):
        with pytest.raises(ValidationError):
            FetchUrlToolArgs(url="http://example.com", timeout_seconds=120)

    def test_timeout_floor(self):
        with pytest.raises(ValidationError):
            FetchUrlToolArgs(url="http://example.com", timeout_seconds=0.5)

    def test_body_max_length(self):
        with pytest.raises(ValidationError):
            FetchUrlToolArgs(
                url="http://example.com",
                method="POST",
                body="x" * 1_000_001,
            )

    def test_valid_args_accepted(self):
        args = FetchUrlToolArgs(
            url="http://example.com/api/data",
            method="GET",
            timeout_seconds=15.0,
        )
        assert args.method == "GET"
        assert args.timeout_seconds == 15.0


# ---------------------------------------------------------------------------
# URL scheme validation
# ---------------------------------------------------------------------------


class TestSchemeValidation:
    @pytest.mark.asyncio
    async def test_rejects_ftp_scheme(self, tool, tool_context):
        args = FetchUrlToolArgs(url="ftp://example.com/file")
        result = await tool.execute(tool_context, args)
        assert result.success is False
        assert "http" in result.result_for_llm.lower()

    @pytest.mark.asyncio
    async def test_rejects_file_scheme(self, tool, tool_context):
        args = FetchUrlToolArgs(url="file:///etc/passwd")
        result = await tool.execute(tool_context, args)
        assert result.success is False


# ---------------------------------------------------------------------------
# _validate_url_target unit tests
# ---------------------------------------------------------------------------


class TestValidateUrlTarget:
    def test_blocks_localhost_ip(self):
        assert _validate_url_target("http://127.0.0.1/data") is not None

    def test_blocks_private_10(self):
        assert _validate_url_target("http://10.0.0.1/data") is not None

    def test_blocks_metadata_hostname(self):
        result = _validate_url_target("http://metadata.google.internal/foo")
        assert result is not None
        assert "blocked" in result.lower()

    def test_allows_public_ip(self):
        """Public IPs should pass the IP-literal check; DNS won't block them."""
        # 8.8.8.8 is a known public IP
        result = _validate_url_target("http://8.8.8.8/data")
        assert result is None

    def test_no_hostname_returns_error(self):
        result = _validate_url_target("http:///nohost")
        assert result is not None


# ---------------------------------------------------------------------------
# Happy-path (mocked HTTP)
# ---------------------------------------------------------------------------


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_successful_get_request(self, tool, tool_context):
        mock_response = httpx.Response(
            status_code=200,
            text='{"message": "hello"}',
            headers={"content-type": "application/json"},
            request=httpx.Request("GET", "http://example.com/api"),
        )

        with patch("vanna.tools.fetch_url._validate_url_target", return_value=None):
            with patch("httpx.AsyncClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.get = AsyncMock(return_value=mock_response)
                MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

                args = FetchUrlToolArgs(url="http://example.com/api")
                result = await tool.execute(tool_context, args)

                assert result.success is True

    @pytest.mark.asyncio
    async def test_successful_post_request(self, tool, tool_context):
        mock_response = httpx.Response(
            status_code=200,
            text='{"result": "created"}',
            headers={"content-type": "application/json"},
            request=httpx.Request("POST", "http://example.com/api"),
        )

        with patch("vanna.tools.fetch_url._validate_url_target", return_value=None):
            with patch("httpx.AsyncClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.post = AsyncMock(return_value=mock_response)
                MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

                args = FetchUrlToolArgs(
                    url="http://example.com/api",
                    method="POST",
                    body='{"name": "test"}',
                )
                result = await tool.execute(tool_context, args)

                assert result.success is True
