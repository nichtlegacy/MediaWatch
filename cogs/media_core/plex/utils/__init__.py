"""
Utility modules for Plex integration.

Contains formatters, statistics calculators, and configuration helpers.
"""

# Import from shared formatters
from ...shared.formatters import format_watch_time
from ...shared.config_helper import StreamControlsConfig, StreamDetailsConfig

# Import from local modules
from .config_helper import GlobalStatsConfig, UserStatsConfig
from .statistics import (
    calculate_watch_streak,
    calculate_favorite_genre,
    calculate_previous_period_stats,
    calculate_period_comparison,
)
from .user_stats_utils import (
    calculate_content_type_breakdown,
    calculate_avg_session_length,
    calculate_peak_hour,
    calculate_most_active_day,
    calculate_most_active_device,
    calculate_top_content_type,
)

__all__ = [
    "format_watch_time",
    "GlobalStatsConfig",
    "StreamControlsConfig",
    "StreamDetailsConfig",
    "UserStatsConfig",
    "calculate_watch_streak",
    "calculate_favorite_genre",
    "calculate_previous_period_stats",
    "calculate_period_comparison",
    "calculate_content_type_breakdown",
    "calculate_avg_session_length",
    "calculate_peak_hour",
    "calculate_most_active_day",
    "calculate_most_active_device",
    "calculate_top_content_type",
]
