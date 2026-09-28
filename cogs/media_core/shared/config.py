"""
Configuration management utilities for MediaWatch.

This module handles loading, validating, and managing configuration files
in YAML format. Includes checks for legacy JSON configs with clear migration
instructions.

This is platform-agnostic and supports both Plex and Jellyfin configurations.
"""

import os
import json
import yaml
import logging
from typing import Dict, Any, Optional

from .config_utils import get_config_path, write_json_atomic, write_text_atomic


logger = logging.getLogger("mediawatch_bot.media_core.config")


class ConfigError(Exception):
    """config.yaml exists but cannot be used.

    Raised instead of falling back to defaults: the defaults switch privacy
    options such as ``stream_details.restrict_to_authorized`` back off and
    select Plex, so a typo must stop the bot or reject a reload, never quietly
    run a different configuration.
    """


def read_config_yaml(config_file: str) -> Dict[str, Any]:
    """Parse config.yaml into a mapping, raising :class:`ConfigError` if unusable.

    A missing or empty file (every line commented out) yields ``{}``, i.e. the
    defaults - both look intentional. Anything else that is not a mapping is an
    error.
    """
    if not os.path.exists(config_file):
        return {}
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None) or getattr(e, "context_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        problem = getattr(e, "problem", None) or str(e)
        raise ConfigError(f"{config_file} is not valid YAML{where}: {problem}") from None
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"Cannot read {config_file}: {e}") from None

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"{config_file} must contain option: value pairs at the top level, "
            f"found a {type(data).__name__}"
        )
    return data


# 1.x named the Plex library block `plex_sections`; 2.0 calls it `plex`.
LEGACY_CONFIG_KEY_MAP = {"plex_sections": "plex"}

MIGRATED_CONFIG_HEADER = """\
# MediaWatch config.yaml
#
# Automatically converted from data/config.json when this deployment was
# upgraded to MediaWatch 2.0. The original config.json was left untouched but
# is no longer read by the bot.
#
# Options added in 2.0 are not listed here - they fall back to their defaults.
# See data/config.yaml.example for the full, commented option list and
# the upgrade guide for the 1.x -> 2.0 path.
"""


def convert_legacy_config(legacy_config: Any) -> Dict[str, Any]:
    """Translate a 1.x config.json payload into the 2.0 config.yaml layout.

    Args:
        legacy_config: Parsed contents of config.json

    Returns:
        Configuration dictionary in the 2.0 layout

    Raises:
        ValueError: If the payload is not a JSON object
    """
    if not isinstance(legacy_config, dict):
        raise ValueError(
            f"config.json must contain a JSON object, found {type(legacy_config).__name__}"
        )

    # Only rename plex_sections -> plex when that cannot overwrite an existing
    # plex block, so a hand-edited file never loses settings.
    renames = {} if "plex" in legacy_config else dict(LEGACY_CONFIG_KEY_MAP)

    # 1.x was Plex-only; media_server.type decides which cog main.py loads.
    # Listed first so it ends up at the top of the generated YAML. An explicit
    # value in the source file still wins because the loop below overwrites it.
    migrated: Dict[str, Any] = {"media_server": {"type": "plex"}}
    for key, value in legacy_config.items():
        migrated[renames.get(key, key)] = value

    _convert_presence_sections(migrated)
    return migrated


def _convert_presence_sections(migrated: Dict[str, Any]) -> None:
    """Rewrite the 1.x ``presence.sections`` list into ``presence.libraries``.

    1.x repeated the display name and emoji that the library block already
    carried, which let the presence and the dashboard drift apart. 2.0 takes
    names only, and the runtime does not read the old shape at all - so an
    upgrade has to translate it here or the presence silently loses its
    libraries.
    """
    presence = migrated.get("presence")
    if not isinstance(presence, dict):
        return

    sections = presence.pop("sections", None)
    if not isinstance(sections, list) or not sections:
        return

    libraries = [
        section["section_title"]
        for section in sections
        if isinstance(section, dict) and section.get("section_title")
    ]
    if libraries:
        presence["libraries"] = libraries
        logger.warning(
            "Converted presence.sections to presence.libraries (%s). "
            "The display name and emoji now come from the library block.",
            ", ".join(libraries),
        )


def migrate_legacy_config(config_file_json: str, config_file: str) -> Dict[str, Any]:
    """Convert config.json into a new config.yaml, leaving config.json in place.

    Args:
        config_file_json: Path to the legacy config.json
        config_file: Path to the config.yaml that should be created

    Returns:
        The migrated configuration dictionary

    Raises:
        Exception: Any read, parse or write error. The caller turns this into a
            SystemExit with manual migration instructions.
    """
    with open(config_file_json, "r", encoding="utf-8") as f:
        legacy_config = json.load(f)

    migrated = convert_legacy_config(legacy_config)
    body = yaml.safe_dump(migrated, sort_keys=False, allow_unicode=True, default_flow_style=False)

    # Atomic: a half-written config.yaml would look like a valid config on the
    # next start and silently replace the user's settings with fragments.
    write_text_atomic(config_file, MIGRATED_CONFIG_HEADER + body)
    return migrated


def check_legacy_config(
    config_file: str, config_file_json: str, user_mapping_file_json: str
) -> None:
    """Ensure a usable config.yaml exists, converting a 1.x config.json if needed.

    A 1.x deployment only has data/config.json. Refusing to start would leave
    every upgrading user with a container that simply stops, so the file is
    converted automatically instead. config.json itself is never modified,
    renamed or deleted - it is only ignored from then on.

    Note: user_mapping.json is the CURRENT format (not legacy).

    Args:
        config_file: Path to config.yaml
        config_file_json: Path to config.json (legacy)
        user_mapping_file_json: Path to user_mapping.json (current format, not legacy)

    Raises:
        SystemExit: If config.json exists but cannot be converted
    """
    config_yaml_exists = os.path.exists(config_file)
    config_json_exists = os.path.exists(config_file_json)

    # If YAML exists, we're good
    if config_yaml_exists:
        # Warn if legacy config.json still exists (cleanup reminder)
        if config_json_exists:
            logger.warning(
                f"Legacy {config_file_json} found next to config.yaml and is being ignored. "
                "Safe to delete once config.yaml is confirmed working."
            )
        return

    # No YAML, but a 1.x config.json: convert it instead of stopping the bot
    if config_json_exists:
        logger.warning("=" * 70)
        logger.warning("MediaWatch 2.0: converting legacy config.json to config.yaml")
        logger.warning("=" * 70)

        try:
            migrated = migrate_legacy_config(config_file_json, config_file)
        except Exception as e:
            logger.error("=" * 70)
            logger.error(f"Automatic config migration FAILED: {e}")
            logger.error("=" * 70)
            logger.error("")
            logger.error(f"Source: {config_file_json}")
            logger.error(f"Target: {config_file} (not written)")
            logger.error("")
            logger.error("Your config.json was NOT modified. Migrate manually:")
            logger.error("  1. Copy data/config.yaml.example to data/config.yaml")
            logger.error("  2. Transfer your settings from config.json")
            logger.error("  3. Set media_server.type to 'plex'")
            logger.error("")
            logger.error("Migration guide:")
            logger.error("  https://mediawatch.nichtlegacy.com/docs/operations/upgrading-from-1x/")
            logger.error("")
            logger.error("=" * 70)
            raise SystemExit(
                f"Config migration failed. Bot stopped. See {_log_location()}."
            ) from None

        logger.warning(f"Source: {config_file_json} (left untouched)")
        logger.warning(f"Target: {config_file} (created)")
        logger.warning(f"Migrated sections: {', '.join(migrated)}")
        if "plex" in migrated and "plex_sections" not in migrated:
            logger.warning("Renamed section 'plex_sections' to its 2.0 name 'plex'")
        # An explicit "media_server" in the source file overwrites the default,
        # and 1.x never validated its shape - a bare string would make this
        # index a str. The file is already written at this point, so a raw
        # TypeError here would replace the migration guidance with a traceback.
        migrated_type = migrated.get("media_server") or {}
        migrated_type = migrated_type.get("type") if isinstance(migrated_type, dict) else None
        if migrated_type:
            logger.warning(f"Set media_server.type to '{migrated_type}' (1.x was Plex-only)")
        logger.warning("config.json is NOT read anymore - edit config.yaml from now on.")
        logger.warning("Review data/config.yaml.example for the options added in 2.0.")
        logger.warning("=" * 70)
        return

    # No YAML, no JSON - first time setup
    logger.warning(
        "No config.yaml found. Please copy config.yaml.example to config.yaml and customize."
    )


def _log_location() -> str:
    """Where the error details above ended up.

    main.py logs to the console in Docker but only to a file on a local run,
    where "see logs above" would point at an empty terminal.
    """
    for handler in logging.getLogger("mediawatch_bot").handlers:
        if isinstance(handler, logging.FileHandler):
            return handler.baseFilename
    return "the log output above"


def ensure_config_yaml() -> None:
    """Run :func:`check_legacy_config` against the default ``data/`` paths.

    Called from ``main.py`` before any cog is loaded so a 1.x ``config.json``
    is already converted when cogs read their configuration, and so a failed
    conversion stops the bot with a readable message instead of a SystemExit
    escaping a cog constructor.
    """
    config_file = get_config_path()
    data_dir = os.path.dirname(config_file)
    check_legacy_config(
        config_file,
        os.path.join(data_dir, "config.json"),
        os.path.join(data_dir, "user_mapping.json"),
    )


def load_config(config_file: str, config_file_json: str = "") -> Dict[str, Any]:
    """Load configuration from config.yaml with defaults.

    Deep merges user config with defaults to support seamless upgrades when
    new config fields are added in future versions (e.g., 2.0.0 → 2.1.0).

    Args:
        config_file: Path to config.yaml
        config_file_json: Path to config.json (not used, kept for signature compatibility)

    Returns:
        Dictionary with configuration merged with defaults

    Raises:
        ConfigError: If config.yaml exists but is not a readable YAML mapping
    """
    # Define default configuration for all features
    default_config = {
        # NEW in 2.0.0: Media server type (exclusive mode)
        "media_server": {
            "type": "plex"  # Default to plex for backward compatibility
        },
        "dashboard": {"name": "Media Server Dashboard", "icon_url": "", "footer_icon_url": ""},
        # NEW format: plex-specific settings
        "plex": {"show_all": True, "sections": {}},
        # NEW format: jellyfin-specific settings
        "jellyfin": {"show_all": True, "sections": {}},
        # Legacy format (kept for backward compatibility)
        "plex_sections": {"show_all": True, "sections": {}},
        "presence": {
            "enabled": True,
            # custom keeps the pre-2.1 look; watching/listening render as
            # "Watching <text>" / "Listening to <text>".
            "activity_type": "custom",
            "status": "online",
            "offline_status": "dnd",
            # Names from the platform's own section config; a 1.x "sections"
            # list is rewritten into this on load (see load_config).
            "libraries": [],
            "offline_text": "🔴 Server Offline!",
            "auth_failed_text": "",
            "stream_text": "{count} active Stream{s} 🟢",
        },
        "display": {
            # Applies to the dashboard and the presence alike.
            "thousands_separator": ".",
            # Appended where an episode count is shown, on the dashboard tile
            # and in the presence. Translate it for a non-English setup -
            # "Serien Episodes" is a mix of two languages.
            "episode_label": "Episodes",
        },
        "cache": {
            "library_update_interval": 900,  # 15 minutes
            "user_stats_ttl": 60,  # 1 minute for Tautulli-backed user stats calls
        },
        # NEW in 2.0.0: Server settings
        "server": {
            "offline_threshold": 300  # 5 minutes
        },
        # NEW in 2.0.0: Global statistics
        "global_stats": {
            "button_location": "stream_details",
            "restrict_to_authorized": False,
            "page_2": {
                "time_range": 30  # 30 days for peak hours chart
            },
        },
        "stream_controls": {"kill_stream": {"default_reason": "Stopped by administrator"}},
        "stream_details": {
            "show_ip_for_authorized_users": False,
            "restrict_to_authorized": False,
            # Link button inside the details popup. Discord only accepts http(s)
            # URLs on link buttons, so the app hand-off relies on the Plex
            # universal link rather than a plex:// scheme.
            "links": {
                "plex": {
                    "enabled": True,
                    "emoji": "\u25b6\ufe0f",
                    # A self hosted Plex Web works too, but only app.plex.tv
                    # hands the link over to the Plex app on a phone.
                    "base_url": "https://app.plex.tv/desktop",
                },
            },
        },
        # NEW in 2.0.0: User statistics
        "user_stats": {
            "enabled": True,
            "pages": {
                "behavior": True,  # Page 1: Watch Behavior & Streak
                "devices": True,  # Page 2: Devices & Content Types
                "top_content": True,  # Page 3: Top Content & Recent Activity
            },
            "time_range": 0,  # 0 = all time
            "top_tv_count": 10,
            "restrict_to_authorized": False,
        },
        # NEW in 2.0.0: SABnzbd settings
        "sabnzbd": {
            "show_when_empty": False,
            "show_status_icons": True,  # Status icons for downloads
            "diskspace_free_key": "diskspace1",
            "diskspace_total_key": "diskspacetotal1",
            "keywords": [
                # Languages & Audio
                "German",
                "GERMAN",
                "English",
                "ENGLISH",
                "DL",
                "Dubbed",
                "Subbed",
                "AC3",
                "AC3D",
                "EAC3",
                "AAC",
                "Atmos",
                "5.1",
                # Resolution
                "1080p",
                "1080P",
                "2160p",
                "4K",
                "720p",
                "UHD",
                # Video Quality
                "HDR",
                "DV",
                "10bit",
                # Codecs
                "x264",
                "x265",
                "h264",
                "h265",
                "HEVC",
                "AVC",
                # Sources & Formats
                "WEB",
                "BluRay",
                "BDRip",
                "REPACK",
                "Remux",
            ],
        },
    }

    # If no config.yaml exists, use defaults
    if not os.path.exists(config_file):
        logger.warning("No config.yaml found. Using defaults.")
        return default_config

    # Raises ConfigError on a broken file - never fall back to defaults here.
    yaml_config = read_config_yaml(config_file)

    # Remove user_mapping from config (loaded separately)
    config = {k: v for k, v in yaml_config.items() if k != "user_mapping"}

    # The config.json migration translates the 1.x presence list, but a
    # config.yaml written by hand from 1.x docs can still carry it.
    presence = config.get("presence")
    if isinstance(presence, dict) and "sections" in presence and "libraries" not in presence:
        logger.warning(
            f"{config_file} uses the 1.x option presence.sections. "
            "Rename it to presence.libraries and list only the library names."
        )
        _convert_presence_sections(config)

    # Start with merge: defaults + user config
    merged_config = {**default_config, **config}

    # Deep merge for nested dicts to preserve user settings while adding new defaults
    # This is crucial for 2.0.0 → 2.1.0+ upgrades where new fields are added
    for key, default in default_config.items():
        if not isinstance(default, dict):
            continue
        section = _merge_section(key, default, config.get(key))
        # Handle nested dicts (e.g., global_stats.page_2, user_stats.pages)
        for nested_key, nested_default in default.items():
            if isinstance(nested_default, dict):
                section[nested_key] = _merge_section(
                    f"{key}.{nested_key}", nested_default, section.get(nested_key)
                )
        merged_config[key] = section

    # Copy plex_sections to plex if plex not specified (backward compatibility)
    if config.get("plex") is None and "plex_sections" in config:
        merged_config["plex"] = merged_config["plex_sections"]

    # Validate and fix server config
    merged_config = validate_server_config(merged_config)

    return merged_config


def _merge_section(path: str, default: Dict[str, Any], value: Any) -> Dict[str, Any]:
    """Overlay a user block on its defaults.

    A block whose options are all commented out parses as ``None``; that means
    "use the defaults", not "replace the block with None" - readers call
    ``.get()`` on it every tick.
    """
    if value is None:
        return default
    if not isinstance(value, dict):
        logger.warning(
            f"Config option {path} must be a block of options, found {type(value).__name__} "
            f"{value!r}. Using its defaults."
        )
        return default
    return {**default, **value}


def validate_server_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and fix server configuration values.

    Args:
        config: Configuration dictionary

    Returns:
        Validated configuration dictionary
    """
    if "server" not in config:
        config["server"] = {"offline_threshold": 300}
    elif not isinstance(config["server"], dict):
        logger.warning("Invalid server config format. Using defaults.")
        config["server"] = {"offline_threshold": 300}

    server_config = config["server"]
    threshold = server_config.get("offline_threshold", 300)

    # Validate threshold value
    try:
        threshold = int(threshold)
        if threshold < 0:
            logger.warning(
                f"offline_threshold must be >= 0, got {threshold}. Using 0 (immediate offline)."
            )
            threshold = 0
        elif threshold > 3600:
            logger.warning(
                f"offline_threshold is very high ({threshold}s = {threshold / 60:.1f}min). Maximum recommended: 3600s (1 hour)."
            )
        server_config["offline_threshold"] = threshold
    except (ValueError, TypeError):
        logger.warning(f"Invalid offline_threshold value: {threshold}. Using default 300 seconds.")
        server_config["offline_threshold"] = 300

    return config


def load_message_id(message_id_file: str) -> Optional[int]:
    """Load the dashboard message ID from file.

    Args:
        message_id_file: Path to message ID JSON file

    Returns:
        Message ID or None if not found
    """
    if not os.path.exists(message_id_file):
        return None
    try:
        with open(message_id_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Subscript instead of .get(): an emptied or hand-edited file ({}, null,
        # {"message_id": null}, a list) must not take the whole cog down with a
        # TypeError/KeyError in its constructor.
        return int(data["message_id"])
    except (OSError, ValueError, TypeError, KeyError) as e:
        logger.error(
            f"Failed to load message ID from {message_id_file}: {e}. Dashboard message will be recreated."
        )
        return None


def save_message_id(message_id_file: str, message_id: int) -> None:
    """Save the dashboard message ID to file.

    Args:
        message_id_file: Path to message ID JSON file
        message_id: Discord message ID to save
    """
    try:
        write_json_atomic(message_id_file, {"message_id": message_id})
    except OSError as e:
        logger.error(f"Failed to save message ID: {e}")


def load_user_mapping(
    config_file: str, user_mapping_file_json: str, platform: str = "plex"
) -> Dict[str, str]:
    """Load user mapping from user_mapping.json.

    Supports both legacy flat format and new platform-keyed format:
    - Legacy: {"PlexUser": "DisplayName"}
    - New: {"plex": {"PlexUser": "DisplayName"}, "jellyfin": {...}}

    Args:
        config_file: Path to config.yaml (not used, kept for compatibility)
        user_mapping_file_json: Path to user_mapping.json
        platform: Platform to load mappings for ("plex" or "jellyfin")

    Returns:
        Dictionary mapping usernames to display names for the platform
    """
    if not os.path.exists(user_mapping_file_json):
        return {}

    try:
        with open(user_mapping_file_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Check if new format (has platform keys)
        if "plex" in data or "jellyfin" in data:
            return data.get(platform, {})

        # Legacy format - return as-is (assumed to be Plex)
        if platform == "plex":
            return data
        return {}
    except Exception as e:
        logger.error(f"Failed to load user mapping from JSON: {e}")
        return {}
