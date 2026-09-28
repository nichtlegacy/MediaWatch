# Updating and Rolling Back

MediaWatch keeps no state in the image and no state in a database. An update is a
container replacement; a rollback is starting the previous tag again. The only thing that
carries over is the `data/` directory.

## Update a Docker deployment

```bash
cd mediawatch          # the directory with docker-compose.yml
docker compose pull
docker compose up -d
docker logs -f mediawatch
```

Watch for the startup sequence described in
[First run](../getting-started/first-run.md). If the bot comes online and the dashboard
message updates in place, you are done. No message is re-posted, because the ID in
`data/dashboard_message_id.json` survived.

Check the changelog before a major version:
[CHANGELOG.md](https://github.com/nichtlegacy/MediaWatch/blob/main/CHANGELOG.md).
Coming from PlexWatch 1.x, follow
[Upgrading from 1.x](../operations/upgrading-from-1x.md) instead: the image path changed
and `DISCORD_GUILD_ID` is a new requirement.

!!! note "`latest` moves under you"
    `docker compose pull` on `:latest` gives you whatever `main` built last. If you want
    updates to be a decision rather than an event, pin a version tag
    (`ghcr.io/nichtlegacy/mediawatch:2.0.0`) and bump it by hand.

## Update a local install

```bash
cd MediaWatch
git pull
source .venv/bin/activate
pip install -r requirements.txt
```

Then restart the process. `pip install` matters even when no dependency looks new, because the
pins in `requirements.txt` move with releases. See [Running locally](local.md).

## What happens on every start

The entrypoint runs before the bot, and it is the same on an update as on a first
install:

1. Creates `/app/data` if it is missing.
2. Copies each file from `/app/defaults` into `/app/data` **only if the target does not
   exist**. Today that is `config.yaml.example`. An existing file is never overwritten,
   and that includes the example: the copy in `./data` stays the one from your first
   install.
3. If the container is running as root: applies `PUID`/`PGID` to the `mediawatch` user,
   `chown -R`s `/app/data` and `/app/logs`, logs `Starting as mediawatch (1000:1000)`, and
   drops privileges.
4. Starts `python main.py`.

Then `main.py` converts a 1.x `config.json` if one is present, validates the environment,
and connects.

New configuration keys do not need any action from you: `config.yaml` is deep-merged over
the built-in defaults, so options added in a release take their default value until you
set them. To see what is new, compare your file against the example inside the current
image:

```bash
docker compose exec mediawatch cat /app/defaults/config.yaml.example | diff data/config.yaml -
```

Or delete `data/config.yaml.example` before `docker compose up -d`, and the entrypoint
seeds the current one. A local install gets the current example with every `git pull`.

## What persists, and what does not

Persisted in `./data`, survives every update:

| File | Why it matters |
| --- | --- |
| `config.yaml` | Your configuration |
| `user_mapping.json` | Username → display name mapping |
| `dashboard_message_id.json` | Without it, the next start posts a **new** dashboard message and orphans the old one |
| `runtime_state.json` | The media server's uptime baseline, so a bot restart does not reset the displayed uptime, plus the flag that the 1.x global commands were already cleared |
| `config.json` | A 1.x leftover. Kept, never modified, and ignored once `config.yaml` exists |

Not persisted, and safe to lose:

- **Logs.** In Docker they go to the container output and live in the Docker daemon's logging driver.
  `/app/logs` inside the container is discarded with the container. A local run keeps
  `logs/mediawatch_debug.log` on disk, plus seven rotated daily files.
- **Caches.** Library counts and statistics are held in memory and rebuilt after a
  restart; the matplotlib font cache is regenerated under `/tmp`.
- **Slash commands.** They are re-published to `DISCORD_GUILD_ID` on every start, so a
  command added by an update appears without you doing anything.

!!! warning "Back up `data/` before a major upgrade"
    ```bash
    cp -a data data.bak-$(date +%F)
    ```
    It is a handful of small files. This is the whole backup story: there is no database and no
    export command.

## Rolling back

The image is replaceable, so a rollback is a tag change:

```yaml
    image: ghcr.io/nichtlegacy/mediawatch:2.0.0
```

```bash
docker compose up -d
```

Locally, check out the release tag or commit you came from and reinstall the
dependencies:

```bash
git checkout <tag-or-commit>
pip install -r requirements.txt
```

This leaves a detached `HEAD`. Run `git switch main` before the next update, otherwise
`git pull` refuses to run.

### Two one-way conversions

Downgrading the code is easy; two things it did to `data/` do not undo themselves. Both
are why the backup above exists.

**`config.json` → `config.yaml`.** The first 2.0 start writes `config.yaml` and leaves
`config.json` untouched on disk. Going back to 1.x therefore works (1.x reads
`config.json`, which is still the version it wrote), but every change you made in
`config.yaml` since then is not in it. Once you delete `config.json`, that path is gone.
Going back to 1.x also means the old image, `ghcr.io/nichtlegacy/plexwatch:latest`; see
[Rolling back to 1.x](../operations/upgrading-from-1x.md#rolling-back-to-1x). If you later
return to 2.x, run `!sync clearglobal` once: 1.x registered its commands globally again,
and the one-time cleanup is already recorded in `runtime_state.json`.

**`user_mapping.json` flat → nested.** The mapping file is rewritten in place from
`{"user": "Name"}` to `{"plex": {"user": "Name"}, "jellyfin": {}}`. There is no backup
copy and no reverse conversion; 1.x cannot read the nested form. Restore it from your
`data/` backup, or flatten the `plex` block by hand.

Rolling back **between 2.x versions** has neither problem: the format is unchanged and
unknown keys in `config.yaml` are ignored.

## After an update, if something is wrong

- The dashboard stopped updating but the bot is online → check the media server
  credentials and reachability first, then [Troubleshooting](../operations/troubleshooting.md).
- Slash commands are missing → check `DISCORD_GUILD_ID`, then run `!sync guild` inside the
  server.
- Slash commands show twice → run `!sync clearglobal` to drop the global copies. A
  `!sync global` causes exactly that.
- A second dashboard message appeared → `dashboard_message_id.json` was lost or the old
  message was deleted. Delete the stray message by hand. The bot only ever edits the ID
  stored in `dashboard_message_id.json`.
