import asyncio
from datetime import datetime, timedelta

import pytest

from cogs.media_core.plex.tautulli_client import TautulliClient


class FixedDateTime(datetime):
    current = datetime(2026, 4, 12, 12, 0, 0)

    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return cls.current.astimezone(tz)
        return cls.current


@pytest.mark.parametrize("raw_ttl", ["1m", None, [60], True])
def test_non_numeric_user_stats_ttl_falls_back_to_the_default(raw_ttl, caplog):
    client = TautulliClient("http://tautulli", "secret", {"cache": {"user_stats_ttl": raw_ttl}})

    assert client.user_stats_ttl == 60
    assert "cache.user_stats_ttl must be a number of seconds" in caplog.text


def test_cache_write_prunes_expired_entries(monkeypatch):
    client = TautulliClient("http://tautulli", "secret", {"cache": {"user_stats_ttl": 60}})
    cache = {"expired": (99.0, "old"), "fresh": (101.0, "keep")}
    monkeypatch.setattr("cogs.media_core.plex.tautulli_client.time.time", lambda: 100.0)

    client._set_cached_value(cache, "new", "value")

    assert cache == {"fresh": (101.0, "keep"), "new": (160.0, "value")}


class FakeResponse:
    def __init__(self, payload, status=200, headers=None, body=None):
        self.payload = payload
        self.status = status
        self.headers = headers or {}
        self.body = body if body is not None else b""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self.payload

    async def read(self):
        return self.body


class FakeSession:
    def __init__(self, history_entries):
        self.history_entries = history_entries
        self.calls = []

    def get(self, url, params=None):
        params = dict(params or {})
        self.calls.append(params)
        cmd = params.get("cmd")

        if cmd == "get_home_stats":
            payload = {"response": {"result": "success", "data": {"rows": []}}}
            return FakeResponse(payload)

        if cmd == "get_plays_by_hourofday":
            payload = {"response": {"result": "success", "data": {"series": []}}}
            return FakeResponse(payload)

        if cmd == "get_plays_by_dayofweek":
            payload = {"response": {"result": "success", "data": {"categories": [], "series": []}}}
            return FakeResponse(payload)

        if cmd == "get_history":
            start = int(params.get("start", 0))
            length = int(params.get("length", 0))
            batch = self.history_entries[start : start + length]
            payload = {
                "response": {
                    "result": "success",
                    "data": {
                        "data": batch,
                        "recordsFiltered": len(self.history_entries),
                        "recordsTotal": len(self.history_entries),
                    },
                }
            }
            return FakeResponse(payload)

        raise AssertionError(f"Unexpected Tautulli command: {cmd}")


class UserStatsFakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None):
        params = dict(params or {})
        self.calls.append(params)
        cmd = params.get("cmd")

        if cmd == "get_history":
            payload = {
                "response": {
                    "result": "success",
                    "data": {"data": [{"date": 123, "duration": 456}]},
                }
            }
            return FakeResponse(payload)

        if cmd == "get_user_player_stats":
            payload = {
                "response": {
                    "result": "success",
                    "data": [{"player_name": "Apple TV", "total_time": 7200, "total_plays": 4}],
                }
            }
            return FakeResponse(payload)

        if cmd == "get_user_names":
            payload = {
                "response": {
                    "result": "success",
                    "data": [
                        {
                            "user_id": "user-1",
                            "username": "raw_user_1",
                            "friendly_name": "Friendly One",
                        },
                        {
                            "user_id": "user-2",
                            "username": "raw_user_2",
                            "friendly_name": "Friendly Two",
                        },
                    ],
                }
            }
            return FakeResponse(payload)

        if cmd == "get_user_watch_time_stats":
            payload = {
                "response": {
                    "result": "success",
                    "data": [
                        {"query_days": 1, "total_plays": 1, "total_time": 100},
                        {"query_days": 7, "total_plays": 3, "total_time": 300},
                        {"query_days": 30, "total_plays": 8, "total_time": 800},
                        {"query_days": 0, "total_plays": 42, "total_time": 4200},
                    ],
                }
            }
            return FakeResponse(payload)

        raise AssertionError(f"Unexpected Tautulli command: {cmd}")


class UserThumbFakeSession:
    # The content type is a parameter on purpose: ".png" is also the fallback of
    # the extension map, so a hardcoded image/png would pass even if the map
    # were deleted entirely.
    def __init__(self, content_type="image/jpeg"):
        self.calls = []
        self.content_type = content_type

    def get(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        return FakeResponse(
            {},
            headers={"Content-Type": self.content_type},
            body=b"avatar-bytes",
        )


@pytest.mark.asyncio
async def test_fetch_global_server_stats_paginates_history_for_exact_all_time(monkeypatch):
    now = FixedDateTime.current
    history_entries = [
        {"date": int((now - timedelta(hours=1)).timestamp()), "duration": 100, "user_id": "user-1"},
        {"date": int((now - timedelta(days=2)).timestamp()), "duration": 200, "user_id": "user-2"},
        {"date": int((now - timedelta(days=6)).timestamp()), "duration": 300, "user_id": "user-1"},
        {"date": int((now - timedelta(days=15)).timestamp()), "duration": 400, "user_id": "user-3"},
        {"date": int((now - timedelta(days=45)).timestamp()), "duration": 500, "user_id": "user-4"},
    ]
    fake_session = FakeSession(history_entries)

    client = TautulliClient(
        tautulli_url="http://tautulli",
        tautulli_api_key="secret",
        config={"global_stats": {"page_2": {"time_range": 30}}},
    )
    client.HISTORY_PAGE_SIZE = 2

    async def fake_get_session():
        return fake_session

    monkeypatch.setattr(client, "_get_session", fake_get_session)
    monkeypatch.setattr("cogs.media_core.plex.tautulli_client.datetime", FixedDateTime)

    global_stats = await client.fetch_global_server_stats()

    assert global_stats is not None
    assert global_stats["watch_time"]["all_time"] == {"total_plays": 5, "total_time": 1500}
    assert global_stats["watch_time"]["last_24h"] == {"total_plays": 1, "total_time": 100}
    assert global_stats["watch_time"]["last_7d"] == {"total_plays": 3, "total_time": 600}
    assert global_stats["watch_time"]["last_30d"] == {"total_plays": 4, "total_time": 1000}
    assert global_stats["active_users"] == 3

    history_calls = [call for call in fake_session.calls if call.get("cmd") == "get_history"]
    assert [call.get("start", 0) for call in history_calls] == [0, 2, 4]


@pytest.mark.asyncio
async def test_fetch_user_history_uses_ttl_cache(monkeypatch):
    fake_session = UserStatsFakeSession()
    client = TautulliClient(
        tautulli_url="http://tautulli",
        tautulli_api_key="secret",
        config={"cache": {"user_stats_ttl": 60}},
    )

    async def fake_get_session():
        return fake_session

    monkeypatch.setattr(client, "_get_session", fake_get_session)

    first = await client.fetch_user_history("user-1")
    second = await client.fetch_user_history("user-1")

    assert first == second == [{"date": 123, "duration": 456}]
    history_calls = [call for call in fake_session.calls if call.get("cmd") == "get_history"]
    assert len(history_calls) == 1


@pytest.mark.asyncio
async def test_fetch_user_player_stats_uses_ttl_cache(monkeypatch):
    fake_session = UserStatsFakeSession()
    client = TautulliClient(
        tautulli_url="http://tautulli",
        tautulli_api_key="secret",
        config={"cache": {"user_stats_ttl": 60}},
    )

    async def fake_get_session():
        return fake_session

    monkeypatch.setattr(client, "_get_session", fake_get_session)

    first = await client.fetch_user_player_stats("user-1", time_range=30)
    second = await client.fetch_user_player_stats("user-1", time_range=30)

    assert first == second == [{"player_name": "Apple TV", "total_time": 7200, "total_plays": 4}]
    player_calls = [
        call for call in fake_session.calls if call.get("cmd") == "get_user_player_stats"
    ]
    assert len(player_calls) == 1


@pytest.mark.asyncio
async def test_fetch_user_name_uses_ttl_cache(monkeypatch):
    fake_session = UserStatsFakeSession()
    client = TautulliClient(
        tautulli_url="http://tautulli",
        tautulli_api_key="secret",
        config={"cache": {"user_stats_ttl": 60}},
    )

    async def fake_get_session():
        return fake_session

    monkeypatch.setattr(client, "_get_session", fake_get_session)

    first = await client.fetch_user_name("user-1")
    second = await client.fetch_user_name("user-1")

    assert first == second == "raw_user_1"
    name_calls = [call for call in fake_session.calls if call.get("cmd") == "get_user_names"]
    assert len(name_calls) == 1


@pytest.mark.asyncio
async def test_fetch_user_watch_time_stats_uses_ttl_cache(monkeypatch):
    fake_session = UserStatsFakeSession()
    client = TautulliClient(
        tautulli_url="http://tautulli",
        tautulli_api_key="secret",
        config={"cache": {"user_stats_ttl": 60}},
    )

    async def fake_get_session():
        return fake_session

    monkeypatch.setattr(client, "_get_session", fake_get_session)

    first = await client.fetch_user_watch_time_stats("user-1")
    second = await client.fetch_user_watch_time_stats("user-1")

    assert (
        first
        == second
        == {
            "last_24h": {"query_days": 1, "total_plays": 1, "total_time": 100},
            "last_7d": {"query_days": 7, "total_plays": 3, "total_time": 300},
            "last_30d": {"query_days": 30, "total_plays": 8, "total_time": 800},
            "all_time": {"query_days": 0, "total_plays": 42, "total_time": 4200},
        }
    )
    stats_calls = [
        call for call in fake_session.calls if call.get("cmd") == "get_user_watch_time_stats"
    ]
    assert len(stats_calls) == 1


@pytest.mark.asyncio
async def test_get_cached_user_thumb_file_uses_long_lived_cache(monkeypatch):
    fake_session = UserThumbFakeSession()
    client = TautulliClient(
        tautulli_url="http://tautulli",
        tautulli_api_key="secret",
        config={"cache": {"user_stats_ttl": 60}},
    )

    async def fake_get_session():
        return fake_session

    monkeypatch.setattr(client, "_get_session", fake_get_session)

    first = await client.get_cached_user_thumb_file("https://example.com/user.png")
    second = await client.get_cached_user_thumb_file("https://example.com/user.png")

    assert first is not None
    assert second is not None
    # image/jpeg must not land on the ".png" fallback.
    assert first.filename == "user_avatar.jpg"
    assert second.filename == "user_avatar.jpg"
    assert len(fake_session.calls) == 1


@pytest.mark.asyncio
async def test_fetch_global_server_stats_uses_configured_time_range_for_top_users(monkeypatch):
    fake_session = FakeSession([])
    client = TautulliClient(
        tautulli_url="http://tautulli",
        tautulli_api_key="secret",
        config={"global_stats": {"page_2": {"time_range": 90}}},
    )

    captured_calls = []

    async def fake_get_session():
        return fake_session

    async def fake_fetch_home_stats_rows(stat_id, time_range, stats_count, stats_type=None):
        captured_calls.append((stat_id, time_range, stats_count, stats_type))
        # Return something distinguishable per stat so the assertions below
        # prove the rows are routed to the right key instead of matching an
        # empty list that every key would satisfy.
        return [{"title": stat_id}]

    monkeypatch.setattr(client, "_get_session", fake_get_session)
    monkeypatch.setattr(client, "_fetch_home_stats_rows", fake_fetch_home_stats_rows)

    stats = await client.fetch_global_server_stats()

    assert stats is not None
    assert stats["page2_time_range"] == 90
    assert stats["popular_movies"] == [{"title": "popular_movies"}]
    assert stats["top_users"] == [{"title": "top_users"}]
    # The full list, not a membership check: a duplicated or extra call would
    # slip through `in`, and the configured range only applies to top_users.
    assert captured_calls == [
        ("popular_movies", 30, 5, None),
        ("top_tv", 30, 5, None),
        ("top_users", 90, 10, "duration"),
    ]


@pytest.mark.asyncio
async def test_fetch_global_server_stats_reports_no_peak_without_plays(monkeypatch):
    """hourly_activity is pre-seeded with 24 zeros, which must not read as a peak."""
    fake_session = FakeSession([])

    client = TautulliClient(
        tautulli_url="http://tautulli",
        tautulli_api_key="secret",
        config={},
    )

    async def fake_get_session():
        return fake_session

    monkeypatch.setattr(client, "_get_session", fake_get_session)
    monkeypatch.setattr("cogs.media_core.plex.tautulli_client.datetime", FixedDateTime)

    global_stats = await client.fetch_global_server_stats()

    assert global_stats is not None
    assert global_stats["peak_hours"] == {}
    assert global_stats["most_active_day"] == {}


@pytest.mark.asyncio
async def test_fetch_global_server_stats_is_cached_between_clicks(monkeypatch):
    """The button is on the public dashboard and the call walks the full history.

    Measured against a real server: 19k history rows over 20 paginated requests,
    2.6s per click, repeated in full for every click by anyone in the channel.
    """
    fake_session = FakeSession([])
    client = TautulliClient(
        tautulli_url="http://tautulli",
        tautulli_api_key="secret",
        config={},
    )

    async def fake_get_session():
        return fake_session

    async def fake_fetch_home_stats_rows(stat_id, time_range, stats_count, stats_type=None):
        return []

    monkeypatch.setattr(client, "_get_session", fake_get_session)
    monkeypatch.setattr(client, "_fetch_home_stats_rows", fake_fetch_home_stats_rows)

    first = await client.fetch_global_server_stats()
    second = await client.fetch_global_server_stats()

    assert first is not None
    assert second == first
    assert len([call for call in fake_session.calls if call["cmd"] == "get_history"]) == 1


@pytest.mark.parametrize("days, key", [(1, "last_24h"), (7, "last_7d"), (30, "last_30d")])
async def test_global_stats_use_exact_elapsed_time_windows(monkeypatch, days, key):
    now = FixedDateTime.current.timestamp()
    session = FakeSession(
        [
            {"date": now - days * 86400 + 1, "duration": 10, "user_id": "inside"},
            {"date": now - days * 86400, "duration": 20, "user_id": "boundary"},
            {"date": now - days * 86400 - 1, "duration": 40, "user_id": "outside"},
            {"date": now + 1, "duration": 80, "user_id": "future"},
        ]
    )
    client = TautulliClient(
        "http://tautulli", "secret", {"global_stats": {"page_2": {"time_range": days}}}
    )

    async def get_session():
        return session

    monkeypatch.setattr(client, "_get_session", get_session)
    monkeypatch.setattr("cogs.media_core.plex.tautulli_client.datetime", FixedDateTime)
    stats = await client.fetch_global_server_stats()
    assert stats["watch_time"][key] == {"total_plays": 2, "total_time": 30}
    assert stats["watch_time"]["all_time"] == {"total_plays": 3, "total_time": 70}
    assert stats["active_users"] == 2


async def test_history_is_aggregated_before_requesting_next_page(monkeypatch):
    processed = []

    class TrackedRow(dict):
        def get(self, key, default=None):
            if key == "date":
                processed.append(self["user_id"])
            return super().get(key, default)

    class Session(FakeSession):
        def get(self, url, params=None):
            if params.get("cmd") == "get_history" and params["start"]:
                assert processed == ["first"]
            return super().get(url, params)

    session = Session(
        [
            TrackedRow(date=1, duration=10, user_id="first"),
            TrackedRow(date=2, duration=20, user_id="second"),
        ]
    )
    client = TautulliClient("http://tautulli", "secret", {})
    client.HISTORY_PAGE_SIZE = 1

    async def get_session():
        return session

    monkeypatch.setattr(client, "_get_session", get_session)
    stats, users = await client._fetch_history_stats("all")
    assert stats["all_time"] == {"total_plays": 2, "total_time": 30}
    assert users == {"first", "second"}


@pytest.mark.parametrize("failure", ["http", "exception", "page_limit"])
async def test_incomplete_history_does_not_publish_partial_totals(monkeypatch, failure):
    class Session(FakeSession):
        def get(self, url, params=None):
            if params.get("cmd") == "get_history" and params["start"]:
                if failure == "http":
                    return FakeResponse({}, status=500)
                raise ConnectionError("server unavailable")
            return super().get(url, params)

    session = Session(
        [
            {"date": 1, "duration": 10, "user_id": "first"},
            {"date": 2, "duration": 20, "user_id": "second"},
        ]
    )
    client = TautulliClient("http://tautulli", "secret", {})
    client.HISTORY_PAGE_SIZE = 1
    if failure == "page_limit":
        client.MAX_HISTORY_PAGES = 1

    async def get_session():
        return session

    monkeypatch.setattr(client, "_get_session", get_session)
    stats = await client.fetch_global_server_stats()
    assert stats["watch_time"] == {}
    assert stats["active_users"] == 0


@pytest.mark.parametrize("cancel_first", [False, True])
async def test_global_stats_share_concurrent_fetch_and_recover_from_cancellation(
    monkeypatch, cancel_first
):
    client = TautulliClient("http://tautulli", "secret", {})
    session = FakeSession([])
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0
    fetch_history = client._fetch_history_stats

    async def get_session():
        return session

    async def gated_history(days):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return await fetch_history(days)

    monkeypatch.setattr(client, "_get_session", get_session)
    monkeypatch.setattr(client, "_fetch_history_stats", gated_history)
    first = asyncio.create_task(client.fetch_global_server_stats())
    await asyncio.wait_for(entered.wait(), 1)
    second = asyncio.create_task(client.fetch_global_server_stats())
    await asyncio.sleep(0)
    try:
        assert calls == 1
        if cancel_first:
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        release.set()
        result = await asyncio.wait_for(second, 1)
        assert result["watch_time"]["all_time"] == {"total_plays": 0, "total_time": 0}
        if not cancel_first:
            assert await first == result
        assert calls == (2 if cancel_first else 1)
    finally:
        release.set()
        await asyncio.gather(first, second, return_exceptions=True)
