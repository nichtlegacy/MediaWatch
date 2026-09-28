"""Regression tests for how MediaWatch publishes its application commands.

These assert the state of the local command tree, not just that a helper was
called - both bugs they cover looked correct at call level and only showed up
in what the tree contained afterwards.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from discord import app_commands


def _tree_command_names(tree, guild=None):
    return sorted(command.name for command in tree.get_commands(guild=guild))


def _install_fake_http(main, monkeypatch):
    """Replace the bot's HTTP layer so no request leaves the test process."""
    bulk_upsert = AsyncMock(return_value=[])
    monkeypatch.setattr(
        main.bot, "_connection", SimpleNamespace(application_id=4242), raising=False
    )
    monkeypatch.setattr(main.bot, "http", SimpleNamespace(bulk_upsert_global_commands=bulk_upsert))
    return bulk_upsert


@pytest.mark.asyncio
async def test_clearing_global_scope_keeps_the_local_commands(import_main_module, monkeypatch):
    """R1: after the startup cleanup the bot must still know its own commands.

    The old implementation called `tree.clear_commands(guild=None)`, which wiped
    the in-process tree as well. A later `!sync clear` then emptied the guild
    container too and left the bot without a single slash command.
    """
    main = import_main_module()
    guild = discord.Object(id=99)
    bulk_upsert = _install_fake_http(main, monkeypatch)
    monkeypatch.setattr(main.tree, "sync", AsyncMock(return_value=[]))

    before = _tree_command_names(main.tree)
    assert before, "expected main.py to register slash commands at import time"

    # Startup: publish into the guild, then unregister the 1.x global commands.
    await main.sync_command_tree(guild=guild)
    await main.sync_command_tree(clear_global_commands=True)

    bulk_upsert.assert_awaited_once_with(4242, [])
    assert _tree_command_names(main.tree) == before

    # `!sync clear` empties the guild scope; the global container must survive it
    # so `!sync copy` can restore the commands without a restart.
    await main.sync_command_tree(guild=guild, clear_guild_commands=True)
    assert _tree_command_names(main.tree) == before

    await main.sync_command_tree(guild=guild)
    assert _tree_command_names(main.tree, guild=guild) == before


@pytest.mark.asyncio
async def test_guild_sync_mirrors_commands_added_and_removed_after_startup(
    import_main_module, monkeypatch
):
    """R2: `!sync guild` must publish the current tree, not the startup snapshot.

    Cogs register into the global container, so a guild sync that skips the copy
    pushed a stale snapshot: `/load` never made a command appear and `/unload`
    never made one disappear.
    """
    main = import_main_module()
    guild = discord.Object(id=99)
    monkeypatch.setattr(main.tree, "sync", AsyncMock(return_value=[]))

    # Startup snapshot.
    await main.sync_command_tree(guild=guild)
    baseline = _tree_command_names(main.tree, guild=guild)

    # A cog loaded at runtime registers globally, like commands.GroupCog does.
    @app_commands.command(name="mapping", description="added by a cog")
    async def mapping(interaction: discord.Interaction) -> None:  # pragma: no cover
        pass

    main.tree.add_command(mapping)
    await main.sync_command_tree(guild=guild)
    assert "mapping" in _tree_command_names(main.tree, guild=guild)

    # ... and unloading it has to remove it from the guild scope again.
    main.tree.remove_command("mapping")
    await main.sync_command_tree(guild=guild)
    assert _tree_command_names(main.tree, guild=guild) == baseline


def test_command_sync_hint_names_a_scope_that_publishes_cog_commands(import_main_module):
    """R2: the hint shown by /load, /unload and /reload must name a working scope."""
    main = import_main_module()
    hint = main._command_sync_hint()

    assert "!sync guild" in hint or "!sync copy" in hint


@pytest.mark.asyncio
async def test_setup_hook_survives_a_non_http_failure(import_main_module, monkeypatch):
    """R3: setup_hook runs inside login(), so nothing may escape it.

    Only `discord.HTTPException` used to be caught, but a `data/` the container
    cannot write to made `mark_global_commands_cleared()` raise `PermissionError`
    - and the bot never came online again, on every restart.
    """
    main = import_main_module()

    monkeypatch.setattr(main, "load_cogs", AsyncMock())
    monkeypatch.setattr(main, "get_command_guild", lambda: discord.Object(id=42))
    monkeypatch.setattr(main, "sync_command_tree", AsyncMock())
    monkeypatch.setattr(
        main,
        "clear_stale_global_commands",
        AsyncMock(side_effect=PermissionError("data/ is not writable")),
    )
    main.cogs_loaded = False

    bot = main.MediaWatchBot(command_prefix="!", intents=discord.Intents.none())

    await bot.setup_hook()
