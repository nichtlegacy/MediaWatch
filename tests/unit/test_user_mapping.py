import logging
from types import SimpleNamespace

import pytest

from cogs.user_mapping import UserMapping


def make_cog(tmp_path, authorized=(111,), mapping=None):
    """Build a UserMapping instance without touching __init__ side effects."""
    cog = UserMapping.__new__(UserMapping)
    cog.bot = SimpleNamespace(user=None)
    cog.logger = logging.getLogger("test.user_mapping")
    cog.mapping_file = str(tmp_path / "user_mapping.json")
    cog.authorized_users = list(authorized)
    if mapping is not None:
        cog._save_mapping(mapping)
    return cog


def interaction(user_id, platform="plex"):
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        namespace=SimpleNamespace(platform=platform),
    )


@pytest.mark.asyncio
async def test_autocomplete_returns_nothing_for_unauthorized_user(tmp_path):
    cog = make_cog(tmp_path, mapping={"plex": {"alice": "Alice"}, "jellyfin": {}})

    choices = await cog.username_autocomplete(interaction(999), "")

    assert choices == []


@pytest.mark.asyncio
async def test_autocomplete_returns_matches_for_authorized_user(tmp_path):
    cog = make_cog(tmp_path, mapping={"plex": {"alice": "Alice", "bob": "Bob"}, "jellyfin": {}})

    choices = await cog.username_autocomplete(interaction(111), "ali")

    assert [choice.value for choice in choices] == ["alice"]


def test_save_mapping_leaves_previous_file_intact_when_write_fails(tmp_path, monkeypatch):
    cog = make_cog(tmp_path, mapping={"plex": {"alice": "Alice"}, "jellyfin": {}})

    def exploding_write(path, payload, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("cogs.user_mapping.write_json_atomic", exploding_write)
    assert cog._save_mapping({"plex": {}, "jellyfin": {}}) is False

    monkeypatch.undo()
    assert cog._load_mapping("plex") == {"alice": "Alice"}
    assert [path.name for path in tmp_path.iterdir()] == ["user_mapping.json"]


def test_media_core_mapping_update_stays_flat_for_jellyfin(tmp_path):
    cog = make_cog(tmp_path)
    jellyfin_core = SimpleNamespace(
        user_mapping={},
        jellyfin_service=SimpleNamespace(user_mapping={}),
    )
    cog.bot = SimpleNamespace(
        user=None,
        get_cog=lambda name: jellyfin_core if name == "JellyfinCore" else None,
    )

    cog._update_media_core_mapping("jellyfin", {"alice": "Alice A."})

    # A nested {"jellyfin": {...}} wrapper here would break every lookup in the
    # service, which loads and expects the flat mapping.
    assert jellyfin_core.jellyfin_service.user_mapping == {"alice": "Alice A."}
    assert jellyfin_core.user_mapping == {"alice": "Alice A."}


def test_init_tolerates_blank_entries_in_authorized_users(monkeypatch):
    # Env validation accepts "123, ,456"; a stricter parse here used to raise
    # ValueError and keep the cog from loading at all.
    monkeypatch.setenv("DISCORD_AUTHORIZED_USERS", " 123, ,456 ")
    monkeypatch.setattr(UserMapping, "_ensure_mapping_file", lambda self: None)
    monkeypatch.setattr(UserMapping, "_migrate_flat_to_nested", lambda self: None)

    cog = UserMapping(SimpleNamespace(user=None))

    assert cog.authorized_users == [123, 456]
