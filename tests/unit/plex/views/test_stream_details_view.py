import io
from types import SimpleNamespace

import discord
import pytest

from cogs.media_core.plex.views.stream_details_view import StreamDetailsView


def make_plex_core(
    button_location="stream_details", tautulli_enabled=True, show_ip_for_authorized_users=False
):
    core = SimpleNamespace(
        config={
            "global_stats": {"button_location": button_location},
            "stream_details": {"show_ip_for_authorized_users": show_ip_for_authorized_users},
            "dashboard": {
                "name": "Plex Dashboard",
                "icon_url": "https://example.com/plex.png",
                "footer_icon_url": "https://example.com/footer.png",
            },
        },
        TAUTULLI_URL="http://tautulli" if tautulli_enabled else None,
        TAUTULLI_API_KEY="key" if tautulli_enabled else None,
        active_sessions={},
        user_mapping={"verylongusername123": "Display Name That Is Too Long"},
        AUTHORIZED_USERS=[],
        plex=True,
        tautulli_client=SimpleNamespace(),
    )
    core._get_session_cache_key = lambda session: (
        str(session.sessionKey) if hasattr(session, "sessionKey") else None
    )

    async def resolve_active_session(session_key):
        return core.active_sessions.get(session_key)

    core.resolve_active_session = resolve_active_session
    return core


def make_session(
    session_key=1, username="verylongusername123", section="Movies", media_type="movie"
):
    return SimpleNamespace(
        sessionKey=session_key,
        usernames=[username],
        librarySectionTitle=section,
        type=media_type,
    )


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
async def test_create_buttons_places_global_stats_first_when_enabled():
    view = StreamDetailsView(make_plex_core(button_location="both"))

    await view.create_buttons([make_session()])

    labels = [child.label for child in view.children]

    assert labels == ["Global Stats", "Stream 1 - Display Name..."]
    assert view.children[0].custom_id == "global_stats:dashboard"
    assert view.children[1].custom_id == "stream_details:1"


@pytest.mark.asyncio
async def test_create_buttons_dashboard_only_shows_global_stats_without_streams():
    view = StreamDetailsView(make_plex_core(button_location="dashboard"))

    await view.create_buttons([])

    assert [child.label for child in view.children] == ["Global Stats"]


@pytest.mark.asyncio
async def test_create_buttons_stream_details_only_does_not_add_dashboard_button():
    view = StreamDetailsView(make_plex_core(button_location="stream_details"))

    await view.create_buttons([make_session()], {"Movies": {"emoji": "🎥"}})

    assert [child.label for child in view.children] == ["Stream 1 - Display Name..."]


@pytest.mark.asyncio
async def test_create_buttons_skips_everything_without_tautulli_and_without_admins():
    view = StreamDetailsView(make_plex_core(button_location="both", tautulli_enabled=False))

    await view.create_buttons([make_session()], {"Movies": {"emoji": "🎥"}})

    assert view.children == []


@pytest.mark.asyncio
async def test_create_buttons_keeps_stream_buttons_without_tautulli_for_kill_stream():
    core = make_plex_core(button_location="both", tautulli_enabled=False)
    core.AUTHORIZED_USERS = [123]
    view = StreamDetailsView(core)

    await view.create_buttons([make_session()], {"Movies": {"emoji": "🎥"}})

    assert [child.label for child in view.children] == ["Stream 1 - Display Name..."]


@pytest.mark.asyncio
async def test_show_stream_details_without_tautulli_still_offers_kill_stream():
    core = make_plex_core(tautulli_enabled=False)
    core.AUTHORIZED_USERS = [123]
    session = make_session()
    core.active_sessions[str(session.sessionKey)] = session
    view = StreamDetailsView(core)
    interaction = _FakeInteraction(user_id=123)

    await view.show_stream_details(interaction, str(session.sessionKey))

    kwargs = interaction.followup.messages[0][1]
    assert kwargs["embed"].footer.text == "Tautulli Not Configured"
    assert [child.label for child in kwargs["view"].children] == ["Kill Stream"]


@pytest.mark.asyncio
async def test_show_stream_details_without_tautulli_sends_no_view_for_regular_users():
    core = make_plex_core(tautulli_enabled=False)
    core.AUTHORIZED_USERS = [999]
    session = make_session()
    core.active_sessions[str(session.sessionKey)] = session
    view = StreamDetailsView(core)
    interaction = _FakeInteraction(user_id=123)

    await view.show_stream_details(interaction, str(session.sessionKey))

    kwargs = interaction.followup.messages[0][1]
    assert kwargs["embed"].footer.text == "Tautulli Not Configured"
    assert kwargs["view"] is None


@pytest.mark.asyncio
async def test_show_stream_details_returns_styled_error_when_session_missing():
    core = make_plex_core(button_location="both")
    view = StreamDetailsView(core)
    interaction = _FakeInteraction()

    await view.show_stream_details(interaction, "missing-session")

    assert interaction.followup.messages
    embed = interaction.followup.messages[0][1]["embed"]
    assert embed.title == "❌ Stream Details Unavailable"
    assert "session cache expired" in embed.description
    assert embed.author.name == "Plex Dashboard"
    assert embed.footer.text == "Plex Stream Status"


@pytest.mark.asyncio
async def test_show_stream_details_passes_ip_visibility_for_authorized_users(monkeypatch):
    captured = {}
    core = make_plex_core(button_location="both", show_ip_for_authorized_users=True)
    core.AUTHORIZED_USERS = [123]
    session = make_session()
    core.active_sessions[str(session.sessionKey)] = session

    async def fake_create_detailed_stream_embed(*args, **kwargs):
        captured["show_connection_ip"] = kwargs.get("show_connection_ip")
        return discord.Embed(title="Stream"), None

    async def fake_fetch_session(session_key):
        return None

    monkeypatch.setattr(
        "cogs.media_core.plex.embeds.stream_embeds.create_detailed_stream_embed",
        fake_create_detailed_stream_embed,
    )
    core.tautulli_client.fetch_session = fake_fetch_session

    view = StreamDetailsView(core)
    interaction = _FakeInteraction(user_id=123)

    await view.show_stream_details(interaction, str(session.sessionKey))

    assert captured["show_connection_ip"] is True


@pytest.mark.asyncio
async def test_show_stream_details_hides_ip_for_unauthorized_users(monkeypatch):
    captured = {}
    core = make_plex_core(button_location="both", show_ip_for_authorized_users=True)
    core.AUTHORIZED_USERS = [999]
    session = make_session()
    core.active_sessions[str(session.sessionKey)] = session

    async def fake_create_detailed_stream_embed(*args, **kwargs):
        captured["show_connection_ip"] = kwargs.get("show_connection_ip")
        return discord.Embed(title="Stream"), None

    async def fake_fetch_session(session_key):
        return None

    monkeypatch.setattr(
        "cogs.media_core.plex.embeds.stream_embeds.create_detailed_stream_embed",
        fake_create_detailed_stream_embed,
    )
    core.tautulli_client.fetch_session = fake_fetch_session

    view = StreamDetailsView(core)
    interaction = _FakeInteraction(user_id=123)

    await view.show_stream_details(interaction, str(session.sessionKey))

    assert captured["show_connection_ip"] is False


@pytest.mark.asyncio
async def test_show_stream_details_sends_multiple_attachments(monkeypatch):
    core = make_plex_core(button_location="both")
    session = make_session()
    core.active_sessions[str(session.sessionKey)] = session

    async def fake_create_detailed_stream_embed(*args, **kwargs):
        first = discord.File(fp=io.BytesIO(b"poster"), filename="poster.jpg")
        second = discord.File(fp=io.BytesIO(b"avatar"), filename="user_avatar.png")
        return discord.Embed(title="Stream"), [first, second]

    async def fake_fetch_session(session_key):
        return None

    monkeypatch.setattr(
        "cogs.media_core.plex.embeds.stream_embeds.create_detailed_stream_embed",
        fake_create_detailed_stream_embed,
    )
    core.tautulli_client.fetch_session = fake_fetch_session

    view = StreamDetailsView(core)
    interaction = _FakeInteraction()

    await view.show_stream_details(interaction, str(session.sessionKey))

    kwargs = interaction.followup.messages[0][1]
    assert "files" in kwargs
    assert [file.filename for file in kwargs["files"]] == ["poster.jpg", "user_avatar.png"]


@pytest.mark.asyncio
async def test_show_stream_details_is_open_to_everyone_by_default():
    core = make_plex_core()
    core.AUTHORIZED_USERS = [999]
    view = StreamDetailsView(core)
    interaction = _FakeInteraction(user_id=123)

    await view.show_stream_details(interaction, "missing-session")

    embed = interaction.followup.messages[0][1]["embed"]
    assert embed.title == "❌ Stream Details Unavailable"


@pytest.mark.asyncio
async def test_show_stream_details_rejects_unauthorized_users_when_restricted():
    core = make_plex_core()
    core.config["stream_details"]["restrict_to_authorized"] = True
    core.AUTHORIZED_USERS = [999]
    view = StreamDetailsView(core)
    interaction = _FakeInteraction(user_id=123)

    await view.show_stream_details(interaction, "session-1")

    assert interaction.followup.messages[0][0][0] == (
        "❌ Stream details are restricted to authorized users on this server."
    )


@pytest.mark.asyncio
async def test_show_stream_details_allows_authorized_users_when_restricted():
    core = make_plex_core()
    core.config["stream_details"]["restrict_to_authorized"] = True
    core.AUTHORIZED_USERS = [123]
    view = StreamDetailsView(core)
    interaction = _FakeInteraction(user_id=123)

    await view.show_stream_details(interaction, "missing-session")

    embed = interaction.followup.messages[0][1]["embed"]
    assert embed.title == "❌ Stream Details Unavailable"


@pytest.mark.asyncio
async def test_show_global_stats_is_open_to_everyone_by_default():
    core = make_plex_core(button_location="dashboard")
    core.AUTHORIZED_USERS = [999]

    async def fake_fetch_global_server_stats():
        return None

    core.tautulli_client.fetch_global_server_stats = fake_fetch_global_server_stats
    view = StreamDetailsView(core)
    interaction = _FakeInteraction(user_id=123)

    await view.show_global_stats(interaction)

    assert interaction.followup.messages[0][0][0] == "❌ Could not fetch global server statistics."


@pytest.mark.asyncio
async def test_show_global_stats_rejects_unauthorized_users_when_restricted():
    core = make_plex_core(button_location="dashboard")
    core.config["global_stats"]["restrict_to_authorized"] = True
    core.AUTHORIZED_USERS = [999]
    view = StreamDetailsView(core)
    interaction = _FakeInteraction(user_id=123)

    await view.show_global_stats(interaction)

    assert interaction.followup.messages[0][0][0] == (
        "❌ Global statistics are restricted to authorized users on this server."
    )


@pytest.mark.asyncio
async def test_show_global_stats_allows_authorized_users_when_restricted():
    core = make_plex_core(button_location="dashboard")
    core.config["global_stats"]["restrict_to_authorized"] = True
    core.AUTHORIZED_USERS = [123]

    async def fake_fetch_global_server_stats():
        return None

    core.tautulli_client.fetch_global_server_stats = fake_fetch_global_server_stats
    view = StreamDetailsView(core)
    interaction = _FakeInteraction(user_id=123)

    await view.show_global_stats(interaction)

    assert interaction.followup.messages[0][0][0] == "❌ Could not fetch global server statistics."


@pytest.mark.asyncio
async def test_show_user_stats_rejects_unauthorized_users_before_asking_tautulli():
    core = make_plex_core()
    core.config["user_stats"] = {"restrict_to_authorized": True}
    core.AUTHORIZED_USERS = [999]
    calls = []

    async def fake_fetch_user_watch_time_stats(user_id):
        calls.append(user_id)
        return None

    core.tautulli_client.fetch_user_watch_time_stats = fake_fetch_user_watch_time_stats
    view = StreamDetailsView(core)
    interaction = _FakeInteraction(user_id=123)

    await view.show_user_stats(interaction, "42")

    assert interaction.followup.messages[0][0][0] == (
        "❌ User statistics are restricted to authorized users on this server."
    )
    assert calls == []


@pytest.mark.asyncio
async def test_show_user_stats_stays_open_to_everyone_by_default():
    core = make_plex_core()
    core.AUTHORIZED_USERS = []
    calls = []

    async def fake_fetch_user_watch_time_stats(user_id):
        calls.append(user_id)
        return None

    core.tautulli_client.fetch_user_watch_time_stats = fake_fetch_user_watch_time_stats
    view = StreamDetailsView(core)
    interaction = _FakeInteraction(user_id=123)

    await view.show_user_stats(interaction, "42")

    assert calls == ["42"]
    assert interaction.followup.messages[0][0][0] == "❌ Could not fetch user statistics."


@pytest.mark.asyncio
async def test_show_user_stats_allows_authorized_users_when_restricted():
    core = make_plex_core()
    core.config["user_stats"] = {"restrict_to_authorized": True}
    core.AUTHORIZED_USERS = [123]
    calls = []

    async def fake_fetch_user_watch_time_stats(user_id):
        calls.append(user_id)
        return None

    core.tautulli_client.fetch_user_watch_time_stats = fake_fetch_user_watch_time_stats
    view = StreamDetailsView(core)
    interaction = _FakeInteraction(user_id=123)

    await view.show_user_stats(interaction, "42")

    assert calls == ["42"]
    assert interaction.followup.messages[0][0][0] == "❌ Could not fetch user statistics."


@pytest.mark.asyncio
async def test_create_buttons_takes_the_section_emoji_from_the_passed_stats():
    view = StreamDetailsView(make_plex_core())

    await view.create_buttons([make_session()], {"Movies": {"emoji": "🍿"}})

    stream_button = view.children[-1]
    assert str(stream_button.emoji) == "🍿"


@pytest.mark.asyncio
async def test_create_buttons_falls_back_to_the_media_type_emoji_without_stats():
    view = StreamDetailsView(make_plex_core())

    await view.create_buttons([make_session()])

    stream_button = view.children[-1]
    assert str(stream_button.emoji) == "🎥"


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
    core = make_plex_core()
    core.AUTHORIZED_USERS = [999]
    callback = StreamDetailsView(core)._create_kill_callback("1")
    interaction = _FakeModalInteraction(user_id=123)

    await callback(interaction)

    assert interaction.response.modals == []
    assert interaction.response.messages[0][0][0] == "❌ You are not authorized to kill streams."


@pytest.mark.asyncio
async def test_kill_callback_opens_the_modal_for_authorized_users():
    core = make_plex_core()
    core.AUTHORIZED_USERS = [123]
    callback = StreamDetailsView(core)._create_kill_callback("1")
    interaction = _FakeModalInteraction(user_id=123)

    await callback(interaction)

    assert interaction.response.messages == []
    assert [modal.session_key for modal in interaction.response.modals] == ["1"]


def make_link_session(media_type="movie", rating_key=42, parent_rating_key=7):
    session = make_session(media_type=media_type)
    session.ratingKey = rating_key
    session.parentRatingKey = parent_rating_key
    return session


def test_the_plex_link_points_at_plex_web():
    core = make_plex_core()
    core.plex = SimpleNamespace(machineIdentifier="abc123")
    view = discord.ui.View()

    StreamDetailsView(core)._add_link_buttons(view, make_link_session())

    assert [(item.label, item.url) for item in view.children] == [
        (
            "Plex",
            "https://app.plex.tv/desktop#!/server/abc123/details?key=%2Flibrary%2Fmetadata%2F42",
        )
    ]


def test_music_links_to_the_album():
    # Plex Web has no page for a single track.
    core = make_plex_core()
    core.plex = SimpleNamespace(machineIdentifier="abc123")
    view = discord.ui.View()

    StreamDetailsView(core)._add_link_buttons(view, make_link_session(media_type="track"))

    assert [item.url for item in view.children] == [
        "https://app.plex.tv/desktop#!/server/abc123/details?key=%2Flibrary%2Fmetadata%2F7"
    ]


def test_the_plex_link_is_left_out_without_a_server_identifier():
    core = make_plex_core()
    core.plex = SimpleNamespace(machineIdentifier=None)
    view = discord.ui.View()

    StreamDetailsView(core)._add_link_buttons(view, make_link_session())

    assert view.children == []


def test_the_plex_link_can_be_turned_off_in_the_config():
    core = make_plex_core()
    core.config["stream_details"]["links"] = {"plex": {"enabled": False}}
    core.plex = SimpleNamespace(machineIdentifier="abc123")
    view = discord.ui.View()

    StreamDetailsView(core)._add_link_buttons(view, make_link_session())

    assert view.children == []


def test_the_plex_link_follows_a_configured_base_url():
    core = make_plex_core()
    core.config["stream_details"]["links"] = {"plex": {"base_url": "https://plex.example.com/web"}}
    core.plex = SimpleNamespace(machineIdentifier="abc123")
    view = discord.ui.View()

    StreamDetailsView(core)._add_link_buttons(view, make_link_session())

    assert [item.url for item in view.children] == [
        "https://plex.example.com/web#!/server/abc123/details?key=%2Flibrary%2Fmetadata%2F42"
    ]
