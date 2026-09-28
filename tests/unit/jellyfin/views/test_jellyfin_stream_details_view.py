from types import SimpleNamespace

import pytest

from cogs.media_core.jellyfin.views.stream_details_view import StreamDetailsView


def make_jellyfin_core():
    core = SimpleNamespace(
        config={
            "dashboard": {
                "name": "Jellyfin Dashboard",
                "icon_url": "https://example.com/jellyfin.png",
                "footer_icon_url": "https://example.com/footer.png",
            }
        },
        active_sessions={},
        user_mapping={},
        AUTHORIZED_USERS=[],
        jellyfin_client=SimpleNamespace(is_connected=lambda: True),
    )
    core._get_session_cache_key = lambda session: (
        str(session.get("Id")) if session and session.get("Id") else None
    )

    async def resolve_active_session(session_key):
        return core.active_sessions.get(session_key)

    core.resolve_active_session = resolve_active_session
    return core


@pytest.mark.asyncio
async def test_create_buttons_uses_stable_session_ids():
    core = make_jellyfin_core()
    core.user_mapping = {"verylongusername123": "Display Name That Is Too Long"}
    view = StreamDetailsView(core)

    await view.create_buttons(
        [{"Id": "abc123", "UserName": "verylongusername123", "NowPlayingItem": {"Type": "Movie"}}]
    )

    assert [child.label for child in view.children] == ["Stream 1 - Display Name..."]
    assert view.children[0].custom_id == "jellyfin_stream_details:abc123"


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
async def test_show_stream_details_returns_styled_error_when_session_missing():
    core = make_jellyfin_core()
    view = StreamDetailsView(core)
    interaction = _FakeInteraction()

    await view.show_stream_details(interaction, "missing-session")

    assert interaction.followup.messages
    embed = interaction.followup.messages[0][1]["embed"]
    assert embed.title == "❌ Stream Details Unavailable"
    assert "session cache expired" in embed.description
    assert embed.author.name == "Jellyfin Dashboard"
    assert embed.footer.text == "Jellyfin Stream Status"


@pytest.mark.asyncio
async def test_show_stream_details_is_open_to_everyone_by_default():
    core = make_jellyfin_core()
    core.AUTHORIZED_USERS = [999]
    view = StreamDetailsView(core)
    interaction = _FakeInteraction(user_id=123)

    await view.show_stream_details(interaction, "missing-session")

    embed = interaction.followup.messages[0][1]["embed"]
    assert embed.title == "❌ Stream Details Unavailable"


@pytest.mark.asyncio
async def test_show_stream_details_rejects_unauthorized_users_when_restricted():
    core = make_jellyfin_core()
    core.config["stream_details"] = {"restrict_to_authorized": True}
    core.AUTHORIZED_USERS = [999]
    view = StreamDetailsView(core)
    interaction = _FakeInteraction(user_id=123)

    await view.show_stream_details(interaction, "session-1")

    assert interaction.followup.messages[0][0][0] == (
        "❌ Stream details are restricted to authorized users on this server."
    )


@pytest.mark.asyncio
async def test_show_stream_details_allows_authorized_users_when_restricted():
    core = make_jellyfin_core()
    core.config["stream_details"] = {"restrict_to_authorized": True}
    core.AUTHORIZED_USERS = [123]
    view = StreamDetailsView(core)
    interaction = _FakeInteraction(user_id=123)

    await view.show_stream_details(interaction, "missing-session")

    embed = interaction.followup.messages[0][1]["embed"]
    assert embed.title == "❌ Stream Details Unavailable"


class _FakeModalResponse:
    def __init__(self):
        self.modals = []
        self.messages = []

    async def defer(self, ephemeral=False):
        self.ephemeral = ephemeral

    async def send_message(self, *args, **kwargs):
        self.messages.append((args, kwargs))

    async def send_modal(self, modal):
        self.modals.append(modal)


class _FakeModalInteraction(_FakeInteraction):
    def __init__(self, user_id=123):
        super().__init__(user_id=user_id)
        self.response = _FakeModalResponse()


@pytest.mark.asyncio
async def test_kill_callback_refuses_unauthorized_users():
    # The button is hidden for regular users, but its custom_id can be replayed,
    # so the callback has to re-check instead of trusting the visible view.
    core = make_jellyfin_core()
    core.AUTHORIZED_USERS = [999]
    callback = StreamDetailsView(core)._create_kill_callback("abc123")
    interaction = _FakeModalInteraction(user_id=123)

    await callback(interaction)

    assert interaction.response.modals == []
    assert interaction.response.messages[0][0][0] == "❌ You are not authorized to kill streams."


@pytest.mark.asyncio
async def test_kill_callback_opens_the_modal_for_authorized_users():
    core = make_jellyfin_core()
    core.AUTHORIZED_USERS = [123]
    callback = StreamDetailsView(core)._create_kill_callback("abc123")
    interaction = _FakeModalInteraction(user_id=123)

    await callback(interaction)

    assert interaction.response.messages == []
    assert [modal.session_key for modal in interaction.response.modals] == ["abc123"]
