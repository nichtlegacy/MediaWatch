from cogs.media_core.shared.config_helper import StreamControlsConfig, StreamDetailsConfig


def test_stream_controls_default_reason_uses_fallback_for_invalid_values():
    assert StreamControlsConfig({}).get_kill_stream_default_reason() == "Stopped by administrator"
    assert (
        StreamControlsConfig({"stream_controls": "invalid"}).get_kill_stream_default_reason()
        == "Stopped by administrator"
    )
    assert (
        StreamControlsConfig(
            {"stream_controls": {"kill_stream": {"default_reason": "   "}}}
        ).get_kill_stream_default_reason()
        == "Stopped by administrator"
    )


def test_stream_controls_default_reason_is_trimmed_and_limited():
    reason = "  " + ("x" * 220) + "  "
    result = StreamControlsConfig(
        {"stream_controls": {"kill_stream": {"default_reason": reason}}}
    ).get_kill_stream_default_reason()

    assert result == "x" * 200


def test_stream_details_config_controls_ip_visibility_for_authorized_users():
    assert StreamDetailsConfig({}).show_ip_for_authorized_users() is False
    assert (
        StreamDetailsConfig(
            {"stream_details": {"show_ip_for_authorized_users": True}}
        ).show_ip_for_authorized_users()
        is True
    )
    assert (
        StreamDetailsConfig({"stream_details": "invalid"}).show_ip_for_authorized_users() is False
    )


def test_stream_details_config_restrict_to_authorized_defaults_to_false():
    assert StreamDetailsConfig({}).restrict_to_authorized() is False
    assert StreamDetailsConfig({"stream_details": {}}).restrict_to_authorized() is False
    assert StreamDetailsConfig({"stream_details": "invalid"}).restrict_to_authorized() is False
    assert (
        StreamDetailsConfig(
            {"stream_details": {"restrict_to_authorized": True}}
        ).restrict_to_authorized()
        is True
    )


def test_stream_details_link_button_is_on_by_default():
    config = StreamDetailsConfig({})

    assert config.link_enabled("plex") is True
    assert config.link_enabled("unknown") is False


def test_stream_details_partial_link_config_keeps_the_other_defaults():
    # load_config only deep merges two levels, so setting just the emoji must not
    # drop "enabled" underneath it.
    config = StreamDetailsConfig(
        {"stream_details": {"links": {"plex": {"emoji": "<:plex:123456789012345678>"}}}}
    )

    assert config.link_enabled("plex") is True
    assert config.link_emoji("plex") == "<:plex:123456789012345678>"


def test_stream_details_link_can_be_turned_off():
    config = StreamDetailsConfig({"stream_details": {"links": {"plex": {"enabled": False}}}})

    assert config.link_enabled("plex") is False


def test_stream_details_link_emoji_falls_back_on_invalid_values():
    # A plain word would make Discord answer the whole message with HTTP 400.
    assert (
        StreamDetailsConfig({"stream_details": {"links": {"plex": {"emoji": "Plex"}}}}).link_emoji(
            "plex"
        )
        == "\u25b6\ufe0f"
    )
    assert (
        StreamDetailsConfig({"stream_details": {"links": {"plex": {"emoji": 7}}}}).link_emoji(
            "plex"
        )
        == "\u25b6\ufe0f"
    )
    assert (
        StreamDetailsConfig(
            {"stream_details": {"links": {"plex": {"emoji": "\U0001f3a5"}}}}
        ).link_emoji("plex")
        == "\U0001f3a5"
    )


def test_stream_details_empty_link_emoji_means_no_icon():
    assert (
        StreamDetailsConfig({"stream_details": {"links": {"plex": {"emoji": ""}}}}).link_emoji(
            "plex"
        )
        is None
    )


def test_stream_details_invalid_links_block_falls_back_to_defaults():
    config = StreamDetailsConfig({"stream_details": {"links": "invalid"}})

    assert config.link_enabled("plex") is True
    assert config.link_emoji("plex") == "\u25b6\ufe0f"


def test_stream_details_link_base_url_defaults_to_plex_tv():
    assert StreamDetailsConfig({}).link_base_url("plex") == "https://app.plex.tv/desktop"


def test_stream_details_link_base_url_takes_a_self_hosted_plex_web():
    config = StreamDetailsConfig(
        {"stream_details": {"links": {"plex": {"base_url": "https://plex.example.com/web/"}}}}
    )

    # The trailing slash goes, so the "#!" route can be appended blindly.
    assert config.link_base_url("plex") == "https://plex.example.com/web"


def test_stream_details_link_base_url_rejects_anything_but_http():
    # Discord refuses a link button with another scheme, so it never gets there.
    for value in ("plex.example.com", "plex://app", "", 7):
        assert (
            StreamDetailsConfig(
                {"stream_details": {"links": {"plex": {"base_url": value}}}}
            ).link_base_url("plex")
            == "https://app.plex.tv/desktop"
        )
