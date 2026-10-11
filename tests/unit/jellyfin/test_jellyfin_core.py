import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from cogs.media_core.jellyfin.core import JellyfinCore


class FakeChannel:
    def __init__(self, *, fetch_error=None):
        self.fetch_error = fetch_error
        self.sent_messages = []

    def get_partial_message(self, message_id):
        async def edit(**kwargs):
            if self.fetch_error:
                raise self.fetch_error

        return SimpleNamespace(edit=edit)

    async def send(self, *, embed=None, view=None):
        message = SimpleNamespace(id=222333444, embed=embed, view=view)
        self.sent_messages.append(message)
        return message


class FakeStreamDetailsView:
    def __init__(self, child_count=1):
        self.children = [object()] * child_count
        self.calls = []

    async def create_buttons(self, sessions):
        self.calls.append(list(sessions))

    def stop(self):
        return None


@pytest.mark.asyncio
async def test_update_dashboard_message_recreates_message_after_not_found(monkeypatch):
    saved_message_ids = []
    core = JellyfinCore.__new__(JellyfinCore)
    core.logger = SimpleNamespace(
        debug=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        info=lambda *a, **k: None,
    )
    core.stream_details_view = FakeStreamDetailsView(child_count=1)
    core.dashboard_message_id = 123
    core.MESSAGE_ID_FILE = "/tmp/jellyfin_dashboard_message_id.json"

    monkeypatch.setattr(
        "cogs.media_core.jellyfin.core.save_message_id",
        lambda path, message_id: saved_message_ids.append((path, message_id)),
    )

    channel = FakeChannel(
        fetch_error=discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Missing")
    )
    embed = discord.Embed(title="Dashboard")
    fake_raw_session = {"id": "session"}

    await core._update_dashboard_message(
        channel,
        embed,
        {"current_streams": [SimpleNamespace(raw_session=fake_raw_session)]},
    )

    assert core.stream_details_view.calls == [[fake_raw_session]]
    assert core.dashboard_message_id == 222333444
    assert saved_message_ids == [("/tmp/jellyfin_dashboard_message_id.json", 222333444)]
    assert len(channel.sent_messages) == 1


@pytest.mark.asyncio
async def test_shutdown_is_idempotent_for_jellyfin_core():
    cancelled = []
    closed = []

    class FakeLoop:
        def __init__(self, name):
            self.name = name

        def is_running(self):
            return True

        def cancel(self):
            cancelled.append(self.name)

    class FakeService:
        async def close(self):
            closed.append("closed")

    core = JellyfinCore.__new__(JellyfinCore)
    core._shutdown_started = False
    core.update_status = FakeLoop("status")
    core.update_dashboard = FakeLoop("dashboard")
    core.stream_details_view = SimpleNamespace(stop=lambda: cancelled.append("view-stop"))
    core.jellyfin_service = FakeService()

    await core.shutdown()
    await core.shutdown()

    assert cancelled == ["status", "dashboard", "view-stop"]
    assert closed == ["closed"]


@pytest.mark.asyncio
async def test_resolve_active_session_refreshes_cache_on_miss():
    session = {"Id": "abc123", "UserName": "Alice"}
    core = JellyfinCore.__new__(JellyfinCore)
    core.active_sessions = {}
    core.jellyfin_service = SimpleNamespace(
        get_active_streams=AsyncMock(return_value=[SimpleNamespace(raw_session=session)])
    )

    resolved = await JellyfinCore.resolve_active_session(core, "abc123")

    assert resolved == session
    assert core.active_sessions == {"abc123": session}


@pytest.mark.asyncio
async def test_init_tolerates_blank_entries_in_authorized_users(monkeypatch):
    # Env validation accepts "123, ,456"; a stricter parse here used to raise
    # ValueError, so the media cog never loaded and no dashboard appeared.
    import cogs.media_core.jellyfin.core as jellyfin_core

    monkeypatch.setenv("DISCORD_AUTHORIZED_USERS", " 123, ,456 ")
    monkeypatch.setenv("CHANNEL_ID", "1")
    monkeypatch.setattr(jellyfin_core, "check_legacy_config", lambda *a: None)
    monkeypatch.setattr(jellyfin_core, "load_config", lambda *a: {})
    monkeypatch.setattr(jellyfin_core, "load_user_mapping", lambda *a, **k: {})
    monkeypatch.setattr(jellyfin_core, "load_message_id", lambda *a: None)
    monkeypatch.setattr(
        jellyfin_core, "JellyfinMediaService", lambda **k: SimpleNamespace(jellyfin_client=None)
    )
    monkeypatch.setattr(
        "cogs.media_core.jellyfin.views.stream_details_view.StreamDetailsView", lambda core: None
    )

    core = JellyfinCore(SimpleNamespace())

    assert core.AUTHORIZED_USERS == [123, 456]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "auth_failed", "maintenance", "fetched"),
    [
        ("🟢 Online", False, None, False),
        ("🔴 Offline", True, None, False),
        ("🔴 Offline", False, None, True),
        # The maintenance embed has no uptime fields either.
        ("🔴 Offline", False, object(), False),
    ],
)
async def test_update_dashboard_fetches_uptime_kuma_only_for_offline_embed(
    status, auth_failed, maintenance, fetched
):
    # The uptime fields only render in the offline embed; fetching them while
    # online cost a socket.io login per tick for nothing.
    fetches = []
    uptime_cog = SimpleNamespace(
        get_uptime_data=lambda: fetches.append(1) or (99.0, 60.0, 98.0, 120.0, 97.0, 180.0),
        format_online_time=lambda minutes: f"{int(minutes)}m",
    )
    rendered = []
    core = JellyfinCore.__new__(JellyfinCore)
    core._dashboard_lock = asyncio.Lock()
    core.logger = SimpleNamespace(error=lambda *a, **k: None)
    core.bot = SimpleNamespace(get_cog=lambda name: uptime_cog if name == "Uptime" else None)
    core._resolve_channel = AsyncMock(return_value=object())
    core.get_server_info = AsyncMock(
        return_value={"status": status, "auth_failed": auth_failed, "maintenance": maintenance}
    )
    core._create_dashboard_embed = AsyncMock(side_effect=lambda info: rendered.append(info))
    core._update_dashboard_message = AsyncMock()

    await JellyfinCore.update_dashboard.coro(core)

    assert bool(fetches) is fetched
    assert ("uptime_24h" in rendered[0]) is fetched
    if fetched:
        assert rendered[0]["uptime_24h"] == "99.0% (60m)"


@pytest.mark.asyncio
@pytest.mark.parametrize(("reachable", "ended"), [(False, False), (True, True)])
async def test_get_server_info_ends_overdue_maintenance_only_once_the_server_answers(
    reachable, ended
):
    # Within server.offline_threshold a server that stopped answering is still
    # reported online; ending the maintenance then would be premature.
    from cogs.media_core.shared import maintenance
    from cogs.media_core.shared.models import ServerStatus, ServerType

    maintenance.start(started_by=1, duration=60, now=time.time() - 120)
    core = JellyfinCore.__new__(JellyfinCore)
    core.config = {"maintenance": {"auto_end": True}}
    core.jellyfin_service = SimpleNamespace(
        get_server_status=AsyncMock(
            return_value=ServerStatus(
                server_type=ServerType.JELLYFIN, is_online=True, reachable=reachable
            )
        )
    )

    info = await core.get_server_info()

    assert info["reachable"] is reachable
    assert (info["maintenance"] is None) is ended
    assert (maintenance.current() is None) is ended


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("published", "in_maintenance", "refreshed"),
    [(None, True, False), (False, True, True), (True, True, False), (True, False, True)],
)
async def test_update_dashboard_brings_the_presence_along_when_maintenance_changes(
    published, in_maintenance, refreshed
):
    # The presence loop runs every five minutes; a start, end or auto-end seen
    # by the dashboard must not leave it stale that long.
    core = JellyfinCore.__new__(JellyfinCore)
    core._dashboard_lock = asyncio.Lock()
    core._presence_in_maintenance = published
    core.logger = SimpleNamespace(error=lambda *a, **k: None)
    core.bot = SimpleNamespace(get_cog=lambda name: None)
    core._resolve_channel = AsyncMock(return_value=object())
    core.get_server_info = AsyncMock(
        return_value={
            "status": "🔴 Offline",
            "maintenance": object() if in_maintenance else None,
        }
    )
    core._create_dashboard_embed = AsyncMock()
    core._update_dashboard_message = AsyncMock()
    core.update_status = AsyncMock()

    await JellyfinCore.update_dashboard.coro(core)

    assert core.update_status.await_count == (1 if refreshed else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(("error", "recorded"), [(None, True), (ConnectionResetError(), None)])
async def test_update_status_records_maintenance_only_once_the_presence_went_out(error, recorded):
    # A failed change_presence must leave the mismatch visible, so the next
    # dashboard tick retries instead of believing the presence is current.
    core = JellyfinCore.__new__(JellyfinCore)
    core.logger = SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None)
    core.config = {
        "presence": {"enabled": True, "maintenance_text": "🛠️ Maintenance"},
        "display": {"thousands_separator": ".", "episode_label": "Episodes"},
    }
    core.bot = SimpleNamespace(change_presence=AsyncMock(side_effect=error))
    core.get_server_info = AsyncMock(
        return_value={
            "status": "🔴 Offline",
            "active_users": [],
            "library_stats": {},
            "maintenance": object(),
        }
    )

    await JellyfinCore.update_status.coro(core)

    assert core._presence_in_maintenance is recorded
