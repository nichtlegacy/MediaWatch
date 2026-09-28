"""
Plex Media Service implementation for MediaWatch.

This module implements the MediaService protocol for Plex,
wrapping the PlexClient and providing normalized data models.
"""

import asyncio
import discord
import logging
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

from ..shared.models import (
    ServerType,
    ServerStatus,
    ActiveStream,
    LibraryStats,
    PlayState,
    TranscodeDecision,
    MediaType,
)
from ..shared.formatters import (
    format_audio_quality,
    format_resolution,
    format_uptime,
    resolve_user_display_name,
)
from ..shared.runtime_state import (
    load_online_since,
    persist_last_seen,
    persist_online_since,
    refresh_last_seen,
)
from .plex_client import PlexClient
from .tautulli_client import TautulliClient


logger = logging.getLogger("mediawatch_bot.media_core.plex.service")


class PlexMediaService:
    """MediaService implementation for Plex Media Server."""

    # Plex brand color (orange)
    PLEX_COLOR = discord.Color.from_rgb(229, 160, 13)

    def __init__(
        self,
        plex_url: str,
        plex_token: str,
        tautulli_url: Optional[str],
        tautulli_api_key: Optional[str],
        config: Dict[str, Any],
        user_mapping: Dict[str, str],
    ):
        """Initialize Plex media service.

        Args:
            plex_url: URL to Plex server
            plex_token: Plex authentication token
            tautulli_url: Optional Tautulli server URL
            tautulli_api_key: Optional Tautulli API key
            config: Configuration dictionary
            user_mapping: Username to display name mapping
        """
        self.config = config
        self.user_mapping = user_mapping

        # Initialize clients
        self.plex_client = PlexClient(plex_url, plex_token)
        self.tautulli_client = TautulliClient(tautulli_url, tautulli_api_key, config)

        # Library cache
        self._library_cache: Dict[str, LibraryStats] = {}
        self._last_library_update: Optional[float] = None  # time.monotonic()
        self._library_update_interval = config.get("cache", {}).get("library_update_interval", 900)

        # Offline tracking
        self._offline_since: Optional[datetime] = None
        self._first_failure_time: Optional[datetime] = None
        self._offline_threshold = config.get("server", {}).get("offline_threshold", 300)
        self._has_connected_once = False
        self._online_since_timestamp: Optional[float] = load_online_since(
            "plex", self._offline_threshold
        )
        self._confirmed_offline = False

        self._library_lock = asyncio.Lock()

        self.logger = logger

    @property
    def server_type(self) -> ServerType:
        """Return the server type."""
        return ServerType.PLEX

    @property
    def embed_color(self) -> discord.Color:
        """Return the Plex brand color."""
        return self.PLEX_COLOR

    @property
    def server_name(self) -> str:
        """Return the server name."""
        return self.plex_client.get_server_name() or "Plex Server"

    def is_connected(self) -> bool:
        """Check if connected to Plex server."""
        return self.plex_client.is_connected()

    async def get_server_status(self) -> ServerStatus:
        """Get current server status including online state and uptime.

        Returns:
            ServerStatus object with current server state
        """
        current_time = discord.utils.utcnow()
        server = await asyncio.to_thread(self.plex_client.connect)

        if not server:
            # Server is unreachable
            if self._first_failure_time is None:
                self._first_failure_time = current_time
                self.logger.info(
                    f"Server unreachable. Starting threshold timer ({self._offline_threshold}s)."
                )

            if self.plex_client.auth_failed:
                # Rejected credentials are not a transient outage - report them
                # right away instead of waiting out the offline threshold.
                return ServerStatus(
                    server_type=ServerType.PLEX,
                    server_name=self.server_name,
                    is_online=False,
                    auth_failed=True,
                    library_stats=self._get_empty_library_stats(),
                    active_streams=[],
                    stream_count=0,
                )

            time_since_first_failure = (current_time - self._first_failure_time).total_seconds()

            if self._offline_threshold == 0 or time_since_first_failure >= self._offline_threshold:
                if self._offline_since is None:
                    self._offline_since = self._first_failure_time
                    self.logger.warning("Server marked as offline")
                self._confirmed_offline = True

                return ServerStatus(
                    server_type=ServerType.PLEX,
                    server_name=self.server_name,
                    is_online=False,
                    offline_since=self._offline_since,
                    library_stats=self._get_empty_library_stats(),
                    active_streams=[],
                    stream_count=0,
                )
            else:
                if not self._has_connected_once:
                    return ServerStatus(
                        server_type=ServerType.PLEX,
                        server_name=self.server_name,
                        is_online=False,
                        offline_since=self._first_failure_time,
                        library_stats=self._get_empty_library_stats(),
                        active_streams=[],
                        stream_count=0,
                    )

                # Still within threshold, show as online with cached data
                return ServerStatus(
                    server_type=ServerType.PLEX,
                    server_name=self.server_name,
                    is_online=True,
                    uptime_string=format_uptime(self._online_since_timestamp),
                    start_time=self._online_since_timestamp,
                    library_stats=self._library_cache or self._get_empty_library_stats(),
                    active_streams=[],
                    stream_count=0,
                )

        # Server is online - reset failure tracking
        was_confirmed_offline = self._confirmed_offline
        if self._first_failure_time is not None:
            self.logger.info("Server recovered. Resetting failure tracking.")
            self._first_failure_time = None

        self._offline_since = None
        self._confirmed_offline = False
        self._has_connected_once = True

        if self._online_since_timestamp is None or was_confirmed_offline:
            self._set_online_since(time.time())
        # Only while the server is seen reachable: a stale value then means the
        # bot or the server was gone, and either way the baseline must go.
        refresh_last_seen("plex")

        # Get active streams
        active_streams = await self.get_active_streams()

        # Get library stats
        library_stats = await self.get_library_stats()

        return ServerStatus(
            server_type=ServerType.PLEX,
            server_name=self.plex_client.get_server_name(),
            server_version=self.plex_client.get_server_version(),
            is_online=True,
            uptime_string=format_uptime(self._online_since_timestamp),
            start_time=self._online_since_timestamp,
            library_stats=library_stats,
            active_streams=active_streams,
            stream_count=len(active_streams),
        )

    def _set_online_since(self, timestamp: float) -> None:
        """Update and persist the platform online-since timestamp."""
        self._online_since_timestamp = float(timestamp)
        persist_online_since("plex", self._online_since_timestamp)

    async def get_active_streams(self) -> List[ActiveStream]:
        """Get list of currently active streaming sessions.

        Returns:
            List of ActiveStream objects representing current streams
        """
        sessions = await asyncio.to_thread(self.plex_client.get_sessions)
        streams = []

        for session in sessions:
            try:
                stream = self._convert_session_to_stream(session)
                if stream:
                    streams.append(stream)
            except Exception as e:
                self.logger.error(f"Error converting session: {e}")

        return streams

    async def get_library_stats(self) -> Dict[str, LibraryStats]:
        """Get statistics for all configured library sections.

        Returns:
            Dictionary mapping section titles to LibraryStats objects
        """
        # Both @tasks.loop callbacks reach this through get_server_status(), and
        # they align every few minutes. Without the lock a cold or expired cache
        # lets both enumerate the whole library at once - observed twice within
        # 80ms on the first dashboard cycle. The second waiter re-checks the
        # cache and returns it instead of repeating the work.
        async with self._library_lock:
            # Monotonic so a wall-clock jump (NTP, DST on a naive clock) cannot
            # expire the cache early or pin it for hours.
            current_time = time.monotonic()

            # Check cache validity
            if (
                self._last_library_update is not None
                and current_time - self._last_library_update <= self._library_update_interval
            ):
                return self._library_cache

            if not self.plex_client.is_connected():
                return self._library_cache

            stats = await asyncio.to_thread(self._collect_library_stats)
            if stats is None:
                return self._library_cache

            self._library_cache = stats
            self._last_library_update = current_time
            self.logger.info(
                f"Library stats updated and cached (interval: {self._library_update_interval}s)"
            )

            return stats

    def _collect_library_stats(self) -> Optional[Dict[str, LibraryStats]]:
        """Fetch library statistics from Plex (blocking, run via asyncio.to_thread).

        Returns:
            Dictionary of library statistics, or None if the fetch failed
        """
        try:
            sections = self.plex_client.get_library_sections()
            if sections is None:
                return None
            stats: Dict[str, LibraryStats] = {}

            # Get config for sections
            plex_config = self.config.get("plex", {}).get("sections", {})
            show_all = self.config.get("plex", {}).get("show_all", True)

            if not show_all:
                # Only configured sections
                for title in plex_config:
                    if title in sections:
                        config_section = plex_config[title]
                        section = sections[title]
                        stats[title] = self._build_library_stats(section, config_section)
            else:
                # Configured sections first, then others
                for title in plex_config:
                    if title in sections:
                        config_section = plex_config[title]
                        section = sections[title]
                        stats[title] = self._build_library_stats(section, config_section)

                # Add non-configured sections
                for title, section in sections.items():
                    if title not in plex_config:
                        stats[title] = LibraryStats(
                            section_id=str(section.key),
                            section_title=title,
                            item_count=section.totalViewSize(),
                            episode_count=0,
                            display_name=title,
                            emoji="🎬",
                            show_episodes=False,
                            library_type=section.type,
                        )

            return stats
        except Exception as e:
            self.logger.error(f"Error updating library stats: {e}")
            return None

    async def close(self) -> None:
        """Clean up resources and close connections."""
        try:
            self.plex_client.disconnect()
            await self.tautulli_client.close()
        finally:
            # Bounds the gap that load_online_since() checks on the next start,
            # so a bot restart keeps the server uptime while a longer outage
            # drops it. In finally: a failing disconnect must not cost it.
            # Not during a confirmed outage: that would vouch for a baseline
            # the server has already broken, and a quick restart would keep it.
            if not self._confirmed_offline:
                persist_last_seen("plex")

    def _convert_session_to_stream(self, session) -> Optional[ActiveStream]:
        """Convert a Plex session to an ActiveStream.

        Args:
            session: Plex session object

        Returns:
            ActiveStream object or None if conversion fails
        """
        try:
            # Get user info
            username = (
                session.usernames[0]
                if hasattr(session, "usernames") and session.usernames
                else "Unknown"
            )
            displayed_user = resolve_user_display_name(self.user_mapping, username)

            # Determine media type
            session_type = getattr(session, "type", "movie")
            if session_type == "track":
                media_type = MediaType.TRACK
            elif session_type == "episode":
                media_type = MediaType.EPISODE
            else:
                media_type = MediaType.MOVIE

            # Get play state
            player_state = "playing"
            if hasattr(session, "players") and session.players:
                player_state = getattr(session.players[0], "state", "playing")

            if player_state == "paused":
                play_state = PlayState.PAUSED
            elif player_state == "buffering":
                play_state = PlayState.BUFFERING
            else:
                play_state = PlayState.PLAYING

            # Get media info
            media = session.media[0] if hasattr(session, "media") and session.media else None

            video_resolution = ""
            video_bitrate = None

            if media:
                # plexapi sets this to None for music, not to an empty string.
                video_resolution = getattr(media, "videoResolution", None) or ""
                if video_resolution:
                    # Handles "1080", "1080p", "4k", "2160", "sd", ...
                    video_resolution = format_resolution(video_resolution)

                # Try to get bitrate from multiple sources
                video_bitrate = getattr(media, "bitrate", None)

                # Fallback: try to get bitrate from media parts/streams
                if not video_bitrate and hasattr(media, "parts") and media.parts:
                    part = media.parts[0]
                    # Try container bitrate first
                    video_bitrate = getattr(part, "bitrate", None)

                    # If still no bitrate, try to get from video stream
                    if not video_bitrate and hasattr(part, "streams"):
                        for stream in part.streams:
                            if getattr(stream, "streamType", 0) == 1:  # Video stream
                                video_bitrate = getattr(stream, "bitrate", None)
                                break

            audio_quality = ""
            if media_type == MediaType.TRACK and media and getattr(media, "parts", None):
                audio_stream = next(
                    (
                        stream
                        for stream in getattr(media.parts[0], "streams", None) or []
                        if getattr(stream, "streamType", 0) == 2  # Audio stream
                    ),
                    None,
                )
                if audio_stream is not None:
                    audio_quality = format_audio_quality(
                        getattr(audio_stream, "bitDepth", None),
                        getattr(audio_stream, "samplingRate", None),
                    )

            # Get transcode info
            transcode_session = getattr(session, "transcodeSession", None)
            is_transcoding = transcode_session is not None

            video_decision = TranscodeDecision.UNKNOWN
            audio_decision = TranscodeDecision.UNKNOWN
            transcode_bitrate = None

            if transcode_session:
                video_dec = getattr(transcode_session, "videoDecision", "")
                audio_dec = getattr(transcode_session, "audioDecision", "")

                if video_dec == "transcode":
                    video_decision = TranscodeDecision.TRANSCODE
                elif video_dec in ("copy", "directplay"):
                    video_decision = TranscodeDecision.DIRECT_STREAM

                if audio_dec == "transcode":
                    audio_decision = TranscodeDecision.TRANSCODE
                elif audio_dec in ("copy", "directplay"):
                    audio_decision = TranscodeDecision.DIRECT_STREAM

                transcode_bitrate = getattr(transcode_session, "bitrate", None)

            # Get player info
            player_name = "Unknown"
            player_device = ""
            if hasattr(session, "players") and session.players:
                player = session.players[0]
                # plexapi sets these attributes even when the client sent
                # nothing, so the getattr default never applies; DLNA and Cast
                # targets arrive with product/device as None.
                product = getattr(player, "product", None) or "Unknown"
                player_name = product.replace("Plex for ", "").replace("Infuse-Library", "Infuse")
                player_device = getattr(player, "device", None) or ""

            # Get thumb path
            thumb_path = None
            if media_type == MediaType.EPISODE:
                thumb_path = getattr(session, "grandparentThumb", None) or getattr(
                    session, "thumb", None
                )
            else:
                thumb_path = getattr(session, "thumb", None)

            return ActiveStream(
                session_id=str(session.sessionKey) if hasattr(session, "sessionKey") else "",
                session_key=str(session.sessionKey) if hasattr(session, "sessionKey") else "",
                username=displayed_user,
                user_id=str(session.usernames[0])
                if hasattr(session, "usernames") and session.usernames
                else None,
                media_type=media_type,
                title=getattr(session, "title", None) or "Unknown",
                year=getattr(session, "year", None),
                series_title=getattr(session, "grandparentTitle", None),
                season_number=getattr(session, "parentIndex", None),
                episode_number=getattr(session, "index", None),
                artist=getattr(session, "grandparentTitle", None)
                if media_type == MediaType.TRACK
                else None,
                album=getattr(session, "parentTitle", None)
                if media_type == MediaType.TRACK
                else None,
                library_section_title=getattr(session, "librarySectionTitle", None) or "",
                play_state=play_state,
                view_offset_ms=getattr(session, "viewOffset", 0) or 0,
                duration_ms=getattr(session, "duration", 0) or 0,
                video_resolution=video_resolution,
                video_bitrate_kbps=video_bitrate,
                audio_quality=audio_quality,
                video_decision=video_decision,
                audio_decision=audio_decision,
                transcode_bitrate_kbps=transcode_bitrate,
                is_transcoding=is_transcoding,
                player_name=player_name,
                player_device=player_device,
                thumb_path=thumb_path,
                raw_session=session,
            )
        except Exception as e:
            self.logger.error(f"Error converting session to stream: {e}")
            return None

    def _build_library_stats(self, section, config: Dict[str, Any]) -> LibraryStats:
        """Build LibraryStats from a Plex section.

        Args:
            section: Plex library section
            config: Configuration for this section

        Returns:
            LibraryStats object
        """
        item_count = section.totalViewSize()
        episode_count = 0

        if config.get("show_episodes", False):
            try:
                episode_count = section.totalViewSize(libtype="episode")
            except Exception as e:
                # Keep the last known count instead of caching a fake 0, but don't
                # fail the whole refresh: a section that always errors would
                # otherwise freeze every other tile too.
                previous = self._library_cache.get(section.title)
                episode_count = previous.episode_count if previous else 0
                self.logger.warning(f"Episode count for {section.title} failed: {e}")

        return LibraryStats(
            section_id=str(section.key),
            section_title=section.title,
            item_count=item_count,
            episode_count=episode_count,
            display_name=config.get("display_name", section.title),
            emoji=config.get("emoji", "🎬"),
            show_episodes=config.get("show_episodes", False),
            library_type=section.type,
        )

    def _get_empty_library_stats(self) -> Dict[str, LibraryStats]:
        """Generate empty library stats matching config structure.

        Returns:
            Dictionary of empty library statistics
        """
        stats: Dict[str, LibraryStats] = {}
        plex_config = self.config.get("plex", {}).get("sections", {})

        for title, config in plex_config.items():
            stats[title] = LibraryStats(
                section_id="",
                section_title=title,
                item_count=0,
                episode_count=0,
                display_name=config.get("display_name", title),
                emoji=config.get("emoji", "🎬"),
                show_episodes=config.get("show_episodes", False),
            )

        return stats
