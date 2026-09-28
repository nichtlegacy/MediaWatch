"""Authorization coverage for the privileged bot commands.

`is_authorized` guards `/load`, `/unload`, `/reload`, `/reload_config` and
`/cogs`; `!sync` checks `AUTHORIZED_USERS` inline. `/load` can pull in any
extension, so these checks are the only thing between a regular server member
and the bot's extension loader.
"""

from types import SimpleNamespace

import pytest


UNAUTHORIZED = 999
AUTHORIZED = 123
REJECTION = "❌ You are not authorized to execute this command."


class _FakeResponse:
    def __init__(self):
        self.messages = []
        self.deferred = False

    async def defer(self, ephemeral=False):
        self.deferred = True

    async def send_message(self, *args, **kwargs):
        self.messages.append((args, kwargs))


class _FakeFollowup:
    def __init__(self):
        self.messages = []

    async def send(self, *args, **kwargs):
        self.messages.append((args, kwargs))


class _FakeInteraction:
    def __init__(self, user_id):
        self.user = SimpleNamespace(id=user_id, name="someone")
        self.response = _FakeResponse()
        self.followup = _FakeFollowup()


class _FakeBot:
    """Records extension changes so a bypassed check becomes visible."""

    def __init__(self):
        self.extensions = {"cogs.user_mapping": object()}
        self.user = None

    async def load_extension(self, name):
        self.extensions[name] = object()

    async def unload_extension(self, name):
        self.extensions.pop(name)

    async def reload_extension(self, name):
        self.extensions[name] = object()

    def get_cog(self, name):
        return None

    @property
    def cogs(self):
        return {}


def _sent_text(interaction):
    """Return every string the command sent back, from either channel."""
    texts = []
    for args, kwargs in interaction.response.messages + interaction.followup.messages:
        texts.extend(arg for arg in args if isinstance(arg, str))
        embed = kwargs.get("embed")
        if embed is not None:
            texts.append(f"{embed.title}\n{embed.description}")
    return "\n".join(texts)


@pytest.fixture
def main_with_fake_bot(import_main_module, monkeypatch):
    main = import_main_module()
    bot = _FakeBot()
    monkeypatch.setattr(main, "bot", bot)
    return main, bot


@pytest.mark.asyncio
async def test_load_refuses_unauthorized_users(main_with_fake_bot):
    main, bot = main_with_fake_bot
    bot.extensions.clear()
    interaction = _FakeInteraction(UNAUTHORIZED)

    await main.load.callback(interaction, "user_mapping")

    assert "cogs.user_mapping" not in bot.extensions
    assert REJECTION in _sent_text(interaction)


@pytest.mark.asyncio
async def test_load_works_for_authorized_users(main_with_fake_bot):
    main, bot = main_with_fake_bot
    bot.extensions.clear()
    interaction = _FakeInteraction(AUTHORIZED)

    await main.load.callback(interaction, "user_mapping")

    assert "cogs.user_mapping" in bot.extensions
    assert REJECTION not in _sent_text(interaction)


@pytest.mark.asyncio
async def test_unload_refuses_unauthorized_users(main_with_fake_bot):
    main, bot = main_with_fake_bot
    interaction = _FakeInteraction(UNAUTHORIZED)

    await main.unload.callback(interaction, "user_mapping")

    assert "cogs.user_mapping" in bot.extensions
    assert REJECTION in _sent_text(interaction)


@pytest.mark.asyncio
async def test_reload_refuses_unauthorized_users(main_with_fake_bot):
    main, bot = main_with_fake_bot
    reloaded = []
    bot.reload_extension = lambda name: reloaded.append(name)
    interaction = _FakeInteraction(UNAUTHORIZED)

    await main.reload.callback(interaction, "user_mapping")

    assert reloaded == []
    assert REJECTION in _sent_text(interaction)


@pytest.mark.asyncio
async def test_reload_config_refuses_unauthorized_users(main_with_fake_bot, monkeypatch):
    main, _ = main_with_fake_bot
    calls = []

    async def fake_reload_runtime_config(bot_instance=None):
        calls.append(bot_instance)
        return []

    monkeypatch.setattr(main, "reload_runtime_config", fake_reload_runtime_config)
    interaction = _FakeInteraction(UNAUTHORIZED)

    await main.reload_config.callback(interaction)

    assert calls == []
    assert REJECTION in _sent_text(interaction)


@pytest.mark.asyncio
async def test_list_cogs_refuses_unauthorized_users(main_with_fake_bot):
    main, _ = main_with_fake_bot
    interaction = _FakeInteraction(UNAUTHORIZED)

    await main.list_cogs.callback(interaction)

    assert REJECTION in _sent_text(interaction)
    assert not interaction.followup.messages


@pytest.mark.asyncio
async def test_list_cogs_lists_the_cogs_for_authorized_users(main_with_fake_bot):
    main, _ = main_with_fake_bot
    interaction = _FakeInteraction(AUTHORIZED)

    await main.list_cogs.callback(interaction)

    text = _sent_text(interaction)
    assert REJECTION not in text
    assert "user_mapping" in text.lower() or "user mapping" in text.lower()


class _FakeContext:
    def __init__(self, user_id):
        self.author = SimpleNamespace(id=user_id, name="someone")
        self.guild = None
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append(args[0] if args else kwargs)


@pytest.mark.asyncio
async def test_sync_prefix_command_refuses_unauthorized_users(import_main_module, monkeypatch):
    main = import_main_module()
    synced = []

    async def fake_sync_command_tree(guild=None, copy_global_to_guild=False):
        synced.append(guild)
        return []

    monkeypatch.setattr(main, "sync_command_tree", fake_sync_command_tree)
    ctx = _FakeContext(UNAUTHORIZED)

    await main.sync_prefix_command.callback(ctx, "global")

    assert synced == []
    assert ctx.sent == ["❌ You are not authorized to execute this command."]


@pytest.mark.asyncio
async def test_sync_prefix_command_syncs_for_authorized_users(import_main_module, monkeypatch):
    main = import_main_module()
    synced = []

    async def fake_sync_command_tree(guild=None, copy_global_to_guild=False):
        synced.append(guild)
        return []

    monkeypatch.setattr(main, "sync_command_tree", fake_sync_command_tree)
    ctx = _FakeContext(AUTHORIZED)

    await main.sync_prefix_command.callback(ctx, "global")

    assert synced == [None]
    assert ctx.sent == ["Synced 0 global commands."]


def test_is_authorized_rejects_users_outside_the_configured_list(import_main_module):
    main = import_main_module()

    assert main.is_authorized(_FakeInteraction(AUTHORIZED)) is True
    assert main.is_authorized(_FakeInteraction(UNAUTHORIZED)) is False
