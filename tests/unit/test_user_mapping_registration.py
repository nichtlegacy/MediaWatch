from discord.ext import commands

from cogs.user_mapping import UserMapping


def test_user_mapping_uses_group_cog_with_expected_group_metadata():
    assert issubclass(UserMapping, commands.GroupCog)
    assert UserMapping.__cog_group_name__ == "mapping"
    assert (
        UserMapping.__cog_group_description__
        == "Manage username to display name mappings for Plex/Jellyfin"
    )


def test_user_mapping_registers_expected_subcommands():
    command_names = sorted(command.name for command in UserMapping.__cog_app_commands__)

    assert command_names == ["add", "edit", "list", "remove"]
