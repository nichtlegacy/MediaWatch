"""Persistent runtime state helpers for MediaWatch."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .config_utils import write_json_atomic


logger = logging.getLogger("mediawatch_bot.media_core.runtime_state")

_RUNTIME_STATE_FILE = "runtime_state.json"
_ONLINE_SINCE_KEY = "online_since"
_LAST_SEEN_KEY = "last_seen"
_SUPPORTED_PLATFORMS = {"plex", "jellyfin"}
# Bot-level state that is not tied to a media platform
_BOT_SECTION = "bot"
_GLOBAL_COMMANDS_CLEARED_KEY = "global_commands_cleared"
_SUPPORTED_SECTIONS = _SUPPORTED_PLATFORMS | {_BOT_SECTION}
# At most one last_seen write per platform and minute. It has to stay well below
# server.offline_threshold (default 300 s): the gap a restart may cost before the
# baseline is dropped is the threshold minus this interval.
LAST_SEEN_REFRESH_SECONDS = 60
_last_seen_refreshed: Dict[str, float] = {}


def get_runtime_state_path() -> Path:
    """Return the path to the persisted runtime state file."""
    return Path(__file__).resolve().parents[3] / "data" / _RUNTIME_STATE_FILE


def load_runtime_state() -> Dict[str, Dict[str, Any]]:
    """Load persisted runtime state from disk."""
    path = get_runtime_state_path()
    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read runtime state from %s: %s", path, exc)
        return {}

    if not isinstance(data, dict):
        logger.warning("Ignoring invalid runtime state payload in %s", path)
        return {}

    return {
        section: state
        for section, state in data.items()
        if section in _SUPPORTED_SECTIONS and isinstance(state, dict)
    }


def save_runtime_state(state: Dict[str, Dict[str, Any]]) -> None:
    """Persist runtime state to disk.

    Runtime state is a convenience cache, never something the bot needs to run:
    losing it costs an uptime baseline or one extra command-sync call. A
    `data/` the container cannot write to - a compose file with a `user:`
    override on top of a root-owned 1.x volume - must therefore not be able to
    take the bot down. This is called from `setup_hook`, where an escaping
    `PermissionError` leaves the bot permanently unable to start.
    """
    try:
        write_json_atomic(get_runtime_state_path(), state, indent=2, ensure_ascii=False)
    except OSError as exc:
        logger.error("Failed to persist runtime state to %s: %s", get_runtime_state_path(), exc)


def load_online_since(platform: str, max_gap_seconds: Optional[float] = None) -> Optional[float]:
    """Load the persisted online-since timestamp for a platform.

    The stored baseline says when the *media server* came up, so it survives a
    bot restart on purpose - restarting the bot for an image update must not
    reset the displayed server uptime. But it is only trustworthy for as long
    as the bot was actually watching: if the bot was down long enough for the
    media server to restart unnoticed, the old baseline would be reported
    forever, off by days.

    `max_gap_seconds` (the configured offline threshold) bounds that. The
    baseline is discarded when the gap since `last_seen` exceeds it, or when
    there is no `last_seen` at all - the bot was killed rather than shut down,
    so the gap is unknown and re-baselining is the safe direction.
    """
    state = load_runtime_state()
    platform_state = state.get(platform, {})
    value = platform_state.get(_ONLINE_SINCE_KEY)

    if value is None:
        return None

    if max_gap_seconds is not None:
        last_seen = platform_state.get(_LAST_SEEN_KEY)
        try:
            gap = time.time() - float(last_seen)
        except (TypeError, ValueError):
            logger.info(
                "Discarding the %s uptime baseline: no usable last_seen timestamp.", platform
            )
            return None
        if gap > max_gap_seconds:
            logger.info(
                "Discarding the %s uptime baseline: bot was away for %.0fs (threshold %.0fs).",
                platform,
                gap,
                max_gap_seconds,
            )
            return None

    try:
        return float(value)
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid online_since value for %s: %r", platform, value)
        return None


def persist_online_since(platform: str, timestamp: Optional[float]) -> None:
    """Persist the online-since timestamp for a platform."""
    if platform not in _SUPPORTED_PLATFORMS:
        raise ValueError(f"Unsupported platform: {platform}")

    state = load_runtime_state()
    platform_state = state.setdefault(platform, {})

    if timestamp is None:
        platform_state.pop(_ONLINE_SINCE_KEY, None)
        platform_state.pop(_LAST_SEEN_KEY, None)
    else:
        platform_state[_ONLINE_SINCE_KEY] = float(timestamp)
        platform_state[_LAST_SEEN_KEY] = time.time()

    save_runtime_state(state)


def persist_last_seen(platform: str) -> None:
    """Record that the bot saw this platform's server reachable right now.

    Written on shutdown and, through `refresh_last_seen`, once a minute while the
    server is online. The shutdown write alone was not enough: a crash, a
    `docker kill` or a host reboot skips it, and the next start then dropped a
    baseline the bot had been watching the whole time.
    """
    if platform not in _SUPPORTED_PLATFORMS:
        raise ValueError(f"Unsupported platform: {platform}")

    state = load_runtime_state()
    platform_state = state.setdefault(platform, {})
    if _ONLINE_SINCE_KEY not in platform_state:
        return

    platform_state[_LAST_SEEN_KEY] = time.time()
    save_runtime_state(state)


def refresh_last_seen(platform: str) -> None:
    """Call `persist_last_seen` at most once per `LAST_SEEN_REFRESH_SECONDS`.

    Called on every successful status check, which both loops trigger, so the
    throttle keeps it to one small write per minute against the mounted volume.
    """
    now = time.monotonic()
    last = _last_seen_refreshed.get(platform)
    if last is not None and now - last < LAST_SEEN_REFRESH_SECONDS:
        return
    _last_seen_refreshed[platform] = now
    persist_last_seen(platform)


def global_commands_cleared() -> bool:
    """Whether the one-time cleanup of 1.x global slash commands already ran."""
    return bool(load_runtime_state().get(_BOT_SECTION, {}).get(_GLOBAL_COMMANDS_CLEARED_KEY))


def mark_global_commands_cleared() -> None:
    """Remember that the global command scope was emptied, so it happens once."""
    state = load_runtime_state()
    state.setdefault(_BOT_SECTION, {})[_GLOBAL_COMMANDS_CLEARED_KEY] = True
    save_runtime_state(state)
