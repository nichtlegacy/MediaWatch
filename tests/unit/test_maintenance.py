from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from discord.ext import commands

from cogs.maintenance import Maintenance
from cogs.media_core.shared import maintenance, runtime_state

AUTHORIZED = 123
UNAUTHORIZED = 999


class _FakeFollowup:
    def __init__(self, error=None):
        self.embeds = []
        self.error = error

    async def send(self, *, embed, ephemeral):
        assert ephemeral is True
        if self.error:
            raise self.error
        self.embeds.append(embed)


def _interaction(user_id=AUTHORIZED, followup_error=None):
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        response=SimpleNamespace(defer=AsyncMock()),
        followup=_FakeFollowup(followup_error),
    )


def _cog(monkeypatch, core=None):
    monkeypatch.setenv("DISCORD_AUTHORIZED_USERS", str(AUTHORIZED))
    bot = SimpleNamespace(get_cog=lambda name: core if name == "PlexCore" else None)
    return Maintenance(bot)


def _core():
    return SimpleNamespace(update_dashboard=AsyncMock())


def test_maintenance_registers_as_a_group_with_three_subcommands():
    assert issubclass(Maintenance, commands.GroupCog)
    assert Maintenance.__cog_group_name__ == "maintenance"
    assert sorted(c.name for c in Maintenance.__cog_app_commands__) == ["end", "start", "status"]


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["maintenance_start", "maintenance_end", "maintenance_status"])
async def test_unauthorized_users_cannot_touch_maintenance(monkeypatch, command):
    maintenance.start(started_by=AUTHORIZED, reason="Disk swap")
    core = _core()
    cog = _cog(monkeypatch, core)
    interaction = _interaction(UNAUTHORIZED)

    await getattr(cog, command).callback(cog, interaction)

    assert interaction.followup.embeds[0].title == "❌ Not authorized"
    assert maintenance.current().reason == "Disk swap"
    core.update_dashboard.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_activates_maintenance_and_refreshes_the_dashboard_at_once(monkeypatch):
    core = _core()
    cog = _cog(monkeypatch, core)
    interaction = _interaction()

    await cog.maintenance_start.callback(cog, interaction, reason="Disk swap", duration="1h30m")

    window = maintenance.current()
    assert window.reason == "Disk swap"
    assert window.started_by == AUTHORIZED
    assert window.ends_at - window.started_at == pytest.approx(5400, abs=5)
    assert interaction.followup.embeds[0].title == "🛠️ Maintenance started"
    core.update_dashboard.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_again_reports_an_update(monkeypatch):
    cog = _cog(monkeypatch, _core())
    await cog.maintenance_start.callback(cog, _interaction(), reason="Disk swap")
    interaction = _interaction()

    await cog.maintenance_start.callback(cog, interaction, duration="30m")

    assert interaction.followup.embeds[0].title == "🛠️ Maintenance updated"
    assert maintenance.current().reason == "Disk swap"


@pytest.mark.asyncio
async def test_an_invalid_duration_changes_nothing(monkeypatch):
    core = _core()
    cog = _cog(monkeypatch, core)
    interaction = _interaction()

    await cog.maintenance_start.callback(cog, interaction, reason="x", duration="soon")

    assert interaction.followup.embeds[0].title == "❌ Invalid duration"
    assert "30m, 2h, 1h30m or 1d" in interaction.followup.embeds[0].description
    assert maintenance.current() is None
    core.update_dashboard.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_dashboard_follows_even_when_the_reply_fails(monkeypatch):
    core = _core()
    cog = _cog(monkeypatch, core)
    error = discord.HTTPException(SimpleNamespace(status=500, reason="boom"), "boom")

    with pytest.raises(discord.HTTPException):
        await cog.maintenance_start.callback(cog, _interaction(followup_error=error))

    assert maintenance.current() is not None
    core.update_dashboard.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_failing_refresh_does_not_fail_the_command(monkeypatch):
    core = SimpleNamespace(update_dashboard=AsyncMock(side_effect=RuntimeError("down")))
    cog = _cog(monkeypatch, core)
    interaction = _interaction()

    await cog.maintenance_start.callback(cog, interaction)

    assert interaction.followup.embeds[0].title == "🛠️ Maintenance started"


@pytest.mark.asyncio
async def test_start_warns_when_it_cannot_be_saved_or_shown(monkeypatch):
    def fail(*args, **kwargs):
        raise PermissionError("read-only")

    monkeypatch.setattr(runtime_state, "write_json_atomic", fail)
    cog = _cog(monkeypatch, core=None)
    interaction = _interaction()

    await cog.maintenance_start.callback(cog, interaction)

    names = [f.name for f in interaction.followup.embeds[0].fields]
    assert "⚠️ Not saved" in names
    assert "⚠️ No media core loaded" in names
    assert maintenance.current() is not None


@pytest.mark.asyncio
async def test_end_clears_maintenance_and_refreshes(monkeypatch):
    maintenance.start(started_by=AUTHORIZED)
    core = _core()
    cog = _cog(monkeypatch, core)
    interaction = _interaction()

    await cog.maintenance_end.callback(cog, interaction)

    assert interaction.followup.embeds[0].title == "✅ Maintenance ended"
    assert maintenance.current() is None
    core.update_dashboard.assert_awaited_once()


@pytest.mark.asyncio
async def test_end_without_maintenance_says_so(monkeypatch):
    core = _core()
    cog = _cog(monkeypatch, core)
    interaction = _interaction()

    await cog.maintenance_end.callback(cog, interaction)

    assert interaction.followup.embeds[0].title == "Maintenance mode is not active"
    core.update_dashboard.assert_not_awaited()


@pytest.mark.asyncio
async def test_status_shows_the_running_window(monkeypatch):
    cog = _cog(monkeypatch, _core())
    interaction = _interaction()
    await cog.maintenance_status.callback(cog, interaction)
    assert interaction.followup.embeds[0].title == "Maintenance mode is not active"

    maintenance.start(started_by=AUTHORIZED, reason="Disk swap")
    interaction = _interaction()
    await cog.maintenance_status.callback(cog, interaction)

    embed = interaction.followup.embeds[0]
    assert embed.title == "🛠️ Maintenance mode is active"
    assert embed.fields[0].value == "Disk swap"
    assert embed.fields[-1].value == f"<@{AUTHORIZED}>"


@pytest.mark.asyncio
async def test_duration_autocomplete_filters_the_suggestions(monkeypatch):
    cog = _cog(monkeypatch)

    choices = await cog.duration_autocomplete(_interaction(), "1")

    assert [c.value for c in choices] == ["15m", "1h", "1d"]
