# Upgrading from PlexWatch 1.x

PlexWatch is now called MediaWatch. Follow this page to move a PlexWatch 1.x install to
MediaWatch 2.0.

Three things are **not** automatic and have to be done by hand:

1. change the container image path (Docker/Unraid only)
2. set `DISCORD_GUILD_ID`
3. check the result of the automatic `config.json` conversion

Everything else happens on the first start: `config.json` is converted to `config.yaml`,
a flat `user_mapping.json` is converted to the platform-keyed format, and the slash
commands that 1.x registered globally are unregistered.

## What a 1.x deployment looks like

- `data/config.json` as the configuration file
- `data/user_mapping.json` in the flat format
- `data/dashboard_message_id.json`
- slash commands registered **globally**
- image `ghcr.io/nichtlegacy/plexwatch`

## Before you start

Back up the whole `data/` directory. The conversion never deletes or rewrites
`config.json`, but a backup is the only way back if you decide to roll back
(see [Rolling back to 1.x](#rolling-back-to-1x)).

```bash
cp -a data data.backup-1x
```

## Docker / Unraid

1. Stop the container.

2. Change the image path:

   ```text
   ghcr.io/nichtlegacy/plexwatch:latest   ->   ghcr.io/nichtlegacy/mediawatch:latest
   ```

   These are two separate GHCR packages, not a rename. `plexwatch` keeps its existing
   tags and receives no further updates, so `plexwatch:latest` will never become 2.0.
   Staying on the old path means staying on 1.x.

3. Add the `DISCORD_GUILD_ID` environment variable. It is **required** in 2.0. Without
   it the bot stops at startup with an explicit message, because slash commands are
   published guild-scoped and there would be no guild to publish them into.

   To find the ID: Discord -> User Settings -> Advanced -> enable Developer Mode, then
   right-click your server name -> Copy Server ID.

4. Leave the `/app/data` volume mount as it is. The conversion reads and writes inside it,
   so the container needs write access to that directory.

   2.0 no longer runs the bot as root: the container starts as root, takes ownership of
   `data/` and `logs/`, and then drops to `PUID`/`PGID` (default `1000:1000`). On every
   start the entrypoint re-owns the whole `data/` directory to that account, your 1.x
   files included. Set `PUID`/`PGID` to your host account before the first start, so you
   can edit the converted `config.yaml` from the host. If you forget, set them and
   recreate the container with `docker compose up -d`: a plain `docker restart` keeps the
   old environment. On Unraid, set `PUID=99` and `PGID=100`; applying the template
   recreates the container.

5. Optional, only if you use them: `TAUTULLI_URL` / `TAUTULLI_API_KEY` (Plex only).
   `JELLYFIN_URL` / `JELLYFIN_API_KEY` are only needed if you switch to Jellyfin.

6. Start the container and follow the log (`docker logs -f <container>`).

On Unraid, points 2 to 4 are template fields: `Repository`, a new variable
`DISCORD_GUILD_ID`, and the two variables `PUID=99` / `PGID=100`.

There is no MediaWatch Unraid template yet. The existing PlexWatch template in Community
Applications is maintained by a third party, not by this project, and keeps pointing at
the frozen `plexwatch` package. Until a MediaWatch template exists, edit the two fields on
your existing container by hand. Do not expect the old template to follow this release.

## Local installation

1. Stop the bot.

2. Update the checkout. 2.0 needs Python 3.12; if your virtualenv is older, recreate it
   as described in [Running locally](../deployment/local.md#install).

   ```bash
   git pull
   pip install -r requirements.txt
   ```

3. Add `DISCORD_GUILD_ID` to your `.env`. Every variable is listed in the
   [environment reference](../configuration/environment.md).

4. Start the bot:

   ```bash
   python main.py
   ```

The log file is now `logs/mediawatch_debug.log`, not `logs/plexwatch_debug.log`.

## What the first start does

With `data/config.json` present and no `data/config.yaml`, the log shows:

```text
======================================================================
MediaWatch 2.0: converting legacy config.json to config.yaml
======================================================================
Converted presence.sections to presence.libraries (Movies, Shows). The display name and emoji now come from the library block.
Source: .../data/config.json (left untouched)
Target: .../data/config.yaml (created)
Migrated sections: media_server, dashboard, plex, presence, cache, sabnzbd
Renamed section 'plex_sections' to its 2.0 name 'plex'
Set media_server.type to 'plex' (1.x was Plex-only)
config.json is NOT read anymore - edit config.yaml from now on.
Review data/config.yaml.example for the options added in 2.0.
======================================================================
```

The `presence.sections` line only appears if your `config.json` had that list.

What the conversion does:

- `plex_sections` becomes `plex` (same content, 2.0 section name)
- `media_server.type` is set to `plex`, because 1.x was Plex-only
- `presence.sections` becomes `presence.libraries` (library names only). The presence now
  takes display name and emoji from the `plex` block, so a presence label that differed
  from the dashboard changes
- every other key (`dashboard`, `cache`, `sabnzbd`, anything custom) is carried over
  unchanged
- options that only exist in 2.0 are not written into the file; they fall back to
  their defaults
- `config.json` stays on disk, untouched, and is ignored from then on

`data/user_mapping.json` is rewritten in place from the flat 1.x format:

```json
{
  "SomePlexUser": "Display Name"
}
```

to the platform-keyed format:

```json
{
  "plex": {
    "SomePlexUser": "Display Name"
  },
  "jellyfin": {}
}
```

The global slash commands from 1.x are unregistered once, right after the guild sync:

```text
Cleared globally registered slash commands (1.x leftovers); commands are published to the configured guild from now on.
```

This runs once per installation. The outcome is recorded in `data/runtime_state.json`,
so it does not cost an API call on every start.

## Verify after the first start

- `data/config.yaml` exists. It opens with a generated header comment explaining where
  it came from, followed by `media_server:` / `type: plex`
- your library sections, dashboard name, presence texts and SABnzbd keywords are in
  `config.yaml` and match what `config.json` had
- `data/config.json` is still there and unchanged
- in Discord, every command appears exactly once, and `/mapping` and `/reload_config`
  are present. Discord clients cache the command list, so if you still see duplicates,
  wait a minute or restart the client (Ctrl+R)
- `/mapping list` shows your mappings under the `plex` key
- the dashboard updates in the configured channel

The converted file only holds what 1.x had. Everything added in 2.0 runs on its default:

- new blocks: `server`, `display`, `global_stats`, `stream_controls`, `stream_details`,
  `user_stats`
- new keys in existing blocks: `presence.enabled`, `presence.activity_type`,
  `presence.status`, `presence.offline_status`, `presence.auth_failed_text`,
  `cache.user_stats_ttl`, `sabnzbd.show_when_empty`, `sabnzbd.show_status_icons`,
  `sabnzbd.diskspace_free_key`, `sabnzbd.diskspace_total_key`

`data/config.yaml.example` documents all of them; copy the blocks you want to change into
your `config.yaml`. The [configuration reference](../configuration/reference.md) lists
every default.

Once the deployment is confirmed healthy, you can delete `data/config.json`. Until then
the bot logs on every start that it is being ignored.

## If the bot stops with "Config migration failed"

The conversion only aborts when it cannot produce a correct `config.yaml`: a `config.json`
it cannot read or parse, a payload that is not a JSON object, or a `data/` directory it
cannot write to. `config.json` is never modified in that case. The log names the reason.
To continue manually:

```bash
cp data/config.yaml.example data/config.yaml
```

Then transfer your settings from `config.json`, put the `plex_sections` block under the
`plex` key, and set `media_server.type` to `plex`.

## Rolling back to 1.x

Before you stop 2.0, run `!sync clear` in the server. 1.x never touches the guild scope,
so the 2.0 guild commands would otherwise stay registered and do nothing under 1.x.

Then point the image back at `ghcr.io/nichtlegacy/plexwatch:latest` (locally: check out
the `v1.1.3` tag). `config.json` was never touched, so 1.x reads its configuration as
before. `data/config.yaml` and `data/runtime_state.json` can stay; 1.x ignores them.

One file does need attention: `data/user_mapping.json` **is** rewritten by 2.0 into the
platform-keyed format, which 1.x cannot read. Restore it from your backup:

```bash
cp data.backup-1x/user_mapping.json data/user_mapping.json
```

1.x re-registers its slash commands globally on the next start. If you later upgrade to
2.0 again, run `!sync clearglobal` once after the first start: the automatic cleanup is
already recorded in `data/runtime_state.json` and does not run a second time.
