"""
Shared module for MediaWatch multi-platform support.

Contains platform-agnostic data models, service protocols, and utilities
that are shared between Plex and Jellyfin implementations.
"""

from .models import (
    ServerType,
    PlayState,
    TranscodeDecision,
    MediaType,
    ActiveStream,
    LibraryStats,
    ServerStatus,
)
from .base_service import MediaService
from .formatters import (
    format_watch_time,
    format_resolution,
    format_channels,
    format_bitrate,
    format_progress_bar,
)
from .dashboard_service import DashboardService
from .config_helper import StreamControlsConfig, StreamDetailsConfig
from .config_utils import get_server_type, get_current_platform, get_config_path
from .config import (
    load_config,
    load_message_id,
    save_message_id,
    load_user_mapping,
    check_legacy_config,
)

__all__ = [
    # Models
    "ServerType",
    "PlayState",
    "TranscodeDecision",
    "MediaType",
    "ActiveStream",
    "LibraryStats",
    "ServerStatus",
    # Protocol
    "MediaService",
    # Formatters
    "format_watch_time",
    "format_resolution",
    "format_channels",
    "format_bitrate",
    "format_progress_bar",
    # Dashboard
    "DashboardService",
    # Config helpers
    "StreamControlsConfig",
    "StreamDetailsConfig",
    # Config Utils
    "get_server_type",
    "get_current_platform",
    "get_config_path",
    # Config loading
    "load_config",
    "load_message_id",
    "save_message_id",
    "load_user_mapping",
    "check_legacy_config",
]
