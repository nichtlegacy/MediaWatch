"""
User Mapping Management Cog for MediaWatch.

Provides Discord slash commands to manage username to display name mappings
for both Plex and Jellyfin without requiring a bot restart.

Supports multi-platform format:
{
    "plex": {"PlexUser": "DisplayName"},
    "jellyfin": {"JellyfinUser": "DisplayName"}
}
"""

import discord
from discord import app_commands
from discord.ext import commands
import os
import json
import logging
from typing import Optional, Literal
from typing import List

import version
from cogs.media_core.shared.config_utils import get_current_platform, write_json_atomic
from cogs.media_core.shared.env_validation import parse_authorized_users


logger = logging.getLogger("mediawatch_bot.user_mapping")


class UserMapping(
    commands.GroupCog,
    group_name="mapping",
    group_description="Manage username to display name mappings for Plex/Jellyfin",
):
    """Manage username to display name mappings via Discord commands.

    Supports both Plex and Jellyfin platforms with platform-keyed storage.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger = logger

        # Setup paths
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.mapping_file = os.path.join(base_dir, "data", "user_mapping.json")

        # Load authorized users
        self.authorized_users = parse_authorized_users(os.getenv("DISCORD_AUTHORIZED_USERS"))

        # Ensure mapping file exists and migrate if needed
        self._ensure_mapping_file()
        self._migrate_flat_to_nested()

    def _ensure_mapping_file(self) -> None:
        """Ensure user_mapping.json exists. Create empty file if not."""
        if os.path.exists(self.mapping_file):
            return

        # Create empty mapping file with new nested structure
        self._save_mapping({"plex": {}, "jellyfin": {}})
        self.logger.info("Created empty user_mapping.json with multi-platform structure")

    def _migrate_flat_to_nested(self) -> None:
        """Migrate flat JSON format to platform-keyed nested format.

        Old format: {"PlexUser": "DisplayName"}
        New format: {"plex": {"PlexUser": "DisplayName"}, "jellyfin": {}}
        """
        if not os.path.exists(self.mapping_file):
            return

        try:
            with open(self.mapping_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Check if already in new format
            if "plex" in data or "jellyfin" in data:
                # Ensure both keys exist
                if "plex" not in data:
                    data["plex"] = {}
                if "jellyfin" not in data:
                    data["jellyfin"] = {}
                self._save_mapping(data)
                return

            # Migrate flat format to nested
            if data:
                self.logger.info("Migrating user_mapping.json from flat to nested format")
                new_data = {
                    "plex": data,  # Assume existing mappings are for Plex
                    "jellyfin": {},
                }
                self._save_mapping(new_data)
                self.logger.info(f"Migrated {len(data)} mappings to plex platform")
        except Exception as e:
            self.logger.error(f"Failed to migrate user_mapping.json: {e}")

    def _load_mapping(self, platform: Optional[str] = None) -> dict:
        """Load user mapping from JSON file.

        Args:
            platform: Optional platform to filter by ('plex' or 'jellyfin').
                     If None, returns the entire mapping structure.

        Returns:
            Dictionary of mappings (either full structure or platform-specific)
        """
        if not os.path.exists(self.mapping_file):
            return {} if platform else {"plex": {}, "jellyfin": {}}

        try:
            with open(self.mapping_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Ensure new format
            if "plex" not in data and "jellyfin" not in data:
                # Legacy format - return as-is for backward compatibility
                if platform == "plex":
                    return data
                return data

            if platform:
                return data.get(platform, {})
            return data
        except Exception as e:
            self.logger.error(f"Failed to load user_mapping.json: {e}")
            return {} if platform else {"plex": {}, "jellyfin": {}}

    def _save_mapping(self, mapping: dict) -> bool:
        """Save user mapping to JSON file atomically.

        A crash mid-write must not leave an empty or truncated mapping behind;
        write_json_atomic() writes a temp file and renames it into place.
        """
        try:
            write_json_atomic(self.mapping_file, mapping, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            self.logger.error(f"Failed to save user_mapping.json: {e}")
            return False

    def _update_media_core_mapping(self, platform: str, platform_mapping: dict) -> None:
        """Update the mapping in the appropriate media core cog for immediate effect.

        Args:
            platform: The platform ('plex' or 'jellyfin')
            platform_mapping: The mapping dict for that platform
        """
        if platform == "plex":
            plex_core = self.bot.get_cog("PlexCore")
            if plex_core:
                plex_core.user_mapping = platform_mapping
                if hasattr(plex_core, "plex_service"):
                    plex_core.plex_service.user_mapping = platform_mapping
                self.logger.info("PlexCore user_mapping updated")
        elif platform == "jellyfin":
            jellyfin_core = self.bot.get_cog("JellyfinCore")
            if jellyfin_core:
                # JellyfinCore.user_mapping uses flat format for backward compatibility
                jellyfin_core.user_mapping = platform_mapping
                if hasattr(jellyfin_core, "jellyfin_service"):
                    # Flat, like JellyfinCore.__init__ loads it.
                    jellyfin_core.jellyfin_service.user_mapping = platform_mapping
                self.logger.info("JellyfinCore user_mapping updated")

    def _is_authorized(self, user_id: int) -> bool:
        """Check if user is authorized to manage mappings."""
        return user_id in self.authorized_users

    def _create_embed(self, title: str, description: str, color: discord.Color) -> discord.Embed:
        """Create a standardized embed for responses."""
        embed = discord.Embed(
            title=title, description=description, color=color, timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f"{version.__project_name__} v{version.__version__}")
        if self.bot.user:
            embed.set_author(name="User Mapping Manager", icon_url=self.bot.user.display_avatar.url)
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        return embed

    @app_commands.command(
        name="add", description="Add a new user mapping (username → Display name)"
    )
    @app_commands.describe(
        platform="The media server platform (plex or jellyfin)",
        username="The exact username (case-sensitive)",
        display_name="The name to display in the dashboard",
    )
    async def mapping_add(
        self,
        interaction: discord.Interaction,
        platform: Literal["plex", "jellyfin"],
        username: str,
        display_name: str,
    ) -> None:
        """Add a new user mapping."""
        await interaction.response.defer(ephemeral=True)

        if not self._is_authorized(interaction.user.id):
            embed = self._create_embed(
                "❌ Not Authorized",
                "You are not authorized to manage user mappings.",
                discord.Color.red(),
            )
            await interaction.followup.send(embed=embed)
            return

        full_mapping = self._load_mapping()
        platform_mapping = full_mapping.get(platform, {})

        if username in platform_mapping:
            embed = self._create_embed(
                "⚠️ Already Exists",
                f"Mapping for `{username}` ({platform}) already exists.\n"
                f"Current display name: **{platform_mapping[username]}**\n\n"
                f"Use `/mapping edit` to change it.",
                discord.Color.orange(),
            )
            await interaction.followup.send(embed=embed)
            return

        platform_mapping[username] = display_name
        full_mapping[platform] = platform_mapping

        if self._save_mapping(full_mapping):
            self._update_media_core_mapping(platform, platform_mapping)
            embed = self._create_embed(
                "✅ Mapping Added",
                f"**Platform:** {platform.title()}\n"
                f"`{username}` → **{display_name}**\n\n"
                f"Total {platform} mappings: {len(platform_mapping)}",
                discord.Color.green(),
            )
            self.logger.info(
                f"User {interaction.user} added mapping: {platform}/{username} -> {display_name}"
            )
        else:
            embed = self._create_embed(
                "❌ Error", "Failed to save mapping. Check logs for details.", discord.Color.red()
            )

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="remove", description="Remove an existing user mapping")
    @app_commands.describe(
        platform="The media server platform (plex or jellyfin)", username="The username to remove"
    )
    async def mapping_remove(
        self, interaction: discord.Interaction, platform: Literal["plex", "jellyfin"], username: str
    ) -> None:
        """Remove a user mapping."""
        await interaction.response.defer(ephemeral=True)

        if not self._is_authorized(interaction.user.id):
            embed = self._create_embed(
                "❌ Not Authorized",
                "You are not authorized to manage user mappings.",
                discord.Color.red(),
            )
            await interaction.followup.send(embed=embed)
            return

        full_mapping = self._load_mapping()
        platform_mapping = full_mapping.get(platform, {})

        if username not in platform_mapping:
            embed = self._create_embed(
                "⚠️ Not Found",
                f"No mapping found for `{username}` ({platform}).\n\n"
                f"Use `/mapping list` to see all mappings.",
                discord.Color.orange(),
            )
            await interaction.followup.send(embed=embed)
            return

        old_display = platform_mapping.pop(username)
        full_mapping[platform] = platform_mapping

        if self._save_mapping(full_mapping):
            self._update_media_core_mapping(platform, platform_mapping)
            embed = self._create_embed(
                "✅ Mapping Removed",
                f"**Platform:** {platform.title()}\n"
                f"Removed: `{username}` → ~~{old_display}~~\n\n"
                f"Remaining {platform} mappings: {len(platform_mapping)}",
                discord.Color.green(),
            )
            self.logger.info(f"User {interaction.user} removed mapping: {platform}/{username}")
        else:
            embed = self._create_embed(
                "❌ Error", "Failed to save changes. Check logs for details.", discord.Color.red()
            )

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="edit", description="Edit an existing user mapping's display name")
    @app_commands.describe(
        platform="The media server platform (plex or jellyfin)",
        username="The username to edit",
        new_display_name="The new display name",
    )
    async def mapping_edit(
        self,
        interaction: discord.Interaction,
        platform: Literal["plex", "jellyfin"],
        username: str,
        new_display_name: str,
    ) -> None:
        """Edit an existing user mapping."""
        await interaction.response.defer(ephemeral=True)

        if not self._is_authorized(interaction.user.id):
            embed = self._create_embed(
                "❌ Not Authorized",
                "You are not authorized to manage user mappings.",
                discord.Color.red(),
            )
            await interaction.followup.send(embed=embed)
            return

        full_mapping = self._load_mapping()
        platform_mapping = full_mapping.get(platform, {})

        if username not in platform_mapping:
            embed = self._create_embed(
                "⚠️ Not Found",
                f"No mapping found for `{username}` ({platform}).\n\n"
                f"Use `/mapping add` to create a new mapping.",
                discord.Color.orange(),
            )
            await interaction.followup.send(embed=embed)
            return

        old_display = platform_mapping[username]
        platform_mapping[username] = new_display_name
        full_mapping[platform] = platform_mapping

        if self._save_mapping(full_mapping):
            self._update_media_core_mapping(platform, platform_mapping)
            embed = self._create_embed(
                "✅ Mapping Updated",
                f"**Platform:** {platform.title()}\n"
                f"`{username}`\n"
                f"~~{old_display}~~ → **{new_display_name}**",
                discord.Color.green(),
            )
            self.logger.info(
                f"User {interaction.user} edited mapping: {platform}/{username} -> {new_display_name}"
            )
        else:
            embed = self._create_embed(
                "❌ Error", "Failed to save changes. Check logs for details.", discord.Color.red()
            )

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="list", description="Show all user mappings")
    @app_commands.describe(platform="Filter by platform (optional, defaults to current platform)")
    async def mapping_list(
        self,
        interaction: discord.Interaction,
        platform: Optional[Literal["plex", "jellyfin", "all"]] = None,
    ) -> None:
        """List all user mappings."""
        await interaction.response.defer(ephemeral=True)

        if not self._is_authorized(interaction.user.id):
            embed = self._create_embed(
                "❌ Not Authorized",
                "You are not authorized to view user mappings.",
                discord.Color.red(),
            )
            await interaction.followup.send(embed=embed)
            return

        full_mapping = self._load_mapping()

        # Default to current platform if not specified
        if platform is None:
            platform = get_current_platform()

        if platform == "all":
            # Show all platforms
            lines = []
            total_count = 0

            for plat in ["plex", "jellyfin"]:
                plat_mapping = full_mapping.get(plat, {})
                if plat_mapping:
                    lines.append(f"\n**{plat.title()}** ({len(plat_mapping)} mappings):")
                    sorted_mappings = sorted(plat_mapping.items(), key=lambda x: x[0].lower())
                    for user, display_name in sorted_mappings:
                        lines.append(f"`{user}` → **{display_name}**")
                    total_count += len(plat_mapping)

            if not lines:
                embed = self._create_embed(
                    "👥 User Mappings",
                    "No mappings configured.\n\nUse `/mapping add` to add your first mapping.",
                    discord.Color.blurple(),
                )
                await interaction.followup.send(embed=embed)
                return

            description = "\n".join(lines)
            if len(description) > 4000:
                description = description[:4000] + "\n\n*...truncated*"

            embed = self._create_embed(
                "👥 User Mappings (All Platforms)", description, discord.Color.blurple()
            )
            embed.add_field(name="Total Mappings", value=str(total_count), inline=True)
        else:
            # Show specific platform
            platform_mapping = full_mapping.get(platform, {})

            if not platform_mapping:
                embed = self._create_embed(
                    f"👥 User Mappings ({platform.title()})",
                    f"No mappings configured for {platform}.\n\n"
                    f"Use `/mapping add` to add your first mapping.",
                    discord.Color.blurple(),
                )
                await interaction.followup.send(embed=embed)
                return

            sorted_mappings = sorted(platform_mapping.items(), key=lambda x: x[0].lower())
            lines = [f"`{user}` → **{display_name}**" for user, display_name in sorted_mappings]

            description = "\n".join(lines)
            if len(description) > 4000:
                description = description[:4000] + "\n\n*...truncated*"

            embed = self._create_embed(
                f"👥 User Mappings ({platform.title()})", description, discord.Color.blurple()
            )
            embed.add_field(name="Total Mappings", value=str(len(platform_mapping)), inline=True)

        await interaction.followup.send(embed=embed)

    # Autocomplete for remove and edit commands
    @mapping_remove.autocomplete("username")
    @mapping_edit.autocomplete("username")
    async def username_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete for usernames based on selected platform."""
        # Autocomplete fires before the command runs, so it needs the same
        # authorization check - otherwise it leaks every mapping via the dropdown.
        if not self._is_authorized(interaction.user.id):
            return []

        # Get the platform from the interaction options
        platform = None
        if interaction.namespace:
            platform = getattr(interaction.namespace, "platform", None)

        # Default to current platform if not specified
        if not platform:
            platform = get_current_platform()

        full_mapping = self._load_mapping()
        platform_mapping = full_mapping.get(platform, {})
        choices = []

        for user in platform_mapping:
            if current.lower() in user.lower():
                display = platform_mapping[user]
                label = f"{user} ({display})"
                if len(label) > 100:
                    label = label[:97] + "..."
                choices.append(app_commands.Choice(name=label, value=user))

        return choices[:25]  # Discord limit


async def setup(bot: commands.Bot) -> None:
    """Set up the UserMapping cog for the bot."""
    await bot.add_cog(UserMapping(bot))
