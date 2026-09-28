"""
Startup validation of the environment variables MediaWatch needs.

Without this check a missing ``PLEX_TOKEN`` (or any other required value) makes
the bot start, never connect, and show a permanently "offline" dashboard without
any hint about the cause. The validation runs once before ``bot.run()`` and stops
the bot with an explicit message naming what is missing and where to set it.
"""

import logging
import os
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .config_utils import get_server_type


logger = logging.getLogger("mediawatch_bot.media_core.env_validation")


# Required regardless of the configured media server.
# DISCORD_GUILD_ID is mandatory since 2.0: commands are published guild-scoped,
# and without it setup_hook skips the sync entirely - an upgraded 1.x bot would
# keep its stale global commands and never show the ones added in 2.0.
REQUIRED_ALWAYS: Tuple[str, ...] = (
    "DISCORD_TOKEN",
    "CHANNEL_ID",
    "DISCORD_AUTHORIZED_USERS",
    "DISCORD_GUILD_ID",
)

# Required depending on media_server.type in data/config.yaml
PLATFORM_VARS: Dict[str, Tuple[str, ...]] = {
    "plex": ("PLEX_URL", "PLEX_TOKEN"),
    "jellyfin": ("JELLYFIN_URL", "JELLYFIN_API_KEY"),
}

# Optional integrations: all-or-nothing, never fatal
INTEGRATIONS: Dict[str, Tuple[str, ...]] = {
    "Tautulli": ("TAUTULLI_URL", "TAUTULLI_API_KEY"),
    "SABnzbd": ("SABNZBD_URL", "SABNZBD_API_KEY"),
    "Uptime Kuma": ("UPTIME_URL", "UPTIME_USERNAME", "UPTIME_PASSWORD", "UPTIME_MONITOR_ID"),
}

DESCRIPTIONS: Dict[str, str] = {
    "DISCORD_TOKEN": (
        "Discord bot token, taken from https://discord.com/developers/applications "
        "-> your application -> Bot -> Reset Token"
    ),
    "CHANNEL_ID": (
        "ID of the Discord channel the dashboard is posted into "
        "(enable Developer Mode in Discord, then right-click the channel -> Copy Channel ID)"
    ),
    "DISCORD_AUTHORIZED_USERS": (
        "comma-separated Discord user IDs that may use the admin commands, "
        "e.g. DISCORD_AUTHORIZED_USERS=123456789012345678,987654321098765432"
    ),
    "DISCORD_GUILD_ID": (
        "ID of the Discord server the slash commands are published into "
        "(enable Developer Mode in Discord, then right-click the server -> Copy Server ID). "
        "Required since 2.0 - slash commands are published into this server only"
    ),
    "PLEX_URL": "URL of your Plex server, e.g. PLEX_URL=http://192.168.1.10:32400",
    "PLEX_TOKEN": (
        "Plex authentication token, see "
        "https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/"
    ),
    "JELLYFIN_URL": "URL of your Jellyfin server, e.g. JELLYFIN_URL=http://192.168.1.10:8096",
    "JELLYFIN_API_KEY": "Jellyfin API key, created under Dashboard -> Advanced -> API Keys",
}


def _value(env: Mapping[str, str], name: str) -> str:
    """Return a stripped environment value, treating blanks as unset."""
    return (env.get(name) or "").strip()


def _is_int(value: str) -> bool:
    try:
        int(value)
    except ValueError:
        return False
    return True


def parse_authorized_users(raw: Optional[str]) -> List[int]:
    """Parse DISCORD_AUTHORIZED_USERS into IDs, skipping unparsable entries.

    Malformed entries are reported by :func:`validate_environment`; parsing here
    stays lenient so importing the bot module never dies with a raw traceback.
    """
    users: List[int] = []
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            users.append(int(entry))
        except ValueError:
            logger.warning(f"Ignoring non-numeric entry in DISCORD_AUTHORIZED_USERS: {entry!r}")
    return users


def _missing_required(env: Mapping[str, str], names: Sequence[str]) -> List[str]:
    return [name for name in names if not _value(env, name)]


def collect_env_issues(env: Mapping[str, str], server_type: str) -> Tuple[List[str], List[str]]:
    """Collect fatal errors and non-fatal warnings for the given environment.

    Args:
        env: Mapping of environment variables (usually ``os.environ``)
        server_type: Active media server type ('plex' or 'jellyfin')

    Returns:
        Tuple of (errors, warnings) as ready-to-log message strings
    """
    errors: List[str] = []
    warnings: List[str] = []

    for name in _missing_required(env, REQUIRED_ALWAYS):
        errors.append(f"{name} is not set - {DESCRIPTIONS[name]}.")

    required = PLATFORM_VARS.get(server_type, PLATFORM_VARS["plex"])
    other_type = "jellyfin" if server_type == "plex" else "plex"
    other_vars = PLATFORM_VARS[other_type]

    missing_platform = _missing_required(env, required)
    if missing_platform:
        other_set = [name for name in other_vars if _value(env, name)]
        if len(missing_platform) == len(required) and other_set:
            errors.append(
                f"media_server.type is '{server_type}', but none of {' / '.join(required)} are set - "
                f"only {' / '.join(other_set)} found. Either set {' and '.join(required)}, "
                f"or switch media_server.type to '{other_type}' in data/config.yaml."
            )
        else:
            for name in missing_platform:
                errors.append(
                    f"{name} is not set, but media_server.type is '{server_type}' - "
                    f"{DESCRIPTIONS[name]}."
                )

    for name in ("CHANNEL_ID", "DISCORD_GUILD_ID"):
        value = _value(env, name)
        if value and not _is_int(value):
            errors.append(
                f"{name} must be a numeric Discord ID, got {value!r}. "
                "Enable Developer Mode in Discord and copy the ID via right-click -> Copy ID."
            )

    # A value like "," or ",," is not blank, so the "is not set" check above
    # lets it through, and it contains no entry the filter below could reject
    # either - while parse_authorized_users() still returns an empty list and
    # every admin command (/load, /reload_config, /cogs, /mapping, !sync) is
    # dead. What matters is whether at least one usable ID comes out.
    raw_users = _value(env, "DISCORD_AUTHORIZED_USERS")
    user_entries = [entry.strip() for entry in raw_users.split(",") if entry.strip()]
    invalid_users = [entry for entry in user_entries if not _is_int(entry)]

    if invalid_users:
        errors.append(
            f"DISCORD_AUTHORIZED_USERS contains non-numeric entries: {', '.join(invalid_users)}. "
            "Use a comma-separated list of numeric Discord user IDs, "
            "e.g. 123456789012345678,987654321098765432."
        )
    elif raw_users and not user_entries:
        errors.append(
            f"DISCORD_AUTHORIZED_USERS is set to {raw_users!r}, which contains no user ID - "
            "nobody could use the admin commands. "
            "Use a comma-separated list of numeric Discord user IDs, "
            "e.g. 123456789012345678,987654321098765432."
        )

    for label, names in INTEGRATIONS.items():
        configured = [name for name in names if _value(env, name)]
        if configured and len(configured) < len(names):
            missing = [name for name in names if name not in configured]
            warnings.append(
                f"{label} is only partially configured (missing: {', '.join(missing)}). "
                f"The integration stays disabled until all of {', '.join(names)} are set."
            )

    if server_type == "jellyfin" and any(_value(env, name) for name in INTEGRATIONS["Tautulli"]):
        warnings.append(
            "TAUTULLI_* is set but media_server.type is 'jellyfin'. "
            "Tautulli is a Plex-only integration and will be ignored."
        )

    return errors, warnings


def validate_environment(
    env: Optional[Mapping[str, str]] = None,
    server_type: Optional[str] = None,
) -> None:
    """Validate the environment and stop the bot when required values are missing.

    Args:
        env: Environment mapping to check, defaults to ``os.environ``
        server_type: Media server type, defaults to the value from data/config.yaml

    Raises:
        SystemExit: If at least one required value is missing or malformed
    """
    env = os.environ if env is None else env
    server_type = server_type or get_server_type()

    errors, warnings = collect_env_issues(env, server_type)

    for warning in warnings:
        logger.warning(warning)

    if not errors:
        logger.info(f"Environment validation passed (media server: {server_type})")
        return

    lines = [
        "=" * 70,
        "MediaWatch cannot start: required configuration is missing",
        "=" * 70,
        "",
        f"Active media server (data/config.yaml -> media_server.type): {server_type}",
        "",
    ]
    lines.extend(f"  - {error}" for error in errors)
    lines.extend(
        [
            "",
            "All of these are environment variables:",
            "  Local run: put them into the .env file next to main.py (template: .env.example)",
            "  Docker:    put them into a .env file next to docker-compose.yml (loaded via",
            "             'env_file: - .env'), or set them under 'environment:' in your",
            "             compose file or as variables of an Unraid or Portainer template",
            "",
            "=" * 70,
        ]
    )

    logger.error("Environment validation failed: " + " | ".join(errors))

    # Raised as the SystemExit message so the full block always lands on stderr,
    # even when logging is configured to write into the log file only.
    raise SystemExit("\n" + "\n".join(lines))
