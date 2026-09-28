"""
Dashboard embed builder shared by both media server platforms.

Plex and Jellyfin render the same dashboard; the only platform-specific part is
which config block holds the library sections.
"""

import discord
import logging
from typing import Dict, Any, List
from datetime import datetime

from .formatters import embed_field_budget, format_number, join_within_limit

logger = logging.getLogger("mediawatch_bot.media_core.dashboard_service")

# The credential each platform rejects with HTTP 401/403. Keep in sync with
# PLATFORM_VARS in env_validation.py, which covers the "not set at all" case.
CREDENTIAL_VARS = {
    "plex": "PLEX_TOKEN",
    "jellyfin": "JELLYFIN_API_KEY",
}

# Discord accepts at most 25 fields per embed. Leave room for the streams and
# downloads block so a server with many libraries cannot break the update.
MAX_LIBRARY_FIELDS = 15


def calculate_total_download_size(downloads: List[Dict[str, Any]]) -> str:
    """Sum the sizes of the given downloads into a human-readable string.

    Args:
        downloads: List of download dictionaries as built by the SABnzbd cog

    Returns:
        Formatted total size string
    """
    units = {"KB": 1 / 1024, "MB": 1, "GB": 1024, "TB": 1024 * 1024}
    total_size_mb = 0.0

    for download in downloads:
        size = download.get("size", "Unknown")
        if size == "Unknown":
            continue
        try:
            value, unit = str(size).split()
            total_size_mb += float(value) * units.get(unit, 0)
        except (ValueError, AttributeError):
            continue

    if total_size_mb >= 1024:
        return f"{total_size_mb / 1024:.2f} GB"
    return f"{total_size_mb:.2f} MB"


class DashboardService:
    """Service for dashboard embed creation."""

    def __init__(self, bot, config: Dict[str, Any], platform: str = "plex"):
        """Initialize dashboard service.

        Args:
            bot: Discord bot instance (for get_cog access)
            config: Configuration dictionary
            platform: Active media server type ('plex' or 'jellyfin')
        """
        self.bot = bot
        self.config = config
        self.platform = platform
        self.logger = logger

    async def create_dashboard_embed(self, info: Dict[str, Any]) -> discord.Embed:
        """Create a dashboard embed reflecting server status.

        Args:
            info: Server information dictionary

        Returns:
            Discord Embed with dashboard information
        """
        dashboard_config = self.config["dashboard"]
        auth_failed = bool(info.get("auth_failed"))
        is_online = info["status"] == "🟢 Online"

        if auth_failed:
            title = "Server rejected the credentials! :no_entry:"
            color = discord.Color.orange()
        elif is_online:
            title = "Server is currently Online! :white_check_mark:"
            color = discord.Color.green()
        else:
            title = "Server is currently Offline! :warning:"
            color = discord.Color.red()

        embed = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())

        embed.set_author(name=dashboard_config["name"], icon_url=dashboard_config["icon_url"])
        embed.set_thumbnail(url=dashboard_config["icon_url"])
        embed.set_footer(text="Last updated", icon_url=dashboard_config["footer_icon_url"])

        if auth_failed:
            self._add_auth_failure_field(embed)
        elif is_online:
            await self._add_embed_fields(embed, info)
        else:
            self._add_offline_fields(embed, info)

        return embed

    def _add_auth_failure_field(self, embed: discord.Embed) -> None:
        """Explain a rejected token instead of blaming the media server.

        Without this the dashboard shows "Offline" for a wrong token and the
        user goes looking for the fault on the media server.
        """
        credential = CREDENTIAL_VARS.get(self.platform, "the media server credentials")
        embed.add_field(
            name="Authentication failed:",
            value=(
                "The server is reachable, but it rejected the credentials (HTTP 401/403).\n"
                f"Check **{credential}** in your `.env` file and restart the bot. "
                "The media server itself is not down."
            ),
            inline=False,
        )

    def _add_offline_fields(self, embed: discord.Embed, info: Dict[str, Any]) -> None:
        """Add fields to the dashboard embed when the server is unreachable."""
        offline_since_str, time_diff_str = "Unknown", "Unknown duration"
        if info.get("offline_since") and isinstance(info["offline_since"], datetime):
            offline_since_dt = info["offline_since"]
            offline_since_str = discord.utils.format_dt(offline_since_dt, style="f")
            time_diff_str = discord.utils.format_dt(offline_since_dt, style="R")
        embed.add_field(
            name="Offline since:",
            value=f"**Since:** {offline_since_str}\n**Duration:** {time_diff_str}",
            inline=False,
        )

        uptime_cog = self.bot.get_cog("Uptime")
        if uptime_cog and "uptime_24h" in info and info.get("uptime_24h") != "No data":
            embed.add_field(name="Uptime (24h)", value=f"```{info['uptime_24h']}```", inline=True)
            embed.add_field(
                name="Uptime (7 days)",
                value=f"```{info.get('uptime_7d', 'No data')}```",
                inline=True,
            )
            embed.add_field(
                name="Uptime (30 days)",
                value=f"```{info.get('uptime_30d', 'No data')}```",
                inline=True,
            )

    async def _add_embed_fields(self, embed: discord.Embed, info: Dict[str, Any]) -> None:
        """Add fields to the dashboard embed when server is online.

        Args:
            embed: Discord Embed to add fields to
            info: Server information dictionary
        """
        embed.add_field(name="Server Uptime 🖥️", value=f"```{info['uptime']}```", inline=True)
        embed.add_field(name="", value="", inline=True)  # Spacer
        embed.add_field(name="", value="", inline=True)  # Spacer

        stats = info["library_stats"]
        display_config = self.config.get("display", {})
        separator = display_config.get("thousands_separator", ".")
        episode_label = display_config.get("episode_label", "Episodes")
        platform_config = self.config.get(self.platform, {})
        configured_sections = platform_config.get("sections", {})

        # Configured sections keep their config order, everything else follows
        # in the order the media server reported it.
        sections_to_display = (
            configured_sections
            if not platform_config.get("show_all", True)
            else {**configured_sections, **{k: None for k in stats if k not in configured_sections}}
        )

        # Count fields added for library sections
        fields_added = 0
        sections_shown = 0
        sections_available = sum(1 for title in sections_to_display if title in stats)

        for title in sections_to_display:
            if title in stats and fields_added < MAX_LIBRARY_FIELDS:
                section_data = stats[title]
                display_name = f"{section_data['display_name']} {section_data['emoji']}"
                embed.add_field(
                    name=display_name,
                    value=f"```{format_number(section_data['count'], separator=separator)}```",
                    inline=True,
                )
                fields_added += 1
                sections_shown += 1

                if section_data.get("show_episodes") and fields_added < MAX_LIBRARY_FIELDS:
                    embed.add_field(
                        name=f"{section_data['display_name']} {episode_label} 📺",
                        value=f"```{format_number(section_data.get('episodes', 0), separator=separator)}```",
                        inline=True,
                    )
                    fields_added += 1

        # Add placeholder fields to complete the row (max 3 fields per row)
        remaining_fields = fields_added % 3
        if remaining_fields > 0:
            placeholders_needed = 3 - remaining_fields
            for _ in range(placeholders_needed):
                embed.add_field(name="\u200b", value="\u200b", inline=True)

        # Say so instead of silently dropping libraries: Discord caps an embed
        # at 25 fields, so a server with many sections would just show too few
        # tiles and send the user looking for the mistake in their config.
        # Placed after the row padding so it does not break the 3-per-row grid.
        if sections_shown < sections_available:
            embed.add_field(
                name=f"(showing {sections_shown} of {sections_available} libraries)",
                value="\u200b",
                inline=False,
            )

        if info["active_users"]:
            stream_count = len(info["active_users"])

            name = f"{stream_count} current Stream{'s' if stream_count != 1 else ''}:"
            # Reserve room for the downloads block that may follow.
            streams_text, shown = join_within_limit(
                info["active_users"][:8],
                limit=embed_field_budget(embed, name, reserve=600),
            )
            if shown < stream_count:
                name += f" (showing {shown} of {stream_count})"
            if streams_text:
                embed.add_field(name=name, value=streams_text, inline=False)
        else:
            embed.add_field(
                name="Current Streams:", value="💤 *No active streams currently*", inline=False
            )

        # SABnzbd Downloads Section - only show if SABnzbd is configured
        sabnzbd_cog = self.bot.get_cog("SABnzbd")
        download_info = info.get("downloads", {})

        # Only show SABnzbd section if it's configured
        if sabnzbd_cog and download_info.get("configured", False):
            if download_info.get("downloads"):
                # Active downloads
                downloads = download_info["downloads"][:4]
                download_count = len(download_info["downloads"])
                name = f"{download_count} current Download{'s' if download_count != 1 else ''}:"
                downloads_text, shown = join_within_limit(
                    [
                        sabnzbd_cog.format_download_info(download, i)
                        for i, download in enumerate(downloads)
                    ],
                    # Reserve room for the three size fields below.
                    limit=embed_field_budget(embed, name, reserve=200),
                )
                # Say so, like the streams field above. A queue of six behind a
                # header reading "6 current Downloads:" with four entries under
                # it reads like the section is broken.
                if shown < download_count:
                    name += f" (showing {shown} of {download_count})"
                if downloads_text:
                    embed.add_field(name=name, value=downloads_text, inline=False)
                embed.add_field(
                    name="Downloads 📥",
                    value=f"```{calculate_total_download_size(download_info['downloads'])}```",
                    inline=True,
                )
                embed.add_field(
                    name="Free Space 💾",
                    value=f"```{download_info.get('free_space', 'Unknown')}```",
                    inline=True,
                )
                embed.add_field(
                    name="Total Space 🗄️",
                    value=f"```{download_info.get('total_space', 'Unknown')}```",
                    inline=True,
                )
            elif download_info.get("show_when_empty", False):
                # No active downloads - only show if show_when_empty is True
                embed.add_field(
                    name="Current Downloads:",
                    value="💤 *No active downloads currently*",
                    inline=False,
                )
