"""
Jellyfin Media Service implementation for MediaWatch.

This module implements the MediaService protocol for Jellyfin,
wrapping the JellyfinClient and providing normalized data models.
"""

import time
import discord
import asyncio
import logging
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
    format_resolution_from_dimensions,
    format_uptime,
    resolve_user_display_name,
)
from ..shared.runtime_state import (
    load_online_since,
    persist_last_seen,
    persist_online_since,
    refresh_last_seen,
)
from .jellyfin_client import JellyfinClient


logger = logging.getLogger("mediawatch_bot.media_core.jellyfin.service")


class JellyfinMediaService:
    """MediaService implementation for Jellyfin Media Server."""

    # Jellyfin brand color (blue/purple)
    JELLYFIN_COLOR = discord.Color.from_rgb(0, 164, 220)

    def __init__(
        self,
        jellyfin_url: str,
        jellyfin_api_key: str,
        config: Dict[str, Any],
        user_mapping: Dict[str, str],
    ):
        """Initialize Jellyfin media service.

        Args:
            jellyfin_url: URL to Jellyfin server
            jellyfin_api_key: Jellyfin API key
            config: Configuration dictionary
            user_mapping: Username to display name mapping
        """
        self.config = config
        self.user_mapping = user_mapping

        # Initialize client
        self.jellyfin_client = JellyfinClient(jellyfin_url, jellyfin_api_key)

        # Library cache
        self._library_cache: Dict[str, LibraryStats] = {}
        self._last_library_update: Optional[float] = None  # time.monotonic()
        self._library_update_interval = config.get("cache", {}).get("library_update_interval", 900)

        # Offline tracking
        self._offline_since: Optional[datetime] = None
        self._first_failure_time: Optional[datetime] = None
        self._offline_threshold = config.get("server", {}).get("offline_threshold", 300)
        self._has_connected_once = False
        self._confirmed_offline = False

        # Persisted online-since tracking
        self._start_time: Optional[float] = load_online_since("jellyfin", self._offline_threshold)

        self._library_lock = asyncio.Lock()

        self.logger = logger

    @property
    def server_type(self) -> ServerType:
        """Return the server type."""
        return ServerType.JELLYFIN

    @property
    def embed_color(self) -> discord.Color:
        """Return the Jellyfin brand color."""
        return self.JELLYFIN_COLOR

    @property
    def server_name(self) -> str:
        """Return the server name."""
        return self.jellyfin_client.server_name

    def is_connected(self) -> bool:
        """Check if connected to Jellyfin server."""
        return self.jellyfin_client.is_connected()

    async def get_server_status(self) -> ServerStatus:
        """Get current server status including online state and uptime.

        Returns:
            ServerStatus object with current server state
        """
        current_time = discord.utils.utcnow()
        connected = await self.jellyfin_client.connect()

        if not connected:
            # Server is unreachable
            if self._first_failure_time is None:
                self._first_failure_time = current_time
                self.logger.info(
                    f"Server unreachable. Starting threshold timer ({self._offline_threshold}s)."
                )

            if self.jellyfin_client.auth_failed:
                # Rejected credentials are not a transient outage - report them
                # right away instead of waiting out the offline threshold.
                return ServerStatus(
                    server_type=ServerType.JELLYFIN,
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
                    server_type=ServerType.JELLYFIN,
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
                        server_type=ServerType.JELLYFIN,
                        server_name=self.server_name,
                        is_online=False,
                        offline_since=self._first_failure_time,
                        library_stats=self._get_empty_library_stats(),
                        active_streams=[],
                        stream_count=0,
                    )

                # Still within threshold
                return ServerStatus(
                    server_type=ServerType.JELLYFIN,
                    server_name=self.server_name,
                    is_online=True,
                    uptime_string=format_uptime(self._start_time),
                    start_time=self._start_time,
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

        # Set start time if not set
        if self._start_time is None or was_confirmed_offline:
            self._set_online_since(time.time())
        # Only while the server is seen reachable: a stale value then means the
        # bot or the server was gone, and either way the baseline must go.
        refresh_last_seen("jellyfin")

        # Get active streams
        active_streams = await self.get_active_streams()

        # Get library stats
        library_stats = await self.get_library_stats()

        return ServerStatus(
            server_type=ServerType.JELLYFIN,
            server_name=self.jellyfin_client.server_name,
            server_version=self.jellyfin_client.server_version,
            is_online=True,
            uptime_string=format_uptime(self._start_time),
            start_time=self._start_time,
            library_stats=library_stats,
            active_streams=active_streams,
            stream_count=len(active_streams),
        )

    def _set_online_since(self, timestamp: float) -> None:
        """Update and persist the platform online-since timestamp."""
        self._start_time = float(timestamp)
        persist_online_since("jellyfin", self._start_time)

    async def get_active_streams(self) -> List[ActiveStream]:
        """Get list of currently active streaming sessions.

        Returns:
            List of ActiveStream objects representing current streams
        """
        sessions = await self.jellyfin_client.get_sessions()
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

            if not self.jellyfin_client.is_connected():
                return self._library_cache

            try:
                sections = await self.jellyfin_client.get_library_sections()
                if sections is None:
                    # Keep the old cache and its timestamp so the next tick retries.
                    return self._library_cache
                stats: Dict[str, LibraryStats] = {}

                # Get config for sections
                jellyfin_config = self.config.get("jellyfin", {}).get("sections", {})
                show_all = self.config.get("jellyfin", {}).get("show_all", True)

                for section in sections:
                    section_name = section.get("Name", "Unknown")
                    section_id = section.get("ItemId", "")
                    collection_type = section.get("CollectionType", "")

                    # Skip if not in config and show_all is False
                    if not show_all and section_name not in jellyfin_config:
                        continue

                    # Get config or defaults
                    section_config = jellyfin_config.get(section_name, {})

                    # Determine if this is a TV show library
                    is_tv = collection_type == "tvshows"

                    # Get counts
                    if is_tv:
                        item_count = await self.jellyfin_client.get_series_count(section_id)
                        episode_count = await self.jellyfin_client.get_episodes_count(section_id)
                    else:
                        item_count = await self.jellyfin_client.get_item_counts(section_id)
                        episode_count = 0

                    if item_count is None or episode_count is None:
                        # A failed count must not be cached as a real 0.
                        return self._library_cache

                    stats[section_name] = LibraryStats(
                        section_id=section_id,
                        section_title=section_name,
                        item_count=item_count,
                        episode_count=episode_count,
                        display_name=section_config.get("display_name", section_name),
                        emoji=section_config.get("emoji", self._get_default_emoji(collection_type)),
                        show_episodes=section_config.get("show_episodes", is_tv),
                        library_type=collection_type,
                    )

                self._library_cache = stats
                self._last_library_update = current_time
                self.logger.info(
                    f"Library stats updated and cached (interval: {self._library_update_interval}s)"
                )

                return stats
            except Exception as e:
                self.logger.error(f"Error updating library stats: {e}")
                return self._library_cache

    def get_library_display_name(self, collection_type: str, fallback: str = "Unknown") -> str:
        """Return the configured display name of a library by its collection type.

        Only correct when there is a single library of that type - prefer
        :meth:`resolve_library_display_name`, which asks the server which
        library the item actually belongs to.
        """
        for stats in self._library_cache.values():
            if stats.library_type == collection_type:
                return stats.display_name
        return fallback

    async def resolve_library_display_name(
        self,
        item_id: str,
        collection_type: str,
        fallback: str = "Unknown",
        user_id: Optional[str] = None,
    ) -> str:
        """Return the display name of the library an item really lives in.

        Three sources, in descending order of trust:

        1. the item's own library, matched against the configured display name
        2. that library's name as the server reports it - still right when the
           library cache is cold, where the type lookup would silently hand
           back the built-in English default ("Movies" instead of "Filme")
        3. the type lookup, which is only unambiguous with one library per type

        Args:
            item_id: The item currently playing
            collection_type: ``movies``, ``tvshows`` or ``music``
            fallback: Used when nothing else resolves
            user_id: The session's user; without it Jellyfin returns the
                physical folder chain instead of the library

        Returns:
            The library display name
        """
        library = await self.jellyfin_client.get_item_library(item_id, user_id)
        if library:
            for stats in self._library_cache.values():
                if stats.section_id and stats.section_id == library["id"]:
                    return stats.display_name
            if library["name"]:
                return library["name"]
        return self.get_library_display_name(collection_type, fallback)

    async def close(self) -> None:
        """Clean up resources and close connections."""
        try:
            await self.jellyfin_client.disconnect()
        finally:
            # Bounds the gap that load_online_since() checks on the next start,
            # so a bot restart keeps the server uptime while a longer outage
            # drops it. In finally: a failing disconnect must not cost it.
            # Not during a confirmed outage: that would vouch for a baseline
            # the server has already broken, and a quick restart would keep it.
            if not self._confirmed_offline:
                persist_last_seen("jellyfin")

    def _convert_session_to_stream(self, session: Dict[str, Any]) -> Optional[ActiveStream]:
        """Convert a Jellyfin session to an ActiveStream.

        Args:
            session: Jellyfin session dictionary

        Returns:
            ActiveStream object or None if conversion fails
        """
        try:
            now_playing = session.get("NowPlayingItem", {})
            if not now_playing:
                return None

            # Get user info
            # Jellyfin sends explicit nulls for fields it cannot fill, and a
            # ``.get`` default only covers a *missing* key, never a null value.
            username = session.get("UserName") or "Unknown"
            displayed_user = resolve_user_display_name(self.user_mapping, username)

            # Determine media type
            item_type = now_playing.get("Type") or "Movie"
            if item_type == "Audio":
                media_type = MediaType.TRACK
            elif item_type == "Episode":
                media_type = MediaType.EPISODE
            else:
                media_type = MediaType.MOVIE

            # Get play state
            play_state_info = session.get("PlayState", {})
            is_paused = play_state_info.get("IsPaused", False)

            if is_paused:
                play_state = PlayState.PAUSED
            else:
                play_state = PlayState.PLAYING

            # Get video resolution and bitrate from media streams
            video_resolution = ""
            video_bitrate = None
            media_streams = now_playing.get("MediaStreams", [])

            for media_stream in media_streams:
                if media_stream.get("Type") == "Video":
                    width = media_stream.get("Width") or 0
                    height = media_stream.get("Height") or 0
                    video_resolution = format_resolution_from_dimensions(width, height)
                    video_bitrate = media_stream.get("BitRate")
                    break

            audio_quality = ""
            if media_type == MediaType.TRACK:
                for media_stream in media_streams:
                    if media_stream.get("Type") == "Audio":
                        audio_quality = format_audio_quality(
                            media_stream.get("BitDepth"), media_stream.get("SampleRate")
                        )
                        break

            # Fallback: try to get bitrate from NowPlayingItem if not in MediaStreams
            if video_bitrate is None:
                # Try container bitrate as fallback
                video_bitrate = now_playing.get("Bitrate")

            # Get transcode info
            transcode_info = session.get("TranscodingInfo", {})

            video_decision = TranscodeDecision.UNKNOWN
            audio_decision = TranscodeDecision.UNKNOWN
            transcode_bitrate = None
            is_video_direct = True
            is_audio_direct = True

            if transcode_info:
                # Check if video/audio are actually being transcoded
                is_video_direct = transcode_info.get("IsVideoDirect", True)
                is_audio_direct = transcode_info.get("IsAudioDirect", True)

                video_decision = (
                    TranscodeDecision.DIRECT_STREAM
                    if is_video_direct
                    else TranscodeDecision.TRANSCODE
                )
                audio_decision = (
                    TranscodeDecision.DIRECT_STREAM
                    if is_audio_direct
                    else TranscodeDecision.TRANSCODE
                )

                # Only use transcode bitrate if actually transcoding video
                if not is_video_direct:
                    transcode_bitrate = transcode_info.get("Bitrate")
            else:
                # No TranscodingInfo means Direct Play
                video_decision = TranscodeDecision.DIRECT_PLAY
                audio_decision = TranscodeDecision.DIRECT_PLAY

            # is_transcoding should only be True if VIDEO is being transcoded
            # (audio-only transcode is common and not really "transcoding" in user perception)
            is_transcoding = not is_video_direct

            # Get player info
            device_name = session.get("DeviceName") or "Unknown"
            client_name = session.get("Client") or "Unknown"

            # Get thumbnail - prefer series image for episodes
            thumb_id = None
            if media_type == MediaType.EPISODE:
                thumb_id = now_playing.get("SeriesId") or now_playing.get("Id")
            else:
                thumb_id = now_playing.get("Id")

            # Get playback position
            # Live TV, TvChannel items and .strm sources report these as null.
            position_ticks = play_state_info.get("PositionTicks") or 0
            duration_ticks = now_playing.get("RunTimeTicks") or 0

            # Convert ticks to milliseconds (1 tick = 100 nanoseconds = 0.0001 ms)
            view_offset_ms = position_ticks // 10000
            duration_ms = duration_ticks // 10000

            return ActiveStream(
                session_id=session.get("Id", ""),
                session_key=session.get("Id", ""),
                username=displayed_user,
                user_id=session.get("UserId"),
                media_type=media_type,
                title=now_playing.get("Name") or "Unknown",
                year=now_playing.get("ProductionYear"),
                series_title=now_playing.get("SeriesName"),
                season_number=now_playing.get("ParentIndexNumber"),
                episode_number=now_playing.get("IndexNumber"),
                artist=now_playing.get("AlbumArtist") if media_type == MediaType.TRACK else None,
                album=now_playing.get("Album") if media_type == MediaType.TRACK else None,
                library_section_title="",  # Jellyfin doesn't provide this in session
                play_state=play_state,
                view_offset_ms=view_offset_ms,
                duration_ms=duration_ms,
                video_resolution=video_resolution,
                video_bitrate_kbps=video_bitrate // 1000 if video_bitrate else None,
                audio_quality=audio_quality,
                video_decision=video_decision,
                audio_decision=audio_decision,
                transcode_bitrate_kbps=transcode_bitrate // 1000 if transcode_bitrate else None,
                is_transcoding=is_transcoding,
                player_name=client_name,
                player_device=device_name,
                thumb_path=thumb_id,
                raw_session=session,
            )
        except Exception as e:
            self.logger.error(f"Error converting session to stream: {e}")
            return None

    def _get_default_emoji(self, collection_type: str) -> str:
        """Get default emoji for a collection type."""
        emoji_map = {
            "movies": "🎥",
            "tvshows": "📺",
            "music": "🎵",
            "books": "📚",
            "photos": "📷",
            "homevideos": "📹",
        }
        return emoji_map.get(collection_type, "🎬")

    def _get_empty_library_stats(self) -> Dict[str, LibraryStats]:
        """Generate empty library stats matching config structure.

        Returns:
            Dictionary of empty library statistics
        """
        stats: Dict[str, LibraryStats] = {}
        jellyfin_config = self.config.get("jellyfin", {}).get("sections", {})

        for title, config in jellyfin_config.items():
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
