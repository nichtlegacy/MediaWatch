"""
Maintenance Mode Cog for MediaWatch.

/maintenance puts the dashboard and the bot presence into an announced
maintenance state instead of letting them turn red. The state itself lives in
the shared maintenance module, so it works the same for Plex and Jellyfin.
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import List, Optional

import discord
from discord import app_commands
from discord.ext import commands

import version
from cogs.media_core.shared import maintenance
from cogs.media_core.shared.env_validation import parse_authorized_users
from cogs.media_core.shared.formatters import format_watch_time


logger = logging.getLogger("mediawatch_bot.maintenance")

# Exactly one of them is loaded, depending on media_server.type.
MEDIA_CORE_COGS = ("PlexCore", "JellyfinCore")
DURATION_SUGGESTIONS = ["15m", "30m", "1h", "2h", "4h", "8h", "1d"]
NOT_SAVED_WARNING = (
    "Could not save the change to `data/runtime_state.json`, so it will not survive "
    "a restart of the bot. Check that `data/` is writable; the log has the error."
)


def _timestamp(value: float) -> str:
    moment = datetime.fromtimestamp(value, tz=timezone.utc)
    return f"{discord.utils.format_dt(moment, style='f')} ({discord.utils.format_dt(moment, style='R')})"


class Maintenance(
    commands.GroupCog,
    group_name="maintenance",
    group_description="Announce maintenance on the dashboard instead of showing the server offline",
):
    """Start, update, end and inspect maintenance mode."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger = logger
        self.authorized_users = parse_authorized_users(os.getenv("DISCORD_AUTHORIZED_USERS"))

    def _is_authorized(self, user_id: int) -> bool:
        return user_id in self.authorized_users

    def _media_core(self) -> Optional[commands.Cog]:
        for name in MEDIA_CORE_COGS:
            core = self.bot.get_cog(name)
            if core is not None:
                return core
        return None

    async def _refresh_dashboard(self) -> None:
        """Render the dashboard now instead of on the next tick, up to a minute away.

        The dashboard run also brings the presence up to date when maintenance
        started or ended. A failure only costs the shortcut: the loop renders the
        new state on its next tick anyway.
        """
        core = self._media_core()
        if core is None:
            return
        try:
            await core.update_dashboard()
        except Exception as e:
            self.logger.error(f"Immediate dashboard refresh failed, the next tick retries: {e}")

    def _create_embed(self, title: str, description: str, color: discord.Color) -> discord.Embed:
        """Create an embed in the style of the other command replies."""
        embed = discord.Embed(
            title=title, description=description, color=color, timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f"{version.__project_name__} v{version.__version__}")
        if self.bot.user:
            embed.set_author(name="Maintenance Manager", icon_url=self.bot.user.display_avatar.url)
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        return embed

    def _window_embed(
        self, title: str, description: str, window: maintenance.MaintenanceWindow
    ) -> discord.Embed:
        embed = self._create_embed(title, description, discord.Color.gold())
        embed.add_field(name="Reason", value=window.reason or "No reason given", inline=False)
        embed.add_field(name="Since", value=_timestamp(window.started_at), inline=False)
        if window.ends_at is None:
            end_text = "Not announced. Ends only with `/maintenance end`."
        else:
            end_text = _timestamp(window.ends_at)
            if window.overdue():
                end_text += ", taking longer than planned"
        embed.add_field(name="Expected End", value=end_text, inline=False)
        if window.started_by is not None:
            embed.add_field(name="Started By", value=f"<@{window.started_by}>", inline=False)
        return embed

    def _add_dashboard_notes(self, embed: discord.Embed, persisted: bool) -> None:
        if not persisted:
            embed.add_field(name="⚠️ Not Saved", value=NOT_SAVED_WARNING, inline=False)
        if self._media_core() is None:
            embed.add_field(
                name="⚠️ No Media Core Loaded",
                value="The dashboard shows this once the Plex or Jellyfin cog runs again.",
                inline=False,
            )

    async def _reject_unauthorized(self, interaction: discord.Interaction) -> bool:
        if self._is_authorized(interaction.user.id):
            return False
        embed = self._create_embed(
            "❌ Not Authorized",
            "You are not authorized to manage maintenance mode.",
            discord.Color.red(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return True

    @app_commands.command(
        name="start", description="Start maintenance mode, or update the running one"
    )
    @app_commands.describe(
        reason="Shown on the dashboard. Left out on an update: keeps the current reason",
        duration="Expected duration from now: 30m, 2h, 1h30m, 1d. Left out on an update: keeps the end",
    )
    async def maintenance_start(
        self,
        interaction: discord.Interaction,
        reason: Optional[app_commands.Range[str, 1, maintenance.MAX_REASON_LENGTH]] = None,
        duration: Optional[str] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if await self._reject_unauthorized(interaction):
            return

        seconds = None
        if duration is not None:
            try:
                seconds = maintenance.parse_duration(duration)
            except ValueError as e:
                embed = self._create_embed("❌ Invalid Duration", str(e), discord.Color.red())
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

        was_active = maintenance.current() is not None
        window, persisted = maintenance.start(
            started_by=interaction.user.id, reason=reason, duration=seconds
        )
        self.logger.info(
            "Maintenance %s by %s (%s): reason=%r, ends_at=%s",
            "updated" if was_active else "started",
            interaction.user,
            interaction.user.id,
            window.reason,
            window.ends_at,
        )

        if was_active:
            title, description = "🛠️ Maintenance Updated", "The dashboard shows the new details."
        else:
            title, description = (
                "🛠️ Maintenance Started",
                "The dashboard announces the maintenance instead of showing the server offline.",
            )
        embed = self._window_embed(title, description, window)
        self._add_dashboard_notes(embed, persisted)
        try:
            await interaction.followup.send(embed=embed, ephemeral=True)
        finally:
            # The state is already changed; the dashboard must follow even if
            # the reply could not be delivered.
            await self._refresh_dashboard()

    @maintenance_start.autocomplete("duration")
    async def duration_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        """Suggest common durations. Any other value can still be typed."""
        current = current.strip().lower()
        return [
            app_commands.Choice(name=value, value=value)
            for value in DURATION_SUGGESTIONS
            if value.startswith(current)
        ]

    @app_commands.command(name="end", description="End maintenance mode")
    async def maintenance_end(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if await self._reject_unauthorized(interaction):
            return

        window, persisted = maintenance.end()
        if window is None:
            embed = self._create_embed(
                "⚠️ Not Active",
                "Maintenance mode is not active, so there is nothing to end.\n\n"
                "Use `/maintenance start` to start it.",
                discord.Color.orange(),
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        lasted = format_watch_time(max(0, int(time.time() - window.started_at)))
        self.logger.info(
            "Maintenance ended by %s (%s) after %s", interaction.user, interaction.user.id, lasted
        )
        embed = self._create_embed(
            "✅ Maintenance Ended",
            f"Maintenance lasted {lasted}. The dashboard shows the server again.",
            discord.Color.green(),
        )
        self._add_dashboard_notes(embed, persisted)
        try:
            await interaction.followup.send(embed=embed, ephemeral=True)
        finally:
            await self._refresh_dashboard()

    @app_commands.command(name="status", description="Show whether maintenance mode is active")
    async def maintenance_status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if await self._reject_unauthorized(interaction):
            return

        window = maintenance.current()
        if window is None:
            embed = self._create_embed(
                "🛠️ Maintenance Status",
                "Maintenance mode is **not active**.\n\nUse `/maintenance start` to start it.",
                discord.Color.blurple(),
            )
        else:
            embed = self._window_embed(
                "🛠️ Maintenance Status", "Maintenance mode is **active**.", window
            )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Set up the Maintenance cog for the bot."""
    await bot.add_cog(Maintenance(bot))
