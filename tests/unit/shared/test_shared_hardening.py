"""Regression tests for the shared helpers, driven by reproduced edge cases."""

import pytest

from cogs.media_core.shared import config_utils, env_validation, runtime_state


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    path = tmp_path / "data" / "runtime_state.json"
    path.parent.mkdir()
    monkeypatch.setattr(runtime_state, "get_runtime_state_path", lambda: path)
    return path


def test_unwritable_data_dir_does_not_take_the_bot_down(state_file, caplog, monkeypatch):
    """R3: an unwritable data/ must not raise out of setup_hook.

    `mark_global_commands_cleared()` runs inside `setup_hook`, which runs inside
    `login()`. A `PermissionError` from the atomic write escaped both and left
    the bot permanently unable to start - every restart hit the same error.

    The failure is injected rather than produced with `chmod`: CI runs as root,
    and root writes into a 0500 directory regardless, so the permission-based
    version of this test passed locally and failed on the runner.
    """

    def refuse(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(runtime_state, "write_json_atomic", refuse)

    with caplog.at_level("ERROR"):
        runtime_state.mark_global_commands_cleared()
        runtime_state.persist_online_since("plex", 1700000000.0)

    assert not state_file.exists()
    assert "Failed to persist runtime state" in caplog.text


def _env(**overrides):
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


def test_authorized_users_without_a_single_id_is_rejected():
    """R5: a value like "," is truthy and holds no entry the filter could reject.

    It passed validation, `parse_authorized_users` then returned an empty list,
    and every privileged command was dead - exactly the failure this validation
    exists to prevent.
    """
    assert env_validation.parse_authorized_users(",") == []

    errors, _warnings = env_validation.collect_env_issues(
        _env(DISCORD_AUTHORIZED_USERS=","), "plex"
    )

    assert any("DISCORD_AUTHORIZED_USERS" in error for error in errors)


def test_authorized_users_tolerates_padding_around_valid_ids():
    errors, _warnings = env_validation.collect_env_issues(
        _env(DISCORD_AUTHORIZED_USERS=" 123 , ,456,"), "plex"
    )

    assert errors == []
    assert env_validation.parse_authorized_users(" 123 , ,456,") == [123, 456]


def test_setup_hint_names_every_way_docker_can_pass_the_variables():
    """The bot reads plain environment variables, so .env, compose and templates all work.

    The hint is the first thing a new user reads; naming only env_file sent Unraid
    users, who have no compose file, looking for a file they do not need.
    """
    with pytest.raises(SystemExit) as excinfo:
        env_validation.validate_environment(_env(DISCORD_TOKEN=""), "plex")

    message = str(excinfo.value)
    assert ".env file next to docker-compose.yml" in message
    assert "'environment:'" in message
    assert "Unraid" in message


def test_atomic_write_updates_a_symlinked_target_in_place(tmp_path):
    """R6: data/config.yaml may be a symlink to a central configuration.

    `os.replace()` replaces the link itself, so the real file kept its old
    contents while the bot happily reported a successful write.
    """
    real = tmp_path / "central" / "config.yaml"
    real.parent.mkdir()
    real.write_text("old: true\n", encoding="utf-8")

    link = tmp_path / "config.yaml"
    link.symlink_to(real)

    config_utils.write_text_atomic(link, "new: true\n")

    assert link.is_symlink()
    assert real.read_text(encoding="utf-8") == "new: true\n"
