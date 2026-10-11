"""Maintenance mode: an announced outage instead of a red "Offline".

Platform-agnostic on purpose. Both cores resolve the window in
`get_server_info`, so one implementation covers Plex and Jellyfin, and the
dashboard and the presence read it from the same place.

The window is kept in memory and mirrored to `runtime_state.json`. The file is
what lets it survive a bot crash or a host reboot - often the very reason for
the maintenance. The memory copy is what keeps maintenance mode working when
`data/` is not writable: it then lasts until the next restart instead of not
working at all.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass, replace
from typing import Any, Optional, Tuple

from . import runtime_state

logger = logging.getLogger("mediawatch_bot.media_core.maintenance")

MIN_DURATION_SECONDS = 60
MAX_DURATION_SECONDS = 7 * 86400
MAX_REASON_LENGTH = 300

_DURATION_PATTERN = re.compile(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m(?:in)?)?")


@dataclass(frozen=True)
class MaintenanceWindow:
    """A running maintenance. Timestamps are Unix seconds, so they survive a restart."""

    started_at: float
    started_by: Optional[int] = None
    reason: str = ""
    ends_at: Optional[float] = None

    def overdue(self, now: Optional[float] = None) -> bool:
        """Whether the announced end has passed. Never true without an end."""
        if self.ends_at is None:
            return False
        return (time.time() if now is None else now) >= self.ends_at


# Sentinel: the file has not been read yet. None means "read, no maintenance".
_UNLOADED: Any = object()
_current: Any = _UNLOADED


def parse_duration(text: str) -> int:
    """Turn "30m", "2h", "1h30m", "1d" or bare minutes ("90") into seconds.

    Raises ValueError with a message meant for the user who typed it.
    """
    cleaned = text.strip().lower().replace(" ", "")
    if cleaned.isdigit():
        seconds = int(cleaned) * 60
    else:
        match = _DURATION_PATTERN.fullmatch(cleaned)
        if not cleaned or match is None or not any(match.groups()):
            raise ValueError(
                f'Invalid duration "{text}". Use minutes, hours or days like 30m, 2h, 1h30m or 1d.'
            )
        days, hours, minutes = (int(group or 0) for group in match.groups())
        seconds = days * 86400 + hours * 3600 + minutes * 60
    if not MIN_DURATION_SECONDS <= seconds <= MAX_DURATION_SECONDS:
        raise ValueError("The duration must be between 1 minute and 7 days.")
    return seconds


def _from_payload(payload: Any) -> MaintenanceWindow:
    """Validate a stored window. Raises on anything a hand edit could break."""
    if not isinstance(payload, dict):
        raise TypeError(f"expected a mapping, got {type(payload).__name__}")
    ends_at = payload.get("ends_at")
    started_by = payload.get("started_by")
    return MaintenanceWindow(
        started_at=float(payload["started_at"]),
        started_by=None if started_by is None else int(started_by),
        reason=str(payload.get("reason") or "")[:MAX_REASON_LENGTH],
        ends_at=None if ends_at is None else float(ends_at),
    )


def current() -> Optional[MaintenanceWindow]:
    """The running maintenance window, or None."""
    global _current
    if _current is _UNLOADED:
        payload = runtime_state.load_maintenance()
        _current = None
        if payload is not None:
            try:
                _current = _from_payload(payload)
            except (KeyError, TypeError, ValueError) as exc:
                # Loaded once per process, so this cannot repeat every tick.
                logger.warning("Ignoring the stored maintenance window, it is invalid: %s", exc)
            else:
                logger.info("Maintenance mode is still active from before the restart.")
    return _current


def _store(window: Optional[MaintenanceWindow]) -> bool:
    """Set the window in memory and on disk. Returns whether the disk write worked."""
    global _current
    _current = window
    persisted = runtime_state.persist_maintenance(None if window is None else asdict(window))
    if not persisted:
        logger.error(
            "Maintenance mode %s, but could not be saved; it will not survive a restart.",
            "ended" if window is None else "changed",
        )
    return persisted


def start(
    *,
    started_by: Optional[int],
    reason: Optional[str] = None,
    duration: Optional[int] = None,
    now: Optional[float] = None,
) -> Tuple[MaintenanceWindow, bool]:
    """Start maintenance, or update the running one.

    Updating keeps the start time and who started it; an option left out keeps
    its current value, so extending only takes a new duration. The duration
    counts from now, not from the start.

    Returns the window and whether it was persisted.
    """
    now = time.time() if now is None else now
    if reason is not None:
        reason = reason.strip()[:MAX_REASON_LENGTH]
    ends_at = None if duration is None else now + duration

    existing = current()
    if existing is None:
        window = MaintenanceWindow(
            started_at=now, started_by=started_by, reason=reason or "", ends_at=ends_at
        )
    else:
        window = replace(
            existing,
            reason=existing.reason if reason is None else reason,
            ends_at=existing.ends_at if duration is None else ends_at,
        )
    return window, _store(window)


def end() -> Tuple[Optional[MaintenanceWindow], bool]:
    """End maintenance. Returns the window that ended (None if none ran) and whether it was persisted."""
    window = current()
    if window is None:
        return None, True
    return window, _store(None)


def resolve(*, server_healthy: bool, auto_end: bool) -> Optional[MaintenanceWindow]:
    """The window to render this tick, ending it first when it is done.

    It ends on its own only when the announced end has passed *and* the server
    answers again. Ending on the time alone would flip an overrunning
    maintenance to a red "Offline"; ending on the server alone would end it the
    moment the server comes back up between two steps of the work.
    """
    window = current()
    if window is not None and auto_end and server_healthy and window.overdue():
        logger.info(
            "Maintenance mode ended automatically: the planned end has passed "
            "and the server answers again."
        )
        end()
        return None
    return window
