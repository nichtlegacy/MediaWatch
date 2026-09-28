from cogs.media_core.plex.utils.config_helper import (
    GlobalStatsConfig,
    UserStatsConfig,
)


def test_global_stats_config_validates_button_location():
    default_config = GlobalStatsConfig({})
    assert default_config.get_button_location() == "stream_details"
    assert default_config.show_in_stream_details() is True
    assert default_config.show_in_dashboard() is False

    both_config = GlobalStatsConfig({"global_stats": {"button_location": "both"}})
    assert both_config.show_in_stream_details() is True
    assert both_config.show_in_dashboard() is True

    invalid_config = GlobalStatsConfig({"global_stats": {"button_location": "somewhere-else"}})
    assert invalid_config.get_button_location() == "stream_details"


def test_global_stats_config_is_open_by_default_and_opt_in_restricted():
    assert GlobalStatsConfig({}).restrict_to_authorized() is False
    assert GlobalStatsConfig({"global_stats": "invalid"}).restrict_to_authorized() is False
    assert (
        GlobalStatsConfig(
            {"global_stats": {"restrict_to_authorized": True}}
        ).restrict_to_authorized()
        is True
    )


def test_user_stats_config_is_open_by_default_and_opt_in_restricted():
    assert UserStatsConfig({}).restrict_to_authorized() is False
    assert UserStatsConfig({"user_stats": "invalid"}).restrict_to_authorized() is False
    assert (
        UserStatsConfig({"user_stats": {"restrict_to_authorized": True}}).restrict_to_authorized()
        is True
    )


def test_user_stats_config_handles_defaults_invalid_values_and_zero_top_tv_count():
    config = UserStatsConfig(
        {
            "user_stats": {
                "pages": {"devices": False},
                "time_range": "bad",
                "top_tv_count": 0,
            }
        }
    )

    assert config.is_enabled() is True
    assert config.get_enabled_pages() == ["behavior", "top_content"]
    assert config.get_time_range() == 0
    assert config.get_top_tv_count() == 0


def test_user_stats_config_falls_back_when_top_level_block_is_invalid():
    config = UserStatsConfig({"user_stats": "invalid"})

    assert config.get_enabled_pages() == ["behavior", "devices", "top_content"]
    assert config.get_time_range() == 0
    assert config.get_top_tv_count() == 10
