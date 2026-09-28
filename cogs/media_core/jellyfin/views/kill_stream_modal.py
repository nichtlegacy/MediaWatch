"""
Kill Stream Modal for Jellyfin integration.

This module contains the Discord modal for confirming and customizing
the message when terminating a Jellyfin stream.
"""

import discord
import logging

from ...shared.config_helper import StreamControlsConfig


logger = logging.getLogger("mediawatch_bot.media_core.jellyfin.kill_stream_modal")


class KillStreamModal(discord.ui.Modal, title="Kill Stream"):
    """Modal for confirming and customizing kill stream message."""

    def __init__(self, jellyfin_core_instance, session_key: str):
        super().__init__()
        self.jellyfin_core = jellyfin_core_instance
        self.session_key = session_key
        self.logger = logger
        controls_config = StreamControlsConfig(self.jellyfin_core.config)
        default_reason = controls_config.get_kill_stream_default_reason()

        self.reason_input = discord.ui.TextInput(
            label="Reason Message",
            placeholder=default_reason,
            default=default_reason,
            required=True,
            max_length=200,
            style=discord.TextStyle.short,
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission - kill the stream."""
        await interaction.response.defer(ephemeral=True)
        await self.kill_stream(interaction, self.reason_input.value)

    async def kill_stream(self, interaction: discord.Interaction, reason: str) -> None:
        """Kill a stream (authorized users only)."""
        try:
            if interaction.user.id not in self.jellyfin_core.AUTHORIZED_USERS:
                self.logger.warning(f"Unauthorized kill stream attempt by {interaction.user.name}")
                await interaction.followup.send(
                    "❌ You are not authorized to kill streams.", ephemeral=True
                )
                return

            if not self.jellyfin_core.jellyfin_client.is_connected():
                await interaction.followup.send(
                    "❌ Jellyfin server is not connected.", ephemeral=True
                )
                return

            session = await self.jellyfin_core.resolve_active_session(self.session_key)

            if not session:
                await interaction.followup.send(
                    "❌ This stream is no longer active.", ephemeral=True
                )
                return

            # Get stream info before killing
            now_playing: dict = {}
            media_type = "Movie"
            try:
                user = session.get("UserName", "Unknown")
                now_playing = session.get("NowPlayingItem") or {}
                media_type = now_playing.get("Type", "Movie")

                if media_type == "Episode":
                    series_title = now_playing.get("SeriesName", "Unknown Series")
                    season = int(now_playing.get("ParentIndexNumber") or 0)
                    episode = int(now_playing.get("IndexNumber") or 0)
                    title = f"{series_title} - S{season:02d}E{episode:02d}"
                elif media_type == "Audio":
                    artist = now_playing.get(
                        "AlbumArtist",
                        now_playing.get("Artists", ["Unknown"])[0]
                        if now_playing.get("Artists")
                        else "Unknown",
                    )
                    track = now_playing.get("Name", "Unknown Track")
                    title = f"{artist} - {track}"
                else:
                    year = now_playing.get("ProductionYear", "")
                    movie_title = now_playing.get("Name", "Unknown")
                    title = f"{movie_title} ({year})" if year else movie_title
            except Exception as e:
                self.logger.error(f"Error extracting session info: {e}")
                user = "Unknown"
                title = "Unknown"
                now_playing = {}
                media_type = "Movie"

            # Kill the stream using Jellyfin API
            reason_delivered = False
            try:
                # Use the session Id (not PlaySessionId)
                session_id = session.get("Id")

                if not session_id:
                    raise ValueError("No session ID found")

                # The stop endpoint takes no body, so the reason has to be pushed
                # to the client while the session is still alive. Clients that
                # report their commands without DisplayMessage cannot show it.
                supported_commands = session.get("SupportedCommands")
                if supported_commands is None or "DisplayMessage" in supported_commands:
                    reason_delivered = await self.jellyfin_core.jellyfin_client.send_message(
                        session_id, reason
                    )

                success = await self.jellyfin_core.jellyfin_client.stop_session(session_id)

                if not success:
                    raise ValueError("Failed to stop session")

            except Exception as e:
                self.logger.error(f"Error killing stream: {e}", exc_info=True)
                await interaction.followup.send(
                    f"❌ Failed to kill stream: {str(e)}", ephemeral=True
                )
                return

            self.logger.info(
                f"Stream killed by {interaction.user.name} - User: {user}, Title: {title}"
            )

            # Remove from active sessions
            self.jellyfin_core.active_sessions.pop(self.session_key, None)

            # Create success embed
            embed = discord.Embed(
                title="✅ Stream Killed Successfully",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow(),
            )

            year = now_playing.get("ProductionYear", "")

            if media_type == "Episode":
                show_name = now_playing.get("SeriesName", title)
                season = int(now_playing.get("ParentIndexNumber") or 0)
                episode = int(now_playing.get("IndexNumber") or 0)
                episode_title = now_playing.get("Name", "")

                footer_title = f"{show_name} ({year})" if year else show_name
                embed.add_field(name="📺 Series", value=f"`{footer_title}`", inline=True)
                embed.add_field(name="🔑 Session", value=f"`{session_id}`", inline=True)
                embed.add_field(name="\u200b", value="\u200b", inline=True)
                embed.add_field(
                    name="📋 Episode",
                    value=f"`S{season:02d}E{episode:02d} - {episode_title}`",
                    inline=False,
                )
            elif media_type == "Audio":
                artist = now_playing.get(
                    "AlbumArtist",
                    now_playing.get("Artists", ["Unknown"])[0]
                    if now_playing.get("Artists")
                    else "Unknown",
                )
                track = now_playing.get("Name", "")
                footer_title = f"{artist} - {track}"
                embed.add_field(name="🎵 Track", value=f"`{footer_title}`", inline=True)
                embed.add_field(name="🔑 Session", value=f"`{session_id}`", inline=True)
                embed.add_field(name="\u200b", value="\u200b", inline=True)
            else:
                movie_title = now_playing.get("Name", title)
                footer_title = f"{movie_title} ({year})" if year else movie_title
                embed.add_field(name="🎥 Movie", value=f"`{footer_title}`", inline=True)
                embed.add_field(name="🔑 Session", value=f"`{session_id}`", inline=True)
                embed.add_field(name="\u200b", value="\u200b", inline=True)

            embed.add_field(name="👤 User", value=f"`{user}`", inline=True)
            reason_field_name = "💬 Reason" if reason_delivered else "💬 Reason (not delivered)"
            embed.add_field(name=reason_field_name, value=f"`{reason}`", inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)

            dashboard_config = self.jellyfin_core.config.get("dashboard", {})
            footer_icon = dashboard_config.get("footer_icon_url", "")
            icon_url = dashboard_config.get("icon_url", "")

            if icon_url:
                embed.set_thumbnail(url=icon_url)

            if media_type == "Episode":
                footer_title = now_playing.get("SeriesName", title)
            else:
                footer_title = now_playing.get("Name", title)

            footer_text = f"{footer_title} ({year})" if year else footer_title
            embed.set_footer(text=footer_text, icon_url=footer_icon)

            dashboard_name = dashboard_config.get("name", "Jellyfin Dashboard")
            if icon_url:
                embed.set_author(name=dashboard_name, icon_url=icon_url)

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Unexpected error killing stream: {e}", exc_info=True)
            try:
                await interaction.followup.send("❌ An unexpected error occurred.", ephemeral=True)
            except Exception:
                pass
