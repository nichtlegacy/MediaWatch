import json
import logging

import pytest

from cogs.media_core.shared.config import (
    ConfigError,
    check_legacy_config,
    convert_legacy_config,
    load_config,
    load_message_id,
    load_user_mapping,
    save_message_id,
    validate_server_config,
)

import yaml


# Real-world shape of a PlexWatch 1.x data/config.json (see README of the 1.x tag).
LEGACY_1X_CONFIG = {
    "dashboard": {
        "name": "Your Plex Dashboard",
        "icon_url": "https://example.com/icon.png",
        "footer_icon_url": "https://example.com/icon.png",
    },
    "plex_sections": {
        "show_all": False,
        "sections": {
            "Movies": {"display_name": "Filme", "emoji": "\U0001f3a5", "show_episodes": False},
            "Shows": {"display_name": "Serien", "emoji": "\U0001f4fa", "show_episodes": True},
        },
    },
    "presence": {
        "sections": [{"section_title": "Movies", "display_name": "Filme", "emoji": "\U0001f3a5"}],
        "offline_text": "\U0001f534 Server Offline!",
        "stream_text": "{count} active Stream{s} \U0001f7e2",
    },
    "cache": {"library_update_interval": 600},
    "sabnzbd": {"keywords": ["German", "1080p"]},
}


def _legacy_setup(tmp_path, payload=None, raw=None):
    config_yaml = tmp_path / "config.yaml"
    config_json = tmp_path / "config.json"
    user_mapping = tmp_path / "user_mapping.json"
    if raw is not None:
        config_json.write_text(raw, encoding="utf-8")
    else:
        config_json.write_text(
            json.dumps(payload if payload is not None else LEGACY_1X_CONFIG), encoding="utf-8"
        )
    return config_yaml, config_json, user_mapping


def test_load_config_deep_merges_defaults_and_legacy_plex_sections(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
media_server:
  type: jellyfin
global_stats:
  page_2:
    time_range: 7
user_stats:
  pages:
    devices: false
plex_sections:
  show_all: false
  sections:
    Movies:
      display_name: Filme
stream_controls:
  kill_stream:
    default_reason: Custom reason
stream_details:
  show_ip_for_authorized_users: true
""".strip(),
        encoding="utf-8",
    )

    config = load_config(str(config_file))

    assert config["media_server"]["type"] == "jellyfin"
    assert config["global_stats"]["button_location"] == "stream_details"
    assert config["global_stats"]["page_2"]["time_range"] == 7
    assert config["user_stats"]["pages"]["devices"] is False
    assert config["user_stats"]["pages"]["behavior"] is True
    assert config["stream_controls"]["kill_stream"]["default_reason"] == "Custom reason"
    assert config["stream_details"]["show_ip_for_authorized_users"] is True
    assert config["plex"]["sections"]["Movies"]["display_name"] == "Filme"


def test_validate_server_config_clamps_invalid_thresholds():
    negative = validate_server_config({"server": {"offline_threshold": -5}})
    invalid = validate_server_config({"server": {"offline_threshold": "bad"}})
    missing = validate_server_config({})

    assert negative["server"]["offline_threshold"] == 0
    assert invalid["server"]["offline_threshold"] == 300
    assert missing["server"]["offline_threshold"] == 300


def test_message_id_roundtrip_and_invalid_json(tmp_path):
    message_file = tmp_path / "dashboard_message_id.json"

    save_message_id(str(message_file), 123456789)
    assert load_message_id(str(message_file)) == 123456789

    message_file.write_text("{invalid", encoding="utf-8")
    assert load_message_id(str(message_file)) is None


@pytest.mark.parametrize("payload", ["{}", '{"message_id": null}', "null", "[]", '"nope"', ""])
def test_load_message_id_returns_none_for_unusable_payloads(tmp_path, payload):
    """Emptying dashboard_message_id.json is a common user move to force a repost.

    It must not raise (TypeError/KeyError) inside the cog constructor.
    """
    message_file = tmp_path / "dashboard_message_id.json"
    message_file.write_text(payload, encoding="utf-8")

    assert load_message_id(str(message_file)) is None


def test_save_message_id_never_leaves_a_truncated_file(tmp_path, monkeypatch):
    message_file = tmp_path / "dashboard_message_id.json"
    save_message_id(str(message_file), 111)

    monkeypatch.setattr(
        "cogs.media_core.shared.config_utils.os.replace",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("interrupted")),
    )
    save_message_id(str(message_file), 222)

    assert load_message_id(str(message_file)) == 111
    assert [p.name for p in tmp_path.iterdir()] == ["dashboard_message_id.json"]


def test_load_user_mapping_supports_new_and_legacy_formats(tmp_path):
    mapping_file = tmp_path / "user_mapping.json"
    mapping_file.write_text(
        json.dumps(
            {
                "plex": {"plex_user": "Plex Name"},
                "jellyfin": {"jf_user": "Jellyfin Name"},
            }
        ),
        encoding="utf-8",
    )

    assert load_user_mapping("", str(mapping_file), platform="plex") == {"plex_user": "Plex Name"}
    assert load_user_mapping("", str(mapping_file), platform="jellyfin") == {
        "jf_user": "Jellyfin Name"
    }

    mapping_file.write_text(json.dumps({"legacy_user": "Legacy Name"}), encoding="utf-8")
    assert load_user_mapping("", str(mapping_file), platform="plex") == {
        "legacy_user": "Legacy Name"
    }
    assert load_user_mapping("", str(mapping_file), platform="jellyfin") == {}


def test_check_legacy_config_migrates_1x_config_json(tmp_path):
    config_yaml, config_json, user_mapping = _legacy_setup(tmp_path)
    original_json = config_json.read_bytes()

    check_legacy_config(str(config_yaml), str(config_json), str(user_mapping))

    # config.json must survive byte-identical - it is the user's only backup.
    assert config_json.read_bytes() == original_json

    migrated = yaml.safe_load(config_yaml.read_text(encoding="utf-8"))
    assert migrated["media_server"] == {"type": "plex"}
    assert "plex_sections" not in migrated
    assert migrated["plex"] == LEGACY_1X_CONFIG["plex_sections"]
    assert migrated["dashboard"] == LEGACY_1X_CONFIG["dashboard"]
    # presence is the one block not passed through verbatim: the 1.x
    # "sections" list becomes "libraries", covered by its own test below.
    assert migrated["presence"]["libraries"] == ["Movies"]
    assert migrated["presence"]["offline_text"] == LEGACY_1X_CONFIG["presence"]["offline_text"]
    assert migrated["cache"] == LEGACY_1X_CONFIG["cache"]
    assert migrated["sabnzbd"] == LEGACY_1X_CONFIG["sabnzbd"]

    # The generated file must be a normal config.yaml: same default merge applies.
    config = load_config(str(config_yaml))
    assert config["plex"]["sections"]["Shows"]["display_name"] == "Serien"
    assert config["cache"]["library_update_interval"] == 600
    assert config["sabnzbd"]["keywords"] == ["German", "1080p"]
    assert config["sabnzbd"]["show_when_empty"] is False  # 2.0 default filled in
    assert config["user_stats"]["enabled"] is True  # section added in 2.0
    assert config["server"]["offline_threshold"] == 300


def test_check_legacy_config_migration_is_idempotent(tmp_path):
    config_yaml, config_json, user_mapping = _legacy_setup(tmp_path)

    check_legacy_config(str(config_yaml), str(config_json), str(user_mapping))
    first = config_yaml.read_bytes()

    # Second start: config.yaml wins, config.json is only reported as ignored.
    config_yaml.write_bytes(first + b"\n# hand edit\n")
    check_legacy_config(str(config_yaml), str(config_json), str(user_mapping))

    assert config_yaml.read_bytes() == first + b"\n# hand edit\n"


def test_check_legacy_config_leaves_existing_yaml_untouched(tmp_path):
    config_yaml, config_json, user_mapping = _legacy_setup(tmp_path)
    config_yaml.write_text("media_server:\n  type: jellyfin\n", encoding="utf-8")

    check_legacy_config(str(config_yaml), str(config_json), str(user_mapping))

    assert config_yaml.read_text(encoding="utf-8") == "media_server:\n  type: jellyfin\n"


@pytest.mark.parametrize("raw", ["{broken", "", "[1, 2, 3]", '"just a string"'])
def test_check_legacy_config_exits_when_config_json_cannot_be_converted(tmp_path, raw):
    config_yaml, config_json, user_mapping = _legacy_setup(tmp_path, raw=raw)

    with pytest.raises(SystemExit):
        check_legacy_config(str(config_yaml), str(config_json), str(user_mapping))

    assert not config_yaml.exists()
    assert config_json.read_text(encoding="utf-8") == raw


def test_check_legacy_config_exits_and_writes_nothing_when_target_is_unwritable(
    tmp_path, monkeypatch
):
    config_yaml, config_json, user_mapping = _legacy_setup(tmp_path)

    def boom(*args, **kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr("cogs.media_core.shared.config.write_text_atomic", boom)

    with pytest.raises(SystemExit):
        check_legacy_config(str(config_yaml), str(config_json), str(user_mapping))

    assert not config_yaml.exists()


def test_convert_legacy_config_passes_unknown_keys_through_and_keeps_a_plex_block(tmp_path):
    converted = convert_legacy_config(
        {
            "plex": {"show_all": True, "sections": {}},
            "plex_sections": {"show_all": False, "sections": {"Movies": {}}},
            "something_custom": {"kept": True},
        }
    )

    # A file that already has `plex` must not lose it to the rename.
    assert converted["plex"] == {"show_all": True, "sections": {}}
    assert converted["plex_sections"] == {"show_all": False, "sections": {"Movies": {}}}
    assert converted["something_custom"] == {"kept": True}
    assert list(converted)[0] == "media_server"


def test_convert_legacy_config_keeps_an_explicit_media_server_type():
    assert convert_legacy_config({"media_server": {"type": "jellyfin"}})["media_server"] == {
        "type": "jellyfin"
    }


def test_migration_survives_a_media_server_string_in_the_legacy_config(tmp_path, caplog):
    """1.x never validated the shape of its config, so this reaches us.

    The success logging runs after config.yaml is already written and outside
    the try that turns migration errors into readable instructions, so indexing
    a bare string here replaced the guidance with a raw TypeError.
    """
    config_json = tmp_path / "config.json"
    config_json.write_text(
        json.dumps({"media_server": "plex", "dashboard": {"name": "Legacy"}}),
        encoding="utf-8",
    )
    config_yaml = tmp_path / "config.yaml"

    check_legacy_config(str(config_yaml), str(config_json), str(tmp_path / "user_mapping.json"))

    assert config_yaml.exists()
    assert yaml.safe_load(config_yaml.read_text(encoding="utf-8"))["dashboard"]["name"] == "Legacy"


def test_migration_rewrites_presence_sections_into_libraries(caplog):
    """The runtime no longer reads the 1.x shape, so the migration must translate
    it - otherwise an upgraded install silently loses its presence libraries."""
    with caplog.at_level("WARNING"):
        migrated = convert_legacy_config(
            {
                "presence": {
                    "sections": [
                        {"section_title": "Filme", "display_name": "Filme", "emoji": "🎥"},
                        {"section_title": "Serien", "display_name": "Serien", "emoji": "📺"},
                    ],
                    "offline_text": "off",
                }
            }
        )

    assert migrated["presence"]["libraries"] == ["Filme", "Serien"]
    assert "sections" not in migrated["presence"]
    assert migrated["presence"]["offline_text"] == "off"
    assert "presence.libraries" in caplog.text


def test_migration_leaves_a_presence_without_sections_alone():
    migrated = convert_legacy_config({"presence": {"offline_text": "off"}})

    assert migrated["presence"] == {"offline_text": "off"}


def test_load_config_refuses_broken_yaml_instead_of_using_defaults(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "media_server:\n  type: jellyfin\nstream_details:\n  restrict_to_authorized: true\n"
        "  bad: value: here\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as exc:
        load_config(str(config_file))

    assert str(exc.value) == (
        f"{config_file} is not valid YAML at line 5, column 13: mapping values are not allowed here"
    )


@pytest.mark.parametrize(("raw", "kind"), [("- a\n- b\n", "list"), ("just text\n", "str")])
def test_load_config_refuses_a_non_mapping_top_level(tmp_path, raw, kind):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(raw, encoding="utf-8")

    with pytest.raises(ConfigError, match=f"at the top level, found a {kind}$"):
        load_config(str(config_file))


def test_load_config_treats_an_empty_file_as_defaults(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("# everything commented out\n", encoding="utf-8")

    assert load_config(str(config_file)) == load_config(str(tmp_path / "missing.yaml"))


def test_load_config_uses_defaults_for_a_commented_out_block(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "display:\n  # thousands_separator: ','\npresence:\nglobal_stats:\n  page_2:\n",
        encoding="utf-8",
    )
    defaults = load_config(str(tmp_path / "missing.yaml"))

    config = load_config(str(config_file))

    assert config["display"] == defaults["display"]
    assert config["presence"] == defaults["presence"]
    assert config["global_stats"] == defaults["global_stats"]


def test_load_config_warns_and_uses_defaults_for_a_scalar_block(tmp_path, caplog):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "stream_details: yes\nuser_stats:\n  pages: [behavior]\n", encoding="utf-8"
    )
    defaults = load_config(str(tmp_path / "missing.yaml"))

    with caplog.at_level("WARNING"):
        config = load_config(str(config_file))

    assert config["stream_details"] == defaults["stream_details"]
    assert config["user_stats"]["pages"] == defaults["user_stats"]["pages"]
    assert "Config option stream_details must be a block of options, found bool True" in caplog.text
    assert "Config option user_stats.pages must be a block of options, found list" in caplog.text


def test_load_config_translates_presence_sections_in_config_yaml(tmp_path, caplog):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.safe_dump({"presence": {"sections": [{"section_title": "Movies", "emoji": "x"}]}}),
        encoding="utf-8",
    )

    with caplog.at_level("WARNING"):
        config = load_config(str(config_file))

    assert config["presence"]["libraries"] == ["Movies"]
    assert "sections" not in config["presence"]
    renames = [r for r in caplog.records if "Rename it to presence.libraries" in r.message]
    assert len(renames) == 1


def test_load_config_keeps_presence_libraries_over_legacy_sections(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.safe_dump(
            {"presence": {"libraries": ["Shows"], "sections": [{"section_title": "Movies"}]}}
        ),
        encoding="utf-8",
    )

    assert load_config(str(config_file))["presence"]["libraries"] == ["Shows"]


def test_failed_migration_points_at_the_log_file_on_a_local_run(tmp_path, monkeypatch):
    config_yaml, config_json, user_mapping = _legacy_setup(tmp_path, raw="{broken")
    handler = logging.FileHandler(tmp_path / "bot.log", delay=True)
    bot_logger = logging.getLogger("mediawatch_bot")
    monkeypatch.setattr(bot_logger, "handlers", [handler])

    with pytest.raises(SystemExit) as exc:
        check_legacy_config(str(config_yaml), str(config_json), str(user_mapping))

    assert str(exc.value) == f"Config migration failed. Bot stopped. See {tmp_path / 'bot.log'}."


def test_failed_migration_points_at_the_console_in_docker(tmp_path, monkeypatch):
    config_yaml, config_json, user_mapping = _legacy_setup(tmp_path, raw="{broken")
    monkeypatch.setattr(logging.getLogger("mediawatch_bot"), "handlers", [logging.StreamHandler()])

    with pytest.raises(SystemExit) as exc:
        check_legacy_config(str(config_yaml), str(config_json), str(user_mapping))

    assert str(exc.value) == "Config migration failed. Bot stopped. See the log output above."
