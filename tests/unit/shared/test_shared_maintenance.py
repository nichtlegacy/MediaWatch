import json
import logging
import time

import pytest

from cogs.media_core.shared import maintenance, runtime_state


def _restart():
    """Forget the in-memory window, as a fresh bot process would."""
    maintenance._current = maintenance._UNLOADED


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("30m", 1800),
        ("45min", 2700),
        ("2h", 7200),
        ("1h30m", 5400),
        (" 1H 30M ", 5400),
        ("1d", 86400),
        ("90", 5400),
        ("7d", 7 * 86400),
    ],
)
def test_parse_duration_accepts_the_documented_forms(text, seconds):
    assert maintenance.parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "abc", "1x", "-5", "1h30", "h", "1.5h"])
def test_parse_duration_rejects_garbage_with_the_format_in_the_message(text):
    with pytest.raises(ValueError, match="Use minutes, hours or days"):
        maintenance.parse_duration(text)


@pytest.mark.parametrize("text", ["0", "0m", "8d", "169h"])
def test_parse_duration_rejects_durations_out_of_range(text):
    with pytest.raises(ValueError, match="between 1 minute and 7 days"):
        maintenance.parse_duration(text)


def test_a_started_window_survives_a_bot_restart():
    """A crash or a host reboot is often the maintenance itself."""
    window, persisted = maintenance.start(
        started_by=42, reason="Disk swap", duration=3600, now=1000.0
    )

    _restart()

    assert persisted is True
    assert maintenance.current() == window
    assert window.ends_at == 4600.0


def test_updating_keeps_what_was_left_out_and_counts_the_duration_from_now():
    maintenance.start(started_by=42, reason="Disk swap", duration=3600, now=1000.0)

    window, _ = maintenance.start(started_by=7, duration=1800, now=5000.0)

    assert window.started_at == 1000.0
    assert window.started_by == 42
    assert window.reason == "Disk swap"
    assert window.ends_at == 6800.0

    window, _ = maintenance.start(started_by=7, reason="Plex update", now=6000.0)

    assert window.reason == "Plex update"
    assert window.ends_at == 6800.0


def test_end_clears_the_window_on_disk_too():
    maintenance.start(started_by=42, now=1000.0)

    ended, persisted = maintenance.end()
    _restart()

    assert ended.started_at == 1000.0
    assert persisted is True
    assert maintenance.current() is None


def test_end_without_maintenance_is_a_no_op():
    assert maintenance.end() == (None, True)


def test_maintenance_still_works_when_data_is_not_writable(monkeypatch):
    """A read-only data/ costs the restart survival, not the feature."""

    def fail(*args, **kwargs):
        raise PermissionError("read-only")

    monkeypatch.setattr(runtime_state, "write_json_atomic", fail)

    window, persisted = maintenance.start(started_by=42, reason="Disk swap")

    assert persisted is False
    assert maintenance.current() == window


@pytest.mark.parametrize(
    "payload",
    [{"started_at": "soon"}, {"reason": "no start"}, ["not", "a", "mapping"], "garbage"],
)
def test_an_invalid_stored_window_is_ignored(payload, caplog):
    path = runtime_state.get_runtime_state_path()
    path.write_text(json.dumps({"bot": {"maintenance": payload}}), encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        assert maintenance.current() is None

    assert "Ignoring the stored maintenance window" in caplog.text


@pytest.mark.parametrize(
    ("overdue", "healthy", "auto_end", "ends"),
    [
        (True, True, True, True),
        # Overrunning while the server is still down: keep announcing it.
        (True, False, True, False),
        # Server back before the announced end: the work may not be done.
        (False, True, True, False),
        (True, True, False, False),
    ],
)
def test_resolve_ends_only_overdue_maintenance_on_a_healthy_server(
    overdue, healthy, auto_end, ends
):
    now = time.time()
    maintenance.start(started_by=42, duration=60, now=now - (120 if overdue else 0))

    window = maintenance.resolve(server_healthy=healthy, auto_end=auto_end)
    _restart()

    assert (window is None) is ends
    assert (maintenance.current() is None) is ends


def test_resolve_never_ends_maintenance_without_an_announced_end():
    maintenance.start(started_by=42, now=time.time() - 86400)

    assert maintenance.resolve(server_healthy=True, auto_end=True) is not None
