"""
Stream Details View for Plex integration.

This module contains the Discord UI View for displaying stream details,
user statistics, and global server statistics with interactive buttons.
"""

import discord
import logging
from typing import Any, Dict, List, Optional

from ..utils.config_helper import GlobalStatsConfig, UserStatsConfig
from ..utils.links import build_plex_web_url, web_rating_key
from ...shared.config_helper import StreamDetailsConfig
from ...shared.formatters import resolve_user_display_name


logger = logging.getLogger("mediawatch_bot.media_core.plex.stream_details_view")


class StreamDetailsView(discord.ui.View):
    """Persistent view for stream detail buttons."""

    def __init__(self, plex_core_instance):
        """Initialize the StreamDetailsView.

        Args:
            plex_core_instance: Reference to PlexCore instance
        """
        super().__init__(timeout=None)
        self.plex_core = plex_core_instance
        self.logger = logger
        self.global_stats_config = GlobalStatsConfig(self.plex_core.config)
        self.stream_details_config = StreamDetailsConfig(self.plex_core.config)

    async def create_buttons(
        self,
        sessions: List[Any],
        library_stats: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Create/update dashboard controls for active streams and Tautulli actions.

        Args:
            sessions: List of active Plex sessions
            library_stats: Library statistics from the current dashboard run,
                used for the per-section emoji. Fetching them here again would
                enumerate the whole library a second time per interval.
        """
        self.clear_items()

        if self.should_show_global_stats_in_dashboard():
            global_stats_button = discord.ui.Button(
                label="Global Stats",
                style=discord.ButtonStyle.secondary,
                custom_id="global_stats:dashboard",
                emoji="🌐",
            )
            global_stats_button.callback = self._create_global_stats_callback()
            self.add_item(global_stats_button)

        if self._should_show_stream_buttons():
            stats = library_stats or {}
            for idx, session in enumerate(sessions[:8], start=1):
                try:
                    session_key = self.plex_core._get_session_cache_key(session)
                    if not session_key:
                        continue

                    user = (
                        session.usernames[0]
                        if hasattr(session, "usernames") and session.usernames
                        else "Unknown"
                    )
                    displayed_user = resolve_user_display_name(
                        getattr(self.plex_core, "user_mapping", {}),
                        user,
                    )

                    if len(displayed_user) > 15:
                        displayed_user = displayed_user[:12] + "..."

                    section_title = getattr(session, "librarySectionTitle", "Unknown")
                    content_emoji = stats.get(section_title, {}).get("emoji") or (
                        "🎵"
                        if getattr(session, "type", "") == "track"
                        else "🎥"
                        if getattr(session, "type", "") in ["movie", None]
                        else "📺"
                    )

                    button = discord.ui.Button(
                        label=f"Stream {idx} - {displayed_user}",
                        style=discord.ButtonStyle.primary,
                        custom_id=f"stream_details:{session_key}",
                        emoji=content_emoji,
                    )
                    button.callback = self._create_callback(session_key)
                    self.add_item(button)
                except Exception as e:
                    self.logger.error(f"Error creating button for stream {idx}: {e}", exc_info=True)

    def _has_tautulli(self) -> bool:
        """Return whether Tautulli-backed actions are available."""
        return bool(self.plex_core.TAUTULLI_URL and self.plex_core.TAUTULLI_API_KEY)

    def _should_show_stream_buttons(self) -> bool:
        """Return whether the per-stream buttons are worth showing.

        Stream details need Tautulli, but the Kill Stream action behind the same
        button only needs Plex. The buttons therefore stay useful without
        Tautulli as long as somebody is authorized to kill streams.
        """
        return self._has_tautulli() or bool(self.plex_core.AUTHORIZED_USERS)

    def should_show_global_stats_in_dashboard(self) -> bool:
        """Return whether the dashboard should expose the global stats button."""
        return self._has_tautulli() and self.global_stats_config.show_in_dashboard()

    def should_show_global_stats_in_stream_details(self) -> bool:
        """Return whether stream details should expose the global stats button."""
        return self._has_tautulli() and self.global_stats_config.show_in_stream_details()

    def _create_callback(self, session_key: str):
        """Create a callback function for a specific session."""

        async def callback(interaction: discord.Interaction):
            await self.show_stream_details(interaction, session_key)

        return callback

    def _may_view_stream_details(self, user_id: int) -> bool:
        """Return whether the given Discord user may open stream details."""
        if not self.stream_details_config.restrict_to_authorized():
            return True
        return user_id in self.plex_core.AUTHORIZED_USERS

    async def show_stream_details(self, interaction: discord.Interaction, session_key: str) -> None:
        """Show detailed information about a specific stream."""
        from ..embeds.stream_embeds import create_stream_error_embed

        try:
            await interaction.response.defer(ephemeral=True)

            if not self._may_view_stream_details(interaction.user.id):
                await interaction.followup.send(
                    "\u274c Stream details are restricted to authorized users on this server.",
                    ephemeral=True,
                )
                return

            if not self.plex_core.plex:
                await interaction.followup.send(
                    embed=create_stream_error_embed(
                        self.plex_core,
                        "The Plex server is currently unavailable. Please try again in a moment.",
                        footer_text="Plex Connection Error",
                    ),
                    ephemeral=True,
                )
                return

            session = await self.plex_core.resolve_active_session(session_key)

            if not session:
                await interaction.followup.send(
                    embed=create_stream_error_embed(
                        self.plex_core,
                        "This stream is no longer active, or the session cache expired. Please refresh the dashboard and try again.",
                        footer_text="Plex Stream Status",
                    ),
                    ephemeral=True,
                )
                return

            from ..embeds.stream_embeds import create_detailed_stream_embed

            show_connection_ip = (
                interaction.user.id in self.plex_core.AUTHORIZED_USERS
                and self.stream_details_config.show_ip_for_authorized_users()
            )

            if self._has_tautulli():
                embed, attachment_payload = await create_detailed_stream_embed(
                    session,
                    self.plex_core,
                    self.plex_core.tautulli_client,
                    show_connection_ip=show_connection_ip,
                )
            else:
                embed = create_stream_error_embed(
                    self.plex_core,
                    "Detailed stream information needs Tautulli. Set TAUTULLI_URL and "
                    "TAUTULLI_API_KEY to enable it.",
                    footer_text="Tautulli Not Configured",
                )
                attachment_payload = None

            if "❌" in embed.title:
                # Details are unavailable, but killing the stream does not need
                # Tautulli - keep that action reachable for authorized users.
                fallback_view = discord.ui.View(timeout=300)
                self._add_kill_button(fallback_view, interaction, session_key)
                await interaction.followup.send(
                    embed=embed,
                    view=fallback_view if fallback_view.children else None,
                    ephemeral=True,
                )
                return

            tautulli_data = await self.plex_core.tautulli_client.fetch_session(
                str(session.sessionKey)
            )

            view = discord.ui.View(timeout=300)

            if self.should_show_global_stats_in_stream_details():
                global_stats_button = discord.ui.Button(
                    label="Global Stats", style=discord.ButtonStyle.secondary, emoji="🌐"
                )
                global_stats_button.callback = self._create_global_stats_callback()
                view.add_item(global_stats_button)

            if tautulli_data and tautulli_data.get("user_id"):
                user_id = str(tautulli_data.get("user_id"))
                user_stats_button = discord.ui.Button(
                    label="User Stats", style=discord.ButtonStyle.primary, emoji="📊"
                )
                user_stats_button.callback = self._create_user_stats_callback(session_key, user_id)
                view.add_item(user_stats_button)

            self._add_link_buttons(view, session)
            self._add_kill_button(view, interaction, session_key)

            files = []
            if attachment_payload:
                if isinstance(attachment_payload, (list, tuple)):
                    files = list(attachment_payload)
                else:
                    files = [attachment_payload]

            if files:
                await interaction.followup.send(embed=embed, files=files, view=view, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Unexpected error showing stream details: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    embed=create_stream_error_embed(
                        self.plex_core,
                        "Something went wrong while loading these stream details. Please try again.",
                        footer_text="Plex Stream Details Error",
                    ),
                    ephemeral=True,
                )
            except Exception:
                pass

    def _add_link_buttons(self, view: discord.ui.View, session) -> None:
        """Attach the configured "Plex" link button.

        Link buttons carry no ``custom_id`` and never call back, so there is no
        authorization step here - the details embed the user already sees says
        more than the link does.
        """
        try:
            if not self.stream_details_config.link_enabled("plex"):
                return

            plex_url = build_plex_web_url(
                getattr(self.plex_core.plex, "machineIdentifier", None),
                web_rating_key(session),
                self.stream_details_config.link_base_url("plex"),
            )
            if plex_url:
                view.add_item(
                    discord.ui.Button(
                        label="Plex",
                        style=discord.ButtonStyle.link,
                        url=plex_url,
                        emoji=self.stream_details_config.link_emoji("plex"),
                    )
                )
        except Exception as e:
            # A missing link is not worth losing the stream details over.
            self.logger.warning(f"Could not build the Plex link button: {e}", exc_info=True)

    def _add_kill_button(
        self,
        view: discord.ui.View,
        interaction: discord.Interaction,
        session_key: str,
    ) -> None:
        """Attach the Kill Stream button when the caller is authorized."""
        if interaction.user.id not in self.plex_core.AUTHORIZED_USERS:
            return

        kill_button = discord.ui.Button(
            label="Kill Stream", style=discord.ButtonStyle.danger, emoji="⛔"
        )
        kill_button.callback = self._create_kill_callback(session_key)
        view.add_item(kill_button)

    def _create_kill_callback(self, session_key: str):
        """Create a callback for kill stream modal."""

        async def callback(interaction: discord.Interaction):
            if interaction.user.id not in self.plex_core.AUTHORIZED_USERS:
                await interaction.response.send_message(
                    "❌ You are not authorized to kill streams.", ephemeral=True
                )
                return

            from .kill_stream_modal import KillStreamModal

            modal = KillStreamModal(self.plex_core, session_key)
            await interaction.response.send_modal(modal)

        return callback

    def _create_user_stats_callback(self, session_key: str, user_id: str):
        """Create a callback for user statistics."""

        async def callback(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            await self.show_user_stats(interaction, user_id)

        return callback

    def _create_global_stats_callback(self):
        """Create a callback for global statistics."""

        async def callback(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            await self.show_global_stats(interaction)

        return callback

    async def show_user_stats(self, interaction: discord.Interaction, user_id: str) -> None:
        """Show paginated user statistics."""
        try:
            config = UserStatsConfig(self.plex_core.config)

            if config.restrict_to_authorized() and (
                interaction.user.id not in self.plex_core.AUTHORIZED_USERS
            ):
                await interaction.followup.send(
                    "❌ User statistics are restricted to authorized users on this server.",
                    ephemeral=True,
                )
                return

            if not config.is_enabled():
                await interaction.followup.send(
                    "❌ User statistics feature is disabled.", ephemeral=True
                )
                return

            watch_time_stats = await self.plex_core.tautulli_client.fetch_user_watch_time_stats(
                user_id
            )

            if not watch_time_stats:
                await interaction.followup.send(
                    "❌ Could not fetch user statistics.", ephemeral=True
                )
                return

            # Resolve display name directly from Tautulli user lookup.
            user_display = None
            tautulli_username = await self.plex_core.tautulli_client.fetch_user_name(user_id)
            if tautulli_username:
                user_display = resolve_user_display_name(
                    self.plex_core.user_mapping,
                    tautulli_username,
                )

            if not user_display:
                user_display = f"User {user_id}"

            # Get time_range from config (0 = all time)
            time_range = config.get_time_range()

            # Fetch all required data with time_range
            player_stats = await self.plex_core.tautulli_client.fetch_user_player_stats(
                user_id, time_range=time_range
            )
            user_history = await self.plex_core.tautulli_client.fetch_user_history(user_id)

            # Calculate metrics
            watch_streak = None
            favorite_genre = None
            period_comparisons = {}
            content_breakdown = {}
            top_shows = []
            peak_hour = None
            most_active_day = None
            most_active_device = None
            top_content_type = None

            if user_history:
                from ..utils.statistics import (
                    calculate_watch_streak,
                    calculate_favorite_genre,
                    calculate_previous_period_stats,
                    calculate_period_comparison,
                )
                from ..utils.user_stats_utils import (
                    calculate_content_type_breakdown,
                    calculate_top_shows,
                    filter_history_by_time_range,
                    calculate_peak_hour,
                    calculate_most_active_day,
                    calculate_most_active_device,
                    calculate_top_content_type,
                )

                # Filter history by configured time_range
                filtered_history = filter_history_by_time_range(user_history, time_range)

                watch_streak = calculate_watch_streak(user_history)  # Use full history for streak
                favorite_genre = calculate_favorite_genre(filtered_history)
                content_breakdown = calculate_content_type_breakdown(filtered_history)
                # Calculate top shows from filtered history
                top_shows = calculate_top_shows(filtered_history, limit=config.get_top_tv_count())
                peak_hour = calculate_peak_hour(filtered_history)
                most_active_day = calculate_most_active_day(filtered_history)
                most_active_device = calculate_most_active_device(player_stats or [])
                top_content_type = calculate_top_content_type(content_breakdown)
                if "last_7d" in watch_time_stats:
                    previous_7d_stats = calculate_previous_period_stats(user_history, days=7)
                    period_comparisons["7d"] = calculate_period_comparison(
                        watch_time_stats["last_7d"], previous_7d_stats, "7d"
                    )

                if "last_30d" in watch_time_stats:
                    previous_30d_stats = calculate_previous_period_stats(user_history, days=30)
                    period_comparisons["30d"] = calculate_period_comparison(
                        watch_time_stats["last_30d"], previous_30d_stats, "30d"
                    )

            stats_data = {
                "watch_time_stats": watch_time_stats,
                "top_shows": top_shows or [],
                "player_stats": player_stats or [],
                "watch_streak": watch_streak,
                "favorite_genre": favorite_genre,
                "period_comparisons": period_comparisons,
                "content_breakdown": content_breakdown,
                "time_range": time_range,
                "peak_hour": peak_hour,
                "most_active_day": most_active_day,
                "most_active_device": most_active_device,
                "top_content_type": top_content_type,
            }

            from .user_stats_pagination import UserStatsPaginationView

            view = UserStatsPaginationView(self.plex_core, user_id, user_display, stats_data)
            await view.create_pages()

            if not view.pages:
                await interaction.followup.send(
                    "❌ No statistics pages could be generated.", ephemeral=True
                )
                return

            # Send with files if available for first page
            files = view.page_files.get(0, [])
            if files:
                await interaction.followup.send(
                    embed=view.pages[0], files=files, view=view, ephemeral=True
                )
            else:
                await interaction.followup.send(embed=view.pages[0], view=view, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error showing user stats: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    "❌ An error occurred while fetching user statistics.", ephemeral=True
                )
            except Exception:
                pass

    def _may_view_global_stats(self, user_id: int) -> bool:
        """Return whether the given Discord user may open global stats."""
        if not self.global_stats_config.restrict_to_authorized():
            return True
        return user_id in self.plex_core.AUTHORIZED_USERS

    async def show_global_stats(self, interaction: discord.Interaction) -> None:
        """Show global server statistics with pagination."""
        try:
            if not self._may_view_global_stats(interaction.user.id):
                await interaction.followup.send(
                    "\u274c Global statistics are restricted to authorized users on this server.",
                    ephemeral=True,
                )
                return

            global_stats = await self.plex_core.tautulli_client.fetch_global_server_stats()

            if not global_stats:
                await interaction.followup.send(
                    "❌ Could not fetch global server statistics.", ephemeral=True
                )
                return

            from .global_stats_pagination import GlobalStatsPaginationView

            view = GlobalStatsPaginationView(self.plex_core, global_stats)
            await view.create_pages()

            if view.pages:
                embed = view.pages[0]
                files = view.page_files.get(0, [])
                if files:
                    await interaction.followup.send(
                        embed=embed, files=files, view=view, ephemeral=True
                    )
                else:
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                await interaction.followup.send("❌ No statistics available.", ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error showing global stats: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    "❌ An error occurred while fetching global statistics.", ephemeral=True
                )
            except Exception:
                pass
