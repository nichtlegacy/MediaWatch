import os
import json

import pytest

from cogs.media_core.shared import config_utils
from cogs.media_core.shared.config_utils import (
    get_current_platform,
    get_server_type,
    write_json_atomic,
    write_text_atomic,
)


def test_get_server_type_prefers_valid_config_dict():
    assert get_server_type({"media_server": {"type": "jellyfin"}}) == "jellyfin"
    assert get_server_type({"media_server": {"type": "plex"}}) == "plex"


def test_get_server_type_defaults_to_plex_for_invalid_config_dict():
    assert get_server_type({"media_server": {"type": "emby"}}) == "plex"
    assert get_server_type({"media_server": {}}) == "plex"
    assert get_server_type("invalid") == "plex"


def test_get_server_type_normalises_case_and_whitespace(caplog):
    with caplog.at_level("WARNING"):
        assert get_server_type({"media_server": {"type": " Jellyfin "}}) == "jellyfin"
    assert caplog.text == ""


def test_get_server_type_warns_about_an_unknown_type(caplog):
    with caplog.at_level("WARNING"):
        assert get_server_type({"media_server": {"type": "jellyfn"}}) == "plex"

    assert "Unknown media_server.type 'jellyfn' in config.yaml, falling back to 'plex'" in (
        caplog.text
    )


def test_get_server_type_tolerates_empty_blocks():
    assert get_server_type({"media_server": None}) == "plex"
    assert get_server_type({"media_server": {"type": None}}) == "plex"


def test_get_server_type_defaults_to_plex_when_file_missing(monkeypatch, tmp_path):
    missing_config = tmp_path / "missing-config.yaml"
    monkeypatch.setattr(
        "cogs.media_core.shared.config_utils.get_config_path",
        lambda: str(missing_config),
    )

    assert get_server_type() == "plex"
    assert get_current_platform() == "plex"


def test_get_server_type_defaults_to_plex_on_yaml_error(monkeypatch, tmp_path):
    invalid_config = tmp_path / "invalid-config.yaml"
    invalid_config.write_text("media_server: [broken", encoding="utf-8")
    monkeypatch.setattr(
        "cogs.media_core.shared.config_utils.get_config_path",
        lambda: str(invalid_config),
    )

    assert get_server_type() == "plex"


def test_write_text_atomic_creates_missing_parent_and_leaves_no_temp_files(tmp_path):
    target = tmp_path / "nested" / "state.json"

    write_text_atomic(target, "hello")

    assert target.read_text(encoding="utf-8") == "hello"
    assert [p.name for p in target.parent.iterdir()] == ["state.json"]


def test_write_json_atomic_roundtrips_and_overwrites(tmp_path):
    target = tmp_path / "state.json"

    write_json_atomic(target, {"a": 1}, indent=2)
    write_json_atomic(target, {"b": "\u00e4"}, ensure_ascii=False)

    assert json.loads(target.read_text(encoding="utf-8")) == {"b": "\u00e4"}


def test_write_text_atomic_keeps_previous_content_when_writing_fails(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    target.write_text('{"message_id": 1}', encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("cogs.media_core.shared.config_utils.os.fsync", boom)

    with pytest.raises(OSError):
        write_text_atomic(target, "truncated")

    # The old file must survive untouched and no temp file may be left behind.
    assert target.read_text(encoding="utf-8") == '{"message_id": 1}'
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_write_text_atomic_uses_umask_for_new_files(tmp_path, monkeypatch):
    """A new file must not inherit mkstemp's private 0600.

    data/ is a mounted volume users edit from the host; on Unraid the share
    user is not the container user, so 0600 would lock them out of the
    config.yaml the 1.x migration just wrote.

    The umask is read once at import (see _read_umask), so this patches the
    cached value rather than calling os.umask() - changing it at test time
    would no longer reach the code under test.
    """
    target = tmp_path / "new.yaml"
    monkeypatch.setattr(config_utils, "_PROCESS_UMASK", 0o022)

    write_text_atomic(target, "media_server:\n  type: plex\n")

    assert target.stat().st_mode & 0o777 == 0o644


def test_write_text_atomic_preserves_existing_mode(tmp_path):
    """Rewriting a file must not change permissions the user chose."""
    target = tmp_path / "existing.json"
    target.write_text("{}", encoding="utf-8")
    os.chmod(target, 0o660)

    write_json_atomic(target, {"message_id": 1})

    assert target.stat().st_mode & 0o777 == 0o660


def test_target_mode_does_not_touch_the_process_umask(tmp_path):
    """Reading the umask per write would open a process-wide 0666 window.

    os.umask() has no read-only form, so the old implementation set it to 0 and
    put it back on every write. The bot writes config from asyncio.to_thread and
    rotates its log at midnight; a file created by another thread inside that
    window came out world-writable.
    """
    before = os.umask(0o027)
    try:
        config_utils._target_mode(tmp_path / "does-not-exist.yaml")
        during = os.umask(0o027)
    finally:
        os.umask(before)

    assert during == 0o027
