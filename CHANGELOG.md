# Changelog

All notable changes to MediaWatch are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.0.0] - 2026-09-28

The project was called **PlexWatch** and only spoke to Plex. It is now
**MediaWatch** and monitors Plex **or** Jellyfin from the same bot.

### ⚠️ Breaking changes

Read [the upgrade guide](https://mediawatch.nichtlegacy.com/docs/operations/upgrading-from-1x/)
before upgrading. In short:

- **The Docker image moved.** New path: `ghcr.io/nichtlegacy/mediawatch`.
  The old `ghcr.io/nichtlegacy/plexwatch` package keeps its 1.x tags and gets
  no further updates, so an existing install will not be auto-upgraded into
  2.0. You have to change the image path yourself.
- **`:latest` now follows the `main` branch**, every build that passes CI, not
  only releases. Pin a version tag such as `:2.0.0` to stay on releases. A new
  `:dev` tag follows the `dev` branch.
- **`DISCORD_GUILD_ID` is now required.** 1.x registered slash commands
  globally; 2.0 registers them per guild. Without the variable the bot stops at
  startup. On the first start with it set, leftover global commands from 1.x
  are cleared so nothing appears twice.
- **`DISCORD_AUTHORIZED_USERS` is now required** and has to contain at least
  one numeric user ID. In 1.x it was optional.
- **`config.json` is replaced by `config.yaml`.** An existing
  `data/config.json` is converted automatically on first start. The original
  file is left untouched and ignored from then on; the conversion is logged in
  full. Only if the conversion fails does the bot stop, with manual
  instructions.
- **`media_server.type` selects the platform** (`plex` or `jellyfin`) and is
  set to `plex` by the automatic conversion, which is what every 1.x install
  was.
- **`presence.sections` is replaced by `presence.libraries`**, a list of
  library names. Display name and emoji now come from the library block. The
  conversion translates the old list, and a hand-written `config.yaml` that
  still carries it is translated on load with a warning.
- **`data/user_mapping.json` is rewritten in place** into a platform-keyed
  format that 1.x cannot read. Back it up if you might roll back.
- **Startup fails fast on a broken environment.** Missing or unparsable
  required variables abort the start with a message naming what is missing and
  where to set it, instead of booting into a permanently "offline" dashboard.
- **A broken `config.yaml` stops the bot** instead of falling back to the
  defaults, as 1.x did with a broken `config.json`. With the new privacy
  options, a silent fallback would reopen restricted views. The message names
  the file, line and column. `/reload_config` rejects such a file and keeps the
  running configuration. An empty file still means defaults.
- **The dashboard turns offline after `server.offline_threshold`** (default
  `300` seconds) instead of on the first failed check. Set it to `0` for the
  1.x behaviour.
- **The container no longer runs the bot as root.** It starts as root to adopt
  the volume, then drops to `PUID`/`PGID` (default `1000:1000`). Hosts whose
  share user differs, Unraid uses `99:100`, should set both, and recreate the
  container after a change: a plain `docker restart` keeps the old values.
  `PUID` or `PGID` `0` is refused, and the container exits before the bot
  starts.
- **A fresh Docker volume receives only `config.yaml.example`.** Copy it to
  `config.yaml`; until then the bot runs on built-in defaults. 1.x copied a
  complete default config into an empty volume.
- **A local run needs Python 3.12** (1.x: 3.8 and later). Recreate the
  virtualenv and reinstall `requirements.txt`.
- **The log file of a local run is now `logs/mediawatch_debug.log`** (was
  `logs/plexwatch_debug.log`), and log lines carry `mediawatch_bot` instead of
  `plexwatch_bot`. Update any log filter.
- **`/cogs` is limited to `DISCORD_AUTHORIZED_USERS`**, like the other cog
  commands.
- The single-module `cogs/plex_core.py` from 1.x is gone. The bot is now
  `cogs/media_core/`, a package per platform on top of a shared layer, and
  `/load`, `/unload` and `/reload` take `media_core`, resolved to the active
  platform, instead of `plex_core`.

### Added

- **Jellyfin support**: a full platform next to Plex, selected via
  `media_server.type`, with the same dashboard, stream details, Kill Stream and
  library statistics. Clients on the local network are recognised via
  `ipaddress`, which covers Docker's default networks and IPv6, audio and
  subtitle languages are shown as names (`German`, not `deu`), and music
  streams show bit depth and sample rate, as on Plex.
- **Multi-platform architecture**: `cogs/media_core/` with a shared layer
  (models, formatters, config, dashboard embed, presence) and one package per
  platform.
- **YAML configuration** with a documented `data/config.yaml.example`, and an
  automatic conversion of a 1.x `data/config.json`. A block whose options are
  all commented out means the defaults, and an unknown `media_server.type`
  falls back to `plex` with a warning.
- **Environment validation at startup** that checks the required Discord
  variables and the credentials for the *selected* platform, rejects
  non-numeric IDs, and reports the mismatch case explicitly
  (`media_server.type` is jellyfin but only `PLEX_*` is set). Partially
  configured optional integrations warn instead of aborting.
- **Buttons under the dashboard**: one `Stream N - User` button per running
  stream, up to eight, and optionally `🌐 Global Stats`. They keep working
  after a bot restart.
- **Stream details** behind each stream button: device, player, quality,
  transcode decision and tracks. On Plex they come from Tautulli, Jellyfin
  serves them directly. `TZ` sets the timezone of the start and end clock in
  Plex stream details (default UTC).
- **Kill Stream** for `DISCORD_AUTHORIZED_USERS`, with a reason message
  prefilled from `stream_controls.kill_stream.default_reason`. On Plex it works
  without Tautulli; on Jellyfin, which has no reason field, the reason is sent
  as an on-screen message first.
- **Tautulli integration** for Plex: user statistics in up to three pages
  (watch behaviour, devices with a chart, top shows) and global server
  statistics in three pages (overview, activity with a peak-hour chart, top 10
  users by watch time). Global statistics are cached for five minutes and
  shared between concurrent clicks.
- **Statistics options**: `global_stats.button_location` puts the Global Stats
  button in the stream details, on the dashboard, or both, and
  `global_stats.page_2.time_range` sets the window of the activity page.
  `user_stats.enabled`, `user_stats.pages`, `user_stats.time_range` and
  `user_stats.top_tv_count` shape the user statistics, and
  `cache.user_stats_ttl` caches them.
- **A link to the played item in Plex** from the stream details, which need
  Tautulli: a `Plex` button, and the embed title links to the same place. It
  opens Plex Web, or the Plex app on a phone. Configure it under
  `stream_details.links.plex` (`enabled`, `base_url`, `emoji`); `base_url`
  accepts any Plex Web, for servers that are not reached through plex.tv.
- **Privacy options**, all defaulting to `false` so every view stays open as
  before: `stream_details.restrict_to_authorized`,
  `user_stats.restrict_to_authorized` and `global_stats.restrict_to_authorized`
  limit those views to `DISCORD_AUTHORIZED_USERS`, and
  `stream_details.show_ip_for_authorized_users` shows client IPs to them only.
- **Configurable bot presence**: `presence.enabled`, `activity_type`
  (`custom`, `watching`, `listening`), `status` and `offline_status` (`online`,
  `idle`, `dnd`) and `auth_failed_text`, all defaulting to the 1.x behaviour.
  `presence.libraries` takes library names, `"all"`, and `:episodes` for the
  episode count.
- **`display` options**: `thousands_separator` and `episode_label`, replacing
  the hard-coded English "Episodes".
- **`/mapping` commands** to manage the username-to-display-name mapping from
  Discord, with an autocomplete that only authorized users get. A flat 1.x
  `user_mapping.json` is converted to the platform-keyed format.
- **`/reload_config`** to apply config changes without restarting the bot,
  including a switch of `media_server.type`. If the new platform fails to load,
  the previous one is restored.
- **`!sync`** to republish the slash commands by hand: `guild`, `copy`,
  `global`, `clear` and `clearglobal`. A bare `!sync` means `guild`.
- **Server uptime that survives a bot restart**, kept in
  `data/runtime_state.json`. It is refreshed once a minute while the server is
  reachable, so a crash or `docker kill` keeps it too, and it starts over when
  the bot was away longer than `server.offline_threshold`.
- **A clean shutdown on `SIGTERM`.** The bot runs as PID 1 and 1.x installed no
  handler, so `docker stop` waited out its grace period and killed it.
- **SABnzbd**: a status icon per download (paused, checking, propagating,
  fetching, downloading, can be switched off with `show_status_icons`), disk
  space in the unit that fits instead of fixed GB and TB,
  `sabnzbd.show_when_empty`, and a choice of which disk SABnzbd reports
  (`diskspace_free_key`, `diskspace_total_key`).
- **A test suite and CI**: lint, tests and a Docker build on every push and
  pull request to `main` and `dev`, `ruff` as the single lint and format tool,
  Dependabot for `pip` and `github-actions`, and releases cut by release-please.
  Every published image is started first and checked for its user and file
  permissions.
- A `docker-compose.yml` in the repository, and `CONTRIBUTING.md`,
  `SECURITY.md`, this changelog, issue templates and a pull request template.

### Changed

- Renamed from PlexWatch to MediaWatch across code, docs, image path and
  repository URL.
- The Docker image is based on `python:3.12-slim` instead of
  `python:3-alpine`.
- Blocking `plexapi` calls run off the event loop, so a slow Plex server no
  longer stalls the bot.
- Runtime dependencies are constrained to compatible ranges, so a rebuild
  cannot pull in a new major version.
- The emoji in front of a stream follows the media type (🎥 movie, 📺 episode,
  🎵 track) instead of the library's `emoji`; the stream buttons keep the
  library emoji.
- Episode streams show the full series title. 1.x cut it at the first `:` or
  `-`.
- Library tiles fill complete rows of three.
- Uptime is formatted in days instead of "99+ hours".
- The default `dashboard.name` is `Media Server Dashboard` instead of
  `Plex Dashboard`.
- SABnzbd: each download shows what is left to download instead of its total
  size, and the `Downloads` field sums what is left across the whole queue
  instead of the first four entries. The block is hidden when SABnzbd is not
  configured, and while the queue is empty unless `sabnzbd.show_when_empty` is
  `true`; 1.x always showed "No active downloads". The default `keywords` list
  is longer; a `keywords` list in your config still replaces it completely.

### Performance

- Plex reuses one server connection and HTTP pool. 1.x opened a new connection
  on every loop tick.
- Item and episode counts come from count queries instead of enumerating every
  item of every library.
- The dashboard edit is one request instead of fetching the message first.
- Uptime Kuma is only asked for its history when the offline embed shows it:
  a login and one query, cached for five minutes, off the event loop, instead
  of a login and three queries every minute. A failed fetch is cached too, so
  a Kuma that is down no longer slows every tick.
- The unused Discord message cache is disabled.

### Fixed

- The dashboard no longer stops updating when many streams run at once: the
  stream list respects Discord's 1024-character field limit instead of making
  every edit fail.
- Rejected credentials (401/403) are reported as such instead of showing the
  media server as offline.
- "Offline since" is shown in each reader's local time. 1.x added a fixed hour
  to UTC.
- Plex streams to DLNA and Cast targets are shown instead of "Stream could not
  be loaded".
- One failing episode count no longer blocks the whole library refresh.
- `dashboard_message_id.json` containing `{}` or `null` no longer keeps the
  Plex cog from loading at all, and the file is written atomically.
- A dashboard message the bot may no longer edit is replaced with a new one.
  1.x only handled a deleted message.
- Cogs load and commands sync once at startup. 1.x did both on every gateway
  reconnect, logging "already loaded" errors each time.
- The Uptime Kuma cog loads when `UPTIME_MONITOR_ID` is not set. 1.x failed
  with an error on every start.
- A malformed SABnzbd payload no longer drops the whole dashboard update.
- SABnzbd keeps a base path in `SABNZBD_URL`, so a reverse-proxied SABnzbd is
  reachable.
- SABnzbd download names that start with a filtered keyword are no longer cut
  to an empty string.
- The download list says when it was cut to four entries, like the stream list.
- A server with many libraries no longer makes Discord reject the dashboard:
  the embed shows at most 15 library fields and says how many it left out.
- Elapsed time keeps its hours when the duration is unknown: 3h40m rendered
  as `40:00`.
- The progress bar is clamped, so a stream past 100% no longer draws a wider
  bar and shifts every following line of the dashboard.
- A local run started from another directory finds its cogs. The cogs
  directory was resolved from the working directory.
- The library cache ages on the monotonic clock, so a system clock change no
  longer skews it.
- An Uptime Kuma error after the connection, such as a timeout, no longer drops
  the dashboard update.

### Removed

- The tracked `data/config.json` and `data/user_mapping.json`. The only
  tracked file in `data/` is now `config.yaml.example`.

### Security

- **The container no longer runs the bot as root** (see Breaking changes).
- **Only the `message_content` privileged intent is requested.** 1.x asked for
  all intents, including `members` and `presences`, which it never used.
- **Untrusted strings from the media server are sanitised** and length capped
  before they go into an embed. 1.x rendered titles, usernames, player names
  and SABnzbd release names raw inside the dashboard's code blocks, where they
  could inject Discord markdown and links.
- **Local files stay out of the image.** The 1.x Dockerfile copied the whole
  build context, so a local `docker build` baked the `data/` files and a local
  `.env` into the image. A `.dockerignore` now keeps both out.
- **`.gitignore` ignores every `.env*` file** except `.env.example`, and every
  runtime file in `data/`. 1.x ignored only `.env` and
  `data/dashboard_message_id.json`.
- **Every GitHub workflow pins its actions to commit SHAs** instead of moving
  tags, and the image publishing job no longer requests `id-token: write`.

### Documentation

- A documentation site at
  [mediawatch.nichtlegacy.com/docs](https://mediawatch.nichtlegacy.com/docs/):
  setup guide, Docker and local deployment, updating, a reference for every
  environment variable and config option, dashboard, commands, privacy,
  troubleshooting by symptom, the 1.x upgrade guide and the runtime
  architecture. Every quoted error message matches the code, so you can search
  the log for it.
- A landing page with an interactive Discord demo at
  [mediawatch.nichtlegacy.com](https://mediawatch.nichtlegacy.com/).
- The README was rewritten against the actual runtime behaviour, with
  screenshots of every view of the bot.

## Earlier releases

Up to 1.x this project was released as **PlexWatch**. Those releases are not
listed here; see [v1.1.0 to v1.1.3](https://github.com/nichtlegacy/MediaWatch/releases)
on GitHub. The repository was renamed from `nichtlegacy/PlexWatch` to
`nichtlegacy/MediaWatch`.
