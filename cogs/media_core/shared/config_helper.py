"""
Platform-agnostic configuration helpers for MediaWatch.

These helpers read feature configuration from ``config.yaml`` and are used
by both the Plex and the Jellyfin implementation.
"""

import logging
import re
from typing import Any, Dict, Optional


logger = logging.getLogger("mediawatch_bot.media_core.shared.config_helper")

# ``<:name:id>`` and ``<a:name:id>``, the two forms Discord accepts for a custom
# emoji. discord.py parses the same shapes in ``PartialEmoji.from_str``.
_CUSTOM_EMOJI_PATTERN = re.compile(r"^<a?:[A-Za-z0-9_]{2,32}:\d{15,25}>$")


def resolve_base_url(value: Any, default: Optional[str]) -> Optional[str]:
    """Return an ``http(s)`` base URL for a link, or ``default``.

    Discord rejects a link button whose URL carries any other scheme, so a value
    that would never render is replaced here instead of at send time.
    """
    if value is None:
        return default

    if not isinstance(value, str):
        logger.warning("Ignoring non-text link URL %r, using %r instead.", value, default)
        return default

    base = value.strip().rstrip("/")
    if not base:
        return default

    if not base.startswith(("http://", "https://")):
        logger.warning(
            "Ignoring invalid link URL %r: it has to start with http:// or https://. "
            "Falling back to %r.",
            value,
            default,
        )
        return default

    return base


def resolve_emoji(value: Any, default: Optional[str]) -> Optional[str]:
    """Return a button emoji Discord will accept, or ``None`` for no emoji.

    A typo in ``config.yaml`` must not take the whole message down: Discord
    answers an unknown emoji with HTTP 400, so anything that is neither a custom
    emoji nor plausible unicode falls back to ``default``.
    """
    if value is None:
        return default

    if not isinstance(value, str):
        logger.warning("Ignoring non-text emoji %r, using %r instead.", value, default)
        return default

    emoji = value.strip()
    if not emoji:
        # An empty string is a deliberate "render this button without an icon".
        return None

    if _CUSTOM_EMOJI_PATTERN.match(emoji):
        return emoji

    if emoji.isascii():
        logger.warning(
            "Ignoring invalid emoji %r: use a unicode emoji or the custom form "
            "<:name:id>. Falling back to %r.",
            emoji,
            default,
        )
        return default

    return emoji


class StreamControlsConfig:
    """Helper class for stream control configuration."""

    DEFAULT_REASON = "Stopped by administrator"
    DEFAULT_CONFIG = {
        "kill_stream": {
            "default_reason": DEFAULT_REASON,
        }
    }

    def __init__(self, config: Dict[str, Any]):
        controls_config = config.get("stream_controls", {})
        self.config = self._merge_with_defaults(controls_config)

    def _merge_with_defaults(self, controls_config: Dict[str, Any]) -> Dict[str, Any]:
        merged = {
            "kill_stream": self.DEFAULT_CONFIG["kill_stream"].copy(),
        }

        if not isinstance(controls_config, dict):
            return merged

        kill_stream_config = controls_config.get("kill_stream", {})
        if isinstance(kill_stream_config, dict):
            merged["kill_stream"].update(kill_stream_config)

        return merged

    def get_kill_stream_default_reason(self) -> str:
        """Return the configured default reason text for the kill stream modal."""
        default_reason = self.config.get("kill_stream", {}).get(
            "default_reason", self.DEFAULT_REASON
        )
        if not isinstance(default_reason, str):
            return self.DEFAULT_REASON

        sanitized_reason = default_reason.strip()
        if not sanitized_reason:
            return self.DEFAULT_REASON

        return sanitized_reason[:200]


class StreamDetailsConfig:
    """Helper class for stream details display settings."""

    DEFAULT_LINKS = {
        "plex": {
            "enabled": True,
            "emoji": "\u25b6\ufe0f",
            "base_url": "https://app.plex.tv/desktop",
        },
    }

    DEFAULT_CONFIG = {
        "show_ip_for_authorized_users": False,
        "restrict_to_authorized": False,
        "links": DEFAULT_LINKS,
    }

    def __init__(self, config: Dict[str, Any]):
        stream_details_config = config.get("stream_details", {})
        self.config = self._merge_with_defaults(stream_details_config)

    def _merge_with_defaults(self, stream_details_config: Dict[str, Any]) -> Dict[str, Any]:
        merged = self.DEFAULT_CONFIG.copy()

        if not isinstance(stream_details_config, dict):
            merged["links"] = self._merge_links({})
            return merged

        merged.update(stream_details_config)
        # ``load_config`` only deep merges two levels, so a config that sets a
        # single link key would otherwise drop the other keys of that link.
        merged["links"] = self._merge_links(stream_details_config.get("links"))
        return merged

    def _merge_links(self, links_config: Any) -> Dict[str, Dict[str, Any]]:
        merged = {name: values.copy() for name, values in self.DEFAULT_LINKS.items()}

        if not isinstance(links_config, dict):
            return merged

        for name, values in links_config.items():
            if name not in merged or not isinstance(values, dict):
                continue
            merged[name].update(values)

        return merged

    def link_enabled(self, name: str) -> bool:
        """Return whether the given link button is turned on."""
        return bool(self.config.get("links", {}).get(name, {}).get("enabled", False))

    def link_emoji(self, name: str) -> Optional[str]:
        """Return the configured emoji for a link button, or ``None`` for none."""
        link = self.config.get("links", {}).get(name, {})
        return resolve_emoji(link.get("emoji"), self.DEFAULT_LINKS.get(name, {}).get("emoji"))

    def link_base_url(self, name: str) -> Optional[str]:
        """Return the web base the link button and the embed title point at."""
        link = self.config.get("links", {}).get(name, {})
        return resolve_base_url(
            link.get("base_url"), self.DEFAULT_LINKS.get(name, {}).get("base_url")
        )

    def show_ip_for_authorized_users(self) -> bool:
        """Return whether authorized users should see client IPs in stream details."""
        return bool(self.config.get("show_ip_for_authorized_users", False))

    def restrict_to_authorized(self) -> bool:
        """Return whether only authorized users may open stream details."""
        return bool(self.config.get("restrict_to_authorized", False))
