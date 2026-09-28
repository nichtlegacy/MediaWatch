"""
Shared data models for MediaWatch multi-platform support.

These dataclasses represent platform-agnostic data structures that both
Plex and Jellyfin implementations map their API responses to.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List


class ServerType(Enum):
    """Supported media server types."""

    PLEX = "plex"
    JELLYFIN = "jellyfin"


class PlayState(Enum):
    """Current playback state of a stream."""

    PLAYING = "playing"
    PAUSED = "paused"
    BUFFERING = "buffering"
    STOPPED = "stopped"


class TranscodeDecision(Enum):
    """Transcode decision for video/audio streams."""

    DIRECT_PLAY = "direct_play"
    DIRECT_STREAM = "direct_stream"
    TRANSCODE = "transcode"
    UNKNOWN = "unknown"


class MediaType(Enum):
    """Type of media being played."""

    MOVIE = "movie"
    EPISODE = "episode"
    TRACK = "track"  # Music
    UNKNOWN = "unknown"


@dataclass
class ActiveStream:
    """Represents an active media stream.

    This is a platform-agnostic representation of a streaming session,
    normalized from both Plex and Jellyfin API responses.
    """

    # Session identification
    session_id: str
    session_key: str

    # User information
    username: str
    user_id: Optional[str] = None

    # Media information
    media_type: MediaType = MediaType.UNKNOWN
    title: str = ""
    year: Optional[int] = None

    # For TV shows
    series_title: Optional[str] = None
    season_number: Optional[int] = None
    episode_number: Optional[int] = None

    # For music
    artist: Optional[str] = None
    album: Optional[str] = None

    # Library information
    library_section_title: str = ""

    # Playback state
    play_state: PlayState = PlayState.PLAYING
    view_offset_ms: int = 0
    duration_ms: int = 0

    # Quality information
    video_resolution: str = ""
    video_bitrate_kbps: Optional[int] = None
    audio_channels: Optional[int] = None
    audio_codec: Optional[str] = None
    # Bit depth and sample rate of a music track ("24bit 96kHz"); shown where a
    # video stream shows its resolution.
    audio_quality: str = ""

    # Transcode information
    video_decision: TranscodeDecision = TranscodeDecision.UNKNOWN
    audio_decision: TranscodeDecision = TranscodeDecision.UNKNOWN
    transcode_bitrate_kbps: Optional[int] = None
    is_transcoding: bool = False

    # Client information
    player_name: str = ""
    player_device: str = ""
    player_platform: str = ""

    # Thumbnail
    thumb_path: Optional[str] = None

    # Raw session data for platform-specific features
    raw_session: Any = None

    @property
    def progress_percent(self) -> float:
        """Calculate playback progress percentage."""
        if self.duration_ms <= 0:
            return 0.0
        return (self.view_offset_ms / self.duration_ms) * 100

    @property
    def display_bitrate_kbps(self) -> Optional[int]:
        """Bitrate to show for this stream, in kbps.

        Prefers the transcode bitrate while transcoding and the source bitrate
        otherwise. When both normalized fields stayed empty the raw Plex
        session is used as a last resort; Jellyfin sessions are plain dicts and
        simply fall through.
        """
        if self.is_transcoding:
            bitrate = self.transcode_bitrate_kbps
        else:
            bitrate = self.video_bitrate_kbps or self.transcode_bitrate_kbps

        if bitrate or not self.raw_session:
            return bitrate

        transcode_session = getattr(self.raw_session, "transcodeSession", None)
        if transcode_session is not None and getattr(transcode_session, "bitrate", None):
            return transcode_session.bitrate

        media = getattr(self.raw_session, "media", None)
        if media:
            return getattr(media[0], "bitrate", None)

        return None

    @property
    def is_paused(self) -> bool:
        """Check if stream is paused."""
        return self.play_state == PlayState.PAUSED

    def get_formatted_title(self) -> str:
        """Get a formatted title based on media type."""
        if self.media_type == MediaType.TRACK:
            return f"{self.artist or 'Unknown Artist'} - {self.title}"
        elif self.media_type == MediaType.EPISODE:
            ep_info = ""
            if self.season_number is not None and self.episode_number is not None:
                ep_info = f" - S{self.season_number:02d}E{self.episode_number:02d}"
            return f"{self.series_title or self.title}{ep_info}"
        else:
            year_str = f" ({self.year})" if self.year else ""
            return f"{self.title}{year_str}"


@dataclass
class LibraryStats:
    """Statistics for a single library section.

    Represents counts and metadata for a library section like
    "Movies", "TV Shows", etc.
    """

    section_id: str
    section_title: str

    # Counts
    item_count: int = 0
    episode_count: int = 0  # For TV show libraries

    # Display configuration
    display_name: str = ""
    emoji: str = "🎬"
    show_episodes: bool = False

    # Library type (movie, show, music, etc.)
    library_type: str = ""


@dataclass
class ServerStatus:
    """Current status of the media server.

    Contains server health information and aggregated statistics.
    """

    # Server identification
    server_type: ServerType
    server_name: str = ""
    server_version: str = ""

    # Status
    is_online: bool = True
    offline_since: Optional[datetime] = None
    # Server answered but rejected our credentials (HTTP 401/403)
    auth_failed: bool = False

    # Uptime tracking
    start_time: Optional[float] = None  # Unix timestamp
    uptime_string: str = ""

    # Library statistics (keyed by section title)
    library_stats: Dict[str, LibraryStats] = field(default_factory=dict)

    # Active streams
    active_streams: List[ActiveStream] = field(default_factory=list)
    stream_count: int = 0

    @property
    def status_emoji(self) -> str:
        """Get status emoji based on online state."""
        return "🟢" if self.is_online else "🔴"

    @property
    def status_text(self) -> str:
        """Get status text based on online state."""
        return f"{self.status_emoji} {'Online' if self.is_online else 'Offline'}"
