import asyncio
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from unittest.mock import Mock

import pytest

from cogs.media_core.plex.plex_client import PlexClient
from cogs.media_core.plex.plex_service import PlexMediaService


class FakeTautulliClient:
    def __init__(self, tautulli_url, tautulli_api_key, config):
        self.closed = False

    async def close(self):
        self.closed = True


def make_fake_plex_client(connect_results, auth_failed=False):
    class FakePlexClient:
        def __init__(self, plex_url, plex_token):
            self._connect_results = list(connect_results)
            self.server = None
            self.start_time = 123
            self.disconnected = False
            self.auth_failed = auth_failed

        def connect(self):
            result = self._connect_results.pop(0) if self._connect_results else None
            self.server = result
            return result

        def disconnect(self):
            self.disconnected = True

        def get_server_name(self):
            return "Fake Plex"

        def get_server_version(self):
            return "1.0"

        def is_connected(self):
            return self.server is not None

    return FakePlexClient


def make_utc_sequence(*timestamps):
    values = list(timestamps)

    def _utcnow():
        return values.pop(0)

    return _utcnow


def test_build_library_stats_uses_count_queries_without_loading_items(monkeypatch):
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.PlexClient",
        make_fake_plex_client([]),
    )
    monkeypatch.setattr("cogs.media_core.plex.plex_service.TautulliClient", FakeTautulliClient)
    service = PlexMediaService("url", "token", None, None, {}, {})

    class Section:
        key = "1"
        title = "Shows"
        type = "show"

        def totalViewSize(self, libtype=None):
            return 1200 if libtype == "episode" else 50

        def all(self):  # pragma: no cover - regression guard
            raise AssertionError("library items must not be loaded to count them")

    stats = service._build_library_stats(Section(), {"show_episodes": True})

    assert stats.item_count == 50
    assert stats.episode_count == 1200


@pytest.mark.asyncio
async def test_plex_service_marks_first_connect_failure_offline_immediately(monkeypatch):
    now = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.PlexClient",
        make_fake_plex_client([None]),
    )
    monkeypatch.setattr("cogs.media_core.plex.plex_service.TautulliClient", FakeTautulliClient)
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.discord.utils.utcnow",
        make_utc_sequence(now),
    )

    service = PlexMediaService(
        plex_url="http://plex",
        plex_token="token",
        tautulli_url=None,
        tautulli_api_key=None,
        config={"server": {"offline_threshold": 300}},
        user_mapping={},
    )

    status = await service.get_server_status()

    assert status.is_online is False
    assert status.offline_since == now
    assert status.stream_count == 0


@pytest.mark.asyncio
async def test_plex_service_uses_cached_online_state_within_threshold_after_success(monkeypatch):
    start = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.PlexClient",
        make_fake_plex_client([object(), None]),
    )
    monkeypatch.setattr("cogs.media_core.plex.plex_service.TautulliClient", FakeTautulliClient)
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.discord.utils.utcnow",
        make_utc_sequence(start, start + timedelta(seconds=10)),
    )

    service = PlexMediaService(
        plex_url="http://plex",
        plex_token="token",
        tautulli_url=None,
        tautulli_api_key=None,
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
async def test_plex_service_resets_offline_tracking_after_recovery(monkeypatch):
    start = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.PlexClient",
        make_fake_plex_client([None, object()]),
    )
    monkeypatch.setattr("cogs.media_core.plex.plex_service.TautulliClient", FakeTautulliClient)
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.discord.utils.utcnow",
        make_utc_sequence(start, start + timedelta(seconds=30)),
    )

    service = PlexMediaService(
        plex_url="http://plex",
        plex_token="token",
        tautulli_url=None,
        tautulli_api_key=None,
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
async def test_plex_service_uses_persisted_online_since_until_offline_threshold_is_exceeded(
    monkeypatch,
):
    start = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
    persisted_online_since = 1000.0
    persisted_updates = []

    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.PlexClient",
        make_fake_plex_client([None, object()]),
    )
    monkeypatch.setattr("cogs.media_core.plex.plex_service.TautulliClient", FakeTautulliClient)
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.load_online_since",
        lambda platform, *_: persisted_online_since,
    )
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.persist_online_since",
        lambda platform, timestamp: persisted_updates.append((platform, timestamp)),
    )
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.discord.utils.utcnow",
        make_utc_sequence(start, start + timedelta(seconds=30)),
    )
    monkeypatch.setattr("cogs.media_core.plex.plex_service.time.time", lambda: 2000.0)

    service = PlexMediaService(
        plex_url="http://plex",
        plex_token="token",
        tautulli_url=None,
        tautulli_api_key=None,
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
    assert recovered_status.start_time == persisted_online_since
    assert recovered_status.uptime_string == "00:16"
    assert persisted_updates == []


@pytest.mark.asyncio
async def test_plex_service_resets_online_since_after_confirmed_offline_recovery(monkeypatch):
    start = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
    persisted_updates = []

    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.PlexClient",
        make_fake_plex_client([object(), None, None, object()]),
    )
    monkeypatch.setattr("cogs.media_core.plex.plex_service.TautulliClient", FakeTautulliClient)
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.load_online_since", lambda platform, *_: 1000.0
    )
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.persist_online_since",
        lambda platform, timestamp: persisted_updates.append((platform, timestamp)),
    )
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.discord.utils.utcnow",
        make_utc_sequence(
            start,
            start + timedelta(seconds=1),
            start + timedelta(seconds=302),
            start + timedelta(seconds=303),
        ),
    )
    monkeypatch.setattr("cogs.media_core.plex.plex_service.time.time", lambda: 2000.0)

    service = PlexMediaService(
        plex_url="http://plex",
        plex_token="token",
        tautulli_url=None,
        tautulli_api_key=None,
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
    assert persisted_updates == [("plex", 2000.0)]


@pytest.mark.asyncio
async def test_get_library_stats_runs_collection_off_thread(monkeypatch):
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.PlexClient",
        make_fake_plex_client([]),
    )
    monkeypatch.setattr("cogs.media_core.plex.plex_service.TautulliClient", FakeTautulliClient)

    service = PlexMediaService(
        plex_url="http://plex",
        plex_token="token",
        tautulli_url=None,
        tautulli_api_key=None,
        config={},
        user_mapping={},
    )
    service.plex_client.server = object()

    collected = {"Movies": "stats"}
    service._collect_library_stats = lambda: collected

    assert await service.get_library_stats() == collected
    assert service._library_cache == collected
    assert service._last_library_update is not None


@pytest.mark.asyncio
async def test_get_library_stats_keeps_cache_when_collection_fails(monkeypatch):
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.PlexClient",
        make_fake_plex_client([]),
    )
    monkeypatch.setattr("cogs.media_core.plex.plex_service.TautulliClient", FakeTautulliClient)

    service = PlexMediaService(
        plex_url="http://plex",
        plex_token="token",
        tautulli_url=None,
        tautulli_api_key=None,
        config={},
        user_mapping={},
    )
    service.plex_client.server = object()
    service._library_cache = {"cached": "stats"}
    service._collect_library_stats = lambda: None

    assert await service.get_library_stats() == {"cached": "stats"}
    assert service._last_library_update is None


@pytest.mark.asyncio
async def test_plex_service_reports_rejected_credentials_instead_of_offline(monkeypatch):
    now = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.PlexClient",
        make_fake_plex_client([None], auth_failed=True),
    )
    monkeypatch.setattr("cogs.media_core.plex.plex_service.TautulliClient", FakeTautulliClient)
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.discord.utils.utcnow",
        make_utc_sequence(now),
    )

    service = PlexMediaService(
        plex_url="http://plex",
        plex_token="wrong-token",
        tautulli_url=None,
        tautulli_api_key=None,
        config={"server": {"offline_threshold": 300}},
        user_mapping={},
    )

    status = await service.get_server_status()

    assert status.auth_failed is True
    assert status.is_online is False
    # No "offline since" - the server answered, it just rejected the token.
    assert status.offline_since is None


@pytest.mark.asyncio
async def test_plex_service_collects_library_stats_once_for_concurrent_callers(monkeypatch):
    """Both task loops reach get_library_stats() through get_server_status().

    They align every few minutes, and on a cold or expired cache both used to
    enumerate the whole library at once - seen twice within 80ms on the first
    dashboard cycle of a real deployment.
    """
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.PlexClient",
        make_fake_plex_client([object()]),
    )
    monkeypatch.setattr("cogs.media_core.plex.plex_service.TautulliClient", FakeTautulliClient)
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.load_online_since", lambda platform, *_: None
    )
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.persist_online_since", lambda platform, timestamp: None
    )

    service = PlexMediaService(
        plex_url="http://plex",
        plex_token="token",
        tautulli_url=None,
        tautulli_api_key=None,
        config={},
        user_mapping={},
    )

    collects = []

    def slow_collect():
        collects.append(1)
        return {}

    monkeypatch.setattr(service, "_collect_library_stats", slow_collect)
    monkeypatch.setattr(service.plex_client, "is_connected", lambda: True)

    await asyncio.gather(service.get_library_stats(), service.get_library_stats())

    assert len(collects) == 1


def _service_with_failing_sections(monkeypatch):
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.PlexClient",
        make_fake_plex_client([]),
    )
    monkeypatch.setattr("cogs.media_core.plex.plex_service.TautulliClient", FakeTautulliClient)
    service = PlexMediaService("http://plex", "token", None, None, {}, {})
    service.plex_client.server = object()
    # Run the real client method against a server whose sections() call fails,
    # so the test covers the client/service contract, not a stubbed return value.
    real_client = PlexClient("http://plex", "token")
    real_client._server = Mock()
    real_client._server.library.sections.side_effect = ConnectionError("offline")
    service.plex_client.get_library_sections = real_client.get_library_sections
    return service


async def test_failed_section_fetch_keeps_serving_the_previous_cache(monkeypatch):
    service = _service_with_failing_sections(monkeypatch)
    good = {"Movies": "stats"}
    service._library_cache = good
    service._last_library_update = None  # expired, so the fetch is attempted

    assert await service.get_library_stats() is good
    assert service._library_cache is good
    assert service._last_library_update is None


async def test_failed_first_section_fetch_caches_nothing(monkeypatch):
    service = _service_with_failing_sections(monkeypatch)

    assert await service.get_library_stats() == {}
    assert service._last_library_update is None


def test_failed_episode_count_keeps_the_last_known_count(monkeypatch):
    service = _service_with_failing_sections(monkeypatch)
    service.config = {"plex": {"sections": {"Shows": {"show_episodes": True}}}}
    service._library_cache = {"Shows": SimpleNamespace(episode_count=1200)}

    class Section:
        key = "1"
        title = "Shows"
        type = "show"

        def totalViewSize(self, libtype=None):
            if libtype == "episode":
                raise ConnectionError("timeout")
            return 50

    service.plex_client.get_library_sections = lambda: {"Shows": Section()}

    stats = service._collect_library_stats()
    assert stats["Shows"].item_count == 50
    assert stats["Shows"].episode_count == 1200

    service._library_cache = {}
    assert service._collect_library_stats()["Shows"].episode_count == 0


async def test_library_cache_age_follows_the_monotonic_clock(monkeypatch):
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.PlexClient",
        make_fake_plex_client([]),
    )
    monkeypatch.setattr("cogs.media_core.plex.plex_service.TautulliClient", FakeTautulliClient)
    service = PlexMediaService("http://plex", "token", None, None, {}, {})
    service.plex_client.server = object()
    clock = [1000.0]
    monkeypatch.setattr("cogs.media_core.plex.plex_service.time.monotonic", lambda: clock[0])
    results = iter([{"first": 1}, {"second": 2}])
    service._collect_library_stats = lambda: next(results)

    assert await service.get_library_stats() == {"first": 1}
    clock[0] += 900  # exactly the default interval: still fresh
    assert await service.get_library_stats() == {"first": 1}
    clock[0] += 1
    assert await service.get_library_stats() == {"second": 2}


@pytest.mark.asyncio
async def test_plex_uptime_baseline_survives_a_restart_without_shutdown(monkeypatch):
    """A crash or `docker kill` skips close(); the minute refresh must cover it."""
    from cogs.media_core.shared import runtime_state

    online_since = time.time() - 86400
    runtime_state.persist_online_since("plex", online_since)
    state = runtime_state.load_runtime_state()
    state["plex"]["last_seen"] = time.time() - 250
    runtime_state.save_runtime_state(state)

    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.PlexClient",
        make_fake_plex_client([object()]),
    )
    monkeypatch.setattr("cogs.media_core.plex.plex_service.TautulliClient", FakeTautulliClient)
    config = {"server": {"offline_threshold": 300}}

    watching = PlexMediaService("http://plex", "token", None, None, config, {})
    watching.get_active_streams = _no_streams
    watching.get_library_stats = _no_libraries
    await watching.get_server_status()

    # Killed 250 s after the last shutdown write, now three minutes later.
    state = runtime_state.load_runtime_state()
    assert state["plex"]["last_seen"] == pytest.approx(time.time(), abs=5)
    state["plex"]["last_seen"] -= 180
    runtime_state.save_runtime_state(state)

    restarted = PlexMediaService("http://plex", "token", None, None, config, {})

    assert restarted._online_since_timestamp == pytest.approx(online_since)


async def _no_streams():
    return []


async def _no_libraries():
    return {}


@pytest.mark.asyncio
async def test_plex_close_saves_last_seen_even_when_disconnect_fails(monkeypatch):
    from cogs.media_core.shared import runtime_state

    runtime_state.persist_online_since("plex", time.time() - 86400)
    state = runtime_state.load_runtime_state()
    state["plex"]["last_seen"] = 1.0
    runtime_state.save_runtime_state(state)
    monkeypatch.setattr("cogs.media_core.plex.plex_service.PlexClient", make_fake_plex_client([]))
    monkeypatch.setattr("cogs.media_core.plex.plex_service.TautulliClient", FakeTautulliClient)
    service = PlexMediaService("http://plex", "token", None, None, {}, {})

    def broken_disconnect():
        raise RuntimeError("connection pool already gone")

    service.plex_client.disconnect = broken_disconnect

    with pytest.raises(RuntimeError):
        await service.close()

    last_seen = runtime_state.load_runtime_state()["plex"]["last_seen"]
    assert last_seen == pytest.approx(time.time(), abs=5)


@pytest.mark.asyncio
async def test_plex_close_during_an_outage_does_not_renew_the_baseline(monkeypatch):
    from cogs.media_core.shared import runtime_state

    runtime_state.persist_online_since("plex", time.time() - 86400)
    state = runtime_state.load_runtime_state()
    state["plex"]["last_seen"] = time.time() - 1000
    runtime_state.save_runtime_state(state)
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_service.PlexClient", make_fake_plex_client([None])
    )
    monkeypatch.setattr("cogs.media_core.plex.plex_service.TautulliClient", FakeTautulliClient)
    config = {"server": {"offline_threshold": 0}}
    service = PlexMediaService("http://plex", "token", None, None, config, {})

    status = await service.get_server_status()
    assert status.is_online is False
    await service.close()

    last_seen = runtime_state.load_runtime_state()["plex"]["last_seen"]
    assert last_seen == pytest.approx(time.time() - 1000, abs=5)
    restarted = PlexMediaService(
        "http://plex", "token", None, None, {"server": {"offline_threshold": 300}}, {}
    )
    assert restarted._online_since_timestamp is None
