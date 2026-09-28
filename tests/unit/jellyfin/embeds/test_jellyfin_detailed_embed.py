from types import SimpleNamespace

import discord
import pytest

from cogs.media_core.jellyfin.embeds.stream_embeds import create_detailed_stream_embed


def make_jellyfin_core(config=None, user_mapping=None, library_names=None):
    """Minimal JellyfinCore stand-in; no thumbnail means no HTTP access."""
    client = SimpleNamespace(
        get_thumbnail_url=lambda item_id, image_type="Primary": None,
    )

    async def get_item_details(item_id, user_id=None):
        return None

    client.get_item_details = get_item_details

    names = library_names or {}

    async def resolve_library_display_name(
        item_id, collection_type, fallback="Unknown", user_id=None
    ):
        return names.get(collection_type, fallback)

    service = SimpleNamespace(
        get_library_display_name=lambda collection_type, fallback="Unknown": names.get(
            collection_type, fallback
        ),
        resolve_library_display_name=resolve_library_display_name,
    )

    return SimpleNamespace(
        config=config if config is not None else {"dashboard": {}},
        user_mapping=user_mapping if user_mapping is not None else {},
        jellyfin_client=client,
        jellyfin_service=service,
    )


def make_episode_session(**overrides):
    session = {
        "Id": "session-1",
        "UserName": "alice",
        "UserId": "user-1",
        "Client": "Jellyfin Web",
        "DeviceName": "Firefox",
        "RemoteEndPoint": "192.168.1.5:53124",
        "PlayState": {"PositionTicks": 0, "IsPaused": False},
        "NowPlayingItem": {
            "Type": "Episode",
            "Name": "Pilot",
            "SeriesName": "Series",
            "SeriesId": "series-1",
            "ParentId": "season-1",
            "ParentIndexNumber": 1,
            "IndexNumber": 2,
            "RunTimeTicks": 10_000_000,
            "Container": "mkv",
            "MediaStreams": [{"Type": "Video", "Height": 1080, "Codec": "h264"}],
        },
    }
    session["NowPlayingItem"].update(overrides.pop("now_playing", {}))
    session.update(overrides)
    return session


def field_value(embed, name):
    return next(field.value for field in embed.fields if field.name == name)


@pytest.mark.asyncio
async def test_detailed_embed_handles_episode_without_index_numbers():
    session = make_episode_session(now_playing={"ParentIndexNumber": None, "IndexNumber": None})

    embed, _ = await create_detailed_stream_embed(session, make_jellyfin_core())

    assert embed.title == "📺 Series - S00E00 - Pilot"


@pytest.mark.asyncio
async def test_detailed_embed_hides_subtitles_when_viewer_disabled_them():
    session = make_episode_session(
        now_playing={
            "MediaStreams": [
                {"Type": "Video", "Height": 1080, "Codec": "h264"},
                {
                    "Type": "Subtitle",
                    "Index": 3,
                    "Language": "ger",
                    "Codec": "subrip",
                    "IsDefault": True,
                },
            ]
        },
    )
    session["PlayState"]["SubtitleStreamIndex"] = -1

    embed, _ = await create_detailed_stream_embed(session, make_jellyfin_core())

    assert not any(field.name == "📝 Subtitle" for field in embed.fields)


@pytest.mark.asyncio
async def test_detailed_embed_shows_selected_subtitle_stream():
    session = make_episode_session(
        now_playing={
            "MediaStreams": [
                {"Type": "Video", "Height": 1080, "Codec": "h264"},
                {
                    "Type": "Subtitle",
                    "Index": 2,
                    "Language": "eng",
                    "Codec": "subrip",
                    "IsDefault": True,
                },
                {"Type": "Subtitle", "Index": 3, "Language": "ger", "Codec": "ass"},
            ]
        },
    )
    session["PlayState"]["SubtitleStreamIndex"] = 3

    embed, _ = await create_detailed_stream_embed(session, make_jellyfin_core())

    # "ger" is what Jellyfin reports; the embed resolves it so Plex and Jellyfin
    # show the same wording for the same language.
    assert field_value(embed, "📝 Subtitle") == "`German (ASS)`"


@pytest.mark.asyncio
async def test_detailed_embed_does_not_label_transcode_reasons_as_throttled():
    session = make_episode_session(
        TranscodingInfo={
            "IsVideoDirect": False,
            "IsAudioDirect": True,
            "VideoCodec": "h264",
            "Container": "mkv",
            "TranscodeReasons": ["VideoCodecNotSupported"],
        },
    )

    embed, _ = await create_detailed_stream_embed(session, make_jellyfin_core())

    assert field_value(embed, "🔄 Transcoding").splitlines()[0] == "**Stream:** Transcode"


@pytest.mark.asyncio
async def test_detailed_embed_marks_docker_network_client_as_lan():
    session = make_episode_session(RemoteEndPoint="172.20.0.5:44212")

    embed, _ = await create_detailed_stream_embed(session, make_jellyfin_core())

    assert field_value(embed, "🌍 Connection") == "`🏠 LAN`"


@pytest.mark.asyncio
async def test_detailed_embed_uses_configured_library_display_name():
    core = make_jellyfin_core(library_names={"tvshows": "Serien"})

    embed, _ = await create_detailed_stream_embed(make_episode_session(), core)

    assert field_value(embed, "📚 Library") == "`Serien`"


@pytest.mark.asyncio
async def test_detailed_embed_falls_back_to_generic_library_name():
    embed, _ = await create_detailed_stream_embed(make_episode_session(), make_jellyfin_core())

    assert field_value(embed, "📚 Library") == "`TV Shows`"


@pytest.mark.asyncio
async def test_detailed_embed_resolves_mapped_user_name():
    core = make_jellyfin_core(user_mapping={"alice": "Alice A."})

    embed, _ = await create_detailed_stream_embed(make_episode_session(), core)

    assert field_value(embed, "👤 User") == "`Alice A.`"


@pytest.mark.asyncio
async def test_detailed_embed_hides_the_client_ip_by_default():
    """Needs a WAN endpoint: a LAN client never gets an IP shown anyway, so
    asserting against the default session proved nothing about the flag."""
    embed, _ = await create_detailed_stream_embed(
        make_episode_session(RemoteEndPoint="93.184.216.34:51234"),
        make_jellyfin_core(),
    )

    assert field_value(embed, "🌍 Connection") == "`🌐 WAN`"


@pytest.mark.asyncio
async def test_detailed_embed_shows_the_client_ip_when_requested():
    embed, _ = await create_detailed_stream_embed(
        make_episode_session(RemoteEndPoint="93.184.216.34:51234"),
        make_jellyfin_core(),
        show_connection_ip=True,
    )

    assert field_value(embed, "🌍 Connection") == "`🌐 WAN`\n`📡 93.184.216.34`"


@pytest.mark.asyncio
async def test_detailed_embed_footer_names_the_viewer():
    core = make_jellyfin_core(user_mapping={"alice": "Alice A."})

    embed, _ = await create_detailed_stream_embed(make_episode_session(), core)

    assert embed.footer.text == "Alice A."


@pytest.mark.asyncio
async def test_detailed_embed_uses_the_platform_brand_color():
    core = make_jellyfin_core()
    core.jellyfin_service.embed_color = discord.Color.from_rgb(0, 164, 220)

    embed, _ = await create_detailed_stream_embed(make_episode_session(), core)

    assert embed.color == discord.Color.from_rgb(0, 164, 220)


@pytest.mark.asyncio
async def test_detailed_embed_survives_null_container_and_codecs():
    """Jellyfin reports Container/Codec as null when it could not probe them."""
    session = make_episode_session(
        now_playing={
            "Container": None,
            "MediaStreams": [
                {"Type": "Video", "Height": 1080, "Codec": None},
                {"Type": "Audio", "Codec": None, "Channels": 6, "Language": None},
                {"Type": "Subtitle", "Index": 4, "Language": None, "Codec": None},
            ],
        },
    )
    session["PlayState"]["SubtitleStreamIndex"] = 4
    session["TranscodingInfo"] = {
        "IsVideoDirect": False,
        "IsAudioDirect": False,
        "Container": None,
        "VideoCodec": None,
        "AudioCodec": None,
    }

    embed, _ = await create_detailed_stream_embed(session, make_jellyfin_core())

    assert embed.title == "📺 Series - S01E02 - Pilot"
    assert field_value(embed, "📁 Container") == "`UNKNOWN`"


@pytest.mark.asyncio
async def test_detailed_embed_survives_null_numbers():
    """FLAC/MKV tracks and Live TV items arrive with null ticks, bitrate and size."""
    session = make_episode_session(
        now_playing={
            "RunTimeTicks": None,
            "Bitrate": None,
            "MediaSources": [{"Bitrate": None, "Size": None}],
            "MediaStreams": [
                {"Type": "Video", "Height": 1080, "Codec": "h264", "BitRate": None},
                {"Type": "Audio", "Codec": "flac", "BitRate": None},
            ],
        },
    )
    session["PlayState"]["PositionTicks"] = None

    embed, _ = await create_detailed_stream_embed(session, make_jellyfin_core())

    assert field_value(embed, "📊 Progress") == "`N/A`"
    assert field_value(embed, "📊 Bitrate") == "`Unknown`"


@pytest.mark.asyncio
async def test_detailed_embed_falls_back_when_album_artist_is_null():
    session = make_episode_session(
        now_playing={
            "Type": "Audio",
            "Name": "Song",
            "AlbumArtist": None,
            "Artists": ["The Band"],
        },
    )

    embed, _ = await create_detailed_stream_embed(session, make_jellyfin_core())

    assert embed.title == "🎵 The Band - Song"


@pytest.mark.asyncio
async def test_detailed_embed_sanitizes_and_caps_code_block_fields():
    """A Jellyfin client picks its own DeviceName, so it must not break the fence."""
    session = make_episode_session(Client="Kodi`` @everyone", DeviceName="Kodi`` @everyone")
    core = make_jellyfin_core(library_names={"tvshows": "S" * 300})

    embed, _ = await create_detailed_stream_embed(session, core)

    assert field_value(embed, "📱 Player") == "`Kodi'' @everyone`"
    assert len(field_value(embed, "📚 Library")) <= 102


@pytest.mark.asyncio
async def test_detailed_embed_keeps_progress_on_two_lines():
    session = make_episode_session(
        PlayState={"PositionTicks": 24_550_000_000, "IsPaused": False},
        now_playing={"RunTimeTicks": 39_000_000_000},
    )

    embed, _ = await create_detailed_stream_embed(session, make_jellyfin_core())

    assert field_value(embed, "📊 Progress") == "`[▓▓▓▓▓▓░░░░]`\n`40:55 / 1:05:00`"
