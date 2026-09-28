# Architecture

How MediaWatch is put together, and why. This page is for people who want to contribute
or to understand a behaviour rather than configure one.

## The shape of it

MediaWatch is a discord.py bot. Everything it does happens inside cogs (discord.py
extensions), loaded by `main.py` at startup.

```text
main.py                     entry point: logging, config migration, env validation, cog loading
cogs/
  media_core/
    shared/                 everything that is not platform-specific
      base_service.py         the MediaService protocol
      models.py               ServerStatus, ActiveStream, LibraryStats, and the enums
      dashboard_service.py    builds the dashboard embed for both platforms
      config.py               defaults + config.yaml loading, 1.x config.json conversion
      config_utils.py         paths, media_server.type, atomic file writes
      config_helper.py        stream_controls / stream_details config accessors
      env_validation.py       the startup check that stops the bot on missing credentials
      runtime_state.py        the persisted uptime baseline
      presence.py             builds the bot presence from presence.*
      embeds.py, formatters.py
    plex/                   PlexCore cog, PlexMediaService, Plex + Tautulli clients, views
    jellyfin/               JellyfinCore cog, JellyfinMediaService, Jellyfin client, views
  sabnzbd.py                optional download queue block
  uptime.py                 optional Uptime Kuma block
  user_mapping.py           /mapping commands
```

`shared/` never imports from `plex/` or `jellyfin/`; the dependency only points inward.
That is what lets the same dashboard builder serve both platforms.

## Exactly one platform at runtime

`main.py` reads `media_server.type` from `data/config.yaml`, loads every cog in `cogs/`
except `media_core`, and then loads **one** of
`cogs.media_core.plex` or `cogs.media_core.jellyfin`. An unknown value falls back to
`plex`.

```text
Media server type: jellyfin
Loaded media core cog: cogs.media_core.jellyfin
```

This is exclusive by construction, not by accident. Both cogs write the same
`data/dashboard_message_id.json` and both call `bot.change_presence()`, so running them
together would mean two loops editing one Discord message and overwriting each other's
bot status every minute. One platform per bot instance is the boundary that keeps a
single dashboard single.

The consequences run through the whole system:

- Only the active platform's credentials are validated at startup, and only its config
  block (`plex:` or `jellyfin:`) is read.
- `/reload_config` can switch platforms live: it unloads the active media core extension
  and loads the configured one. If the new one fails to start, the previous one is
  loaded back so you are not left with no dashboard at all.
- Two servers means two bot instances, each with its own `.env`, its own `data/`
  directory and its own channel.

## The MediaService protocol

`shared/base_service.py` defines `MediaService` as a `typing.Protocol`, not a base class.
`PlexMediaService` and `JellyfinMediaService` implement it without inheriting from it:

```python
class MediaService(Protocol):
    @property
    def server_type(self) -> ServerType: ...
    @property
    def embed_color(self) -> discord.Color: ...
    @property
    def server_name(self) -> str: ...
    async def get_server_status(self) -> ServerStatus: ...
    async def get_active_streams(self) -> List[ActiveStream]: ...
    async def get_library_stats(self) -> Dict[str, LibraryStats]: ...
    async def close(self) -> None: ...
    def is_connected(self) -> bool: ...
```

The protocol is deliberately narrow: it covers what the dashboard needs and nothing else.
Anything one platform can do and the other cannot (Tautulli-backed user and global
statistics, for instance) stays inside `plex/` instead of being pushed up as an optional
method the Jellyfin side would have to stub out.

The real integration point is the dataclasses in `shared/models.py`. Each service maps
its own API's shape (plexapi objects, Jellyfin session JSON) into `ActiveStream`,
`LibraryStats` and `ServerStatus`, and from that point on the code is platform-agnostic.

## One dashboard, built once

`shared/dashboard_service.py` builds the embed for both platforms. It takes the config,
the platform name and the info dict each core builds from the normalized `ServerStatus`,
and the only thing the platform name decides
is which config block holds the library sections and which credential is named when
authentication fails.

Everything else is shared: the field layout, the three-per-row grid, the library ordering
(configured sections first, then whatever the server reports), the 15-field cap with its
`(showing 8 of 12 libraries)` note, the streams block, and the optional SABnzbd and
Uptime Kuma blocks pulled from the other cogs via `bot.get_cog()`.

That is also why an outage looks the same on both platforms. The dashboard distinguishes
three states, not two:

| State | Shown as |
| --- | --- |
| Reachable | green, with uptime, libraries and streams |
| Unreachable for longer than `server.offline_threshold` | red, with "offline since" |
| Reachable but rejecting the credentials (HTTP 401/403) | orange, naming `PLEX_TOKEN` or `JELLYFIN_API_KEY` |

The third state exists because a wrong token looks exactly like an outage otherwise, and
sends people debugging the wrong machine.

## State is files

There is no database. No Postgres, no Redis, no ORM: the runtime dependencies are
discord.py, plexapi, aiohttp, requests, PyYAML, python-dotenv, python-dateutil, matplotlib
and the Uptime Kuma client, and that is the whole list. Everything persistent lives in `data/`:

| File | Holds | Written by |
| --- | --- | --- |
| `config.yaml` | your configuration | you, or the 1.x conversion |
| `user_mapping.json` | username → display name, keyed per platform | `/mapping`; created empty, or migrated from the flat 1.x format, when the cog loads |
| `dashboard_message_id.json` | which Discord message to edit | the dashboard loop, on first post |
| `runtime_state.json` | server uptime baseline per platform, and the one-time global command cleanup flag | the media service (uptime), `main.py` at startup (cleanup flag) |
| `config.json` | 1.x configuration, read once and then ignored | never, it is left untouched |

Discord itself holds the dashboard, so the bot only needs to remember which message it
owns. Everything else it can re-derive from the media server on the next cycle. Losing
`runtime_state.json` costs the displayed uptime baseline and one extra global-command
cleanup call on the next start, nothing more.

Writes go through `write_text_atomic()` / `write_json_atomic()` in `shared/config_utils.py`:
temp file in the same directory, `fsync`, `os.replace()`. A restart mid-write leaves
either the old file or the new one, never a truncated `config.yaml` that would look valid
on the next start and silently replace your settings with fragments.

## Two loops

The active media core cog runs exactly two background tasks. Both wait for Discord to be
ready before their first tick.

| Loop | Interval | Does |
| --- | --- | --- |
| `update_dashboard` | 1 minute | Fetches server status and streams, asks the SABnzbd cog for downloads and, only while the server is offline, the Uptime cog for its history, builds the embed, edits the dashboard message |
| `update_status` | 5 minutes | Fetches the same status and sets the bot's presence: offline text, stream count, or library totals from `presence.libraries` |

A minute is the resolution of the dashboard: a stream that starts and ends between two
ticks is never shown, and a paused stream can be up to a minute stale. Presence updates
more slowly because Discord rate-limits status changes harder than message edits.

Library totals are not fetched every minute. They are cached inside the service for
`cache.library_update_interval` seconds (default 900), so the per-minute cycle costs a
reachability check and one sessions call, not a full library enumeration.

Both loops catch their own exceptions and log them. A failing tick is skipped, not fatal.
An unreachable server is not an exception at all: it logs a `Failed to connect to …`
line on every tick, shows sixty offline dashboards over an hour, and recovers on its own
when the server comes back. An unexpected error inside a tick is logged as:

```text
Error updating dashboard: <reason>
Error updating status: <reason>
```

### Shutdown, and the uptime baseline

`main.py` installs its own `SIGTERM` and `SIGINT` handlers. discord.py does not do this
for you, and without them `docker stop` gets no cleanup at all: the process dies on the
spot, the grace period runs out and Docker sends `SIGKILL`. With the handlers, closing the
bot walks the loaded cogs, cancels both loops, closes the HTTP sessions and writes a
`last_seen` timestamp.

Two values in `runtime_state.json` carry the server uptime, one per platform:

| Key | Meaning |
| --- | --- |
| `online_since` | when MediaWatch first saw this server reachable, and the number the dashboard counts from |
| `last_seen` | when MediaWatch last saw the server reachable: refreshed once a minute while it is, on shutdown unless the server is confirmed offline, and whenever `online_since` changes |

The pair exists because the two questions are different. `online_since` should survive a
bot restart: updating the image must not reset a server uptime of twelve days. But the bot
cannot see what happened while it was down, and an outage it slept through would leave the
old baseline wrong by exactly that much. `last_seen` bounds the blind spot: on start, if
the gap since it exceeds `server.offline_threshold`, the baseline is dropped and starts
over rather than being reported days off.

!!! note "A hard kill only costs the baseline if the restart is slow"

    `last_seen` is refreshed once a minute while the server is reachable, not only on
    shutdown. After a `docker kill`, an OOM kill, a crash or a host reboot it is at most
    a minute old, so a restart that is back within `server.offline_threshold` minus that
    minute keeps the uptime. A longer gap re-baselines. That is the safe direction (the
    alternative is reporting an uptime that never happened).

## Where the platform difference actually is

| | Plex | Jellyfin |
| --- | --- | --- |
| Client | `plexapi`, synchronous; calls run through `asyncio.to_thread` so a slow server never blocks the event loop | `aiohttp`, async throughout |
| Companion service | Tautulli, optional, unlocks stream details and statistics | none needed |
| User and global statistics | yes, via Tautulli | no, there is no equivalent history source |
| Kill stream | reason passed to the client directly | stop endpoint takes no reason, so it is sent as a separate on-screen message first |
| Library metadata | section names and types from Plex | collection type drives the default emoji and episode counts |

Plex has the larger surface because Tautulli exists, not because Jellyfin is a second
tier. Both go through the same protocol, produce the same models and render through the
same embed builder.
