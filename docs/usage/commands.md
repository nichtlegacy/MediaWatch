# Commands

MediaWatch has five slash commands, two slash command groups, and one prefix command.
**Every one of them is restricted to `DISCORD_AUTHORIZED_USERS`**. There are no roles
and no per-command permissions. An unauthorized call is answered, not silently ignored.
`/load`, `/unload`, `/reload`, `/reload_config`, `/cogs` and `!sync` reply:

```
❌ You are not authorized to execute this command.
```

`/mapping` replies with a `❌ Not Authorized` embed instead: `You are not authorized to
manage user mappings.` (`/mapping list`: `You are not authorized to view user mappings.`)
`/maintenance` replies with a `❌ Not Authorized` embed: `You are not authorized to manage
maintenance mode.`

All slash commands are published into `DISCORD_GUILD_ID` only. They do not appear in any
other server the bot is in. If none of them show up at all, see
[Troubleshooting](../operations/troubleshooting.md#slash-commands-do-not-appear).

## Day-to-day

### `/mapping`

Maps a media server username to the name shown on the dashboard, without a restart and
without editing `data/user_mapping.json` by hand. Mappings are stored per platform, so a
deployment that switches between Plex and Jellyfin keeps both sets.

| Subcommand | Parameters | What it does |
| --- | --- | --- |
| `/mapping add` | `platform`, `username`, `display_name` | Adds a mapping. Refuses if one already exists for that username and points you at `/mapping edit`. |
| `/mapping edit` | `platform`, `username`, `new_display_name` | Changes the display name of an existing mapping. |
| `/mapping remove` | `platform`, `username` | Deletes a mapping. |
| `/mapping list` | `platform` (optional: `plex`, `jellyfin`, `all`) | Lists the mappings. Without the parameter it lists the currently active platform. |

`username` is the **exact, case-sensitive** name on the media server. For `remove` and
`edit` the field autocompletes from the mappings you already have. That autocomplete
runs the same authorization check as the command itself, so it does not leak the list to
anyone else.

Changes take effect on the next dashboard update; no `/reload_config` needed.

### `/maintenance`

Announces planned work on the dashboard instead of letting it turn red. While it is
active, the dashboard reads **"Server is under maintenance 🛠️"** with your reason and the
expected end, and the presence shows `presence.maintenance_text`. See
[The Dashboard](dashboard.md#during-maintenance) for what the embed shows.

| Subcommand | Parameters | What it does |
| --- | --- | --- |
| `/maintenance start` | `reason` (optional, up to 300 characters), `duration` (optional) | Starts maintenance. Run it again while maintenance is active to update it: the start time stays, and an option you leave out keeps its current value. |
| `/maintenance end` | none | Ends maintenance. The reply says how long it lasted. |
| `/maintenance status` | none | Shows whether maintenance is active, since when, the expected end and who started it. |

`duration` is counted **from now**, also on an update, so `/maintenance start duration:30m`
during an overrunning maintenance means "30 more minutes". It takes minutes, hours and
days: `30m`, `45min`, `2h`, `1h30m`, `1d`, or bare minutes like `90`. The field suggests
common values, and you can type any other. The range is 1 minute to 7 days; anything else
is answered with `❌ Invalid Duration` and changes nothing:

```text
Invalid duration "soon". Use minutes, hours or days like 30m, 2h, 1h30m or 1d.
The duration must be between 1 minute and 7 days.
```

Without a duration, maintenance runs until `/maintenance end`. With one, it ends on its
own once the announced end has passed **and** the server answers again (turn that off
with `maintenance.auto_end: false`). An overrun while the server is still down keeps the
maintenance embed and adds "⚠️ Taking longer than planned" instead of flipping to offline.

All replies are ephemeral. Start and end re-render the dashboard right away, not on the
next one-minute tick, and the presence follows with it. Maintenance is saved to
`data/runtime_state.json`, so it survives a crash or a restart of the bot or the host.
When that file cannot be written, the reply adds a `⚠️ Not Saved` field: maintenance mode
still works, but only until the bot restarts.

### `/reload_config`

Re-reads `data/config.yaml` and reloads the cogs that are driven by it: the active media
core extension and, if loaded, SABnzbd. Use it after editing library sections, presence
texts, the privacy options or SABnzbd settings.

It also handles a change of `media_server.type`: the running platform is unloaded and the
newly configured one loaded. If the new one fails to load, the previous one is restored
rather than leaving you with no media cog at all. The reply lists what happened:

```
✅ Applied config reload.
- reloaded `cogs.media_core.plex`
- reloaded `cogs.sabnzbd`

If this changes slash commands, publish them with `!sync guild`.
```

If `config.yaml` is invalid, nothing is reloaded and the reply reads `❌ Config not reloaded,
the running configuration is unchanged. Fix the file and run /reload_config again.`,
followed by the parse error.

!!! note "Not everything is config"

    Environment variables are read at process start. Changing `.env` (a token, a URL,
    `DISCORD_AUTHORIZED_USERS`) needs a restart, not `/reload_config`.

## Extension management

`/cogs`, `/load`, `/unload` and `/reload` operate on the bot's extensions. You need them
rarely: to turn an integration off without editing the deployment, or to recover a cog
that failed to load at startup.

| Command | Parameter | What it does |
| --- | --- | --- |
| `/cogs` | none | Lists every extension with 🟢 loaded / 🔴 not loaded and its description. The media core entry names the active platform, e.g. `Media Core (Plex)`. |
| `/load` | `cog` | Loads an extension that is not running. |
| `/unload` | `cog` | Unloads a running extension. |
| `/reload` | `cog` | Reloads an extension; loads it if it was not running. |

Valid `cog` values are the file and package names under `cogs/`: `sabnzbd`, `uptime`,
`user_mapping`, `maintenance`, and `media_core` for the media server itself. `media_core` resolves to
whichever platform `media_server.type` selects, so you never type `media_core.plex`.
`media-core` and `mediacore` are accepted as spellings.

Loading or unloading an extension changes which slash commands exist, and Discord does
not learn that by itself. The replies say so:

> If this changes slash commands, publish them with `!sync guild`.

## `!sync`: the prefix command

`!sync` pushes the bot's current command tree to Discord. You need it after `/load` or
`/unload` added or removed commands, or when Discord's copy of the command list is out of
step with what the bot has.

Type it as a normal message in a channel the bot can read:

```
!sync guild
```

| Scope | Alias | What it does |
| --- | --- | --- |
| `global` | `g` | Publishes the tree globally. Global commands can take up to an hour to propagate, and MediaWatch publishes guild-scoped on every start, so you rarely want this one: with the guild scope already populated, a global sync makes each command appear twice in this server. Undo it with `!sync clearglobal`. |
| `guild` | `~` | Clears the guild scope, copies the current tree into it and syncs. This is the default when you write a bare `!sync`, and the one you want: it takes effect immediately and mirrors exactly what the bot has loaded. |
| `copy` | `*` | Identical to `guild` in effect; only the confirmation message differs. |
| `clear` | `^` | Empties the guild scope. Every slash command disappears from this server until you sync again. |
| `clearglobal` | `clear-global`, `^^` | Drops the global registration without touching the guild scope. This is what removes leftover globally registered commands from PlexWatch 1.x, but 2.0 already does it once automatically on first start. |

`guild`, `copy` and `clear` have to be used inside a server; in a DM they answer
`` ❌ `<scope>` sync requires running this command inside a server. ``, for example
`` ❌ `guild` sync requires running this command inside a server. ``. An unknown scope lists
the valid ones back to you.

!!! warning "`!sync` is the only reason the bot needs a privileged intent"

    `!sync` is a **prefix** command: to see it, the bot has to read the text of your
    message, which requires the **Message Content Intent** in the Discord developer
    portal. Nothing else in MediaWatch reads message content: the dashboard, the buttons
    and every slash command work without it, and the Server Members and Presence intents
    stay off entirely.

    The intent is requested unconditionally, so it is not optional in practice: with the
    box unticked in the portal, Discord closes the connection and the bot never comes
    online. See
    [Discord bot setup](../getting-started/discord-bot.md#2-enable-the-message-content-intent).
