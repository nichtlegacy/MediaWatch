"""
Configuration helpers for Plex/Tautulli-backed controls and statistics.

This module provides helper classes for accessing and validating feature
configuration from ``config.yaml``.
"""

from typing import Dict, Any, List


class GlobalStatsConfig:
    """Helper class for global Tautulli statistics configuration."""

    DEFAULT_BUTTON_LOCATION = "stream_details"
    VALID_BUTTON_LOCATIONS = {"stream_details", "dashboard", "both"}
    DEFAULT_CONFIG = {
        "button_location": DEFAULT_BUTTON_LOCATION,
        "restrict_to_authorized": False,
        "page_2": {
            "time_range": 30,
        },
    }

    def __init__(self, config: Dict[str, Any]):
        global_stats_config = config.get("global_stats", {})
        self.config = self._merge_with_defaults(global_stats_config)

    def _merge_with_defaults(self, global_stats_config: Dict[str, Any]) -> Dict[str, Any]:
        merged = {
            "button_location": self.DEFAULT_CONFIG["button_location"],
            "restrict_to_authorized": self.DEFAULT_CONFIG["restrict_to_authorized"],
            "page_2": self.DEFAULT_CONFIG["page_2"].copy(),
        }

        if not isinstance(global_stats_config, dict):
            return merged

        merged["restrict_to_authorized"] = bool(
            global_stats_config.get("restrict_to_authorized", merged["restrict_to_authorized"])
        )

        button_location = global_stats_config.get("button_location")
        if isinstance(button_location, str):
            normalized_location = button_location.strip().lower()
            if normalized_location in self.VALID_BUTTON_LOCATIONS:
                merged["button_location"] = normalized_location

        page_2_config = global_stats_config.get("page_2", {})
        if isinstance(page_2_config, dict):
            merged["page_2"].update(page_2_config)

        return merged

    def get_button_location(self) -> str:
        """Return the configured location for the global stats button."""
        return self.config.get("button_location", self.DEFAULT_BUTTON_LOCATION)

    def show_in_dashboard(self) -> bool:
        """Return whether the global stats button should appear in the dashboard."""
        return self.get_button_location() in {"dashboard", "both"}

    def show_in_stream_details(self) -> bool:
        """Return whether the global stats button should appear in stream details."""
        return self.get_button_location() in {"stream_details", "both"}

    def restrict_to_authorized(self) -> bool:
        """Return whether global stats are limited to authorized users.

        This is deliberately separate from ``stream_details.restrict_to_authorized``:
        stream details only expose what is playing right now, while global stats
        expose the server-wide watch history of every user.
        """
        return bool(self.config.get("restrict_to_authorized", False))


class UserStatsConfig:
    """Helper class for user stats configuration."""

    DEFAULT_CONFIG = {
        "enabled": True,
        "pages": {
            "behavior": True,
            "devices": True,
            "top_content": True,
        },
        "time_range": 0,  # 0 = all time
        "top_tv_count": 10,
        "restrict_to_authorized": False,
    }

    CACHE_DURATION = 300  # Hardcoded: 5 minutes

    def __init__(self, config: Dict[str, Any]):
        """Initialize UserStatsConfig.

        Args:
            config: Main configuration dictionary
        """
        user_config = config.get("user_stats", {})
        self.config = self._merge_with_defaults(user_config)

    def _merge_with_defaults(self, user_config: Dict[str, Any]) -> Dict[str, Any]:
        """Merge user config with defaults.

        Args:
            user_config: User-provided configuration

        Returns:
            Merged configuration with defaults
        """
        merged = self.DEFAULT_CONFIG.copy()

        if not isinstance(user_config, dict):
            return merged

        # Merge top-level settings
        for key, value in user_config.items():
            if key == "pages" and isinstance(value, dict):
                # Merge pages dict
                merged["pages"] = merged["pages"].copy()
                merged["pages"].update(value)
            else:
                merged[key] = value

        return merged

    def restrict_to_authorized(self) -> bool:
        """Return whether user stats are limited to authorized users.

        Separate from ``stream_details.restrict_to_authorized``, which only closed
        this view by closing the way in: user stats are one person's whole watch
        history, so a server can keep live stream details open and still lock them.
        """
        return bool(self.config.get("restrict_to_authorized", False))

    def is_enabled(self) -> bool:
        """Check if user stats feature is enabled.

        Returns:
            True if enabled, False otherwise
        """
        return self.config.get("enabled", True)

    def get_enabled_pages(self) -> List[str]:
        """Get list of enabled pages in fixed order.

        Returns:
            List of enabled page names in order: behavior, devices, top_content
        """
        pages = self.config.get("pages", {})
        page_order = ["behavior", "devices", "top_content"]
        return [page for page in page_order if pages.get(page, True)]

    def get_time_range(self) -> int:
        """Get time range in days (0 = all time).

        Returns:
            Time range in days, minimum 0
        """
        try:
            return max(0, int(self.config.get("time_range", 0)))
        except (ValueError, TypeError):
            return 0

    def get_top_tv_count(self) -> int:
        """Get number of top TV shows for page 3 (0-10).

        Returns:
            Number of shows to display, clamped to 0-10
        """
        try:
            return max(0, min(10, int(self.config.get("top_tv_count", 10))))
        except (ValueError, TypeError):
            return 10
