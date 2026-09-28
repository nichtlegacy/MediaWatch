from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from cogs.media_core.plex.core import PlexCore


class FakeMessage:
    def __init__(self, edit_error=None):
        self.edits = []
        self.edit_error = edit_error

    async def edit(self, *, embed=None, view=None):
        if self.edit_error:
            raise self.edit_error
        self.edits.append({"embed": embed, "view": view})


class FakeChannel:
    def __init__(self, *, fetch_error=None):
        self.fetch_error = fetch_error
        self.sent_messages = []

    def get_partial_message(self, message_id):
        return FakeMessage(self.fetch_error)

    async def send(self, *, embed=None, view=None):
        message = SimpleNamespace(id=987654321, embed=embed, view=view)
        self.sent_messages.append(message)
        return message


class FakeStreamView:
    def __init__(self, child_count=1):
        self.children = [object()] * child_count
        self.calls = []

    async def create_buttons(self, sessions, library_stats=None):
        self.calls.append(list(sessions))
        self.library_stats = library_stats

    def stop(self):
        return None


@pytest.mark.asyncio
async def test_update_dashboard_message_recreates_message_after_forbidden(monkeypatch):
    saved_message_ids = []
    core = PlexCore.__new__(PlexCore)
    core.logger = SimpleNamespace(
        debug=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        info=lambda *a, **k: None,
    )
    core.stream_view = FakeStreamView(child_count=1)
    core.dashboard_message_id = 123
    core.MESSAGE_ID_FILE = "/tmp/dashboard_message_id.json"

    monkeypatch.setattr(
        "cogs.media_core.plex.core.save_message_id",
        lambda path, message_id: saved_message_ids.append((path, message_id)),
    )

    channel = FakeChannel(
        fetch_error=discord.Forbidden(
            SimpleNamespace(status=403, reason="Forbidden"), "Cannot edit"
        )
    )
    embed = discord.Embed(title="Dashboard")

    await core._update_dashboard_message(channel, embed, {"current_streams": ["session-1"]})

    assert core.stream_view.calls == [["session-1"]]
    assert core.dashboard_message_id == 987654321
    assert saved_message_ids == [("/tmp/dashboard_message_id.json", 987654321)]
    assert len(channel.sent_messages) == 1


@pytest.mark.asyncio
async def test_shutdown_cancels_loops_and_closes_service():
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

    core = PlexCore.__new__(PlexCore)
    core._shutdown_started = False
    core.update_status = FakeLoop("status")
    core.update_dashboard = FakeLoop("dashboard")
    core.stream_view = SimpleNamespace(stop=lambda: cancelled.append("view-stop"))
    core.plex_service = FakeService()

    await core.shutdown()
    await core.shutdown()

    assert cancelled == ["status", "dashboard", "view-stop"]
    assert closed == ["closed"]


@pytest.mark.asyncio
async def test_resolve_active_session_refreshes_cache_on_miss():
    session = SimpleNamespace(sessionKey=42)
    core = PlexCore.__new__(PlexCore)
    core.active_sessions = {}
    core.plex_service = SimpleNamespace(
        get_active_streams=AsyncMock(return_value=[SimpleNamespace(raw_session=session)])
    )

    resolved = await PlexCore.resolve_active_session(core, "42")

    assert resolved is session
    assert core.active_sessions == {"42": session}


@pytest.mark.asyncio
async def test_cog_load_connects_plex_off_thread_and_propagates_to_services():
    class FakePlexClient:
        def __init__(self):
            self.server = None
            self.connect_calls = 0

        def connect(self):
            self.connect_calls += 1
            self.server = "plex-server"
            return self.server

    class FakeTaskLoop:
        def __init__(self):
            self.started = False

        def is_running(self):
            return False

        def start(self):
            self.started = True

    core = PlexCore.__new__(PlexCore)
    core.bot = SimpleNamespace(add_view=lambda view: None)
    core.stream_view = FakeStreamView()
    core.plex_client = FakePlexClient()
    core.plex = None
    core.stream_service = SimpleNamespace(plex=None)
    core.update_status = FakeTaskLoop()
    core.update_dashboard = FakeTaskLoop()

    await PlexCore.cog_load(core)

    assert core.plex_client.connect_calls == 1
    assert core.plex == "plex-server"
    assert core.stream_service.plex == "plex-server"
    assert core.update_status.started is True
    assert core.update_dashboard.started is True


@pytest.mark.asyncio
async def test_cog_load_survives_unreachable_plex_server():
    class FailingPlexClient:
        def __init__(self):
            self.server = None

        def connect(self):
            return None

    class FakeTaskLoop:
        def is_running(self):
            return True

    core = PlexCore.__new__(PlexCore)
    core.bot = SimpleNamespace(add_view=lambda view: None)
    core.stream_view = FakeStreamView()
    core.plex_client = FailingPlexClient()
    core.plex = None
    core.stream_service = SimpleNamespace(plex=None)
    core.update_status = FakeTaskLoop()
    core.update_dashboard = FakeTaskLoop()

    await PlexCore.cog_load(core)

    assert core.plex is None


@pytest.mark.asyncio
async def test_init_tolerates_blank_entries_in_authorized_users(monkeypatch):
    # Env validation accepts "123, ,456"; a stricter parse here used to raise
    # ValueError, so the media cog never loaded and no dashboard appeared.
    import cogs.media_core.plex.core as plex_core

    monkeypatch.setenv("DISCORD_AUTHORIZED_USERS", " 123, ,456 ")
    monkeypatch.setenv("CHANNEL_ID", "1")
    monkeypatch.setattr(plex_core, "check_legacy_config", lambda *a: None)
    monkeypatch.setattr(plex_core, "load_config", lambda *a: {})
    monkeypatch.setattr(plex_core, "load_user_mapping", lambda *a, **k: {})
    monkeypatch.setattr(plex_core, "load_message_id", lambda *a: None)
    monkeypatch.setattr(
        plex_core,
        "PlexMediaService",
        lambda **k: SimpleNamespace(plex_client=None, tautulli_client=None),
    )
    monkeypatch.setattr(plex_core, "StreamDetailsView", lambda core: None)

    core = PlexCore(SimpleNamespace())

    assert core.AUTHORIZED_USERS == [123, 456]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "auth_failed", "fetched"),
    [("🟢 Online", False, False), ("🔴 Offline", True, False), ("🔴 Offline", False, True)],
)
async def test_update_dashboard_fetches_uptime_kuma_only_for_offline_embed(
    status, auth_failed, fetched
):
    # The uptime fields only render in the offline embed; fetching them while
    # online cost a socket.io login per tick for nothing.
    fetches = []
    uptime_cog = SimpleNamespace(
        get_uptime_data=lambda: fetches.append(1) or (99.0, 60.0, 98.0, 120.0, 97.0, 180.0),
        format_online_time=lambda minutes: f"{int(minutes)}m",
    )
    rendered = []
    core = PlexCore.__new__(PlexCore)
    core.logger = SimpleNamespace(error=lambda *a, **k: None)
    core.bot = SimpleNamespace(get_cog=lambda name: uptime_cog if name == "Uptime" else None)
    core._resolve_channel = AsyncMock(return_value=object())
    core.get_server_info = AsyncMock(return_value={"status": status, "auth_failed": auth_failed})
    core._create_dashboard_embed = AsyncMock(side_effect=lambda info: rendered.append(info))
    core._update_dashboard_message = AsyncMock()

    await PlexCore.update_dashboard.coro(core)

    assert bool(fetches) is fetched
    assert ("uptime_24h" in rendered[0]) is fetched
    if fetched:
        assert rendered[0]["uptime_24h"] == "99.0% (60m)"
