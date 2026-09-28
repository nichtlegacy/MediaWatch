from cogs.media_core.jellyfin.jellyfin_service import JellyfinMediaService
from cogs.media_core.shared.models import MediaType, PlayState, TranscodeDecision


class FakeJellyfinClient:
    def __init__(self, jellyfin_url, jellyfin_api_key):
        self.server_name = "Fake Jellyfin"
        self.server_version = "10.0"

    async def connect(self):
        return False

    async def disconnect(self):
        return None

    def is_connected(self):
        return False


def make_service(monkeypatch):
    monkeypatch.setattr(
        "cogs.media_core.jellyfin.jellyfin_service.JellyfinClient", FakeJellyfinClient
    )

    return JellyfinMediaService(
        jellyfin_url="http://jellyfin",
        jellyfin_api_key="token",
        config={},
        user_mapping={"raw_user": "Mapped User"},
    )


def test_convert_session_to_stream_maps_episode_direct_play(monkeypatch):
    service = make_service(monkeypatch)
    session = {
        "Id": "session-1",
        "UserName": "raw_user",
        "UserId": "user-1",
        "DeviceName": "Apple TV",
        "Client": "Jellyfin Web",
        "PlayState": {
            "IsPaused": True,
            "PositionTicks": 5_000_000,
        },
        "NowPlayingItem": {
            "Type": "Episode",
            "Name": "Pilot",
            "SeriesName": "Series",
            "ParentIndexNumber": 1,
            "IndexNumber": 2,
            "SeriesId": "series-123",
            "RunTimeTicks": 10_000_000,
            "MediaStreams": [
                {"Type": "Video", "Width": 1920, "Height": 1080, "BitRate": 8_000_000}
            ],
        },
    }

    stream = service._convert_session_to_stream(session)

    assert stream is not None
    assert stream.username == "Mapped User"
    assert stream.media_type == MediaType.EPISODE
    assert stream.play_state == PlayState.PAUSED
    assert stream.video_resolution == "1080p"
    assert stream.video_bitrate_kbps == 8000
    assert stream.video_decision == TranscodeDecision.DIRECT_PLAY
    assert stream.audio_decision == TranscodeDecision.DIRECT_PLAY
    assert stream.is_transcoding is False
    assert stream.thumb_path == "series-123"


def test_convert_session_to_stream_marks_video_transcode(monkeypatch):
    service = make_service(monkeypatch)
    session = {
        "Id": "session-2",
        "UserName": "raw_user",
        "PlayState": {"IsPaused": False, "PositionTicks": 0},
        "TranscodingInfo": {
            "IsVideoDirect": False,
            "IsAudioDirect": True,
            "Bitrate": 4_500_000,
        },
        "NowPlayingItem": {
            "Type": "Movie",
            "Name": "Film",
            "Id": "movie-123",
            "RunTimeTicks": 10_000_000,
            "MediaStreams": [
                {"Type": "Video", "Width": 3840, "Height": 2160, "BitRate": 12_000_000}
            ],
        },
    }

    stream = service._convert_session_to_stream(session)

    assert stream is not None
    assert stream.media_type == MediaType.MOVIE
    assert stream.video_decision == TranscodeDecision.TRANSCODE
    assert stream.audio_decision == TranscodeDecision.DIRECT_STREAM
    assert stream.transcode_bitrate_kbps == 4500
    assert stream.is_transcoding is True


def test_convert_session_to_stream_survives_null_ticks(monkeypatch):
    """Live TV / .strm items report PositionTicks and RunTimeTicks as null."""
    service = make_service(monkeypatch)
    session = {
        "Id": "session-3",
        "UserName": "raw_user",
        "PlayState": {"IsPaused": False, "PositionTicks": None},
        "NowPlayingItem": {
            "Type": "TvChannel",
            "Name": "Live Channel",
            "Id": "channel-1",
            "RunTimeTicks": None,
            "MediaStreams": [],
        },
    }

    stream = service._convert_session_to_stream(session)

    assert stream is not None
    assert stream.view_offset_ms == 0
    assert stream.duration_ms == 0


def test_convert_session_to_stream_survives_null_video_dimensions(monkeypatch):
    service = make_service(monkeypatch)
    session = {
        "Id": "session-4",
        "UserName": "raw_user",
        "PlayState": {"IsPaused": False, "PositionTicks": 0},
        "NowPlayingItem": {
            "Type": "Movie",
            "Name": None,
            "Id": "movie-1",
            "RunTimeTicks": 10_000_000,
            "MediaStreams": [{"Type": "Video", "Width": None, "Height": None}],
        },
        "DeviceName": None,
        "Client": None,
    }

    stream = service._convert_session_to_stream(session)

    assert stream is not None
    assert stream.video_resolution == "Unknown"
    assert stream.title == "Unknown"
    assert stream.player_name == "Unknown"
    assert stream.player_device == "Unknown"


def test_convert_session_to_stream_reads_the_audio_quality_of_a_track(monkeypatch):
    service = make_service(monkeypatch)
    session = {
        "Id": "session-2",
        "UserName": "raw_user",
        "DeviceName": "iPhone",
        "Client": "Finamp",
        "PlayState": {"PositionTicks": 10_000_000},
        "NowPlayingItem": {
            "Type": "Audio",
            "Name": "Song",
            "AlbumArtist": "Artist",
            "Album": "Album",
            "RunTimeTicks": 2_000_000_000,
            "MediaStreams": [
                {"Type": "Audio", "BitDepth": 16, "SampleRate": 44100, "BitRate": 1_411_000}
            ],
        },
    }

    stream = service._convert_session_to_stream(session)

    assert stream.media_type == MediaType.TRACK
    assert stream.audio_quality == "16bit 44.1kHz"


def test_convert_session_to_stream_tolerates_null_audio_quality_fields(monkeypatch):
    service = make_service(monkeypatch)
    session = {
        "Id": "session-3",
        "UserName": "raw_user",
        "PlayState": {},
        "NowPlayingItem": {
            "Type": "Audio",
            "Name": "Song",
            "MediaStreams": [{"Type": "Audio", "BitDepth": None, "SampleRate": None}],
        },
    }

    stream = service._convert_session_to_stream(session)

    assert stream is not None
    assert stream.audio_quality == ""
