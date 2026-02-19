"""Tests for the PreferenceResolverEnhancer."""

import pytest
import asyncio
from unittest.mock import MagicMock
from vanna.personalization.models import (
    UserProfile, TenantProfile, GlossaryEntry,
)
from vanna.personalization.stores import (
    InMemoryProfileStore, InMemoryGlossaryStore,
)
from vanna.personalization.preference_resolver import PreferenceResolverEnhancer


@pytest.fixture
def stores():
    return InMemoryProfileStore(), InMemoryGlossaryStore()


def _make_user(user_id="u1", tenant_id="t1"):
    user = MagicMock()
    user.id = user_id
    user.tenant_id = tenant_id
    return user


class TestPreferenceResolver:
    def test_injects_preferences(self, stores):
        profile_store, glossary_store = stores
        async def run():
            # Set up tenant + user profiles
            await profile_store.upsert_tenant_profile(
                TenantProfile(
                    tenant_id="t1",
                    personalization_enabled=True,
                    default_currency="USD",
                )
            )
            await profile_store.upsert_user_profile(
                UserProfile(
                    user_id="u1", tenant_id="t1",
                    locale="en-GB", currency="GBP",
                    personalization_enabled=True,
                )
            )

            enhancer = PreferenceResolverEnhancer(profile_store, glossary_store)
            user = _make_user()
            result = await enhancer.enhance_system_prompt(
                "You are an assistant", "Show revenue", user
            )
            assert "Locale: en-GB" in result
            assert "Currency: GBP" in result

        asyncio.run(run())

    def test_falls_back_to_tenant_defaults(self, stores):
        profile_store, glossary_store = stores
        async def run():
            await profile_store.upsert_tenant_profile(
                TenantProfile(
                    tenant_id="t1",
                    personalization_enabled=True,
                    default_currency="USD",
                    default_locale="en-US",
                )
            )
            await profile_store.upsert_user_profile(
                UserProfile(
                    user_id="u1", tenant_id="t1",
                    personalization_enabled=True,
                    # No locale/currency overrides
                )
            )

            enhancer = PreferenceResolverEnhancer(profile_store, glossary_store)
            user = _make_user()
            result = await enhancer.enhance_system_prompt(
                "You are an assistant", "question", user
            )
            assert "Locale: en-US" in result
            assert "Currency: USD" in result

        asyncio.run(run())

    def test_glossary_injected(self, stores):
        profile_store, glossary_store = stores
        async def run():
            await profile_store.upsert_tenant_profile(
                TenantProfile(tenant_id="t1", personalization_enabled=True)
            )
            await profile_store.upsert_user_profile(
                UserProfile(
                    user_id="u1", tenant_id="t1",
                    personalization_enabled=True,
                )
            )
            await glossary_store.create_entry(
                GlossaryEntry(
                    tenant_id="t1", term="GMV",
                    definition="Gross merchandise value",
                    synonyms=["gross merch value"],
                    approved=True,
                )
            )
            enhancer = PreferenceResolverEnhancer(profile_store, glossary_store)
            user = _make_user()
            result = await enhancer.enhance_system_prompt(
                "You are an assistant", "question", user
            )
            assert "GMV" in result
            assert "Gross merchandise value" in result
            assert "gross merch value" in result

        asyncio.run(run())

    def test_disabled_personalization_no_injection(self, stores):
        profile_store, glossary_store = stores
        async def run():
            await profile_store.upsert_tenant_profile(
                TenantProfile(tenant_id="t1", personalization_enabled=False)
            )
            enhancer = PreferenceResolverEnhancer(profile_store, glossary_store)
            user = _make_user()
            result = await enhancer.enhance_system_prompt(
                "You are an assistant", "question", user
            )
            assert result == "You are an assistant"

        asyncio.run(run())

    def test_enhance_user_messages_noop(self, stores):
        profile_store, glossary_store = stores
        async def run():
            enhancer = PreferenceResolverEnhancer(profile_store, glossary_store)
            user = _make_user()
            messages = [{"role": "user", "content": "hello"}]
            result = await enhancer.enhance_user_messages(messages, user)
            assert result == messages

        asyncio.run(run())
