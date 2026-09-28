import io
from types import SimpleNamespace

import discord
import pytest

from cogs.media_core.plex.embeds.stream_embeds import (
    _format_connection_info,
    _format_dynamic_range_label,
    create_detailed_stream_embed,
)


def _field_value(embed: discord.Embed, name: str) -> str:
    for field in embed.fields:
        if field.name == name:
            return field.value
    raise AssertionError(f"Field {name!r} not found")


def test_format_connection_info_appends_ip_when_enabled():
    info = _format_connection_info("wan", 0, 0, ip_address="37.5.252.97", show_ip_address=True)

    assert info == "`🌐 WAN 🔓`\n`📡 37.5.252.97`"


def test_format_connection_info_hides_ip_when_disabled():
    info = _format_connection_info("lan", 1, 0, ip_address="192.168.1.100", show_ip_address=False)

    assert info == "`🏠 LAN 🔒`"


def test_format_dynamic_range_label_prefers_specific_hdr_labels():
    """Only the string is set - the DoVi flag would produce the label on its
    own, so setting both left the string parsing untested."""
    label = _format_dynamic_range_label({"stream_video_dynamic_range": "Dolby Vision/HDR10"})

    assert label == "HDR10/DoVi"


def test_format_dynamic_range_label_reads_the_dovi_flag_without_a_string():
    label = _format_dynamic_range_label({"stream_video_dovi_present": 1})

    assert label == "DoVi"


def test_format_dynamic_range_label_keeps_plain_hdr_when_no_specific_variant_exists():
    label = _format_dynamic_range_label(
        {
            "stream_video_dynamic_range": "HDR",
            "stream_video_dovi_present": 0,
        }
    )

    assert label == "HDR"


@pytest.mark.asyncio
async def test_create_detailed_stream_embed_uses_mapped_user_footer_icon():
    session = SimpleNamespace(sessionKey=123, usernames=["raw_user"])
    plex_core = SimpleNamespace(
        user_mapping={"raw_user": "Mapped User"},
        config={
            "dashboard": {
                "name": "Plex Dashboard",
                "icon_url": "https://example.com/dashboard.png",
                "footer_icon_url": "https://example.com/footer.png",
            }
        },
    )

    tautulli_data = {
        "media_type": "movie",
        "title": "Example Movie",
        "year": "2026",
        "summary": "",
        "library_name": "Movies",
        "player": "LIVING-ROOM-PC",
        "product": "Plex for Windows",
        "view_offset": "0",
        "duration": "1000",
        "location": "lan",
        "secure": 1,
        "relay": 0,
        "state": "playing",
        "video_resolution": "1080",
        "video_dynamic_range": "HDR10 / HDR",
        "video_dovi_present": 1,
        "bitrate": "1000",
        "bandwidth": "1200",
        "container": "mkv",
        "audio_language": "German",
        "transcode_decision": "direct play",
        "user_thumb": "https://example.com/user.png",
    }

    tautulli_client = SimpleNamespace()

    async def fake_fetch_session(session_key):
        return tautulli_data

    async def fake_get_thumbnail(data):
        return None

    async def fake_get_cached_user_thumb_file(url):
        return discord.File(io.BytesIO(b"avatar"), filename="user_avatar.png")

    tautulli_client.fetch_session = fake_fetch_session
    tautulli_client.get_thumbnail = fake_get_thumbnail
    tautulli_client.get_cached_user_thumb_file = fake_get_cached_user_thumb_file

    plex_core.stream_service = SimpleNamespace()

    embed, files = await create_detailed_stream_embed(
        session,
        plex_core,
        tautulli_client,
    )

    assert isinstance(files, discord.File)
    assert embed.footer.text == "Mapped User"
    assert embed.footer.icon_url == "attachment://user_avatar.png"
    assert _field_value(embed, "📱 Player") == "`LIVING-ROOM-PC (Windows)`"
    assert _field_value(embed, "📺 Resolution") == "`1080p • HDR10/DoVi`"
    assert _field_value(embed, "📊 Bitrate") == "`1.0 / 1.2 Mbps`"
    # Bar and time only: with the percentage the narrow inline field wrapped
    # into three lines.
    assert _field_value(embed, "📊 Progress") == "`[░░░░░░░░░░]`\n`00:00 / 00:01`"


@pytest.mark.asyncio
async def test_create_detailed_stream_embed_omits_audio_language_separator_when_missing():
    session = SimpleNamespace(sessionKey=123, usernames=["raw_user"])
    plex_core = SimpleNamespace(
        user_mapping={"raw_user": "Mapped User"},
        config={
            "dashboard": {
                "name": "Plex Dashboard",
                "icon_url": "https://example.com/dashboard.png",
                "footer_icon_url": "https://example.com/footer.png",
            }
        },
    )

    tautulli_data = {
        "media_type": "movie",
        "title": "Example Movie",
        "year": "2026",
        "summary": "",
        "library_name": "Movies",
        "player": "iPhone",
        "product": "Plex for iOS",
        "view_offset": "0",
        "duration": "1000",
        "location": "wan",
        "secure": 0,
        "relay": 0,
        "state": "playing",
        "video_resolution": "1080",
        "bitrate": "1000",
        "container": "mkv",
        "transcode_decision": "transcode",
        "transcode_throttled": 0,
        "stream_container": "mkv",
        "stream_container_decision": "copy",
        "video_codec": "hevc",
        "stream_video_codec": "h264",
        "stream_video_resolution": "480",
        "stream_video_decision": "transcode",
        "audio_codec": "ac3",
        "audio_profile": "",
        "audio_channels": "6",
        "audio_language": "",
        "stream_audio_codec": "opus",
        "stream_audio_profile": "",
        "stream_audio_channels": "6",
        "stream_audio_decision": "transcode",
    }

    tautulli_client = SimpleNamespace()

    async def fake_fetch_session(session_key):
        return tautulli_data

    async def fake_get_thumbnail(data):
        return None

    tautulli_client.fetch_session = fake_fetch_session
    tautulli_client.get_thumbnail = fake_get_thumbnail

    plex_core.stream_service = SimpleNamespace()

    embed, _files = await create_detailed_stream_embed(
        session,
        plex_core,
        tautulli_client,
    )

    assert _field_value(embed, "🔄 Transcoding") == "\n".join(
        [
            "**Stream:** Transcode",
            "**Container:** `MKV` (Direct Stream)",
            "**Video:** Transcode (`HEVC 1080p` → `H264 480p`)",
            "**Audio:** Transcode (`AC3 5.1` → `Opus 5.1`)",
        ]
    )


async def _bitrate_field(bitrate, bandwidth):
    """Render a minimal direct-play embed and return its bitrate field."""
    session = SimpleNamespace(sessionKey=1, usernames=["raw_user"])
    plex_core = SimpleNamespace(user_mapping={}, config={"dashboard": {}})

    tautulli_data = {
        "media_type": "movie",
        "title": "Example Movie",
        "summary": "",
        "library_name": "Movies",
        "player": "LIVING-ROOM-PC",
        "view_offset": "0",
        "duration": "1000",
        "state": "playing",
        "video_resolution": "1080",
        "container": "mkv",
        "transcode_decision": "direct play",
        "bitrate": bitrate,
        "bandwidth": bandwidth,
    }

    async def fake_fetch_session(session_key):
        return tautulli_data

    async def fake_get_thumbnail(data):
        return None

    tautulli_client = SimpleNamespace(
        fetch_session=fake_fetch_session,
        get_thumbnail=fake_get_thumbnail,
    )

    embed, _ = await create_detailed_stream_embed(session, plex_core, tautulli_client)
    return _field_value(embed, "📊 Bitrate")


@pytest.mark.asyncio
async def test_bitrate_keeps_its_unit_when_it_differs_from_bandwidth():
    assert await _bitrate_field("800", "5000") == "`800 Kbps / 5.0 Mbps`"


@pytest.mark.asyncio
async def test_bitrate_drops_the_shared_unit():
    assert await _bitrate_field("4500", "5000") == "`4.5 / 5.0 Mbps`"


@pytest.mark.asyncio
async def test_unknown_bitrate_keeps_the_bandwidth_unit():
    assert await _bitrate_field("0", "5000") == "`Unknown / 5.0 Mbps`"


async def _embed_for(tautulli_data):
    """Render a detail embed for a raw Tautulli session payload."""
    session = SimpleNamespace(sessionKey=1, usernames=["raw_user"])
    plex_core = SimpleNamespace(user_mapping={}, config={"dashboard": {}})

    async def fake_fetch_session(session_key):
        return tautulli_data

    async def fake_get_thumbnail(data):
        return None

    tautulli_client = SimpleNamespace(
        fetch_session=fake_fetch_session,
        get_thumbnail=fake_get_thumbnail,
    )

    embed, _ = await create_detailed_stream_embed(session, plex_core, tautulli_client)
    return embed


@pytest.mark.asyncio
async def test_detail_embed_survives_null_session_fields():
    """Hardening: a null instead of "" must not collapse the embed."""
    embed = await _embed_for(
        {
            "media_type": "movie",
            "title": "Example Movie",
            "summary": "",
            "library_name": None,
            "player": None,
            "product": None,
            "view_offset": "0",
            "duration": "1000",
            "state": None,
            "video_resolution": "1080",
            "container": None,
            "transcode_decision": "transcode",
            "stream_container": None,
            "stream_container_decision": "copy",
            "video_codec": None,
            "stream_video_codec": None,
            "stream_video_decision": "copy",
        }
    )

    assert embed.title == "🎥 Example Movie"
    assert _field_value(embed, "📱 Player") == "`Unknown`"
    assert _field_value(embed, "📚 Library") == "`Unknown`"
    assert _field_value(embed, "📁 Container") == "`UNKNOWN`"


@pytest.mark.asyncio
async def test_detail_embed_keeps_current_output_for_empty_strings():
    """Tautulli reports "" today; that path must stay exactly as it was."""
    embed = await _embed_for(
        {
            "media_type": "movie",
            "title": "Example Movie",
            "summary": "",
            "library_name": "",
            "player": "",
            "product": "",
            "view_offset": "0",
            "duration": "1000",
            "state": "",
            "video_resolution": "1080",
            "container": "",
            "transcode_decision": "direct play",
        }
    )

    assert _field_value(embed, "📱 Player") == "``"
    assert _field_value(embed, "📚 Library") == "``"
    assert _field_value(embed, "📁 Container") == "``"


def _wan_tautulli_data():
    return {
        "media_type": "movie",
        "title": "Example Movie",
        "year": "2026",
        "summary": "",
        "library_name": "Movies",
        "player": "LIVING-ROOM-PC",
        "product": "Plex for Windows",
        "view_offset": "0",
        "duration": "1000",
        "location": "wan",
        "secure": 1,
        "relay": 0,
        "ip_address": "37.5.252.97",
        "state": "playing",
        "video_resolution": "1080",
        "bitrate": "1000",
        "bandwidth": "1200",
        "container": "mkv",
        "audio_language": "German",
        "transcode_decision": "direct play",
    }


async def _build_wan_embed(*, show_connection_ip):
    session = SimpleNamespace(sessionKey=123, usernames=["raw_user"])
    plex_core = SimpleNamespace(
        user_mapping={},
        config={"dashboard": {"name": "Plex Dashboard", "icon_url": "", "footer_icon_url": ""}},
        stream_service=SimpleNamespace(),
    )

    async def fake_fetch_session(session_key):
        return _wan_tautulli_data()

    async def fake_get_thumbnail(data):
        return None

    async def fake_get_cached_user_thumb_file(url):
        return None

    tautulli_client = SimpleNamespace(
        fetch_session=fake_fetch_session,
        get_thumbnail=fake_get_thumbnail,
        get_cached_user_thumb_file=fake_get_cached_user_thumb_file,
    )

    embed, _ = await create_detailed_stream_embed(
        session,
        plex_core,
        tautulli_client,
        show_connection_ip=show_connection_ip,
    )
    return embed


@pytest.mark.asyncio
async def test_detailed_embed_hides_the_client_ip_when_not_permitted():
    # The view tests assert this kwarg against a faked embed builder, so the
    # wiring from the kwarg to the connection field is only covered here.
    embed = await _build_wan_embed(show_connection_ip=False)

    assert _field_value(embed, "🌍 Connection") == "`🌐 WAN 🔒`"
    assert "37.5.252.97" not in str(embed.to_dict())


@pytest.mark.asyncio
async def test_detailed_embed_shows_the_client_ip_when_permitted():
    embed = await _build_wan_embed(show_connection_ip=True)

    assert _field_value(embed, "🌍 Connection") == "`🌐 WAN 🔒`\n`📡 37.5.252.97`"


@pytest.mark.asyncio
async def test_detail_embed_sanitizes_and_caps_code_block_fields():
    """A Plex client picks its own device name, so it must not break the fence."""
    embed = await _embed_for(
        {
            "media_type": "movie",
            "title": "Example Movie",
            "summary": "",
            "library_name": "M" * 300,
            "player": "LIVING-ROOM-PC`` @everyone",
            "product": "",
            "view_offset": "0",
            "duration": "1000",
            "state": "playing",
            "video_resolution": "1080",
            "container": "mkv",
            "transcode_decision": "direct play",
        }
    )

    player = _field_value(embed, "📱 Player")
    library = _field_value(embed, "📚 Library")
    assert player == "`LIVING-ROOM-PC'' @everyone`"
    assert len(library) <= 102


@pytest.mark.asyncio
async def test_detailed_embed_never_links_a_tautulli_avatar_url(monkeypatch):
    """A failed avatar download must not fall back to the raw URL.

    Tautulli's pms_image_proxy takes the API key as a query parameter, and an
    embed URL is fetched by Discord and by every client rendering the message.
    """
    session = SimpleNamespace(sessionKey=1, usernames=["raw_user"])
    plex_core = SimpleNamespace(
        user_mapping={},
        config={"dashboard": {"name": "Dash", "icon_url": "", "footer_icon_url": ""}},
        plex_client=SimpleNamespace(),
        stream_service=None,
    )

    async def failing_thumb(url):
        return None

    async def fake_fetch_session(session_key):
        return {
            "media_type": "movie",
            "title": "Movie",
            "user_thumb": "http://tautulli.example/pms_image_proxy?img=x&apikey=SECRET",
            "user_id": "1",
        }

    async def no_poster(data):
        return None

    tautulli_client = SimpleNamespace(
        fetch_session=fake_fetch_session,
        get_thumbnail=no_poster,
        get_cached_user_thumb_file=failing_thumb,
    )

    embed, _files = await create_detailed_stream_embed(session, plex_core, tautulli_client)

    # Guard against asserting on an error embed, which would pass vacuously.
    assert "❌" not in (embed.title or ""), embed.title
    assert "SECRET" not in str(embed.footer.icon_url or "")
    assert "apikey" not in str(embed.footer.icon_url or "")


def _make_title_link_inputs(links_config=None, media_type="movie"):
    session = SimpleNamespace(
        sessionKey=123,
        usernames=["raw_user"],
        type=media_type,
        ratingKey=42,
        parentRatingKey=7,
    )
    stream_details = {}
    if links_config is not None:
        stream_details["links"] = links_config

    plex_core = SimpleNamespace(
        user_mapping={},
        config={
            "dashboard": {
                "name": "Plex Dashboard",
                "icon_url": "https://example.com/dashboard.png",
                "footer_icon_url": "https://example.com/footer.png",
            },
            "stream_details": stream_details,
        },
        plex=SimpleNamespace(machineIdentifier="abc123"),
        stream_service=SimpleNamespace(),
    )

    tautulli_data = {
        "media_type": "movie",
        "title": "Example Movie",
        "year": "2026",
        "summary": "",
        "library_name": "Movies",
        "player": "LIVING-ROOM-PC",
        "product": "Plex for Windows",
        "view_offset": "0",
        "duration": "1000",
        "location": "lan",
        "secure": 1,
        "relay": 0,
        "state": "playing",
        "video_resolution": "1080",
        "bitrate": "1000",
        "bandwidth": "1200",
        "container": "mkv",
        "audio_language": "German",
        "transcode_decision": "direct play",
    }

    async def fake_fetch_session(session_key):
        return tautulli_data

    async def fake_get_thumbnail(data):
        return None

    tautulli_client = SimpleNamespace(
        fetch_session=fake_fetch_session,
        get_thumbnail=fake_get_thumbnail,
    )

    return session, plex_core, tautulli_client


@pytest.mark.asyncio
async def test_detailed_stream_embed_title_links_to_plex_web():
    session, plex_core, tautulli_client = _make_title_link_inputs()

    embed, _ = await create_detailed_stream_embed(session, plex_core, tautulli_client)

    assert (
        embed.url
        == "https://app.plex.tv/desktop#!/server/abc123/details?key=%2Flibrary%2Fmetadata%2F42"
    )


@pytest.mark.asyncio
async def test_detailed_stream_embed_title_follows_a_configured_base_url():
    session, plex_core, tautulli_client = _make_title_link_inputs(
        links_config={"plex": {"base_url": "https://plex.example.com/web"}}
    )

    embed, _ = await create_detailed_stream_embed(session, plex_core, tautulli_client)

    assert (
        embed.url
        == "https://plex.example.com/web#!/server/abc123/details?key=%2Flibrary%2Fmetadata%2F42"
    )


@pytest.mark.asyncio
async def test_detailed_stream_embed_title_stays_plain_when_the_link_is_off():
    # Turning the button off has to turn the title link off with it.
    session, plex_core, tautulli_client = _make_title_link_inputs(
        links_config={"plex": {"enabled": False}}
    )

    embed, _ = await create_detailed_stream_embed(session, plex_core, tautulli_client)

    assert embed.url is None
