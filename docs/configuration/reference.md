# Configuration reference

Every option `data/config.yaml` understands, grouped by block, with the default the code
falls back to when the key is absent. Credentials are not here. They live in
[`.env`](environment.md).

The commented template is
[`data/config.yaml.example`](https://github.com/nichtlegacy/MediaWatch/blob/main/data/config.yaml.example),
and complete blocks to copy are on [Examples](examples.md).

!!! note "Defaults, not the example file"

    The defaults below are what the code uses when a key is missing. The example file
    ships a populated starting point instead, so the two differ in places, most
    visibly `plex.show_all`, which defaults to `true` but is `false` in the example.

Changes take effect with `/reload_config` or a restart.

---

## `media_server`

| Option | Default | Platform | Description |
| --- | --- | --- | --- |
| `type` | `"plex"` | both | Which platform to load: `plex` or `jellyfin`. Exactly one is active. Case and surrounding spaces are ignored. Any other value, including a typo, falls back to `plex` with the warning `Unknown media_server.type 'jellyfn' in config.yaml, falling back to 'plex'. Valid values: 'plex', 'jellyfin'.` |

This key decides which extension the bot loads and which `PLEX_*` / `JELLYFIN_*`
variables become mandatory. Changing it and running `/reload_config` unloads one platform
and loads the other; if the new one fails to start, the previous one is restored.

## `dashboard`

| Option | Default | Platform | Description |
| --- | --- | --- | --- |
| `name` | `"Media Server Dashboard"` | both | Title in the embed's author line |
| `icon_url` | `""` | both | Author icon **and** embed thumbnail, one URL feeds both |
| `footer_icon_url` | `""` | both | Footer icon |

Empty strings are valid and simply render the embed without an icon.

## `plex` / `jellyfin`

Only the block of the active platform is read. Both take the same shape.

| Option | Default | Platform | Description |
| --- | --- | --- | --- |
| `show_all` | `true` | both | `true` shows every library the server reports, `false` only the ones listed under `sections` |
| `sections` | `{}` | both | Map of library name → display settings. The key must match the library name on the server **exactly**, case-sensitive; quote names containing spaces |
| `sections.<name>.display_name` | the key | both | Name shown in the dashboard |
| `sections.<name>.emoji` | `"🎬"` | Plex | Icon next to the section name, also used on the stream buttons |
| `sections.<name>.emoji` | by library type | Jellyfin | 🎥 movies, 📺 tvshows, 🎵 music, 📚 books, 📷 photos, 📹 home videos, 🎬 for anything else |
| `sections.<name>.show_episodes` | `false` | Plex | Adds a second field with the episode count |
| `sections.<name>.show_episodes` | `true` for TV libraries | Jellyfin | Detected from the library's collection type, so TV libraries get episode counts without configuration |

With `show_all: true` the configured sections keep the order you wrote them in and every
remaining library follows in server order. With `show_all: false` a name you list that
does not exist on the server is skipped silently. Check spelling and capitalisation
first when a section is missing.

!!! warning "At most 15 library fields fit into the embed"

    Discord caps an embed at 25 fields, and the streams and downloads blocks need room.
    Libraries past the fifteenth field are dropped, and the embed says so instead of
    quietly showing too few:

    ```text
    (showing 8 of 12 libraries)
    ```

    A library with `show_episodes: true` costs two of those fields. If you hit the cap,
    switch to `show_all: false` and list what you actually want.

The 1.x key `plex_sections` is still read when no `plex` block exists. New configurations
should use `plex`.

## `presence`

The bot's own status line in the member list, refreshed every five minutes.

| Option | Default | Platform | Description |
| --- | --- | --- | --- |
| `enabled` | `true` | both | `false` leaves the presence untouched entirely |
| `activity_type` | `"custom"` | both | `custom`, `watching` or `listening`, see below |
| `status` | `"online"` | both | Circle next to the bot while the server counts as online: `online`, `idle` or `dnd` |
| `offline_status` | `"dnd"` | both | Circle while the server is offline or the credentials were rejected. Same values as `status` |
| `libraries` | `[]` | both | Libraries shown while nothing is playing. Names only; `"all"` takes every library the dashboard shows (with `show_all: true` that includes libraries not listed under `sections`) |
| `offline_text` | `"🔴 Server Offline!"` | both | Text while the server counts as offline |
| `auth_failed_text` | `""` | both | Text when the server answers but rejects the credentials. Empty falls back to `offline_text` |
| `stream_text` | `"{count} active Stream{s} 🟢"` | both | Text with active streams. `{count}` is the count, `{s}` an `s` unless it is exactly one |

An unknown `status` or `offline_status` falls back to `online`, an unknown `activity_type`
to `custom`, both with a warning:

```text
Unknown presence status 'away', falling back to online.
Unknown presence activity_type 'playing', falling back to custom. Valid: custom, listening, watching.
```

### Activity type

| Value | Discord shows |
| --- | --- |
| `custom` | the text on its own |
| `watching` | `Watching <text>` |
| `listening` | `Listening to <text>` |

`playing`, `competing` and `streaming` are deliberately not offered: the first two read
wrong for a media server, and `streaming` needs a Twitch or YouTube URL or Discord
renders it as `Playing` anyway.

### Libraries

`libraries` holds names, not definitions. The display name and emoji come from the active
platform's `sections` block, so renaming a library there also changes the presence and the
two cannot drift apart.

```yaml
presence:
  libraries: ["Movies", "TV Shows"]
```

Append `:episodes` for the episode count instead of the item count. On Plex this needs
`show_episodes: true` on that section, otherwise the count is `0`. The segment then reads
`21.980 TV Shows Episodes 📺`. [`display.episode_label`](#display) is what gets appended:

```yaml
presence:
  libraries: ["Movies", "TV Shows:episodes"]
```

Names are matched **exactly**, so `"Filme"` and `"Filme - 4K"` stay separate libraries
with separate counts. A name that matches no library is skipped; when nothing matches, the
text falls back to `No streams or libraries configured`.

A library whose own name contains a colon still works: an exact match wins over the
`:episodes` suffix, so `"Filme: Klassiker"` resolves to that library rather than to
`Filme`.

!!! note "Upgrading from 1.x"

    1.x used a `presence.sections` list that repeated the display name and emoji. The
    config migration rewrites it into `libraries` on the first start. A `config.yaml`
    that still has `presence.sections` and no `libraries` is translated on every load,
    with a warning asking you to rename the key:

    ```text
    /app/data/config.yaml uses the 1.x option presence.sections. Rename it to presence.libraries and list only the library names.
    ```

!!! note "Discord caps the text at 128 characters"

    Past that Discord rejects the whole update and the presence stops changing. MediaWatch
    truncates instead and logs a warning naming the limit, but a shorter `libraries` list
    is the better answer.

## `display`

Formatting that applies to the dashboard and the presence alike, so both show a number
the same way.

| Option | Default | Platform | Description |
| --- | --- | --- | --- |
| `thousands_separator` | `"."` | both | `"."` → `2.938`, `","` → `2,938`, `" "` → `2 938`, `""` → `2938` |
| `episode_label` | `"Episodes"` | both | Appended where an episode count is shown (the dashboard tile and a `"<name>:episodes"` presence entry), so `Shows` becomes `Shows Episodes`. Translate it for a non-English setup, or set `""` to drop it |

## `cache`

| Option | Default | Platform | Description |
| --- | --- | --- | --- |
| `library_update_interval` | `900` | both | Seconds between library total refreshes. Lower means more API calls; a newly added library takes up to this long to appear |
| `user_stats_ttl` | `60` | Plex | Seconds of TTL caching for Tautulli user history and player calls. A value that is not a number falls back to `60` with a warning. `0` or a negative value disables the cache |

Library counts are cached, the dashboard is not: streams and server state are fetched
fresh every minute regardless of this block.

## `server`

| Option | Default | Platform | Description |
| --- | --- | --- | --- |
| `offline_threshold` | `300` | both | Seconds an unreachable server is tolerated before the dashboard flips to offline. `0` reports it immediately |

Raise it to cover a nightly backup or an update window; the dashboard stays green for
that long after the server stops answering. A negative value is corrected to `0`, a value
above `3600` is accepted but warned about, and a non-numeric value falls back to `300`:

```text
Invalid offline_threshold value: soon. Using default 300 seconds.
```

The threshold covers unreachability only. A server that answers but **rejects the
credentials** is reported at once, as an authentication failure rather than an outage.
It also bounds the persisted uptime baseline. MediaWatch remembers when it first saw the
server come up, so restarting the bot does not reset the displayed server uptime, even
after a crash: the time it last saw the server reachable is saved once a minute. But it
cannot see what happened while it was down: if the gap is longer than this threshold, the
media server could have restarted unnoticed, so the baseline is dropped and starts over
rather than being reported days off. The log says which:

```text
Discarding the plex uptime baseline: bot was away for 542s (threshold 420s).
```

## `global_stats`

Needs Plex **and** Tautulli. Without `TAUTULLI_URL` and `TAUTULLI_API_KEY` the button
does not exist and this block does nothing.

| Option | Default | Platform | Description |
| --- | --- | --- | --- |
| `button_location` | `"stream_details"` | Plex + Tautulli | Where the Global Stats button appears: `stream_details`, `dashboard` or `both`. An unknown value falls back to the default |
| `restrict_to_authorized` | `false` | Plex + Tautulli | `true` limits the button to `DISCORD_AUTHORIZED_USERS`; everyone else gets an ephemeral rejection |
| `page_2.time_range` | `30` | Plex + Tautulli | Days covered by the page 2 statistics: peak hours, active users, most active day and the top-users leaderboard. Any positive integer, or `"all"`. `0`, a negative number or a non-numeric value falls back to `30` |

!!! warning "This is watch history, not current activity"

    Global statistics include a server-wide top-users-by-watch-time leaderboard.
    `restrict_to_authorized` is kept separate from the one in `stream_details` on
    purpose. See [Privacy and visibility](../usage/privacy.md).

## `stream_controls`

| Option | Default | Platform | Description |
| --- | --- | --- | --- |
| `kill_stream.default_reason` | `"Stopped by administrator"` | both | Prefilled text in the Kill Stream modal; the admin can still edit it before submitting |

Blank or non-text values fall back to the default, and the text is truncated at 200
characters. Plex passes the reason to the client directly. Jellyfin's stop endpoint has
no reason field, so it is sent as a separate on-screen message beforehand. Clients
without `DisplayMessage` support will not show it.

## `stream_details`

| Option | Default | Platform | Description |
| --- | --- | --- | --- |
| `show_ip_for_authorized_users` | `false` | both | `true` shows the client IP in the Connection block, and only to `DISCORD_AUTHORIZED_USERS`. `false` shows it to nobody |
| `restrict_to_authorized` | `false` | both | `true` limits the `Stream N - User` buttons to `DISCORD_AUTHORIZED_USERS`; everyone else gets an ephemeral rejection |
| `links.plex.enabled` | `true` | Plex | Shows the `Plex` link button in the details popup and links the embed title to the same place |
| `links.plex.emoji` | `"▶️"` | Plex | Icon of that button |
| `links.plex.base_url` | `"https://app.plex.tv/desktop"` | Plex | The Plex Web both links point at. A value that is not `http://` or `https://` falls back to the default |

On Plex the details view itself needs Tautulli. The buttons still appear without it as
long as somebody is authorized, because the Kill Stream action behind them only needs
Plex. Jellyfin needs no companion service.

### The Plex link button

`Plex` points at `https://app.plex.tv/desktop#!/server/<machine-id>/details?key=…`,
the same address Tautulli uses for its `plex_url` notification parameter. Discord only
accepts `http`/`https` on a link button, so there is no `plex://` variant. The Plex
mobile apps claim this web link themselves and open in the app, while a desktop click
lands in the browser. Music links to the album, since Plex Web has no page for a single
track.

The **title of the details embed** links to the same address. `enabled: false` removes
the button and the title link together. A switch that only did half of it would be a
half truth.

`base_url` exists because not every server is reached through plex.tv. The route after it
is identical, so a self hosted Plex Web works as well:

```yaml
stream_details:
  links:
    plex:
      base_url: "https://plex.example.com/web"   # or http://192.168.1.10:32400/web
```

!!! warning "Only `app.plex.tv` opens the Plex app"

    The hand-off to the phone app is a universal/app link registered for
    `app.plex.tv`. With your own domain the link stays in the browser on every
    device. Change it when the server is not reachable through plex.tv, or when you
    deliberately want the web app, not to make the link "nicer".

The emoji takes either a unicode emoji or a Discord custom emoji in the form
`"<:name:id>"`, `"<a:name:id>"` for an animated one. The bot can only render a custom
emoji from a server it is a member of, or one of its own application emojis. An empty
string renders the button without an icon. An invalid value, a plain word for example,
falls back to the default and logs:

```text
Ignoring invalid emoji 'Plex': use a unicode emoji or the custom form <:name:id>.
```

## `user_stats`

Needs Plex **and** Tautulli.

| Option | Default | Platform | Description |
| --- | --- | --- | --- |
| `enabled` | `true` | Plex + Tautulli | Shows the User Stats button inside stream details |
| `restrict_to_authorized` | `false` | Plex + Tautulli | `true` limits the user statistics to `DISCORD_AUTHORIZED_USERS`; everyone else gets an ephemeral refusal. The button stays visible |
| `pages.behavior` | `true` | Plex + Tautulli | Page 1: watch behaviour and streak |
| `pages.devices` | `true` | Plex + Tautulli | Page 2: devices and content types |
| `pages.top_content` | `true` | Plex + Tautulli | Page 3: top TV shows |
| `time_range` | `0` | Plex + Tautulli | Days covered, `0` means all time. Negative or non-numeric values become `0` |
| `top_tv_count` | `10` | Plex + Tautulli | Number of shows on page 3, clamped to `0`–`10`, a non-numeric value becomes `10`. `0` hides the section |

Page order is fixed; the footer numbering follows whichever pages you leave enabled.
Music, TV and movies drop out of the content breakdown automatically when the user has no
plays of that type. The chart cache is a hardcoded 300 seconds and not configurable.

## `sabnzbd`

Needs `SABNZBD_URL` and `SABNZBD_API_KEY`. Without them the block is skipped entirely.

| Option | Default | Platform | Description |
| --- | --- | --- | --- |
| `show_when_empty` | `false` | both | `true` keeps the block with a "no active downloads" note, `false` hides it while the queue is empty |
| `show_status_icons` | `true` | both | Status icon before each download name: ⏸️ paused, 🔍 checking, ⏳ propagating, 📦 fetching, 📥 downloading |
| `diskspace_free_key` | `"diskspace1"` | both | Which SABnzbd value is reported as free space: `diskspace1` (download directory) or `diskspace2` (complete directory) |
| `diskspace_total_key` | `"diskspacetotal1"` | both | Same for total space: `diskspacetotal1` or `diskspacetotal2` |
| `keywords` | long built-in list | both | Release tags the download name is truncated at. Your own list **replaces** the default, it is not added to it |

The disk space keys are checked against the live API each time the SABnzbd cog loads, at
startup and on `/reload_config`. A key your SABnzbd does not report is logged as a warning,
and the embed shows `Unknown` for it:

```text
⚠️ SABnzbd config: 'diskspace_free_key' is set to 'diskspace2' but this key was not found in SABnzbd API response. Available disk space keys: ['diskspace1', 'diskspacetotal1']
```

The dashboard shows at most four downloads at a time; the `Downloads` field shows the
remaining size of the whole queue.
