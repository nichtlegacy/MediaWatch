import discord
import pytest

from cogs.media_core.shared.presence import MAX_ACTIVITY_LENGTH, build_presence

STATS = {
    "Filme": {"count": 2938, "episodes": 0, "display_name": "Filme", "emoji": "🎥"},
    "Serien": {"count": 545, "episodes": 21980, "display_name": "Serien", "emoji": "📺"},
}


def _config(**overrides):
    config = {
        "enabled": True,
        "activity_type": "custom",
        "status": "online",
        "offline_status": "dnd",
        "libraries": ["Filme", "Serien"],
        "offline_text": "🔴 Offline",
        "auth_failed_text": "",
        "stream_text": "{count} Stream{s}",
    }
    config.update(overrides)
    return config


def test_libraries_reference_the_platform_config():
    """Names only - display name and emoji come from the library stats, so the
    dashboard and the presence cannot drift apart."""
    activity, status = build_presence(
        _config(), is_online=True, auth_failed=False, active_streams=0, library_stats=STATS
    )
    assert activity.name == "2.938 Filme 🎥 | 545 Serien 📺"
    assert status is discord.Status.online


def test_episode_counts_via_suffix():
    activity, _ = build_presence(
        _config(libraries=["Serien:episodes"]),
        is_online=True,
        auth_failed=False,
        active_streams=0,
        library_stats=STATS,
    )
    # The number is episodes, so the label has to say so - "21.980 Serien"
    # would read as the series count.
    assert activity.name == "21.980 Serien Episodes 📺"


def test_the_episode_label_is_configurable():
    """A German setup must not be stuck with "Serien Episodes"."""
    activity, _ = build_presence(
        _config(libraries=["Serien:episodes"]),
        is_online=True,
        auth_failed=False,
        active_streams=0,
        library_stats=STATS,
        episode_label="Episoden",
    )
    assert activity.name == "21.980 Serien Episoden 📺"


def test_an_empty_episode_label_drops_it():
    activity, _ = build_presence(
        _config(libraries=["Serien:episodes"]),
        is_online=True,
        auth_failed=False,
        active_streams=0,
        library_stats=STATS,
        episode_label="",
    )
    assert activity.name == "21.980 Serien 📺"


def test_the_episode_label_is_not_appended_to_an_item_count():
    activity, _ = build_presence(
        _config(libraries=["Serien"]),
        is_online=True,
        auth_failed=False,
        active_streams=0,
        library_stats=STATS,
    )
    assert activity.name == "545 Serien 📺"


def test_all_libraries():
    activity, _ = build_presence(
        _config(libraries="all"),
        is_online=True,
        auth_failed=False,
        active_streams=0,
        library_stats=STATS,
    )
    assert "Filme" in activity.name and "Serien" in activity.name


def test_separator_is_configurable():
    activity, _ = build_presence(
        _config(libraries=["Filme"]),
        is_online=True,
        auth_failed=False,
        active_streams=0,
        library_stats=STATS,
        separator=",",
    )
    assert activity.name == "2,938 Filme 🎥"


def test_text_is_truncated_to_the_discord_limit():
    """Past 128 characters Discord rejects the update and the presence silently
    stops changing - so it is cut here instead."""
    stats = {
        f"Library {i}": {"count": 1234, "display_name": f"Library {i}", "emoji": "📚"}
        for i in range(20)
    }
    activity, _ = build_presence(
        _config(libraries="all"),
        is_online=True,
        auth_failed=False,
        active_streams=0,
        library_stats=stats,
    )
    assert len(activity.name) <= MAX_ACTIVITY_LENGTH


def test_malformed_library_is_skipped_not_fatal(caplog):
    """A missing count used to raise into the loop's catch-all, leaving only
    'Error updating status' with no hint which entry was wrong."""
    stats = {"Broken": {"display_name": "Broken", "emoji": "❓"}, **STATS}
    with caplog.at_level("WARNING"):
        activity, _ = build_presence(
            _config(libraries=["Broken", "Filme"]),
            is_online=True,
            auth_failed=False,
            active_streams=0,
            library_stats=stats,
        )
    assert activity.name == "2.938 Filme 🎥"
    assert "Broken" in caplog.text


@pytest.mark.parametrize(
    "name,expected",
    [
        ("custom", discord.ActivityType.custom),
        ("watching", discord.ActivityType.watching),
        ("listening", discord.ActivityType.listening),
    ],
)
def test_activity_types(name, expected):
    activity, _ = build_presence(
        _config(activity_type=name),
        is_online=True,
        auth_failed=False,
        active_streams=2,
        library_stats=STATS,
    )
    assert activity.type is expected


def test_unknown_activity_type_falls_back_to_custom(caplog):
    with caplog.at_level("WARNING"):
        activity, _ = build_presence(
            _config(activity_type="playing"),
            is_online=True,
            auth_failed=False,
            active_streams=1,
            library_stats=STATS,
        )
    assert activity.type is discord.ActivityType.custom
    assert "playing" in caplog.text


def test_auth_failure_is_distinguishable_from_an_outage():
    """Both used to show offline_text and DND, so a rejected token looked like
    a dead server in the member list."""
    activity, status = build_presence(
        _config(auth_failed_text="⚠️ Credentials rejected"),
        is_online=False,
        auth_failed=True,
        active_streams=0,
        library_stats=STATS,
    )
    assert activity.name == "⚠️ Credentials rejected"
    assert status is discord.Status.dnd


def test_auth_failure_falls_back_to_the_offline_text():
    activity, _ = build_presence(
        _config(), is_online=False, auth_failed=True, active_streams=0, library_stats=STATS
    )
    assert activity.name == "🔴 Offline"


def test_disabled_returns_nothing():
    assert (
        build_presence(
            _config(enabled=False),
            is_online=True,
            auth_failed=False,
            active_streams=0,
            library_stats=STATS,
        )
        is None
    )


def test_stream_text_pluralisation():
    one, _ = build_presence(
        _config(), is_online=True, auth_failed=False, active_streams=1, library_stats=STATS
    )
    many, _ = build_presence(
        _config(), is_online=True, auth_failed=False, active_streams=3, library_stats=STATS
    )
    assert one.name == "1 Stream" and many.name == "3 Streams"


def test_status_is_configurable():
    _, status = build_presence(
        _config(status="idle"),
        is_online=True,
        auth_failed=False,
        active_streams=0,
        library_stats=STATS,
    )
    assert status is discord.Status.idle


def test_library_names_match_exactly():
    """ "Filme" must not also pick up "Filme - 4K" - they are separate libraries
    with separate counts."""
    stats = {
        "Filme": {"count": 2938, "display_name": "Filme", "emoji": "🎥"},
        "Filme - 4K": {"count": 412, "display_name": "Filme - 4K", "emoji": "🎬"},
        "Filme - NZB": {"count": 77, "display_name": "Filme - NZB", "emoji": "📥"},
    }
    activity, _ = build_presence(
        _config(libraries=["Filme"]),
        is_online=True,
        auth_failed=False,
        active_streams=0,
        library_stats=stats,
    )
    assert activity.name == "2.938 Filme 🎥"


def test_a_library_name_containing_a_colon_is_not_split(caplog):
    """The ":episodes" suffix must not hijack a name that contains a colon.

    Splitting on the first colon resolved "Filme: Klassiker" to "Filme" - the
    wrong library, with the wrong count, and no error to notice it by.
    """
    stats = {
        "Filme": {"count": 2938, "display_name": "Filme", "emoji": "🎥"},
        "Filme: Klassiker": {"count": 88, "display_name": "Filme: Klassiker", "emoji": "🎞️"},
    }
    with caplog.at_level("WARNING"):
        activity, _ = build_presence(
            _config(libraries=["Filme: Klassiker"]),
            is_online=True,
            auth_failed=False,
            active_streams=0,
            library_stats=stats,
        )

    assert activity.name == "88 Filme: Klassiker 🎞️"
    assert not caplog.text


def test_an_unknown_suffix_is_skipped_not_guessed(caplog):
    stats = {"Serien": {"count": 546, "episodes": 21980, "display_name": "Serien", "emoji": "📺"}}
    with caplog.at_level("WARNING"):
        activity, _ = build_presence(
            _config(libraries=["Serien:nonsense"]),
            is_online=True,
            auth_failed=False,
            active_streams=0,
            library_stats=stats,
        )

    assert activity.name == "No streams or libraries configured"
    assert "nonsense" in caplog.text
