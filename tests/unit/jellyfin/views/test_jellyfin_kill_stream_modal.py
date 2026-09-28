from types import SimpleNamespace

import pytest

from cogs.media_core.jellyfin.views.kill_stream_modal import KillStreamModal


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
        self.user = SimpleNamespace(id=user_id, name="admin")
        self.response = _FakeResponse()
        self.followup = _FakeFollowup()


def make_jellyfin_core(session, message_delivered=True):
    stopped = []
    messages = []

    async def stop_session(session_id):
        stopped.append(session_id)
        return True

    async def send_message(session_id, text):
        messages.append((session_id, text))
        return message_delivered

    core = SimpleNamespace(
        config={"dashboard": {"name": "Jellyfin Dashboard"}},
        AUTHORIZED_USERS=[123],
        active_sessions={"abc123": session},
        jellyfin_client=SimpleNamespace(
            is_connected=lambda: True,
            stop_session=stop_session,
            send_message=send_message,
        ),
        stopped=stopped,
        messages=messages,
    )

    async def resolve_active_session(session_key):
        return core.active_sessions.get(session_key)

    core.resolve_active_session = resolve_active_session
    return core


@pytest.mark.asyncio
async def test_kill_stream_still_confirms_when_session_info_extraction_fails():
    # "NowPlayingItem" in an unexpected shape makes the info extraction raise.
    session = {"Id": "abc123", "UserName": "alice", "NowPlayingItem": ["unexpected"]}
    core = make_jellyfin_core(session)
    modal = KillStreamModal.__new__(KillStreamModal)
    modal.jellyfin_core = core
    modal.session_key = "abc123"
    modal.logger = SimpleNamespace(
        warning=lambda *a, **k: None, error=lambda *a, **k: None, info=lambda *a, **k: None
    )

    interaction = _FakeInteraction()
    await modal.kill_stream(interaction, "Please stop")

    assert core.stopped == ["abc123"]
    assert core.messages == [("abc123", "Please stop")]
    assert core.active_sessions == {}
    assert len(interaction.followup.messages) == 1
    embed = interaction.followup.messages[0][1]["embed"]
    assert embed.title == "✅ Stream Killed Successfully"


def test_kill_stream_modal_uses_configured_default_reason():
    core = make_jellyfin_core({"Id": "abc123"})
    core.config["stream_controls"] = {"kill_stream": {"default_reason": "Bitte pausieren"}}

    modal = KillStreamModal(core, "abc123")

    assert modal.reason_input.default == "Bitte pausieren"
    assert modal.reason_input.placeholder == "Bitte pausieren"


def test_kill_stream_modal_falls_back_to_shared_default_reason():
    modal = KillStreamModal(make_jellyfin_core({"Id": "abc123"}), "abc123")

    assert modal.reason_input.default == "Stopped by administrator"


def _make_modal(core):
    modal = KillStreamModal.__new__(KillStreamModal)
    modal.jellyfin_core = core
    modal.session_key = "abc123"
    modal.logger = SimpleNamespace(
        warning=lambda *a, **k: None, error=lambda *a, **k: None, info=lambda *a, **k: None
    )
    return modal


def _reason_field(embed):
    return next(field for field in embed.fields if field.name.startswith("💬"))


@pytest.mark.asyncio
async def test_kill_stream_marks_reason_as_undelivered_when_message_fails():
    session = {
        "Id": "abc123",
        "UserName": "alice",
        "NowPlayingItem": {"Type": "Movie", "Name": "Movie"},
    }
    core = make_jellyfin_core(session, message_delivered=False)
    interaction = _FakeInteraction()

    await _make_modal(core).kill_stream(interaction, "Please stop")

    embed = interaction.followup.messages[0][1]["embed"]
    assert _reason_field(embed).name == "💬 Reason (not delivered)"


@pytest.mark.asyncio
async def test_kill_stream_shows_plain_reason_when_message_is_delivered():
    session = {
        "Id": "abc123",
        "UserName": "alice",
        "NowPlayingItem": {"Type": "Movie", "Name": "Movie"},
    }
    core = make_jellyfin_core(session)
    interaction = _FakeInteraction()

    await _make_modal(core).kill_stream(interaction, "Please stop")

    embed = interaction.followup.messages[0][1]["embed"]
    assert _reason_field(embed).name == "💬 Reason"


@pytest.mark.asyncio
async def test_kill_stream_handles_episode_without_index_numbers():
    session = {
        "Id": "abc123",
        "UserName": "alice",
        "NowPlayingItem": {
            "Type": "Episode",
            "SeriesName": "Series",
            "Name": "Pilot",
            "ParentIndexNumber": None,
            "IndexNumber": None,
        },
    }
    core = make_jellyfin_core(session)
    interaction = _FakeInteraction()

    await _make_modal(core).kill_stream(interaction, "Please stop")

    embed = interaction.followup.messages[0][1]["embed"]
    assert embed.title == "✅ Stream Killed Successfully"
    episode_field = next(field for field in embed.fields if field.name == "📋 Episode")
    assert episode_field.value == "`S00E00 - Pilot`"
    session_field = next(field for field in embed.fields if field.name == "🔑 Session")
    assert session_field.value == "`abc123`"


@pytest.mark.asyncio
async def test_kill_stream_skips_message_for_clients_without_display_message():
    session = {
        "Id": "abc123",
        "UserName": "alice",
        "SupportedCommands": ["Play", "Pause"],
        "NowPlayingItem": {"Type": "Movie", "Name": "Movie"},
    }
    core = make_jellyfin_core(session)
    interaction = _FakeInteraction()

    await _make_modal(core).kill_stream(interaction, "Please stop")

    assert core.messages == []
    assert core.stopped == ["abc123"]
    embed = interaction.followup.messages[0][1]["embed"]
    assert _reason_field(embed).name == "💬 Reason (not delivered)"


@pytest.mark.asyncio
async def test_kill_stream_refuses_unauthorized_users():
    # A custom_id can be replayed by anyone, so the modal submit itself has to
    # re-check authorization instead of relying on the button being hidden.
    session = {
        "Id": "abc123",
        "UserName": "alice",
        "NowPlayingItem": {"Type": "Movie", "Name": "Movie"},
    }
    core = make_jellyfin_core(session)
    interaction = _FakeInteraction(user_id=999)

    await _make_modal(core).kill_stream(interaction, "Please stop")

    assert core.stopped == []
    assert core.messages == []
    assert set(core.active_sessions) == {"abc123"}
    assert interaction.followup.messages[0][0][0] == "❌ You are not authorized to kill streams."
