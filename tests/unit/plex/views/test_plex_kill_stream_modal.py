from types import SimpleNamespace

import pytest

from cogs.media_core.plex.views.kill_stream_modal import KillStreamModal


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
        self.user = SimpleNamespace(id=user_id, name="someone")
        self.response = _FakeResponse()
        self.followup = _FakeFollowup()


def make_session(stopped):
    session = SimpleNamespace(
        sessionKey=1,
        usernames=["alice"],
        type="movie",
        title="Movie",
        year=2024,
    )
    session.stop = lambda reason=None: stopped.append(reason)
    return session


def make_plex_core(session):
    async def fetch_session(session_key):
        return None

    core = SimpleNamespace(
        config={"dashboard": {"name": "Plex Dashboard"}},
        AUTHORIZED_USERS=[123],
        plex=True,
        active_sessions={"1": session},
        tautulli_client=SimpleNamespace(fetch_session=fetch_session),
    )

    async def resolve_active_session(session_key):
        return core.active_sessions.get(session_key)

    core.resolve_active_session = resolve_active_session
    return core


def _make_modal(core):
    modal = KillStreamModal.__new__(KillStreamModal)
    modal.plex_core = core
    modal.session_key = "1"
    modal.logger = SimpleNamespace(
        warning=lambda *a, **k: None, error=lambda *a, **k: None, info=lambda *a, **k: None
    )
    return modal


@pytest.mark.asyncio
async def test_kill_stream_refuses_unauthorized_users():
    # A custom_id can be replayed by anyone, so the modal submit itself has to
    # re-check authorization instead of relying on the button being hidden.
    stopped = []
    core = make_plex_core(make_session(stopped))
    interaction = _FakeInteraction(user_id=999)

    await _make_modal(core).kill_stream(interaction, "Please stop")

    assert stopped == []
    assert set(core.active_sessions) == {"1"}
    assert interaction.followup.messages[0][0][0] == "❌ You are not authorized to kill streams."


@pytest.mark.asyncio
async def test_kill_stream_stops_the_session_for_authorized_users():
    stopped = []
    core = make_plex_core(make_session(stopped))
    interaction = _FakeInteraction(user_id=123)

    await _make_modal(core).kill_stream(interaction, "Please stop")

    assert stopped == ["Please stop"]
    assert core.active_sessions == {}
    embed = interaction.followup.messages[0][1]["embed"]
    assert embed.title == "✅ Stream Killed Successfully"


def test_kill_stream_modal_uses_configured_default_reason():
    core = make_plex_core(make_session([]))
    core.config["stream_controls"] = {"kill_stream": {"default_reason": "Bitte pausieren"}}

    modal = KillStreamModal(core, "1")

    assert modal.reason_input.default == "Bitte pausieren"
    assert modal.reason_input.placeholder == "Bitte pausieren"


def test_kill_stream_modal_falls_back_to_shared_default_reason():
    modal = KillStreamModal(make_plex_core(make_session([])), "1")

    assert modal.reason_input.default == "Stopped by administrator"
