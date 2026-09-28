"""
Embed helpers shared by both media server platforms.
"""

import discord
from typing import Any


def create_stream_error_embed(
    core: Any,
    description: str,
    *,
    platform_name: str,
    title: str = "❌ Stream Details Unavailable",
    footer_text: str = "",
) -> discord.Embed:
    """Create a styled error embed for stream detail failures.

    Args:
        core: The platform cog, used for its ``config``
        description: What went wrong, in a form the user can act on
        platform_name: "Plex" or "Jellyfin", used in the default labels
        title: Embed title
        footer_text: Footer text, defaults to "<platform> Stream Details"

    Returns:
        Discord Embed describing the failure
    """
    dashboard_config = core.config.get("dashboard", {})
    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow(),
    )
    embed.set_author(
        name=dashboard_config.get("name", f"{platform_name} Dashboard"),
        icon_url=dashboard_config.get("icon_url") or None,
    )
    embed.set_footer(
        text=footer_text or f"{platform_name} Stream Details",
        icon_url=dashboard_config.get("footer_icon_url") or None,
    )
    return embed
