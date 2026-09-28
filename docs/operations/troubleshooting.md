# Troubleshooting

Grouped by what you see, not by what causes it. Every case quotes the message MediaWatch
actually writes, so you can search the log for the text instead of for a description of
it.

Where to find the log:

- **Docker**: `docker logs -f mediawatch`. Everything goes to the container output.
- **Local run**: `logs/mediawatch_debug.log`, under the directory you started the bot
  from. A local run prints nothing to the console while it runs, so an empty terminal is
  normal; only a startup failure prints its message there.

!!! warning "Read the log before you paste it"

    The log level is DEBUG and the output contains usernames, media titles and player
    names. Check it before attaching it to an issue.

## The bot stops right after starting

MediaWatch validates its environment before it connects to Discord and stops with a block
on stderr rather than booting into a broken state:

```
======================================================================
MediaWatch cannot start: required configuration is missing
======================================================================

Active media server (data/config.yaml -> media_server.type): plex

  - PLEX_TOKEN is not set, but media_server.type is 'plex' - Plex authentication token, see https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/.

All of these are environment variables:
  Local run: put them into the .env file next to main.py (template: .env.example)
  Docker:    put them into a .env file next to docker-compose.yml (loaded via
             'env_file: - .env'), or set them under 'environment:' in your
             compose file or as variables of an Unraid or Portainer template

======================================================================
```

Every missing value gets its own line naming the variable and where to get it. Fill it in
and start again.

Variants of the same block:

- **A value that is set but not a number.** `CHANNEL_ID` and `DISCORD_GUILD_ID` are
  checked, and the pasted channel mention is the classic mistake:

  ```text
  CHANNEL_ID must be a numeric Discord ID, got '<#123456789012345678>'. Enable Developer Mode in Discord and copy the ID via right-click -> Copy ID.
  ```

- **An unusable authorized-user list.** Entries that are not numbers are named:

  ```text
  DISCORD_AUTHORIZED_USERS contains non-numeric entries: @admin. Use a comma-separated list of numeric Discord user IDs, e.g. 123456789012345678,987654321098765432.
  ```

  A value that only contains separators, like `,`, is rejected too, because it would leave
  nobody able to use any command:

  ```text
  DISCORD_AUTHORIZED_USERS is set to ',', which contains no user ID - nobody could use the admin commands. Use a comma-separated list of numeric Discord user IDs, e.g. 123456789012345678,987654321098765432.
  ```

- **The credentials belong to the other platform.** See
  [The wrong platform is loaded](#wrong-platform-selected).

A broken `data/config.yaml` stops the bot before that check, with the file position of
the problem:

```
Bot stopped: /app/data/config.yaml is not valid YAML at line 5, column 13: mapping values are not allowed here. Fix the file and start the bot again.
```

Usually a tab instead of spaces, or an unquoted value containing `: `. A file whose top
level is a list or a plain value fails with `must contain option: value pairs at the top
level`.

## The bot starts, then dies without reaching Discord

Validation only checks that values are present and shaped correctly. A wrong token gets
past it, and discord.py rejects it:

```
Failed to start bot: Invalid token - Improper token has been passed.
```

Reset the token in the developer portal and copy the new one; the displayed token cannot
be read again after you leave the page.

If the **Message Content Intent** is not enabled in the portal, Discord closes the
connection instead:

```text
Unexpected error starting bot: Shard ID None is requesting privileged intents that have not been explicitly enabled in the developer portal. It is recommended to go to https://discord.com/developers/applications/ and explicitly enable the privileged intents within your application's page. If this is not possible, then consider disabling the privileged intents instead.
```

MediaWatch requests that intent unconditionally for the `!sync` prefix command, so it is
not optional. Enable it under **Bot → Privileged Gateway Intents**. Leave Server Members
and Presence off.

## The dashboard says "offline" although the server is running

Two different states, two different causes. Read the embed title first.

**"Server is currently Offline! ⚠️"**: MediaWatch could not reach the server at all. In
the log:

```text
Server unreachable. Starting threshold timer (300s).
Server marked as offline
```

The line before them names the cause: `Failed to connect to Plex server: …`,
`Failed to connect to Jellyfin server: …` or `Failed to connect to Jellyfin: HTTP 5xx`.

Check, in this order:

1. `PLEX_URL` / `JELLYFIN_URL` including scheme and port
   (`http://192.168.1.10:32400`, `http://192.168.1.10:8096`).
2. Whether that address is reachable **from inside the container**, not just from your
   desktop. `localhost` in a container is the container, not the host.
3. That the server is actually up.

Note the delay: once the bot has reached the server, `server.offline_threshold` (default
300 seconds) has to elapse before the dashboard flips, so a short media server restart
does not turn the dashboard red. If the bot never reached the server since it started, a
wrong URL on the first start for example, the dashboard shows offline straight away.

**"Server rejected the credentials! ⛔"**: new in 2.0. The server answered but refused the
token. The embed says so directly:

> **Authentication failed:** The server is reachable, but it rejected the credentials
> (HTTP 401/403). Check **PLEX_TOKEN** in your `.env` file and restart the bot. The media
> server itself is not down.

In the log:

```text
Plex rejected the configured PLEX_TOKEN (HTTP 401/403)
Jellyfin rejected the configured JELLYFIN_API_KEY (HTTP 401)
```

Jellyfin names the actual status, so the second line can also end in `(HTTP 403)`.

This state is reported immediately and does not wait out the offline threshold, because a
rejected token is not a transient outage. Re-fetch the Plex token or create a new Jellyfin
API key. Jellyfin keys stop working the moment they are deleted in its dashboard.

## No dashboard message appears at all

The channel could not be resolved:

```text
Failed to fetch dashboard channel 123456789012345678: <Discord's error>
Dashboard channel 123456789012345678 could not be resolved
```

Either `CHANNEL_ID` is wrong, or the bot cannot see the channel. If the channel resolves
but the bot may not post into it, the error comes one step later:

```text
Failed to create dashboard message: 403 Forbidden (error code: 50013): Missing Permissions
```

Check the channel-level permission overrides for View Channel, Send Messages, Embed Links
and Attach Files: a server-wide permission can be overridden per channel.

## The dashboard message exists but never changes

- The update loop runs **once per minute**. Give it that long; the footer timestamp tells
  you when the last successful edit happened.
- If the message was deleted, the bot notices and posts a new one:
  `Dashboard message not found, creating new one`.
- If the bot lost permission to edit it, it says so and starts over:
  `Dashboard message 123456789012345678 is not editable by this bot anymore`.
- If you changed `CHANNEL_ID`, the bot posts a new dashboard in the new channel
  (`Dashboard message not found, creating new one`). The old message stays behind; delete
  it by hand.

## Something is missing from the embed

- **A library is missing.** With `show_all: false`, only the sections listed under
  `plex:` / `jellyfin:` are shown, and the key has to match the library name on the server
  exactly, including case and spaces. Quote names containing spaces (`"TV Shows"`).
- **A newly added library does not show up.** Library totals are cached for
  `cache.library_update_interval` seconds (default 900).
- **Libraries stop after the fifteenth field.** The embed is capped at 15 library fields
  so Discord's 25-field limit still leaves room for streams and downloads. A section with
  `show_episodes: true` uses two of them, and the embed names the cap:
  `(showing 6 of 9 libraries)`.
- **Only eight streams are listed.** That is the cap on both the stream list and the
  per-stream buttons. Long stream blocks can cut the list below eight to stay within
  Discord's field limit. Either way the field header says so:
  `12 current Streams: (showing 8 of 12)`.
- **No streams while the server is restarting.** Within `server.offline_threshold` the
  dashboard stays green with the cached library counts and an empty stream list.
- **The SABnzbd block is missing.** With an empty queue it is hidden unless
  `sabnzbd.show_when_empty: true`. A partially configured integration stays off and says
  so:

  ```text
  SABnzbd is only partially configured (missing: SABNZBD_API_KEY). The integration stays disabled until all of SABNZBD_URL, SABNZBD_API_KEY are set.
  ```

- **The Uptime Kuma block is missing although it is configured.** A non-numeric monitor
  ID disables it:

  ```text
  Invalid UPTIME_MONITOR_ID: 'abc'. Must be an integer.
  Uptime integration disabled due to incomplete/invalid configuration. Set UPTIME_URL, UPTIME_USERNAME, UPTIME_PASSWORD, UPTIME_MONITOR_ID.
  ```

- **The Uptime Kuma fields never appear.** They are part of the **offline** embed only.
  An online dashboard shows no uptime history by design. See
  [The Dashboard](../usage/dashboard.md#when-the-server-is-online).

## Slash commands do not appear

MediaWatch publishes its commands into `DISCORD_GUILD_ID` on every start. A successful
sync logs:

```
Command tree synced (guild 123456789012345678)
```

If that line is missing, look for `Failed to sync command tree during setup:` followed by
Discord's error; it names the reason. The usual causes:

- `DISCORD_GUILD_ID` is unset. The bot no longer starts at all in that case, so check the
  startup block above.
- `DISCORD_GUILD_ID` points at a different server than the one you are looking at.
- The bot was invited without the `applications.commands` scope. Re-run the invite URL
  from [step 3](../getting-started/discord-bot.md#3-invite-the-bot); it applies to a bot
  that is already in the server.
- Your Discord client is caching the old command list. Reload it with `Ctrl+R`.

Coming from 1.x you may briefly see every command twice. 2.0 clears the globally
registered 1.x commands once, right after the first guild sync:

```text
Cleared globally registered slash commands (1.x leftovers); commands are published to the configured guild from now on.
```

If commands show up twice later on, a `!sync global` did it: it republishes the whole tree
globally next to the guild copy. Remove the global copy with `!sync clearglobal`. A bare
`!sync` publishes to the guild and does not cause this.

To force a sync by hand, use `!sync guild` in the server. See
[Commands](../usage/commands.md#sync-the-prefix-command).

## A button answers with a refusal

```
❌ Stream details are restricted to authorized users on this server.
❌ User statistics are restricted to authorized users on this server.
❌ Global statistics are restricted to authorized users on this server.
```

That is `stream_details`, `user_stats` or `global_stats` with `restrict_to_authorized: true`,
and the clicking user not being in `DISCORD_AUTHORIZED_USERS`. All three default to
`false`; see [Privacy and visibility](../usage/privacy.md).

Other button outcomes that are not faults:

- `Detailed stream information needs Tautulli. Set TAUTULLI_URL and TAUTULLI_API_KEY to enable it.`:
  Plex stream details are Tautulli-backed. The `Kill Stream` button stays
  available for authorized users without it.
- `This stream is no longer active, or the session cache expired. Please refresh the dashboard and try again.`:
  the stream ended between the last dashboard update and your
  click.
- Nothing happens at all: the buttons inside the stream details stop responding five
  minutes after the last click, the page buttons of the statistics after three. Click the
  dashboard button again.

## Config changes have no effect

`data/config.yaml` is read when a cog loads. Apply changes with `/reload_config`, or
restart the bot. If the file does not parse, `/reload_config` answers with
`❌ Config not reloaded, the running configuration is unchanged.` and the parser error;
the bot keeps running on the previous configuration.

Environment variables are read once at process start. Changing `.env`, including
`DISCORD_AUTHORIZED_USERS`, always needs a restart. In Docker, recreate the container
with `docker compose up -d`; a plain `docker restart` keeps the old values.

## The wrong platform is loaded { #wrong-platform-selected }

If `media_server.type` does not match the credentials you set, startup validation names it
instead of letting you guess:

```text
media_server.type is 'jellyfin', but none of JELLYFIN_URL / JELLYFIN_API_KEY are set - only PLEX_URL / PLEX_TOKEN found. Either set JELLYFIN_URL and JELLYFIN_API_KEY, or switch media_server.type to 'plex' in data/config.yaml.
```

A softer variant of the same mistake only warns, because it is not fatal:

```text
TAUTULLI_* is set but media_server.type is 'jellyfin'. Tautulli is a Plex-only integration and will be ignored.
```

Which platform actually loaded is logged on every start:

```
Media server type: plex
Loaded media core cog: cogs.media_core.plex
```

If that says `plex` while you expected Jellyfin, the bot is not reading the
`data/config.yaml` you edited, or the type is misspelled. A misspelled type falls back to
Plex and says so:

```text
Unknown media_server.type 'jellyfn' in config.yaml, falling back to 'plex'. Valid values: 'plex', 'jellyfin'.
```

In Docker a file that is not read at all means the `./data` mount does not point where you
think it does. A missing config file is logged too:

```
No config.yaml found. Using defaults.
```
