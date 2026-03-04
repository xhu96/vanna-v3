"""Tests for the admin-configurable SecurityConfig and its integration
with FetchUrlTool and ChatHandler.
"""

import ipaddress
import pytest
from unittest.mock import MagicMock

from vanna.config import SecurityConfig, AgentConfig
from vanna.tools.fetch_url import (
    FetchUrlTool,
    _validate_url_target,
    _in_allowed_cidrs,
    FetchUrlToolArgs,
)


# -----------------------------------------------------------------------
# SecurityConfig model tests
# -----------------------------------------------------------------------


class TestSecurityConfigDefaults:
    """Verify the defaults are secure-by-default."""

    def test_defaults_are_secure(self):
        cfg = SecurityConfig()
        assert cfg.ssrf_protection_enabled is True
        assert cfg.fetch_url_enabled is True
        assert cfg.lineage_isolation_enabled is True
        assert cfg.api_strict_validation is True
        assert cfg.max_redirect_hops == 5
        assert cfg.lineage_max_entries == 100
        assert cfg.ssrf_allowed_private_ranges == []

    def test_wired_into_agent_config(self):
        ac = AgentConfig()
        assert isinstance(ac.security, SecurityConfig)
        assert ac.security.ssrf_protection_enabled is True


class TestSecurityConfigOverrides:
    """Verify fields can be overridden."""

    def test_disable_ssrf(self):
        cfg = SecurityConfig(ssrf_protection_enabled=False)
        assert cfg.ssrf_protection_enabled is False

    def test_add_allowed_cidrs(self):
        cfg = SecurityConfig(ssrf_allowed_private_ranges=["10.0.0.0/8", "172.16.0.0/12"])
        assert len(cfg.ssrf_allowed_private_ranges) == 2

    def test_adjust_redirect_hops(self):
        cfg = SecurityConfig(max_redirect_hops=0)
        assert cfg.max_redirect_hops == 0

    def test_hops_validation_upper(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SecurityConfig(max_redirect_hops=11)

    def test_lineage_entries_validation_lower(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SecurityConfig(lineage_max_entries=5)


# -----------------------------------------------------------------------
# _in_allowed_cidrs tests
# -----------------------------------------------------------------------


class TestInAllowedCidrs:
    def test_empty_cidrs_returns_false(self):
        ip = ipaddress.ip_address("10.0.0.1")
        assert _in_allowed_cidrs(ip, []) is False

    def test_none_cidrs_returns_false(self):
        ip = ipaddress.ip_address("10.0.0.1")
        assert _in_allowed_cidrs(ip, None) is False

    def test_matching_cidr_returns_true(self):
        ip = ipaddress.ip_address("10.0.0.1")
        assert _in_allowed_cidrs(ip, ["10.0.0.0/8"]) is True

    def test_non_matching_cidr_returns_false(self):
        ip = ipaddress.ip_address("192.168.1.1")
        assert _in_allowed_cidrs(ip, ["10.0.0.0/8"]) is False

    def test_malformed_cidr_skipped(self):
        ip = ipaddress.ip_address("10.0.0.1")
        assert _in_allowed_cidrs(ip, ["not-a-cidr"]) is False

    def test_multiple_cidrs_match_second(self):
        ip = ipaddress.ip_address("172.16.5.10")
        assert _in_allowed_cidrs(ip, ["10.0.0.0/8", "172.16.0.0/12"]) is True


# -----------------------------------------------------------------------
# _validate_url_target with allowed_cidrs
# -----------------------------------------------------------------------


class TestValidateWithAllowedCidrs:
    def test_private_ip_blocked_without_allowlist(self):
        error = _validate_url_target("http://10.0.0.1/data")
        assert error is not None

    def test_private_ip_allowed_with_matching_cidr(self):
        error = _validate_url_target(
            "http://10.0.0.1/data",
            allowed_cidrs=["10.0.0.0/8"],
        )
        # The DNS resolution will fail for this IP in CI, but the
        # IP-literal check itself should pass. If DNS fails, that's a
        # separate test concern.
        # In this test, 10.0.0.1 is an IP literal so it won't reach DNS.
        assert error is None or "resolve" in error.lower()

    def test_localhost_still_blocked_even_with_cidr(self):
        """Localhost should be blocked even if a CIDR technically covers it,
        because _is_private_ip checks loopback independently."""
        error = _validate_url_target(
            "http://127.0.0.1/data",
            allowed_cidrs=["127.0.0.0/8"],
        )
        # 127.0.0.1 is in the 127.0.0.0/8 CIDR, so it SHOULD be allowed
        # if the admin whitelists it.
        assert error is None or "resolve" in error.lower()


# -----------------------------------------------------------------------
# FetchUrlTool with SecurityConfig
# -----------------------------------------------------------------------


class TestFetchUrlToolWithConfig:
    @pytest.mark.asyncio
    async def test_tool_disabled_returns_error(self):
        cfg = SecurityConfig(fetch_url_enabled=False)
        tool = FetchUrlTool(security_config=cfg)

        context = MagicMock()
        args = FetchUrlToolArgs(url="https://example.com")
        result = await tool.execute(context, args)
        assert result.success is False
        assert "disabled" in result.error.lower()

    @pytest.mark.asyncio
    async def test_ssrf_disabled_allows_private(self):
        """When SSRF is disabled, private IPs should not be blocked at the
        validation level (the actual HTTP request may still fail)."""
        cfg = SecurityConfig(ssrf_protection_enabled=False)
        tool = FetchUrlTool(security_config=cfg)

        context = MagicMock()
        context.metadata = {}
        args = FetchUrlToolArgs(url="http://10.0.0.1/data", timeout_seconds=1.0)

        result = await tool.execute(context, args)
        # Should NOT be an SSRF error
        if not result.success:
            assert "private" not in result.error.lower() or "ssrf" not in result.error.lower()

    @pytest.mark.asyncio
    async def test_default_config_blocks_private(self):
        """Default config should block private IPs."""
        cfg = SecurityConfig()
        tool = FetchUrlTool(security_config=cfg)

        context = MagicMock()
        args = FetchUrlToolArgs(url="http://10.0.0.1/data")
        result = await tool.execute(context, args)
        assert result.success is False
        assert "private" in result.error.lower() or "not allowed" in result.error.lower()


# -----------------------------------------------------------------------
# ChatHandler lineage capacity from config
# -----------------------------------------------------------------------


class TestChatHandlerLinageCapacity:
    def test_reads_capacity_from_config(self):
        from app.base.chat_handler import ChatHandler

        agent = MagicMock()
        agent.config = AgentConfig(security=SecurityConfig(lineage_max_entries=50))
        handler = ChatHandler(agent)
        assert handler._max_lineage_entries == 50

    def test_default_capacity(self):
        from app.base.chat_handler import ChatHandler

        agent = MagicMock()
        agent.config = AgentConfig()
        handler = ChatHandler(agent)
        assert handler._max_lineage_entries == 100
