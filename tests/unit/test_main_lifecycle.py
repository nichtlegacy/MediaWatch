from discord.ext import commands
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.mark.asyncio
async def test_mediawatch_bot_close_calls_sync_and_async_cog_shutdown(
    import_main_module, monkeypatch
):
    main = import_main_module()
    shutdown_calls = []

    async def fake_super_close(self):
        shutdown_calls.append("super-close")

    monkeypatch.setattr(main.commands.Bot, "close", fake_super_close)

    bot = main.MediaWatchBot(command_prefix="!", intents=main.discord.Intents.none())

    class AsyncShutdownCog(commands.Cog):
        async def shutdown(self):
            shutdown_calls.append("async-shutdown")

    class SyncShutdownCog(commands.Cog):
        def shutdown(self):
            shutdown_calls.append("sync-shutdown")

    class PassiveCog(commands.Cog):
        pass

    await bot.add_cog(AsyncShutdownCog())
    await bot.add_cog(SyncShutdownCog())
    await bot.add_cog(PassiveCog())

    await bot.close()

    assert shutdown_calls == ["async-shutdown", "sync-shutdown", "super-close"]


def test_resolve_extension_name_uses_active_media_core_extension(import_main_module, monkeypatch):
    main = import_main_module()
    fake_bot = SimpleNamespace(extensions={"cogs.media_core.jellyfin": object()})

    monkeypatch.setattr(main, "bot", fake_bot)
    monkeypatch.setattr(main, "get_media_server_type", lambda: "plex")

    assert main.resolve_extension_name("media_core") == "cogs.media_core.jellyfin"
    assert (
        main.resolve_extension_name("media_core", prefer_configured_media_core=True)
        == "cogs.media_core.plex"
    )
    assert main.get_cog_display_name("media_core") == "Media Core (Jellyfin)"
    assert main.is_cog_loaded("media_core")


@pytest.mark.asyncio
async def test_reload_runtime_config_switches_media_core_and_reloads_sabnzbd(
    import_main_module, monkeypatch, tmp_path
):
    main = import_main_module()
    monkeypatch.setattr(main, "get_config_path", lambda: str(tmp_path / "config.yaml"))
    calls = []

    class FakeBot:
        def __init__(self):
            self.extensions = {
                "cogs.media_core.plex": object(),
                "cogs.sabnzbd": object(),
            }

        async def unload_extension(self, extension_name):
            calls.append(("unload", extension_name))
            self.extensions.pop(extension_name, None)

        async def load_extension(self, extension_name):
            calls.append(("load", extension_name))
            self.extensions[extension_name] = object()

        async def reload_extension(self, extension_name):
            calls.append(("reload", extension_name))

    fake_bot = FakeBot()
    monkeypatch.setattr(main, "bot", fake_bot)
    monkeypatch.setattr(main, "get_media_server_type", lambda: "jellyfin")

    actions = await main.reload_runtime_config()

    assert actions == [
        "unloaded `cogs.media_core.plex`",
        "loaded `cogs.media_core.jellyfin`",
        "reloaded `cogs.sabnzbd`",
    ]
    assert calls == [
        ("unload", "cogs.media_core.plex"),
        ("load", "cogs.media_core.jellyfin"),
        ("reload", "cogs.sabnzbd"),
    ]


@pytest.mark.asyncio
async def test_reload_runtime_config_restores_previous_media_core_on_failure(
    import_main_module, monkeypatch, tmp_path
):
    main = import_main_module()
    monkeypatch.setattr(main, "get_config_path", lambda: str(tmp_path / "config.yaml"))
    calls = []

    class FakeBot:
        def __init__(self):
            self.extensions = {
                "cogs.media_core.plex": object(),
            }

        async def unload_extension(self, extension_name):
            calls.append(("unload", extension_name))
            self.extensions.pop(extension_name, None)

        async def load_extension(self, extension_name):
            calls.append(("load", extension_name))
            if extension_name == "cogs.media_core.jellyfin":
                raise RuntimeError("boom")
            self.extensions[extension_name] = object()

        async def reload_extension(self, extension_name):
            calls.append(("reload", extension_name))

    fake_bot = FakeBot()
    monkeypatch.setattr(main, "bot", fake_bot)
    monkeypatch.setattr(main, "get_media_server_type", lambda: "jellyfin")

    with pytest.raises(RuntimeError, match="boom"):
        await main.reload_runtime_config()

    assert calls == [
        ("unload", "cogs.media_core.plex"),
        ("load", "cogs.media_core.jellyfin"),
        ("load", "cogs.media_core.plex"),
    ]
    assert "cogs.media_core.plex" in fake_bot.extensions


@pytest.mark.asyncio
async def test_sync_command_tree_updates_flag_and_calls_tree_sync(import_main_module, monkeypatch):
    main = import_main_module()
    sync_mock = AsyncMock()
    copy_mock = Mock()
    clear_mock = Mock()

    monkeypatch.setattr(
        main,
        "tree",
        SimpleNamespace(sync=sync_mock, copy_global_to=copy_mock, clear_commands=clear_mock),
    )
    main.commands_synced = False

    await main.sync_command_tree()

    sync_mock.assert_awaited_once_with(guild=None)
    copy_mock.assert_not_called()
    clear_mock.assert_not_called()
    assert main.commands_synced is True


class _FakeResponse:
    async def defer(self, ephemeral=False):
        self.ephemeral = ephemeral


class _FakeFollowup:
    def __init__(self):
        self.messages = []

    async def send(self, *args, **kwargs):
        self.messages.append((args, kwargs))


class _FakeInteraction:
    def __init__(self, user_id=123):
        self.user = SimpleNamespace(id=user_id)
        self.response = _FakeResponse()
        self.followup = _FakeFollowup()


@pytest.mark.asyncio
async def test_setup_hook_loads_cogs_without_sync_by_default(import_main_module, monkeypatch):
    main = import_main_module()
    load_cogs_mock = AsyncMock()
    sync_mock = AsyncMock()

    monkeypatch.setattr(main, "load_cogs", load_cogs_mock)
    monkeypatch.setattr(main, "sync_command_tree", sync_mock)
    monkeypatch.setattr(main, "get_command_guild", lambda: None)
    main.cogs_loaded = False

    bot = main.MediaWatchBot(command_prefix="!", intents=main.discord.Intents.none())
    await bot.setup_hook()

    load_cogs_mock.assert_awaited_once_with()
    sync_mock.assert_not_called()
    assert main.cogs_loaded is True


@pytest.mark.asyncio
async def test_setup_hook_syncs_configured_guild(import_main_module, monkeypatch):
    main = import_main_module()
    load_cogs_mock = AsyncMock()
    sync_mock = AsyncMock()
    clear_mock = AsyncMock()
    guild = main.discord.Object(id=42)

    monkeypatch.setattr(main, "load_cogs", load_cogs_mock)
    monkeypatch.setattr(main, "sync_command_tree", sync_mock)
    monkeypatch.setattr(main, "clear_stale_global_commands", clear_mock)
    monkeypatch.setattr(main, "get_command_guild", lambda: guild)
    main.cogs_loaded = False

    bot = main.MediaWatchBot(command_prefix="!", intents=main.discord.Intents.none())
    await bot.setup_hook()

    load_cogs_mock.assert_awaited_once_with()
    sync_mock.assert_awaited_once_with(guild=guild)
    # Guild sync first, then drop the 1.x global registrations.
    clear_mock.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_clear_stale_global_commands_runs_once_and_persists(
    import_main_module, monkeypatch, tmp_path
):
    main = import_main_module()
    sync_mock = AsyncMock()

    monkeypatch.setattr(main, "sync_command_tree", sync_mock)
    monkeypatch.setattr(
        main.runtime_state, "get_runtime_state_path", lambda: tmp_path / "runtime_state.json"
    )

    assert await main.clear_stale_global_commands() is True
    sync_mock.assert_awaited_once_with(clear_global_commands=True)

    # Second start must not spend another API call on it.
    assert await main.clear_stale_global_commands() is False
    assert sync_mock.await_count == 1


@pytest.mark.asyncio
async def test_clear_stale_global_commands_is_not_marked_done_when_sync_fails(
    import_main_module, monkeypatch, tmp_path
):
    main = import_main_module()
    state_file = tmp_path / "runtime_state.json"

    monkeypatch.setattr(main, "sync_command_tree", AsyncMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(main.runtime_state, "get_runtime_state_path", lambda: state_file)

    with pytest.raises(RuntimeError):
        await main.clear_stale_global_commands()

    assert not state_file.exists()
    assert main.runtime_state.global_commands_cleared() is False


@pytest.mark.asyncio
async def test_sync_command_tree_clears_global_scope(import_main_module, monkeypatch):
    main = import_main_module()
    sync_mock = AsyncMock(return_value=[])
    clear_mock = Mock()
    bulk_upsert_mock = AsyncMock(return_value=[])

    monkeypatch.setattr(
        main,
        "tree",
        SimpleNamespace(sync=sync_mock, copy_global_to=Mock(), clear_commands=clear_mock),
    )
    monkeypatch.setattr(
        main.bot, "_connection", SimpleNamespace(application_id=4242), raising=False
    )
    monkeypatch.setattr(
        main.bot, "http", SimpleNamespace(bulk_upsert_global_commands=bulk_upsert_mock)
    )

    await main.sync_command_tree(clear_global_commands=True)

    # Only the registration at Discord is dropped - clearing the local tree
    # would leave the bot without commands after a later `!sync clear`.
    bulk_upsert_mock.assert_awaited_once_with(4242, [])
    clear_mock.assert_not_called()
    sync_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_command_tree_rejects_global_clear_with_guild_target(import_main_module):
    main = import_main_module()

    with pytest.raises(ValueError):
        await main.sync_command_tree(guild=main.discord.Object(id=1), clear_global_commands=True)


@pytest.mark.asyncio
async def test_sync_prefix_command_clears_global_commands(import_main_module, monkeypatch):
    main = import_main_module()
    ctx = _FakeContext()
    sync_mock = AsyncMock(return_value=[])

    monkeypatch.setattr(main, "sync_command_tree", sync_mock)

    await main.sync_prefix_command.callback(ctx, "clearglobal")

    sync_mock.assert_awaited_once_with(clear_global_commands=True)
    assert ctx.messages == [
        "Cleared globally registered commands and synced the empty global tree."
    ]


@pytest.mark.asyncio
async def test_load_command_does_not_resync_tree_after_success(import_main_module, monkeypatch):
    main = import_main_module()
    interaction = _FakeInteraction()
    sync_mock = AsyncMock()

    class FakeBot:
        def __init__(self):
            self.extensions = {}
            self.user = None

        async def load_extension(self, extension_name):
            self.extensions[extension_name] = object()

    fake_bot = FakeBot()
    monkeypatch.setattr(main, "bot", fake_bot)
    monkeypatch.setattr(main, "sync_command_tree", sync_mock)

    await main.load.callback(interaction, "user_mapping")

    assert "cogs.user_mapping" in fake_bot.extensions
    sync_mock.assert_not_called()
    assert interaction.followup.messages
    embed = interaction.followup.messages[0][1]["embed"]
    assert "!sync guild" in embed.description


@pytest.mark.asyncio
async def test_unload_command_does_not_resync_tree_after_success(import_main_module, monkeypatch):
    main = import_main_module()
    interaction = _FakeInteraction()
    sync_mock = AsyncMock()

    class FakeBot:
        def __init__(self):
            self.extensions = {"cogs.user_mapping": object()}
            self.user = None

        async def unload_extension(self, extension_name):
            self.extensions.pop(extension_name, None)

    fake_bot = FakeBot()
    monkeypatch.setattr(main, "bot", fake_bot)
    monkeypatch.setattr(main, "sync_command_tree", sync_mock)

    await main.unload.callback(interaction, "user_mapping")

    assert "cogs.user_mapping" not in fake_bot.extensions
    sync_mock.assert_not_called()
    assert interaction.followup.messages


@pytest.mark.asyncio
async def test_reload_command_does_not_resync_tree_after_success(import_main_module, monkeypatch):
    main = import_main_module()
    interaction = _FakeInteraction()
    sync_mock = AsyncMock()
    reload_mock = AsyncMock()

    class FakeBot:
        def __init__(self):
            self.extensions = {"cogs.user_mapping": object()}
            self.user = None

        async def reload_extension(self, extension_name):
            await reload_mock(extension_name)

    fake_bot = FakeBot()
    monkeypatch.setattr(main, "bot", fake_bot)
    monkeypatch.setattr(main, "sync_command_tree", sync_mock)

    await main.reload.callback(interaction, "user_mapping")

    reload_mock.assert_awaited_once_with("cogs.user_mapping")
    sync_mock.assert_not_called()
    assert interaction.followup.messages


@pytest.mark.asyncio
async def test_reload_config_does_not_resync_tree_after_success(import_main_module, monkeypatch):
    main = import_main_module()
    interaction = _FakeInteraction()
    sync_mock = AsyncMock()
    reload_runtime_mock = AsyncMock(return_value=["reloaded `cogs.sabnzbd`"])

    monkeypatch.setattr(main, "sync_command_tree", sync_mock)
    monkeypatch.setattr(main, "reload_runtime_config", reload_runtime_mock)

    await main.reload_config.callback(interaction)

    reload_runtime_mock.assert_awaited_once_with()
    sync_mock.assert_not_called()
    assert interaction.followup.messages


async def test_reload_runtime_config_rejects_broken_yaml_before_touching_cogs(
    import_main_module, monkeypatch, tmp_path
):
    main = import_main_module()
    config_file = tmp_path / "config.yaml"
    config_file.write_text("media_server:\n  type: jellyfin\n  bad: [\n", encoding="utf-8")
    fake_bot = SimpleNamespace(
        extensions={"cogs.media_core.jellyfin": object()},
        reload_extension=AsyncMock(),
        load_extension=AsyncMock(),
        unload_extension=AsyncMock(),
    )
    monkeypatch.setattr(main, "bot", fake_bot)
    monkeypatch.setattr(main, "get_config_path", lambda: str(config_file))

    with pytest.raises(main.ConfigError, match="is not valid YAML at line"):
        await main.reload_runtime_config()

    fake_bot.reload_extension.assert_not_called()
    fake_bot.load_extension.assert_not_called()
    fake_bot.unload_extension.assert_not_called()


@pytest.mark.asyncio
async def test_reload_config_reports_a_rejected_config(import_main_module, monkeypatch):
    main = import_main_module()
    interaction = _FakeInteraction()
    monkeypatch.setattr(
        main,
        "reload_runtime_config",
        AsyncMock(side_effect=main.ConfigError("config.yaml is not valid YAML")),
    )

    await main.reload_config.callback(interaction)

    ((_, kwargs),) = interaction.followup.messages
    description = kwargs["embed"].description
    assert description.startswith("❌ Config not reloaded, the running configuration is unchanged.")
    assert "config.yaml is not valid YAML" in description


def test_ensure_config_usable_stops_the_bot_on_a_broken_file(
    import_main_module, monkeypatch, tmp_path
):
    main = import_main_module()
    config_file = tmp_path / "config.yaml"
    config_file.write_text("- just\n- a list\n", encoding="utf-8")
    monkeypatch.setattr(main, "get_config_path", lambda: str(config_file))

    with pytest.raises(SystemExit) as exc:
        main.ensure_config_usable()

    assert str(exc.value).startswith(f"Bot stopped: {config_file} must contain")


def test_ensure_config_usable_accepts_a_missing_file(import_main_module, monkeypatch, tmp_path):
    main = import_main_module()
    monkeypatch.setattr(main, "get_config_path", lambda: str(tmp_path / "config.yaml"))

    main.ensure_config_usable()


class _FakeContext:
    def __init__(self, author_id=123, guild_id=999):
        self.author = SimpleNamespace(id=author_id)
        self.guild = None if guild_id is None else SimpleNamespace(id=guild_id)
        self.messages = []

    async def send(self, message):
        self.messages.append(message)


@pytest.mark.asyncio
async def test_bare_sync_publishes_to_the_guild_not_globally(import_main_module, monkeypatch):
    """A global sync next to the guild copies would show every command twice."""
    main = import_main_module()
    ctx = _FakeContext(guild_id=77)
    sync_mock = AsyncMock(return_value=["one", "two"])

    monkeypatch.setattr(main, "sync_command_tree", sync_mock)

    await main.sync_prefix_command.callback(ctx, None)

    sync_mock.assert_awaited_once_with(guild=ctx.guild)
    assert ctx.messages == ["Synced 2 commands to guild `77`."]


@pytest.mark.asyncio
async def test_bare_sync_in_a_dm_publishes_nothing(import_main_module, monkeypatch):
    main = import_main_module()
    ctx = _FakeContext(guild_id=None)
    sync_mock = AsyncMock(return_value=[])

    monkeypatch.setattr(main, "sync_command_tree", sync_mock)

    await main.sync_prefix_command.callback(ctx, None)

    sync_mock.assert_not_awaited()
    assert ctx.messages == ["❌ `guild` sync requires running this command inside a server."]


@pytest.mark.asyncio
async def test_sync_prefix_command_syncs_current_guild(import_main_module, monkeypatch):
    main = import_main_module()
    ctx = _FakeContext(guild_id=77)
    sync_mock = AsyncMock(return_value=["one"])

    monkeypatch.setattr(main, "sync_command_tree", sync_mock)

    await main.sync_prefix_command.callback(ctx, "guild")

    sync_mock.assert_awaited_once_with(guild=ctx.guild)
    assert ctx.messages == ["Synced 1 commands to guild `77`."]


def test_bot_requests_only_message_content_privileged_intent(import_main_module):
    main = import_main_module()

    assert main.intents.message_content is True
    assert main.intents.members is False
    assert main.intents.presences is False


def test_importing_main_writes_no_log_file_and_leaks_no_dotenv(import_main_module, monkeypatch):
    """Importing `main` must stay free of side effects on the developer's box.

    19 tests re-import `main`; each one used to attach another
    TimedRotatingFileHandler to the real logs/ directory, and `load_dotenv()`
    pushed a real PLEX_TOKEN/CHANNEL_ID into os.environ for the whole session.
    """
    import dotenv

    dotenv_calls = []
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: dotenv_calls.append(a))

    main = import_main_module()

    assert dotenv_calls == []
    assert not any(
        isinstance(handler, TimedRotatingFileHandler)
        for handler in logging.getLogger("mediawatch_bot").handlers
    ), "main attached a file handler; the suite would write into the real log"
    assert main.RUNNING_IN_DOCKER is True


@pytest.mark.asyncio
async def test_load_cogs_loads_every_cog_plus_the_configured_media_core(
    import_main_module, monkeypatch, tmp_path
):
    main = import_main_module()

    class FakeBot:
        def __init__(self):
            self.extensions = {}

        async def load_extension(self, name):
            self.extensions[name] = object()

    fake_bot = FakeBot()
    monkeypatch.setattr(main, "bot", fake_bot)
    monkeypatch.setattr(main, "get_media_server_type", lambda: "jellyfin")
    # load_cogs() reads "./cogs", so it only works from the project root.
    monkeypatch.chdir(Path(main.__file__).parent)

    await main.load_cogs()

    assert set(fake_bot.extensions) == {
        "cogs.sabnzbd",
        "cogs.uptime",
        "cogs.user_mapping",
        "cogs.media_core.jellyfin",
    }


@pytest.mark.asyncio
async def test_load_cogs_keeps_going_when_one_extension_fails(import_main_module, monkeypatch):
    main = import_main_module()

    class FakeBot:
        def __init__(self):
            self.extensions = {}

        async def load_extension(self, name):
            if name == "cogs.sabnzbd":
                raise commands.ExtensionFailed(name, ValueError("boom"))
            self.extensions[name] = object()

    fake_bot = FakeBot()
    monkeypatch.setattr(main, "bot", fake_bot)
    monkeypatch.setattr(main, "get_media_server_type", lambda: "plex")
    monkeypatch.chdir(Path(main.__file__).parent)

    await main.load_cogs()

    assert "cogs.sabnzbd" not in fake_bot.extensions
    assert "cogs.uptime" in fake_bot.extensions
    assert "cogs.media_core.plex" in fake_bot.extensions


@pytest.mark.asyncio
async def test_load_cogs_finds_the_cogs_from_any_working_directory(
    import_main_module, monkeypatch, tmp_path
):
    """load_cogs() only logs failures, so a wrong CWD used to be silent.

    os.listdir("./cogs") resolved against the working directory: started as
    `python /path/to/main.py` from somewhere else, the bot came up with zero
    cogs, no dashboard and nothing in the log that named the cause. Docker hid
    it because the image sets WORKDIR.
    """
    main = import_main_module()
    monkeypatch.chdir(tmp_path)

    loaded = []

    async def fake_load_extension(name):
        loaded.append(name)

    monkeypatch.setattr(main.bot, "load_extension", fake_load_extension)
    monkeypatch.setattr(main.bot, "_BotBase__extensions", {}, raising=False)
    monkeypatch.setattr(main, "get_media_server_type", lambda: "plex")

    await main.load_cogs()

    assert "cogs.media_core.plex" in loaded
    assert "cogs.user_mapping" in loaded
    # The platform that is not configured must stay unloaded.
    assert "cogs.media_core.jellyfin" not in loaded


@pytest.mark.asyncio
async def test_load_cogs_loads_the_configured_platform_only(
    import_main_module, monkeypatch, tmp_path
):
    main = import_main_module()
    monkeypatch.chdir(tmp_path)

    loaded = []

    async def fake_load_extension(name):
        loaded.append(name)

    monkeypatch.setattr(main.bot, "load_extension", fake_load_extension)
    monkeypatch.setattr(main.bot, "_BotBase__extensions", {}, raising=False)
    monkeypatch.setattr(main, "get_media_server_type", lambda: "jellyfin")

    await main.load_cogs()

    assert "cogs.media_core.jellyfin" in loaded
    assert "cogs.media_core.plex" not in loaded


def test_version_info_matches_the_version_string():
    """release-please rewrites __version__ only; the tuple must follow it."""
    import version

    assert version.__version_info__ == tuple(int(part) for part in version.__version__.split("."))
    assert len(version.__version_info__) == 3


@pytest.mark.asyncio
async def test_run_bot_closes_the_bot_on_sigterm(import_main_module, monkeypatch):
    """discord.py installs no signal handlers of its own.

    Under Docker that meant SIGTERM killed the process outright: no cog
    shutdown, no aiohttp session close, no last_seen write - and `docker stop`
    waited out its ten second grace period before sending SIGKILL.
    """
    import asyncio
    import signal

    main = import_main_module()
    handlers = {}
    closed = []

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda sig, cb: handlers.__setitem__(sig, cb))

    async def fake_start(token):
        # Stands in for the gateway connection: raise SIGTERM once we are "up".
        handlers[signal.SIGTERM]()
        await asyncio.sleep(0)

    async def fake_close(*_args):
        closed.append(True)

    async def noop(*_args):
        return None

    monkeypatch.setattr(main.bot, "start", fake_start)
    monkeypatch.setattr(main.bot, "close", fake_close)
    # Dunders resolve on the type, not the instance.
    monkeypatch.setattr(type(main.bot), "__aenter__", noop, raising=False)
    monkeypatch.setattr(type(main.bot), "__aexit__", noop, raising=False)

    await main.run_bot()
    await asyncio.sleep(0)

    assert signal.SIGTERM in handlers
    assert signal.SIGINT in handlers
    assert closed, "SIGTERM must close the bot"


def test_bot_does_not_retain_gateway_messages(import_main_module):
    main = import_main_module()
    assert main.bot._connection._messages is None
    assert main.bot.command_prefix == "!"
    assert main.bot.intents.message_content is True
