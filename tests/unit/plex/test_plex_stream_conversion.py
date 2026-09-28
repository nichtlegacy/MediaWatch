from types import SimpleNamespace

from cogs.media_core.plex.plex_service import PlexMediaService
from cogs.media_core.shared.models import MediaType, PlayState, TranscodeDecision


class FakePlexClient:
    def __init__(self, plex_url, plex_token):
        self.server = None
        self.start_time = 0

    def connect(self):
        return None

    def disconnect(self):
        return None

    def get_server_name(self):
        return "Fake Plex"

    def get_server_version(self):
        return "1.0"

    def is_connected(self):
        return False


class FakeTautulliClient:
    def __init__(self, tautulli_url, tautulli_api_key, config):
        pass

    async def close(self):
        return None


def make_service(monkeypatch):
    monkeypatch.setattr("cogs.media_core.plex.plex_service.PlexClient", FakePlexClient)
    monkeypatch.setattr("cogs.media_core.plex.plex_service.TautulliClient", FakeTautulliClient)

    return PlexMediaService(
        plex_url="http://plex",
        plex_token="token",
        tautulli_url=None,
        tautulli_api_key=None,
        config={},
        user_mapping={"raw_user": "Mapped User"},
    )


def test_convert_session_to_stream_maps_movie_transcode_fields(monkeypatch):
    service = make_service(monkeypatch)
    media = SimpleNamespace(videoResolution="1080", bitrate=5400, parts=[])
    transcode_session = SimpleNamespace(
        videoDecision="transcode", audioDecision="copy", bitrate=3200
    )
    player = SimpleNamespace(state="paused", product="Plex for Web", device="Chrome")
    session = SimpleNamespace(
        sessionKey=42,
        usernames=["raw_user"],
        type="movie",
        media=[media],
        transcodeSession=transcode_session,
        players=[player],
        title="Tenet",
        year=2020,
        librarySectionTitle="Movies",
        viewOffset=60000,
        duration=120000,
        thumb="/thumb.jpg",
    )

    stream = service._convert_session_to_stream(session)

    assert stream is not None
    assert stream.username == "Mapped User"
    assert stream.media_type == MediaType.MOVIE
    assert stream.play_state == PlayState.PAUSED
    assert stream.video_resolution == "1080p"
    assert stream.video_bitrate_kbps == 5400
    assert stream.video_decision == TranscodeDecision.TRANSCODE
    assert stream.audio_decision == TranscodeDecision.DIRECT_STREAM
    assert stream.transcode_bitrate_kbps == 3200
    assert stream.is_transcoding is True
    assert stream.player_name == "Web"
    assert stream.player_device == "Chrome"
    assert stream.thumb_path == "/thumb.jpg"


def test_convert_session_to_stream_prefers_series_thumb_for_episode(monkeypatch):
    service = make_service(monkeypatch)
    player = SimpleNamespace(state="playing", product="Plex for Apple TV", device="Apple TV")
    session = SimpleNamespace(
        sessionKey=84,
        usernames=["raw_user"],
        type="episode",
        media=[],
        players=[player],
        title="Pilot",
        grandparentTitle="Series",
        parentIndex=1,
        index=2,
        librarySectionTitle="TV Shows",
        viewOffset=0,
        duration=1800000,
        grandparentThumb="/series-thumb.jpg",
        thumb="/episode-thumb.jpg",
    )

    stream = service._convert_session_to_stream(session)

    assert stream is not None
    assert stream.media_type == MediaType.EPISODE
    assert stream.series_title == "Series"
    assert stream.season_number == 1
    assert stream.episode_number == 2
    assert stream.thumb_path == "/series-thumb.jpg"


def test_convert_session_to_stream_keeps_sd_resolution_without_p_suffix(monkeypatch):
    service = make_service(monkeypatch)
    media = SimpleNamespace(videoResolution="SD", bitrate=5400, parts=[])
    player = SimpleNamespace(state="playing", product="Plex for Web", device="Chrome")
    session = SimpleNamespace(
        sessionKey=99,
        usernames=["raw_user"],
        type="movie",
        media=[media],
        transcodeSession=None,
        players=[player],
        title="Clerks",
        year=1994,
        librarySectionTitle="Movies",
        viewOffset=0,
        duration=120000,
        thumb="/thumb.jpg",
    )

    stream = service._convert_session_to_stream(session)

    assert stream is not None
    assert stream.video_resolution == "SD"


def test_convert_session_to_stream_survives_null_player_product(monkeypatch):
    """plexapi sets product/device to None for DLNA and Cast targets."""
    service = make_service(monkeypatch)
    player = SimpleNamespace(state="playing", product=None, device=None)
    session = SimpleNamespace(
        sessionKey=7,
        usernames=["raw_user"],
        type="movie",
        media=[],
        transcodeSession=None,
        players=[player],
        title=None,
        year=None,
        librarySectionTitle=None,
        viewOffset=0,
        duration=0,
        thumb=None,
    )

    stream = service._convert_session_to_stream(session)

    assert stream is not None
    assert stream.player_name == "Unknown"
    assert stream.player_device == ""
    assert stream.title == "Unknown"
    assert stream.library_section_title == ""


def test_convert_session_to_stream_reads_the_audio_quality_of_a_track(monkeypatch):
    service = make_service(monkeypatch)
    audio = SimpleNamespace(streamType=2, bitDepth=24, samplingRate=96000)
    media = SimpleNamespace(
        videoResolution=None, bitrate=4600, parts=[SimpleNamespace(streams=[audio])]
    )
    session = SimpleNamespace(
        sessionKey=7,
        usernames=["raw_user"],
        type="track",
        media=[media],
        transcodeSession=None,
        players=[SimpleNamespace(state="playing", product="Plexamp", device="iPhone")],
        title="Song",
        grandparentTitle="Artist",
        parentTitle="Album",
        librarySectionTitle="Music",
        viewOffset=1000,
        duration=200000,
    )

    stream = service._convert_session_to_stream(session)

    assert stream.media_type == MediaType.TRACK
    assert stream.video_resolution == ""
    assert stream.audio_quality == "24bit 96kHz"


def test_convert_session_to_stream_leaves_audio_quality_empty_for_video(monkeypatch):
    service = make_service(monkeypatch)
    audio = SimpleNamespace(streamType=2, bitDepth=24, samplingRate=48000)
    media = SimpleNamespace(
        videoResolution="1080", bitrate=5400, parts=[SimpleNamespace(streams=[audio])]
    )
    session = SimpleNamespace(
        sessionKey=8,
        usernames=["raw_user"],
        type="movie",
        media=[media],
        transcodeSession=None,
        players=[],
        title="Movie",
        librarySectionTitle="Movies",
        viewOffset=0,
        duration=1,
    )

    assert service._convert_session_to_stream(session).audio_quality == ""
