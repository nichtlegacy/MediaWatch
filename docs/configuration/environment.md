# Environment variables

Everything MediaWatch needs to authenticate lives here.
[`.env.example`](https://github.com/nichtlegacy/MediaWatch/blob/main/.env.example) is the
template. **Empty and unset are treated the same**: a variable written as `PLEX_TOKEN=`
counts as missing.

Values are read once while the bot starts, so a change to `.env` needs a restart, not
`/reload_config`.

## Always required

The bot refuses to start without these four. Validation runs before it logs in to
Discord, so a missing value costs you a startup, not a silently broken dashboard.

| Variable | Purpose |
| --- | --- |
| `DISCORD_TOKEN` | Bot token from the Discord Developer Portal |
| `CHANNEL_ID` | Numeric ID of the channel the dashboard message lives in |
| `DISCORD_GUILD_ID` | Numeric ID of the server the slash commands are published into |
| `DISCORD_AUTHORIZED_USERS` | Comma-separated numeric user IDs allowed to use the admin commands and Kill Stream, and the only users the `restrict_to_authorized` options let through |

```dotenv
DISCORD_TOKEN=MTIzNDU2Nzg5MDEyMzQ1Njc4.GaBcDe.EXAMPLE_TOKEN_REPLACE_ME
CHANNEL_ID=234567890123456789
DISCORD_GUILD_ID=123456789012345678
DISCORD_AUTHORIZED_USERS=345678901234567890,456789012345678901
```

!!! warning "`DISCORD_GUILD_ID` is mandatory since 2.0"

    Slash commands are published guild-scoped. Without the guild ID there is nothing to
    publish them into, so the bot would come up with zero commands, and an upgraded
    1.x install would keep its stale global ones. Rather than start into that state,
    validation stops with:

    ```text
    DISCORD_GUILD_ID is not set - ID of the Discord server the slash commands are published into (enable Developer Mode in Discord, then right-click the server -> Copy Server ID). Required since 2.0 - slash commands are published into this server only.
    ```

`CHANNEL_ID` and `DISCORD_GUILD_ID` must be bare numbers. Pasting a channel mention or a
message link is the common mistake:

```text
CHANNEL_ID must be a numeric Discord ID, got '<#234567890123456789>'. Enable Developer Mode in Discord and copy the ID via right-click -> Copy ID.
```

`DISCORD_AUTHORIZED_USERS` is checked entry by entry:

```text
DISCORD_AUTHORIZED_USERS contains non-numeric entries: alice. Use a comma-separated list of numeric Discord user IDs, e.g. 123456789012345678,987654321098765432.
```

A value that is not blank but still holds no usable ID, such as `,` or `,,`, is caught
separately, because it would leave every admin command dead without looking wrong:

```text
DISCORD_AUTHORIZED_USERS is set to ',,', which contains no user ID - nobody could use the admin commands. Use a comma-separated list of numeric Discord user IDs, e.g. 123456789012345678,987654321098765432.
```

## Required for the active platform

Which pair is mandatory depends on `media_server.type` in `data/config.yaml`. The other
pair is only checked to spot a platform mix-up and may stay empty.

=== "Plex"

    `media_server.type: "plex"`

    | Variable | Purpose |
    | --- | --- |
    | `PLEX_URL` | Base URL of the Plex server, e.g. `http://192.168.1.10:32400` |
    | `PLEX_TOKEN` | Plex authentication token (`X-Plex-Token`) |

    ```dotenv
    PLEX_URL=http://192.168.1.10:32400
    PLEX_TOKEN=EXAMPLE_PLEX_TOKEN_REPLACE_ME
    ```

    ```text
    PLEX_TOKEN is not set, but media_server.type is 'plex' - Plex authentication token, see https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/.
    ```

=== "Jellyfin"

    `media_server.type: "jellyfin"`

    | Variable | Purpose |
    | --- | --- |
    | `JELLYFIN_URL` | Base URL of the Jellyfin server, e.g. `http://192.168.1.10:8096` |
    | `JELLYFIN_API_KEY` | API key from Dashboard → Advanced → API Keys |

    ```dotenv
    JELLYFIN_URL=http://192.168.1.10:8096
    JELLYFIN_API_KEY=EXAMPLE_JELLYFIN_API_KEY_REPLACE_ME
    ```

    ```text
    JELLYFIN_API_KEY is not set, but media_server.type is 'jellyfin' - Jellyfin API key, created under Dashboard -> Advanced -> API Keys.
    ```

Setting up one platform while `media_server.type` still names the other is common enough
to get its own message:

```text
media_server.type is 'plex', but none of PLEX_URL / PLEX_TOKEN are set - only JELLYFIN_URL / JELLYFIN_API_KEY found. Either set PLEX_URL and PLEX_TOKEN, or switch media_server.type to 'jellyfin' in data/config.yaml.
```

See [Wrong platform selected](../operations/troubleshooting.md#wrong-platform-selected).

## Optional integrations

Each group is all-or-nothing and never fatal. Set every variable of a group, or none.

| Group | Variables | Effect |
| --- | --- | --- |
| Tautulli (**Plex only**) | `TAUTULLI_URL`, `TAUTULLI_API_KEY` | Unlocks stream details, user and global statistics, and the Plex link button |
| SABnzbd | `SABNZBD_URL`, `SABNZBD_API_KEY` | Adds the download queue block to the dashboard |
| Uptime Kuma | `UPTIME_URL`, `UPTIME_USERNAME`, `UPTIME_PASSWORD`, `UPTIME_MONITOR_ID` | Adds 24 h / 7 d / 30 d uptime to the dashboard |

```dotenv
TAUTULLI_URL=http://192.168.1.10:8181
TAUTULLI_API_KEY=EXAMPLE_TAUTULLI_API_KEY_REPLACE_ME

SABNZBD_URL=http://192.168.1.10:8080
SABNZBD_API_KEY=EXAMPLE_SABNZBD_API_KEY_REPLACE_ME

UPTIME_URL=http://192.168.1.10:3001
UPTIME_USERNAME=mediawatch
UPTIME_PASSWORD=EXAMPLE_PASSWORD_REPLACE_ME
UPTIME_MONITOR_ID=12
```

A half-filled group is a warning, and the integration simply stays off:

```text
SABnzbd is only partially configured (missing: SABNZBD_API_KEY). The integration stays disabled until all of SABNZBD_URL, SABNZBD_API_KEY are set.
```

`UPTIME_MONITOR_ID` must be the numeric monitor ID. Any other value disables the block:

```text
Invalid UPTIME_MONITOR_ID: 'abc'. Must be an integer.
Uptime integration disabled due to incomplete/invalid configuration. Set UPTIME_URL, UPTIME_USERNAME, UPTIME_PASSWORD, UPTIME_MONITOR_ID.
```

Tautulli has no Jellyfin equivalent. Leaving it configured after switching platforms is
harmless but pointless, and MediaWatch says so:

```text
TAUTULLI_* is set but media_server.type is 'jellyfin'. Tautulli is a Plex-only integration and will be ignored.
```

## Runtime variables

These are not credentials and normally come from the container, not from `.env`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `RUNNING_IN_DOCKER` | `false` | `"true"` logs to stderr instead of `logs/mediawatch_debug.log` and skips parsing `.env`. The shipped `docker-compose.yml` sets it |
| `PUID` / `PGID` | `1000` / `1000` | uid/gid the container drops to after taking ownership of `data/` and `logs/`, when the container starts as root. Set them to the host account that owns `./data` (Unraid: `99` / `100`). `0` is rejected |
| `TZ` | unset → UTC | Timezone for the stream start and end clock in Plex stream details. Jellyfin does not use it |

An unusable `TZ` is not fatal; the clock falls back to UTC and the reason is logged:

```text
Invalid TZ value 'Europe/Nowhere'; falling back to UTC for stream timing.
```

## Confirming it worked

On a healthy start the validation logs one line before the bot connects:

```text
Environment validation passed (media server: plex)
```

If it fails instead, the block on stderr names every problem at once, so you fix them in
one pass rather than one restart per typo. More symptoms and their messages:
[Troubleshooting](../operations/troubleshooting.md).
