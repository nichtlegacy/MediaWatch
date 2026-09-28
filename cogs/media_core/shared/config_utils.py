"""
Shared configuration utilities for MediaWatch.

This module provides centralized configuration loading functions
used across the media_core package and other modules.
"""

import json
import os
import logging
import tempfile
import yaml
from pathlib import Path
from typing import Any, Dict, Optional, Union


logger = logging.getLogger("mediawatch_bot.media_core.config_utils")


def get_config_path() -> str:
    """Get the absolute path to config.yaml.

    Returns:
        Absolute path to the config.yaml file
    """
    # Navigate from this file to the project root
    # This file is in: cogs/media_core/shared/
    base_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    return os.path.join(base_dir, "data", "config.yaml")


def get_server_type(config: Optional[Dict[str, Any]] = None) -> str:
    """Get the media server type from config.

    Args:
        config: Optional config dict. If not provided, loads from file.

    Returns:
        Server type string ('plex' or 'jellyfin'), defaults to 'plex'
    """
    if config is not None:
        return _server_type_from(config)

    config_file = get_config_path()

    if not os.path.exists(config_file):
        return "plex"

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f)
    except Exception as e:
        logger.warning(f"Failed to read config.yaml: {e}. Defaulting to plex.")
        return "plex"
    return _server_type_from(config_data)


def _server_type_from(config: Any) -> str:
    """Read media_server.type, tolerating case and stray whitespace.

    An unset type means Plex (the 1.x behaviour). A set but unknown value is
    logged: silently loading Plex for a mistyped "jellyfn" ends in env errors
    about PLEX_URL that point away from the real problem.
    """
    media_server = config.get("media_server") if isinstance(config, dict) else None
    raw_type = media_server.get("type") if isinstance(media_server, dict) else None
    if raw_type is None:
        return "plex"

    server_type = str(raw_type).strip().lower()
    if server_type in ("plex", "jellyfin"):
        return server_type

    logger.warning(
        f"Unknown media_server.type {raw_type!r} in config.yaml, falling back to 'plex'. "
        "Valid values: 'plex', 'jellyfin'."
    )
    return "plex"


def get_current_platform() -> str:
    """Alias for get_server_type() for backward compatibility.

    Returns:
        Server type string ('plex' or 'jellyfin')
    """
    return get_server_type()


def _read_umask() -> int:
    """Read the process umask once, at import time.

    `os.umask()` has no read-only form - the value can only be queried by
    setting it and putting it back, and that window is process-wide. The bot
    writes configuration from `asyncio.to_thread` and rotates its log file at
    midnight, so a file created by another thread inside that window would come
    out 0666. The umask does not change while the bot runs, so reading it once
    during import - before any handler or worker thread exists - is enough.
    """
    umask = os.umask(0)
    os.umask(umask)
    return umask


_PROCESS_UMASK = _read_umask()


def _target_mode(target: Path) -> int:
    """Return the permission bits an atomically written file should end up with.

    `tempfile.mkstemp()` always creates its file 0600. Renaming that over the
    target would silently tighten permissions on every write, which matters
    because `data/` is a mounted volume that users edit from the host - on
    Unraid the share user is not the container user, so a 0600 config.yaml
    becomes uneditable right after the 1.x migration wrote it.

    An existing file keeps whatever mode it already had. A new file gets what
    `open()` would have given it, i.e. 0666 minus the umask read at import.
    """
    try:
        return target.stat().st_mode & 0o777
    except OSError:
        return 0o666 & ~_PROCESS_UMASK


def write_text_atomic(path: Union[str, Path], text: str) -> None:
    """Write text to `path` without ever leaving a truncated file behind.

    `open(path, "w")` truncates before the first byte is written, so a restart
    or OOM kill mid-write leaves an empty file. Writing into a temp file in the
    same directory, fsyncing it and then `os.replace()`-ing it into place means
    a reader always sees either the previous file or the complete new one.

    Args:
        path: Target file path
        text: Full file contents to write
    """
    target = Path(path)
    # `os.replace()` replaces a symlink itself, while `_target_mode()` reads the
    # link destination via `stat()`. Resolving first keeps the two consistent and
    # writes through the link: a data/config.yaml pointing at a central
    # configuration would otherwise be swapped for a regular file, leaving the
    # real one with its old contents. Resolving also keeps the temp file next to
    # the file that is actually replaced, which is what makes the rename atomic.
    if target.is_symlink():
        target = Path(os.path.realpath(target))

    target.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, _target_mode(target))
        os.replace(tmp_path, target)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def write_json_atomic(path: Union[str, Path], payload: Any, **dump_kwargs: Any) -> None:
    """Serialize `payload` as JSON and write it atomically.

    Args:
        path: Target file path
        payload: JSON-serializable object
        **dump_kwargs: Passed through to `json.dumps`
    """
    write_text_atomic(path, json.dumps(payload, **dump_kwargs))
