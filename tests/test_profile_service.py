"""Tests for profile and glossary services, consent manager."""

import pytest
import asyncio
from vanna.personalization.models import (
    UserProfile, TenantProfile, GlossaryEntry, Provenance,
)
from vanna.personalization.stores import (
    InMemoryProfileStore, InMemoryGlossaryStore,
)
from vanna.personalization.services import (
    ProfileService, GlossaryService, ConsentManager, AuthorizationError,
)


@pytest.fixture
def profile_store():
    return InMemoryProfileStore()


@pytest.fixture
def glossary_store():
    return InMemoryGlossaryStore()


@pytest.fixture
def profile_service(profile_store):
    return ProfileService(profile_store)


@pytest.fixture
def glossary_service(glossary_store):
    return GlossaryService(glossary_store)


@pytest.fixture
def consent_manager(profile_store):
    return ConsentManager(profile_store)


class TestProfileService:
    def test_upsert_and_get(self, profile_service):
        async def run():
            profile = UserProfile(user_id="u1", tenant_id="t1", locale="en-US")
            result = await profile_service.upsert_user_profile(
                profile, requesting_user_id="u1"
            )
            assert result.locale == "en-US"

            fetched = await profile_service.get_user_profile(
                "u1", "t1", requesting_user_id="u1"
            )
            assert fetched is not None
            assert fetched.locale == "en-US"

        asyncio.run(run())

    def test_rbac_denies_cross_user_read(self, profile_service):
        async def run():
            profile = UserProfile(user_id="u1", tenant_id="t1")
            await profile_service.upsert_user_profile(
                profile, requesting_user_id="u1"
            )
            with pytest.raises(AuthorizationError):
                await profile_service.get_user_profile(
                    "u1", "t1", requesting_user_id="u2"
                )

        asyncio.run(run())

    def test_admin_can_read_any_profile(self, profile_service):
        async def run():
            profile = UserProfile(user_id="u1", tenant_id="t1")
            await profile_service.upsert_user_profile(
                profile, requesting_user_id="u1"
            )
            fetched = await profile_service.get_user_profile(
                "u1", "t1",
                requesting_user_id="admin_user",
                requesting_user_groups=["admin"],
            )
            assert fetched is not None

        asyncio.run(run())

    def test_delete_profile(self, profile_service):
        async def run():
            profile = UserProfile(user_id="u1", tenant_id="t1")
            await profile_service.upsert_user_profile(
                profile, requesting_user_id="u1"
            )
            deleted = await profile_service.delete_user_profile(
                "u1", "t1", requesting_user_id="u1"
            )
            assert deleted is True

            fetched = await profile_service.get_user_profile(
                "u1", "t1", requesting_user_id="u1"
            )
            assert fetched is None

        asyncio.run(run())

    def test_export_profile(self, profile_service):
        async def run():
            profile = UserProfile(user_id="u1", tenant_id="t1", locale="en-GB")
            await profile_service.upsert_user_profile(
                profile, requesting_user_id="u1"
            )
            data = await profile_service.export_user_profile(
                "u1", "t1", requesting_user_id="u1"
            )
            assert data is not None
            assert data["locale"] == "en-GB"

        asyncio.run(run())

    def test_tenant_profile_requires_admin(self, profile_service):
        async def run():
            tp = TenantProfile(tenant_id="t1")
            with pytest.raises(AuthorizationError):
                await profile_service.upsert_tenant_profile(
                    tp, requesting_user_groups=["user"]
                )

        asyncio.run(run())


class TestGlossaryService:
    def test_create_and_list(self, glossary_service):
        async def run():
            entry = GlossaryEntry(
                tenant_id="t1", term="GMV", definition="Gross merch value"
            )
            result = await glossary_service.create_entry(
                entry, requesting_user_id="u1"
            )
            assert result.term == "GMV"

            entries = await glossary_service.list_entries("t1")
            assert len(entries) == 1

        asyncio.run(run())

    def test_search(self, glossary_service):
        async def run():
            entry = GlossaryEntry(
                tenant_id="t1", term="Revenue", definition="Total sales",
                synonyms=["turnover"],
            )
            await glossary_service.create_entry(
                entry, requesting_user_id="u1"
            )
            results = await glossary_service.search_entries("t1", "turnover")
            assert len(results) == 1

        asyncio.run(run())

    def test_delete_requires_admin(self, glossary_service):
        async def run():
            entry = GlossaryEntry(
                tenant_id="t1", term="GMV", definition="Gross merch value"
            )
            created = await glossary_service.create_entry(
                entry, requesting_user_id="u1"
            )
            with pytest.raises(AuthorizationError):
                await glossary_service.delete_entry(
                    created.entry_id,
                    requesting_user_id="u1",
                    requesting_user_groups=["user"],
                )

        asyncio.run(run())


class TestConsentManager:
    def test_enable_disable(self, consent_manager):
        async def run():
            # Initially not enabled
            assert not await consent_manager.is_enabled("u1", "t1")

            # Enable
            await consent_manager.enable_personalization("u1", "t1")
            assert await consent_manager.is_enabled("u1", "t1")

            # Disable
            await consent_manager.disable_personalization("u1", "t1")
            assert not await consent_manager.is_enabled("u1", "t1")

        asyncio.run(run())

    def test_export_and_delete(self, consent_manager):
        async def run():
            await consent_manager.enable_personalization("u1", "t1")
            data = await consent_manager.export_data("u1", "t1")
            assert data is not None
            assert data["personalization_enabled"] is True

            deleted = await consent_manager.delete_data("u1", "t1")
            assert deleted is True

        asyncio.run(run())
