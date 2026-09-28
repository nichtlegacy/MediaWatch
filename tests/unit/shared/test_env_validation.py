import pytest

from cogs.media_core.shared.env_validation import (
    collect_env_issues,
    parse_authorized_users,
    validate_environment,
)


def base_env(**overrides):
    env = {
        "DISCORD_TOKEN": "token",
        "CHANNEL_ID": "123456789012345678",
        "DISCORD_AUTHORIZED_USERS": "123456789012345678",
        "DISCORD_GUILD_ID": "987654321098765432",
        "PLEX_URL": "http://plex:32400",
        "PLEX_TOKEN": "plex-token",
    }
    env.update(overrides)
    return env


def test_complete_plex_environment_has_no_issues():
    assert collect_env_issues(base_env(), "plex") == ([], [])


@pytest.mark.parametrize(
    "name", ["DISCORD_TOKEN", "CHANNEL_ID", "DISCORD_AUTHORIZED_USERS", "DISCORD_GUILD_ID"]
)
def test_missing_always_required_variable_is_an_error(name):
    errors, _ = collect_env_issues(base_env(**{name: ""}), "plex")

    assert any(error.startswith(f"{name} is not set") for error in errors)


@pytest.mark.parametrize(
    "server_type,name",
    [
        ("plex", "PLEX_URL"),
        ("plex", "PLEX_TOKEN"),
        ("jellyfin", "JELLYFIN_URL"),
        ("jellyfin", "JELLYFIN_API_KEY"),
    ],
)
def test_missing_platform_variable_is_an_error(server_type, name):
    env = base_env(JELLYFIN_URL="http://jellyfin:8096", JELLYFIN_API_KEY="key")
    env[name] = ""

    errors, _ = collect_env_issues(env, server_type)

    assert any(name in error and server_type in error for error in errors)


def test_credentials_for_the_inactive_platform_produce_an_explicit_error():
    env = base_env(
        PLEX_URL="", PLEX_TOKEN="", JELLYFIN_URL="http://jellyfin:8096", JELLYFIN_API_KEY="key"
    )

    errors, _ = collect_env_issues(env, "plex")

    assert len(errors) == 1
    assert "media_server.type is 'plex'" in errors[0]
    assert "JELLYFIN_URL" in errors[0]
    assert "switch media_server.type to 'jellyfin'" in errors[0]


def test_non_numeric_discord_ids_are_errors():
    env = base_env(
        CHANNEL_ID="my-channel",
        DISCORD_GUILD_ID="not-a-guild",
        DISCORD_AUTHORIZED_USERS="123,alice",
    )

    errors, _ = collect_env_issues(env, "plex")

    assert any("CHANNEL_ID must be a numeric Discord ID" in error for error in errors)
    assert any("DISCORD_GUILD_ID must be a numeric Discord ID" in error for error in errors)
    assert any(
        "DISCORD_AUTHORIZED_USERS contains non-numeric entries: alice" in error for error in errors
    )


def test_missing_guild_id_is_an_error_because_commands_are_guild_scoped():
    errors, _ = collect_env_issues(base_env(DISCORD_GUILD_ID=""), "plex")

    assert any("DISCORD_GUILD_ID is not set" in error for error in errors)
    assert any("published into this server only" in error for error in errors)


def test_partially_configured_integration_only_warns():
    errors, warnings = collect_env_issues(base_env(SABNZBD_URL="http://sab:8080"), "plex")

    assert errors == []
    assert any("SABnzbd is only partially configured" in warning for warning in warnings)
    assert any("SABNZBD_API_KEY" in warning for warning in warnings)


def test_fully_configured_integration_does_not_warn():
    _, warnings = collect_env_issues(
        base_env(SABNZBD_URL="http://sab:8080", SABNZBD_API_KEY="key"), "plex"
    )

    assert warnings == []


def test_tautulli_with_jellyfin_only_warns():
    env = base_env(
        PLEX_URL="",
        PLEX_TOKEN="",
        JELLYFIN_URL="http://jellyfin:8096",
        JELLYFIN_API_KEY="key",
        TAUTULLI_URL="http://tautulli:8181",
        TAUTULLI_API_KEY="key",
    )

    errors, warnings = collect_env_issues(env, "jellyfin")

    assert errors == []
    assert any("Tautulli is a Plex-only integration" in warning for warning in warnings)


def test_parse_authorized_users_skips_unparsable_entries():
    assert parse_authorized_users(" 123 , alice ,456,") == [123, 456]
    assert parse_authorized_users(None) == []


def test_validate_environment_exits_with_actionable_message():
    with pytest.raises(SystemExit) as excinfo:
        validate_environment(env=base_env(PLEX_TOKEN=""), server_type="plex")

    message = str(excinfo.value)
    assert "PLEX_TOKEN is not set" in message
    assert ".env" in message
    assert "docker-compose.yml" in message


def test_validate_environment_passes_for_complete_environment():
    assert validate_environment(env=base_env(), server_type="plex") is None
