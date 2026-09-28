import json
import time

import pytest

from cogs.media_core.shared import runtime_state


def _use_tmp_state(monkeypatch, tmp_path):
    path = tmp_path / "data" / "runtime_state.json"
    monkeypatch.setattr(runtime_state, "get_runtime_state_path", lambda: path)
    return path


def test_persist_and_load_online_since_roundtrip(monkeypatch, tmp_path):
    path = _use_tmp_state(monkeypatch, tmp_path)

    runtime_state.persist_online_since("plex", 1700000000.5)

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["plex"]["online_since"] == 1700000000.5
    assert stored["plex"]["last_seen"] == pytest.approx(time.time(), abs=5)
    assert runtime_state.load_online_since("plex") == 1700000000.5
    assert runtime_state.load_online_since("jellyfin") is None


def test_load_online_since_drops_a_baseline_the_bot_was_away_for(monkeypatch, tmp_path):
    """A bot restart keeps the server uptime; a long gap must not.

    The baseline says when the media server came up, so it deliberately
    survives a bot restart. But if the bot was down long enough for the server
    to have restarted unnoticed, reporting the old value would be wrong by days.
    """
    _use_tmp_state(monkeypatch, tmp_path)
    runtime_state.persist_online_since("plex", time.time() - 86400)

    # Still watching a minute ago: the baseline is trustworthy.
    assert runtime_state.load_online_since("plex", 300) is not None

    runtime_state.persist_last_seen("plex")
    state = runtime_state.load_runtime_state()
    state["plex"]["last_seen"] = time.time() - 900
    runtime_state.save_runtime_state(state)

    assert runtime_state.load_online_since("plex", 300) is None
    # Without the threshold the caller opts out of the check entirely.
    assert runtime_state.load_online_since("plex") is not None


def test_load_online_since_drops_a_baseline_without_a_last_seen(monkeypatch, tmp_path):
    """The bot was killed rather than shut down, so the gap is unknown."""
    path = _use_tmp_state(monkeypatch, tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"plex": {"online_since": 1700000000.5}}), encoding="utf-8")

    assert runtime_state.load_online_since("plex", 300) is None


def test_persist_last_seen_does_not_invent_a_baseline(monkeypatch, tmp_path):
    """Without an online_since there is nothing to bound."""
    _use_tmp_state(monkeypatch, tmp_path)

    runtime_state.persist_last_seen("plex")

    assert runtime_state.load_runtime_state() == {}


def test_save_runtime_state_never_leaves_a_truncated_file(monkeypatch, tmp_path):
    path = _use_tmp_state(monkeypatch, tmp_path)
    runtime_state.persist_online_since("plex", 1.0)

    def boom(*args, **kwargs):
        raise OSError("interrupted")

    monkeypatch.setattr("cogs.media_core.shared.config_utils.os.replace", boom)

    try:
        runtime_state.persist_online_since("plex", 2.0)
    except OSError:
        pass

    assert runtime_state.load_online_since("plex") == 1.0
    assert [p.name for p in path.parent.iterdir()] == ["runtime_state.json"]


def test_refresh_last_seen_writes_at_most_once_per_interval(monkeypatch, tmp_path):
    _use_tmp_state(monkeypatch, tmp_path)
    runtime_state.persist_online_since("plex", 1700000000.0)
    state = runtime_state.load_runtime_state()
    state["plex"]["last_seen"] = 1.0
    runtime_state.save_runtime_state(state)
    clock = [1000.0]
    monkeypatch.setattr(runtime_state.time, "monotonic", lambda: clock[0])

    def last_seen():
        return runtime_state.load_runtime_state()["plex"]["last_seen"]

    runtime_state.refresh_last_seen("plex")
    first = last_seen()
    assert first == pytest.approx(time.time(), abs=5)

    state = runtime_state.load_runtime_state()
    state["plex"]["last_seen"] = 1.0
    runtime_state.save_runtime_state(state)

    clock[0] += runtime_state.LAST_SEEN_REFRESH_SECONDS - 1
    runtime_state.refresh_last_seen("plex")
    assert last_seen() == 1.0

    clock[0] += 1
    runtime_state.refresh_last_seen("plex")
    assert last_seen() == pytest.approx(time.time(), abs=5)


def test_refresh_last_seen_does_not_invent_a_baseline(monkeypatch, tmp_path):
    _use_tmp_state(monkeypatch, tmp_path)

    runtime_state.refresh_last_seen("jellyfin")

    assert runtime_state.load_runtime_state() == {}
