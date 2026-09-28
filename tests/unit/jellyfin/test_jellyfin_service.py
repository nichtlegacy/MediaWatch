import time
from datetime import datetime, timedelta, timezone

import pytest

from cogs.media_core.jellyfin.jellyfin_service import JellyfinMediaService
from cogs.media_core.shared.models import LibraryStats


def make_fake_jellyfin_client(connect_results, auth_failed=False):
    class FakeJellyfinClient:
        def __init__(self, jellyfin_url, jellyfin_api_key):
            self._connect_results = list(connect_results)
            self.connected = False
            self.server_name = "Fake Jellyfin"
            self.server_version = "10.0"
            self.disconnected = False
            self.auth_failed = auth_failed

        async def connect(self):
            result = self._connect_results.pop(0) if self._connect_results else False
            self.connected = result
            return result

        async def disconnect(self):
            self.disconnected = True

        def is_connected(self):
            return self.connected

    return FakeJellyfinClient


def make_utc_sequence(*timestamps):
    values = list(timestamps)

    def _utcnow():
        return values.pop(0)

    return _utcnow


@pytest.mark.asyncio
async def test_jellyfin_service_marks_first_connect_failure_offline_immediately(monkeypatch):
    now = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.JellyfinClient",
        make_fake_jellyfin_client([False]),
    )
    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.discord.utils.utcnow",
        make_utc_sequence(now),
    )

    service = JellyfinMediaService(
        jellyfin_url="http://jellyfin",
        jellyfin_api_key="token",
        config={"server": {"offline_threshold": 300}},
        user_mapping={},
    )

    status = await service.get_server_status()

    assert status.is_online is False
    assert status.offline_since == now
    assert status.stream_count == 0


@pytest.mark.asyncio
async def test_jellyfin_service_uses_cached_online_state_within_threshold_after_success(
    monkeypatch,
):
    start = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.JellyfinClient",
        make_fake_jellyfin_client([True, False]),
    )
    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.discord.utils.utcnow",
        make_utc_sequence(start, start + timedelta(seconds=10)),
    )

    service = JellyfinMediaService(
        jellyfin_url="http://jellyfin",
        jellyfin_api_key="token",
        config={"server": {"offline_threshold": 300}},
        user_mapping={},
    )

    cached_stats = {"cached": "stats"}

    async def fake_get_active_streams():
        return []

    async def fake_get_library_stats():
        return cached_stats

    service.get_active_streams = fake_get_active_streams
    service.get_library_stats = fake_get_library_stats

    await service.get_server_status()
    service._library_cache = cached_stats

    status = await service.get_server_status()

    assert status.is_online is True
    assert status.library_stats == cached_stats
    assert status.stream_count == 0


@pytest.mark.asyncio
async def test_jellyfin_service_resets_offline_tracking_after_recovery(monkeypatch):
    start = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.JellyfinClient",
        make_fake_jellyfin_client([False, True]),
    )
    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.discord.utils.utcnow",
        make_utc_sequence(start, start + timedelta(seconds=30)),
    )

    service = JellyfinMediaService(
        jellyfin_url="http://jellyfin",
        jellyfin_api_key="token",
        config={"server": {"offline_threshold": 300}},
        user_mapping={},
    )

    async def fake_get_active_streams():
        return []

    async def fake_get_library_stats():
        return {}

    service.get_active_streams = fake_get_active_streams
    service.get_library_stats = fake_get_library_stats

    first_status = await service.get_server_status()
    recovered_status = await service.get_server_status()

    assert first_status.is_online is False
    assert recovered_status.is_online is True
    assert service._offline_since is None
    assert service._first_failure_time is None


@pytest.mark.asyncio
async def test_jellyfin_service_uses_persisted_online_since_until_offline_threshold_is_exceeded(
    monkeypatch,
):
    start = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
    persisted_updates = []

    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.JellyfinClient",
        make_fake_jellyfin_client([False, True]),
    )
    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.load_online_since", lambda platform, *_: 1000.0
    )
    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.persist_online_since",
        lambda platform, timestamp: persisted_updates.append((platform, timestamp)),
    )
    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.discord.utils.utcnow",
        make_utc_sequence(start, start + timedelta(seconds=30)),
    )
    monkeypatch.setattr("cogs.media_core.jellyfin.jellyfin_service.time.time", lambda: 2000.0)

    service = JellyfinMediaService(
        jellyfin_url="http://jellyfin",
        jellyfin_api_key="token",
        config={"server": {"offline_threshold": 300}},
        user_mapping={},
    )

    async def fake_get_active_streams():
        return []

    async def fake_get_library_stats():
        return {}

    service.get_active_streams = fake_get_active_streams
    service.get_library_stats = fake_get_library_stats

    first_status = await service.get_server_status()
    recovered_status = await service.get_server_status()

    assert first_status.is_online is False
    assert recovered_status.is_online is True
    assert recovered_status.start_time == 1000.0
    assert recovered_status.uptime_string == "00:16"
    assert persisted_updates == []


@pytest.mark.asyncio
async def test_jellyfin_service_resets_online_since_after_confirmed_offline_recovery(monkeypatch):
    start = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
    persisted_updates = []

    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.JellyfinClient",
        make_fake_jellyfin_client([True, False, False, True]),
    )
    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.load_online_since", lambda platform, *_: 1000.0
    )
    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.persist_online_since",
        lambda platform, timestamp: persisted_updates.append((platform, timestamp)),
    )
    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.discord.utils.utcnow",
        make_utc_sequence(
            start,
            start + timedelta(seconds=1),
            start + timedelta(seconds=302),
            start + timedelta(seconds=303),
        ),
    )
    monkeypatch.setattr("cogs.media_core.jellyfin.jellyfin_service.time.time", lambda: 2000.0)

    service = JellyfinMediaService(
        jellyfin_url="http://jellyfin",
        jellyfin_api_key="token",
        config={"server": {"offline_threshold": 300}},
        user_mapping={},
    )

    async def fake_get_active_streams():
        return []

    async def fake_get_library_stats():
        return {}

    service.get_active_streams = fake_get_active_streams
    service.get_library_stats = fake_get_library_stats

    await service.get_server_status()
    within_threshold_status = await service.get_server_status()
    offline_status = await service.get_server_status()
    recovered_status = await service.get_server_status()

    assert within_threshold_status.is_online is True
    assert offline_status.is_online is False
    assert recovered_status.is_online is True
    assert recovered_status.start_time == 2000.0
    assert recovered_status.uptime_string == "00:00"
    assert persisted_updates == [("jellyfin", 2000.0)]


def test_get_library_display_name_uses_cached_library(monkeypatch):
    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.JellyfinClient",
        make_fake_jellyfin_client([False]),
    )
    service = JellyfinMediaService(
        jellyfin_url="http://jellyfin",
        jellyfin_api_key="token",
        config={},
        user_mapping={},
    )
    service._library_cache = {
        "Serien": LibraryStats(
            section_id="1",
            section_title="Serien",
            item_count=10,
            episode_count=100,
            display_name="Serien",
            emoji="📺",
            show_episodes=True,
            library_type="tvshows",
        )
    }

    assert service.get_library_display_name("tvshows", "TV Shows") == "Serien"
    assert service.get_library_display_name("music", "Music") == "Music"


@pytest.mark.asyncio
async def test_jellyfin_service_reports_rejected_credentials_instead_of_offline(monkeypatch):
    now = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.JellyfinClient",
        make_fake_jellyfin_client([False], auth_failed=True),
    )
    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.discord.utils.utcnow",
        make_utc_sequence(now),
    )

    service = JellyfinMediaService(
        jellyfin_url="http://jellyfin",
        jellyfin_api_key="wrong-key",
        config={"server": {"offline_threshold": 300}},
        user_mapping={},
    )

    status = await service.get_server_status()

    assert status.auth_failed is True
    assert status.is_online is False
    assert status.offline_since is None


def _service_with_libraries(monkeypatch, libraries):
    """Build a service whose library cache holds the given (id, title, type, display) rows."""
    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.JellyfinClient",
        make_fake_jellyfin_client([False]),
    )
    service = JellyfinMediaService(
        jellyfin_url="http://jellyfin",
        jellyfin_api_key="token",
        config={},
        user_mapping={},
    )
    service._library_cache = {
        title: LibraryStats(
            section_id=section_id,
            section_title=title,
            item_count=1,
            episode_count=0,
            display_name=display,
            emoji="🎥",
            show_episodes=False,
            library_type=library_type,
        )
        for section_id, title, library_type, display in libraries
    }
    return service


@pytest.mark.asyncio
async def test_resolve_library_display_name_picks_the_items_own_library(monkeypatch):
    """Two libraries of one type: the type lookup would pick whichever came first."""
    service = _service_with_libraries(
        monkeypatch,
        [
            ("lib-1", "Filme", "movies", "Filme"),
            ("lib-2", "Filme 4K", "movies", "Filme 4K"),
        ],
    )

    async def fake_library(item_id, user_id=None):
        return {"id": "lib-2", "name": "Filme 4K"}

    monkeypatch.setattr(service.jellyfin_client, "get_item_library", fake_library, raising=False)

    assert await service.resolve_library_display_name("item", "movies", "Movies") == "Filme 4K"


@pytest.mark.asyncio
async def test_resolve_library_display_name_uses_the_server_name_on_a_cold_cache(monkeypatch):
    """A cold cache used to hand back the built-in English default silently."""
    service = _service_with_libraries(monkeypatch, [])

    async def fake_library(item_id, user_id=None):
        return {"id": "lib-1", "name": "Filme"}

    monkeypatch.setattr(service.jellyfin_client, "get_item_library", fake_library, raising=False)

    assert await service.resolve_library_display_name("item", "movies", "Movies") == "Filme"


@pytest.mark.asyncio
async def test_resolve_library_display_name_falls_back_when_the_lookup_fails(monkeypatch):
    """No ancestors, no cache: the caller's default is all that is left."""
    service = _service_with_libraries(monkeypatch, [])

    async def fake_library(item_id, user_id=None):
        return None

    monkeypatch.setattr(service.jellyfin_client, "get_item_library", fake_library, raising=False)

    assert await service.resolve_library_display_name("item", "movies", "Movies") == "Movies"


@pytest.mark.asyncio
async def test_resolve_library_display_name_prefers_the_configured_name(monkeypatch):
    """A display_name from config.yaml outranks the raw name on the server."""
    service = _service_with_libraries(monkeypatch, [("lib-1", "Filme", "movies", "Meine Filme")])

    async def fake_library(item_id, user_id=None):
        return {"id": "lib-1", "name": "Filme"}

    monkeypatch.setattr(service.jellyfin_client, "get_item_library", fake_library, raising=False)

    assert await service.resolve_library_display_name("item", "movies", "Movies") == "Meine Filme"


def _service_with_library_responses(monkeypatch, sections, counts):
    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.JellyfinClient",
        make_fake_jellyfin_client([]),
    )
    service = JellyfinMediaService("http://jellyfin", "key", {}, {})
    client = service.jellyfin_client
    client.connected = True

    async def get_library_sections():
        return sections

    async def count(parent_id):
        return counts

    client.get_library_sections = get_library_sections
    client.get_item_counts = count
    client.get_series_count = count
    client.get_episodes_count = count
    return service


def _good_cache():
    return {
        "Movies": LibraryStats(
            section_id="1",
            section_title="Movies",
            item_count=42,
            episode_count=0,
            display_name="Movies",
            emoji="🎬",
            show_episodes=False,
            library_type="movies",
        )
    }


@pytest.mark.parametrize(
    "sections, counts",
    [
        (None, 5),
        ([{"Name": "Movies", "ItemId": "1", "CollectionType": "movies"}], None),
        ([{"Name": "Shows", "ItemId": "2", "CollectionType": "tvshows"}], None),
    ],
    ids=["sections-failed", "item-count-failed", "tv-count-failed"],
)
async def test_failed_library_fetch_keeps_serving_the_previous_cache(monkeypatch, sections, counts):
    service = _service_with_library_responses(monkeypatch, sections, counts)
    good = _good_cache()
    service._library_cache = good

    assert await service.get_library_stats() is good
    assert service._library_cache is good
    assert service._last_library_update is None


async def test_failed_first_library_fetch_caches_nothing(monkeypatch):
    service = _service_with_library_responses(monkeypatch, None, 5)

    assert await service.get_library_stats() == {}
    assert service._last_library_update is None


async def test_successful_library_fetch_replaces_the_cache(monkeypatch):
    service = _service_with_library_responses(
        monkeypatch, [{"Name": "Movies", "ItemId": "1", "CollectionType": "movies"}], 0
    )
    service._library_cache = _good_cache()

    stats = await service.get_library_stats()

    assert stats["Movies"].item_count == 0
    assert service._library_cache is stats
    assert service._last_library_update is not None


@pytest.mark.asyncio
async def test_jellyfin_uptime_baseline_survives_a_restart_without_shutdown(monkeypatch):
    """A crash or `docker kill` skips close(); the minute refresh must cover it."""
    from cogs.media_core.shared import runtime_state

    online_since = time.time() - 86400
    runtime_state.persist_online_since("jellyfin", online_since)
    state = runtime_state.load_runtime_state()
    state["jellyfin"]["last_seen"] = time.time() - 250
    runtime_state.save_runtime_state(state)

    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.JellyfinClient",
        make_fake_jellyfin_client([True]),
    )
    config = {"server": {"offline_threshold": 300}}

    watching = JellyfinMediaService("http://jellyfin", "token", config, {})
    watching.get_active_streams = _no_streams
    watching.get_library_stats = _no_libraries
    await watching.get_server_status()

    # Killed 250 s after the last shutdown write, now three minutes later.
    state = runtime_state.load_runtime_state()
    assert state["jellyfin"]["last_seen"] == pytest.approx(time.time(), abs=5)
    state["jellyfin"]["last_seen"] -= 180
    runtime_state.save_runtime_state(state)

    restarted = JellyfinMediaService("http://jellyfin", "token", config, {})

    assert restarted._start_time == pytest.approx(online_since)


async def _no_streams():
    return []


async def _no_libraries():
    return {}


@pytest.mark.asyncio
async def test_jellyfin_close_saves_last_seen_even_when_disconnect_fails(monkeypatch):
    from cogs.media_core.shared import runtime_state

    runtime_state.persist_online_since("jellyfin", time.time() - 86400)
    state = runtime_state.load_runtime_state()
    state["jellyfin"]["last_seen"] = 1.0
    runtime_state.save_runtime_state(state)
    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.JellyfinClient",
        make_fake_jellyfin_client([]),
    )
    service = JellyfinMediaService("http://jellyfin", "token", {}, {})

    async def broken_disconnect():
        raise RuntimeError("connection pool already gone")

    service.jellyfin_client.disconnect = broken_disconnect

    with pytest.raises(RuntimeError):
        await service.close()

    last_seen = runtime_state.load_runtime_state()["jellyfin"]["last_seen"]
    assert last_seen == pytest.approx(time.time(), abs=5)


@pytest.mark.asyncio
async def test_jellyfin_close_during_an_outage_does_not_renew_the_baseline(monkeypatch):
    from cogs.media_core.shared import runtime_state

    runtime_state.persist_online_since("jellyfin", time.time() - 86400)
    state = runtime_state.load_runtime_state()
    state["jellyfin"]["last_seen"] = time.time() - 1000
    runtime_state.save_runtime_state(state)
    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.JellyfinClient",
        make_fake_jellyfin_client([False]),
    )
    config = {"server": {"offline_threshold": 0}}
    service = JellyfinMediaService("http://jellyfin", "token", config, {})

    status = await service.get_server_status()
    assert status.is_online is False
    await service.close()

    last_seen = runtime_state.load_runtime_state()["jellyfin"]["last_seen"]
    assert last_seen == pytest.approx(time.time() - 1000, abs=5)
    restarted = JellyfinMediaService(
        "http://jellyfin", "token", {"server": {"offline_threshold": 300}}, {}
    )
    assert restarted._start_time is None
