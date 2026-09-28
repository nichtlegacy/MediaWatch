from types import SimpleNamespace

from cogs.media_core.plex.utils.links import build_plex_web_url, web_rating_key


PLEX_TV = "https://app.plex.tv/desktop"


def test_build_plex_web_url_encodes_the_metadata_path():
    assert (
        build_plex_web_url("abc123", 4242, PLEX_TV)
        == "https://app.plex.tv/desktop#!/server/abc123/details?key=%2Flibrary%2Fmetadata%2F4242"
    )


def test_build_plex_web_url_keeps_the_route_on_a_self_hosted_base():
    assert (
        build_plex_web_url("abc123", 4242, "https://plex.example.com/web/")
        == "https://plex.example.com/web#!/server/abc123/details?key=%2Flibrary%2Fmetadata%2F4242"
    )


def test_build_plex_web_url_needs_every_part():
    assert build_plex_web_url(None, 4242, PLEX_TV) is None
    assert build_plex_web_url("abc123", None, PLEX_TV) is None
    assert build_plex_web_url("  ", 4242, PLEX_TV) is None
    assert build_plex_web_url("abc123", 4242, None) is None


def test_web_rating_key_points_music_at_the_album():
    # Plex Web has no page for a single track.
    track = SimpleNamespace(type="track", ratingKey=42, parentRatingKey=7)
    movie = SimpleNamespace(type="movie", ratingKey=42, parentRatingKey=7)

    assert web_rating_key(track) == 7
    assert web_rating_key(movie) == 42
    assert web_rating_key(SimpleNamespace()) is None
