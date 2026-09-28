"""
Kill Stream Modal for Plex integration.

This module contains the Discord modal for confirming and customizing
the message when terminating a Plex stream.
"""

import asyncio
import discord
import logging

from ...shared.config_helper import StreamControlsConfig


logger = logging.getLogger("mediawatch_bot.media_core.plex.kill_stream_modal")


class KillStreamModal(discord.ui.Modal, title="Kill Stream"):
    """Modal for confirming and customizing kill stream message."""

    def __init__(self, plex_core_instance, session_key: str):
        super().__init__()
        self.plex_core = plex_core_instance
        self.session_key = session_key
        self.logger = logger
        controls_config = StreamControlsConfig(self.plex_core.config)
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
            if interaction.user.id not in self.plex_core.AUTHORIZED_USERS:
                self.logger.warning(f"Unauthorized kill stream attempt by {interaction.user.name}")
                await interaction.followup.send(
                    "❌ You are not authorized to kill streams.", ephemeral=True
                )
                return

            if not self.plex_core.plex:
                await interaction.followup.send("❌ Plex server is not connected.", ephemeral=True)
                return

            session = await self.plex_core.resolve_active_session(self.session_key)

            if not session:
                await interaction.followup.send(
                    "❌ This stream is no longer active.", ephemeral=True
                )
                return

            # Get stream info before killing
            try:
                user = (
                    session.usernames[0]
                    if hasattr(session, "usernames") and session.usernames
                    else "Unknown"
                )

                if hasattr(session, "type") and session.type == "track":
                    artist = getattr(session, "grandparentTitle", "Unknown Artist")
                    track = getattr(session, "title", "Unknown Track")
                    title = f"{artist} - {track}"
                elif hasattr(session, "grandparentTitle"):
                    series_title = session.grandparentTitle.strip()
                    episode_info = (
                        f"S{session.parentIndex:02d}E{session.index:02d}"
                        if hasattr(session, "parentIndex") and hasattr(session, "index")
                        else ""
                    )
                    title = f"{series_title} - {episode_info}"
                else:
                    year = f" ({session.year})" if hasattr(session, "year") and session.year else ""
                    title = f"{session.title}{year}"

                session_id = getattr(session, "sessionKey", "Unknown")
            except Exception as e:
                self.logger.error(f"Error extracting session info: {e}")
                user = "Unknown"
                title = "Unknown"
                session_id = "Unknown"

            # Fetch Tautulli data
            tautulli_data = None
            try:
                tautulli_data = await self.plex_core.tautulli_client.fetch_session(
                    str(session.sessionKey)
                )
            except Exception as e:
                self.logger.warning(f"Could not fetch Tautulli data: {e}")

            # Kill the stream
            try:
                await asyncio.to_thread(session.stop, reason=reason)
            except Exception as e:
                self.logger.error(f"Error killing stream: {e}", exc_info=True)
                await interaction.followup.send(
                    f"❌ Failed to kill stream: {str(e)}", ephemeral=True
                )
                return

            self.logger.info(
                f"Stream killed by {interaction.user.name} - User: {user}, Title: {title}"
            )

            self.plex_core.active_sessions.pop(self.session_key, None)

            # Create success embed
            embed = discord.Embed(
                title="✅ Stream Killed Successfully",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow(),
            )

            if tautulli_data:
                media_type = tautulli_data.get("media_type", "movie")
                year = tautulli_data.get("year", "")

                if media_type == "episode":
                    show_name = tautulli_data.get("grandparent_title", title)
                    season = int(tautulli_data.get("parent_media_index") or 0)
                    episode = int(tautulli_data.get("media_index") or 0)
                    episode_title = tautulli_data.get("title", "")

                    footer_title = f"{show_name} ({year})" if year else show_name
                    embed.add_field(name="📺 Series", value=f"`{footer_title}`", inline=True)
                    embed.add_field(name="🔑 Session", value=f"`{session_id}`", inline=True)
                    embed.add_field(name="\u200b", value="\u200b", inline=True)
                    embed.add_field(
                        name="📋 Episode",
                        value=f"`S{season:02d}E{episode:02d} - {episode_title}`",
                        inline=False,
                    )
                elif media_type == "track":
                    artist = tautulli_data.get("grandparent_title", "")
                    track = tautulli_data.get("title", "")
                    footer_title = f"{artist} - {track}"
                    embed.add_field(name="🎵 Track", value=f"`{footer_title}`", inline=True)
                    embed.add_field(name="🔑 Session", value=f"`{session_id}`", inline=True)
                    embed.add_field(name="\u200b", value="\u200b", inline=True)
                else:
                    movie_title = tautulli_data.get("title", title)
                    footer_title = f"{movie_title} ({year})" if year else movie_title
                    embed.add_field(name="🎥 Movie", value=f"`{footer_title}`", inline=True)
                    embed.add_field(name="🔑 Session", value=f"`{session_id}`", inline=True)
                    embed.add_field(name="\u200b", value="\u200b", inline=True)
            else:
                embed.add_field(name="📺 Title", value=f"`{title}`", inline=True)
                embed.add_field(name="🔑 Session", value=f"`{session_id}`", inline=True)
                embed.add_field(name="\u200b", value="\u200b", inline=True)

            embed.add_field(name="👤 User", value=f"`{user}`", inline=True)
            embed.add_field(name="💬 Reason", value=f"`{reason}`", inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)

            dashboard_config = self.plex_core.config.get("dashboard", {})
            footer_icon = dashboard_config.get("footer_icon_url", "")
            icon_url = dashboard_config.get("icon_url", "")

            if icon_url:
                embed.set_thumbnail(url=icon_url)

            if tautulli_data:
                media_type = tautulli_data.get("media_type", "movie")
                year = tautulli_data.get("year", "")

                if media_type == "episode":
                    footer_title = tautulli_data.get("grandparent_title", title)
                else:
                    footer_title = tautulli_data.get("title", title)

                footer_text = f"{footer_title} ({year})" if year else footer_title
            else:
                footer_text = title

            embed.set_footer(text=footer_text, icon_url=footer_icon)

            dashboard_name = dashboard_config.get("name", "Plex Dashboard")
            if icon_url:
                embed.set_author(name=dashboard_name, icon_url=icon_url)

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Unexpected error killing stream: {e}", exc_info=True)
            try:
                await interaction.followup.send("❌ An unexpected error occurred.", ephemeral=True)
            except Exception:
                pass
