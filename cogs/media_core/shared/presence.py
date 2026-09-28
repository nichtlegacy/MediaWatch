"""Bot presence: what the member list shows next to MediaWatch.

Both platform cogs used to carry a byte-identical copy of this logic. It is
platform-agnostic - it only ever sees normalized library stats - so it belongs
here, where a fix reaches Plex and Jellyfin at once.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import discord

from .formatters import format_number

logger = logging.getLogger("mediawatch_bot.media_core.presence")

# Discord truncates an activity name past this, and rejects the whole presence
# update when it is exceeded - the presence then silently stops changing.
MAX_ACTIVITY_LENGTH = 128

# Deliberately not the full ActivityType enum. "playing" and "competing" read
# wrong for a media server, and "streaming" needs a Twitch or YouTube URL or
# Discord renders it as "Playing" anyway.
ACTIVITY_TYPES = {
    "custom": None,
    "watching": discord.ActivityType.watching,
    "listening": discord.ActivityType.listening,
}

STATUS_VALUES = {
    "online": discord.Status.online,
    "idle": discord.Status.idle,
    "dnd": discord.Status.dnd,
}


def _library_entries(
    config: Dict[str, Any], library_stats: Dict[str, Dict[str, Any]]
) -> List[Tuple[str, Dict[str, Any], bool]]:
    """Resolve the configured libraries into (name, stats, wants_episodes).

    `presence.libraries` holds names only; the display name and emoji come from
    the platform's own section config, which the stats already carry. That keeps
    one source of truth - the 1.x `presence.sections` repeated both and could
    drift away from the dashboard. The config migration rewrites the old shape,
    so nothing has to read it here.
    """
    configured = config.get("libraries", [])
    if configured == "all":
        return [(name, stats, False) for name, stats in library_stats.items()]
    if not isinstance(configured, list):
        logger.warning('presence.libraries must be a list or "all", got %r.', configured)
        return []

    entries = []
    for item in configured:
        if not isinstance(item, str):
            logger.warning("presence.libraries entry %r is not a name, skipping it.", item)
            continue
        # An exact library name wins over the suffix syntax. A library called
        # "Filme: Klassiker" would otherwise be split at the colon and silently
        # resolve to "Filme" - the wrong library, with no error.
        if item in library_stats:
            entries.append((item, library_stats[item], False))
            continue

        name, separator, suffix = item.rpartition(":")
        if not separator:
            continue
        if suffix != "episodes":
            logger.warning(
                'presence.libraries entry %r has an unknown suffix; use "<name>:episodes".', item
            )
            continue
        if name not in library_stats:
            continue
        entries.append((name, library_stats[name], True))
    return entries


def build_library_text(
    config: Dict[str, Any],
    library_stats: Dict[str, Dict[str, Any]],
    *,
    separator: str = ".",
    episode_label: str = "Episodes",
) -> str:
    """Render the idle presence: one segment per configured library."""
    parts = []
    for name, stats, wants_episodes in _library_entries(config, library_stats):
        key = "episodes" if wants_episodes else "count"
        # A malformed entry must not take the whole presence down with a
        # KeyError that surfaces only as "Error updating status".
        value = stats.get(key)
        if value is None:
            logger.warning("Library %r has no %r value, skipping it in the presence.", name, key)
            continue
        label = stats.get("display_name") or name
        if wants_episodes and episode_label:
            # Without this the segment reads "21.980 Serien" - the count is
            # episodes, so the label has to say so.
            label = f"{label} {episode_label}"
        emoji = stats.get("emoji") or ""
        segment = f"{format_number(int(value), separator=separator)} {label} {emoji}".strip()
        parts.append(segment)
    return " | ".join(parts)


def build_presence(
    config: Dict[str, Any],
    *,
    is_online: bool,
    auth_failed: bool,
    active_streams: int,
    library_stats: Dict[str, Dict[str, Any]],
    separator: str = ".",
    episode_label: str = "Episodes",
) -> Optional[Tuple[discord.BaseActivity, discord.Status]]:
    """Return the activity and status to publish, or None when disabled."""
    if not config.get("enabled", True):
        return None

    if auth_failed:
        text = config.get("auth_failed_text") or config.get("offline_text", "")
        status_name = config.get("offline_status", "dnd")
    elif not is_online:
        text = config.get("offline_text", "")
        status_name = config.get("offline_status", "dnd")
    elif active_streams > 0:
        template = config.get("stream_text", "")
        try:
            text = template.format(count=active_streams, s="s" if active_streams != 1 else "")
        except (KeyError, IndexError) as exc:
            logger.warning(
                "presence.stream_text has an unknown placeholder (%s); using the raw text.", exc
            )
            text = template
        status_name = config.get("status", "online")
    else:
        text = build_library_text(
            config, library_stats, separator=separator, episode_label=episode_label
        )
        if not text:
            text = "No streams or libraries configured"
        status_name = config.get("status", "online")

    if len(text) > MAX_ACTIVITY_LENGTH:
        logger.warning(
            "Presence text is %d characters, Discord allows %d - truncating. "
            "Configure fewer libraries in presence.libraries to avoid this.",
            len(text),
            MAX_ACTIVITY_LENGTH,
        )
        text = text[: MAX_ACTIVITY_LENGTH - 1].rstrip() + "…"

    status = STATUS_VALUES.get(str(status_name).lower())
    if status is None:
        logger.warning("Unknown presence status %r, falling back to online.", status_name)
        status = discord.Status.online

    type_name = str(config.get("activity_type", "custom")).lower()
    if type_name not in ACTIVITY_TYPES:
        logger.warning(
            "Unknown presence activity_type %r, falling back to custom. Valid: %s.",
            type_name,
            ", ".join(sorted(ACTIVITY_TYPES)),
        )
        type_name = "custom"

    activity_type = ACTIVITY_TYPES[type_name]
    if activity_type is None:
        return discord.CustomActivity(name=text), status
    return discord.Activity(type=activity_type, name=text), status
