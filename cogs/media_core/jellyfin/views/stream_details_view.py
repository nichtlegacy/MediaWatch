"""
Stream Details View for Jellyfin integration.

This module contains the Discord UI View for displaying stream details
with interactive buttons.
"""

import discord
import logging
from typing import Any, Dict, List

from ...shared.config_helper import StreamDetailsConfig
from ...shared.formatters import resolve_user_display_name


logger = logging.getLogger("mediawatch_bot.media_core.jellyfin.stream_details_view")


class StreamDetailsView(discord.ui.View):
    """Persistent view for stream detail buttons."""

    def __init__(self, jellyfin_core_instance):
        """Initialize the StreamDetailsView.

        Args:
            jellyfin_core_instance: Reference to JellyfinCore instance
        """
        super().__init__(timeout=None)
        self.jellyfin_core = jellyfin_core_instance
        self.logger = logger
        self.stream_details_config = StreamDetailsConfig(self.jellyfin_core.config)

    async def create_buttons(self, sessions: List[Dict[str, Any]]) -> None:
        """Create/update buttons for active streams.

        Args:
            sessions: List of active Jellyfin sessions
        """
        self.clear_items()

        for idx, session in enumerate(sessions[:8], start=1):
            try:
                session_key = self.jellyfin_core._get_session_cache_key(session)
                if not session_key:
                    continue

                # Get username
                user = session.get("UserName", "Unknown")
                displayed_user = resolve_user_display_name(self.jellyfin_core.user_mapping, user)

                if len(displayed_user) > 15:
                    displayed_user = displayed_user[:12] + "..."

                # Get content emoji based on media type
                now_playing = session.get("NowPlayingItem", {})
                media_type = now_playing.get("Type", "")

                content_emoji = (
                    "🎵" if media_type == "Audio" else "📺" if media_type == "Episode" else "🎥"
                )

                button = discord.ui.Button(
                    label=f"Stream {idx} - {displayed_user}",
                    style=discord.ButtonStyle.primary,
                    custom_id=f"jellyfin_stream_details:{session_key}",
                    emoji=content_emoji,
                )
                button.callback = self._create_callback(session_key)
                self.add_item(button)
            except Exception as e:
                self.logger.error(f"Error creating button for stream {idx}: {e}", exc_info=True)

    def _create_callback(self, session_key: str):
        """Create a callback function for a specific session."""

        async def callback(interaction: discord.Interaction):
            await self.show_stream_details(interaction, session_key)

        return callback

    def _may_view_stream_details(self, user_id: int) -> bool:
        """Return whether the given Discord user may open stream details."""
        if not self.stream_details_config.restrict_to_authorized():
            return True
        return user_id in self.jellyfin_core.AUTHORIZED_USERS

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

            if not self.jellyfin_core.jellyfin_client.is_connected():
                await interaction.followup.send(
                    embed=create_stream_error_embed(
                        self.jellyfin_core,
                        "The Jellyfin server is currently unavailable. Please try again in a moment.",
                        footer_text="Jellyfin Connection Error",
                    ),
                    ephemeral=True,
                )
                return

            session = await self.jellyfin_core.resolve_active_session(session_key)

            if not session:
                await interaction.followup.send(
                    embed=create_stream_error_embed(
                        self.jellyfin_core,
                        "This stream is no longer active, or the session cache expired. Please refresh the dashboard and try again.",
                        footer_text="Jellyfin Stream Status",
                    ),
                    ephemeral=True,
                )
                return

            # Import from local embeds module
            from ..embeds.stream_embeds import create_detailed_stream_embed

            show_connection_ip = (
                interaction.user.id in self.jellyfin_core.AUTHORIZED_USERS
                and self.stream_details_config.show_ip_for_authorized_users()
            )

            embed, file = await create_detailed_stream_embed(
                session,
                self.jellyfin_core,
                show_connection_ip=show_connection_ip,
            )

            if "❌" in embed.title:
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            view = discord.ui.View(timeout=300)

            # Add kill stream button for authorized users
            if interaction.user.id in self.jellyfin_core.AUTHORIZED_USERS:
                kill_button = discord.ui.Button(
                    label="Kill Stream", style=discord.ButtonStyle.danger, emoji="⛔"
                )
                kill_button.callback = self._create_kill_callback(session_key)
                view.add_item(kill_button)

            if file:
                await interaction.followup.send(embed=embed, file=file, view=view, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Unexpected error showing stream details: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    embed=create_stream_error_embed(
                        self.jellyfin_core,
                        "Something went wrong while loading these stream details. Please try again.",
                        footer_text="Jellyfin Stream Details Error",
                    ),
                    ephemeral=True,
                )
            except Exception:
                pass

    def _create_kill_callback(self, session_key: str):
        """Create a callback for kill stream modal."""

        async def callback(interaction: discord.Interaction):
            if interaction.user.id not in self.jellyfin_core.AUTHORIZED_USERS:
                await interaction.response.send_message(
                    "❌ You are not authorized to kill streams.", ephemeral=True
                )
                return

            from .kill_stream_modal import KillStreamModal

            modal = KillStreamModal(self.jellyfin_core, session_key)
            await interaction.response.send_modal(modal)

        return callback
