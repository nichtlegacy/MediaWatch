"""
Jellyfin Core Discord Cog for MediaWatch.

This is the main Discord cog for Jellyfin integration, providing
dashboard updates, presence management, and stream details.

Note: Jellyfin does not have an equivalent to Tautulli, so advanced
statistics features (user stats, global stats) are not available.
"""

import discord
from discord.ext import commands, tasks
import asyncio
import os
import logging
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv

from .jellyfin_service import JellyfinMediaService
from ..shared.dashboard_service import DashboardService
from ..shared.env_validation import parse_authorized_users
from ..shared.formatters import format_stream_summary
from ..shared.presence import build_presence

# Import config utilities from shared
from ..shared.config import (
    load_config,
    load_message_id,
    save_message_id,
    load_user_mapping,
    check_legacy_config,
)


RUNNING_IN_DOCKER = os.getenv("RUNNING_IN_DOCKER", "false").lower() == "true"

if not RUNNING_IN_DOCKER:
    load_dotenv()


logger = logging.getLogger("mediawatch_bot.media_core.jellyfin")


class JellyfinCore(commands.Cog):
    """Core Jellyfin Media Server integration and dashboard management."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger = logger

        # Load environment variables
        self.JELLYFIN_URL = os.getenv("JELLYFIN_URL")
        self.JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY")

        channel_id = os.getenv("CHANNEL_ID")
        if channel_id is None:
            self.logger.error("CHANNEL_ID not set in .env file")
            raise ValueError("CHANNEL_ID must be set in .env")
        self.CHANNEL_ID = int(channel_id)

        # Convert config paths to absolute
        base_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
        self.CONFIG_FILE = os.path.join(base_dir, "data", "config.yaml")
        self.CONFIG_FILE_JSON = os.path.join(base_dir, "data", "config.json")
        self.USER_MAPPING_FILE_JSON = os.path.join(base_dir, "data", "user_mapping.json")
        self.MESSAGE_ID_FILE = os.path.join(base_dir, "data", "dashboard_message_id.json")

        # Check for legacy JSON config
        check_legacy_config(self.CONFIG_FILE, self.CONFIG_FILE_JSON, self.USER_MAPPING_FILE_JSON)

        # Initialize configuration
        self.config = load_config(self.CONFIG_FILE, self.CONFIG_FILE_JSON)
        # Load user mapping for jellyfin platform (flat format)
        self.user_mapping = load_user_mapping(
            self.CONFIG_FILE, self.USER_MAPPING_FILE_JSON, platform="jellyfin"
        )
        self.dashboard_message_id = load_message_id(self.MESSAGE_ID_FILE)

        # Server settings
        self.offline_threshold = self.config.get("server", {}).get("offline_threshold", 300)

        # Load authorized users
        self.AUTHORIZED_USERS: List[int] = parse_authorized_users(
            os.getenv("DISCORD_AUTHORIZED_USERS")
        )

        # Initialize Jellyfin service
        self.jellyfin_service = JellyfinMediaService(
            jellyfin_url=self.JELLYFIN_URL,
            jellyfin_api_key=self.JELLYFIN_API_KEY,
            config=self.config,
            user_mapping=self.user_mapping,
        )

        # Direct access to client
        self.jellyfin_client = self.jellyfin_service.jellyfin_client

        # Session tracking
        self.active_sessions: Dict[str, Any] = {}

        # Initialize stream details view
        from .views.stream_details_view import StreamDetailsView

        self.stream_details_view = StreamDetailsView(self)

        self._shutdown_started = False

    def _get_session_cache_key(self, session: Dict[str, Any]) -> Optional[str]:
        """Return the stable cache key for a Jellyfin session dictionary."""
        if not session:
            return None
        session_id = session.get("Id")
        if session_id in (None, ""):
            return None
        return str(session_id)

    def _replace_active_sessions(self, sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Replace the active session registry with the provided raw sessions."""
        updated_sessions: Dict[str, Any] = {}
        for session in sessions:
            cache_key = self._get_session_cache_key(session)
            if cache_key:
                updated_sessions[cache_key] = session
        self.active_sessions = updated_sessions
        return updated_sessions

    async def refresh_active_sessions(self) -> Dict[str, Any]:
        """Refresh active sessions from Jellyfin without rebuilding dashboard stats."""
        streams = await self.jellyfin_service.get_active_streams()
        raw_sessions = [stream.raw_session for stream in streams if stream.raw_session]
        return self._replace_active_sessions(raw_sessions)

    async def resolve_active_session(self, session_key: str) -> Optional[Dict[str, Any]]:
        """Resolve an active session from cache, then via a live refresh fallback."""
        session = self.active_sessions.get(session_key)
        if session:
            return session
        refreshed_sessions = await self.refresh_active_sessions()
        return refreshed_sessions.get(session_key)

    async def cog_load(self) -> None:
        """Register persistent views and start background tasks after the cog is ready."""
        self.bot.add_view(self.stream_details_view)

        if not self.update_status.is_running():
            self.update_status.start()

        if not self.update_dashboard.is_running():
            self.update_dashboard.start()

    async def get_server_info(self) -> Dict[str, Any]:
        """Retrieve current Jellyfin server status and statistics.

        Returns:
            Dictionary with server status, uptime, library stats, and active streams
        """
        status = await self.jellyfin_service.get_server_status()

        # Update active sessions
        self._replace_active_sessions(
            [stream.raw_session for stream in status.active_streams if stream.raw_session]
        )

        # Convert to legacy format for backward compatibility
        library_stats_dict = {}
        for title, stats in status.library_stats.items():
            library_stats_dict[title] = {
                "count": stats.item_count,
                "episodes": stats.episode_count,
                "display_name": stats.display_name,
                "emoji": stats.emoji,
                "show_episodes": stats.show_episodes,
            }

        return {
            "status": status.status_text,
            "auth_failed": status.auth_failed,
            "uptime": status.uptime_string,
            "offline_since": status.offline_since,
            "library_stats": library_stats_dict,
            "active_users": [self._format_stream_legacy(s) for s in status.active_streams],
            "current_streams": status.active_streams,
        }

    def _format_stream_legacy(self, stream) -> str:
        """Format stream in legacy format for backward compatibility."""
        return format_stream_summary(stream)

    @tasks.loop(minutes=5)
    async def update_status(self) -> None:
        """Update bot presence with Jellyfin status and stream count."""
        try:
            info = await self.get_server_info()
            presence = build_presence(
                self.config["presence"],
                is_online=info["status"] == "🟢 Online",
                auth_failed=bool(info.get("auth_failed")),
                active_streams=len(info["active_users"]),
                library_stats=info["library_stats"],
                separator=self.config["display"]["thousands_separator"],
                episode_label=self.config["display"]["episode_label"],
            )
            if presence is None:
                return

            activity, status = presence
            await self.bot.change_presence(activity=activity, status=status)
            self.logger.info(f"Status updated: {activity.name} ({status})")
        except Exception as e:
            self.logger.error(f"Error updating status: {e}")

    @update_status.before_loop
    async def before_update_status(self) -> None:
        """Wait until Discord is ready before starting the status loop."""
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def update_dashboard(self) -> None:
        """Update Discord dashboard with Jellyfin, SABnzbd, and Uptime data."""
        channel = await self._resolve_channel()
        if not channel:
            self.logger.warning(f"Dashboard channel {self.CHANNEL_ID} could not be resolved")
            return

        try:
            info = await self.get_server_info()

            # Add SABnzbd info if available
            sabnzbd_cog = self.bot.get_cog("SABnzbd")
            if sabnzbd_cog:
                info["downloads"] = await sabnzbd_cog.get_sabnzbd_info()

            # Uptime Kuma history only appears in the offline embed, so skip the
            # fetch (a socket.io login per call) while the server is online.
            uptime_cog = self.bot.get_cog("Uptime")
            if uptime_cog and info["status"] != "🟢 Online" and not info.get("auth_failed"):
                uptime_data = await asyncio.to_thread(uptime_cog.get_uptime_data)
                info["uptime_24h"] = (
                    f"{uptime_data[0]:.1f}% ({uptime_cog.format_online_time(uptime_data[1])})"
                    if uptime_data[0] is not None
                    else "No data"
                )
                info["uptime_7d"] = (
                    f"{uptime_data[2]:.1f}% ({uptime_cog.format_online_time(uptime_data[3])})"
                    if uptime_data[2] is not None
                    else "No data"
                )
                info["uptime_30d"] = (
                    f"{uptime_data[4]:.1f}% ({uptime_cog.format_online_time(uptime_data[5])})"
                    if uptime_data[4] is not None
                    else "No data"
                )

            # Create dashboard embed
            embed = await self._create_dashboard_embed(info)
            await self._update_dashboard_message(channel, embed, info)
        except Exception as e:
            self.logger.error(f"Error updating dashboard: {e}")

    @update_dashboard.before_loop
    async def before_update_dashboard(self) -> None:
        """Wait until Discord is ready before starting the dashboard loop."""
        await self.bot.wait_until_ready()

    async def _resolve_channel(self) -> Optional[discord.abc.Messageable]:
        """Resolve the configured dashboard channel from cache or API."""
        channel = self.bot.get_channel(self.CHANNEL_ID)
        if channel is not None:
            return channel

        try:
            return await self.bot.fetch_channel(self.CHANNEL_ID)
        except discord.HTTPException as e:
            self.logger.error(f"Failed to fetch dashboard channel {self.CHANNEL_ID}: {e}")
            return None

    async def _create_dashboard_embed(self, info: Dict[str, Any]) -> discord.Embed:
        """Create dashboard embed from server info."""
        return await DashboardService(self.bot, self.config, "jellyfin").create_dashboard_embed(
            info
        )

    async def _update_dashboard_message(
        self, channel: discord.TextChannel, embed: discord.Embed, info: Dict[str, Any]
    ) -> None:
        """Update or create the dashboard message in the specified channel."""
        # Create buttons for active streams
        active_streams = info.get("current_streams", [])

        # Update view buttons based on active streams
        view = None
        sessions = [stream.raw_session for stream in active_streams if stream.raw_session]
        await self.stream_details_view.create_buttons(sessions)
        view = self.stream_details_view if len(self.stream_details_view.children) > 0 else None

        if self.dashboard_message_id:
            try:
                message = channel.get_partial_message(self.dashboard_message_id)
                await message.edit(embed=embed, view=view)
                self.logger.debug("Dashboard message updated successfully")
            except discord.NotFound:
                self.logger.warning("Dashboard message not found, creating new one")
                self.dashboard_message_id = None
            except discord.Forbidden as e:
                self.logger.warning(
                    f"Dashboard message {self.dashboard_message_id} is not editable by this bot anymore: {e}. "
                    "Creating a new dashboard message."
                )
                self.dashboard_message_id = None
            except discord.HTTPException as e:
                self.logger.error(
                    f"Failed to update dashboard message {self.dashboard_message_id}: {e}"
                )
                return

        if not self.dashboard_message_id:
            try:
                message = await channel.send(embed=embed, view=view)
                self.dashboard_message_id = message.id
                save_message_id(self.MESSAGE_ID_FILE, message.id)
                self.logger.info(
                    f"New dashboard message created with ID: {self.dashboard_message_id}"
                )
            except discord.HTTPException as e:
                self.logger.error(f"Failed to create dashboard message: {e}")

    async def shutdown(self) -> None:
        """Clean up background tasks and network resources."""
        if self._shutdown_started:
            return

        self._shutdown_started = True

        if self.update_status.is_running():
            self.update_status.cancel()

        if self.update_dashboard.is_running():
            self.update_dashboard.cancel()

        self.stream_details_view.stop()
        await self.jellyfin_service.close()

    def cog_unload(self):
        """Schedule cleanup when the cog is unloaded."""
        if self.bot.loop.is_running():
            self.bot.loop.create_task(self.shutdown())


async def setup(bot: commands.Bot) -> None:
    """Set up the JellyfinCore cog for the bot."""
    await bot.add_cog(JellyfinCore(bot))
