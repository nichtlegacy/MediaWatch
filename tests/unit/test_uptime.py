import logging
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import cogs.uptime as uptime_module
from cogs.uptime import Uptime, uptime_windows


def make_cog(enabled=True):
    cog = Uptime.__new__(Uptime)
    cog.logger = logging.getLogger("test.uptime")
    cog.api_url = "http://uptime.local"
    cog.username = "user"
    cog.password = "pass"
    cog.monitor_id = 1
    cog.enabled = enabled
    cog._cache_lock = threading.Lock()
    cog._cached_data = None
    cog._cache_expires_at = 0.0
    return cog


def test_get_uptime_data_returns_empty_tuple_on_network_error(monkeypatch):
    def exploding_api(url):
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr(uptime_module, "UptimeKumaApi", exploding_api)

    assert make_cog().get_uptime_data() == (None,) * 6


def test_get_uptime_data_skips_api_when_disabled(monkeypatch):
    def never_called(url):  # pragma: no cover - must not run
        raise AssertionError("API must not be contacted when disabled")

    monkeypatch.setattr(uptime_module, "UptimeKumaApi", never_called)

    assert make_cog(enabled=False).get_uptime_data() == (None,) * 6


def test_get_uptime_data_reuses_cached_result(monkeypatch):
    calls = []

    class FakeApi:
        def __init__(self, url):
            calls.append(url)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def login(self, username, password):
            return None

        def get_monitor_beats(self, monitor_id, hours):
            calls.append(hours)
            return [{"status": SimpleNamespace(name="UP"), "time": "2026-01-01 00:00:00.000"}]

    monkeypatch.setattr(uptime_module, "UptimeKumaApi", FakeApi)
    monkeypatch.setattr(uptime_module.time, "monotonic", lambda: 100.0)
    cog = make_cog()

    assert cog.get_uptime_data() == cog.get_uptime_data()
    assert calls == ["http://uptime.local", 30 * 24]


def _beat(now, hours_ago, status):
    time_str = (now - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return {"status": SimpleNamespace(name=status), "time": time_str}


def _per_window(beats, period_hours):
    """The formula the cog used on each separately fetched window."""
    up = sum(1 for beat in beats if beat["status"].name == "UP")
    return (up / len(beats)) * 100 if beats else 0.0, up * (period_hours * 60 / len(beats))


def test_uptime_windows_match_separately_fetched_windows():
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    # Down 2h ago, down 3 days ago, down 20 days ago; up everywhere else.
    beats = [_beat(now, h, "DOWN" if h in (2, 72, 480) else "UP") for h in range(719, -1, -1)]
    last_24h, last_7d = beats[-24:], beats[-168:]

    expected = _per_window(last_24h, 24) + _per_window(last_7d, 168) + _per_window(beats, 720)

    assert uptime_windows(beats, now) == expected
    assert expected[0] == 23 / 24 * 100 and expected[2] == 166 / 168 * 100


def test_get_uptime_data_caches_failure_until_expiry(monkeypatch):
    attempts = []
    clock = [100.0]

    def exploding_api(url):
        attempts.append(url)
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr(uptime_module, "UptimeKumaApi", exploding_api)
    monkeypatch.setattr(uptime_module.time, "monotonic", lambda: clock[0])
    cog = make_cog()

    assert cog.get_uptime_data() == (None,) * 6
    clock[0] += Uptime.CACHE_TTL_SECONDS - 1
    assert cog.get_uptime_data() == (None,) * 6
    assert len(attempts) == 1

    clock[0] += 2
    cog.get_uptime_data()
    assert len(attempts) == 2
