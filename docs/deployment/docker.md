# Docker Deployment

Docker Compose is the recommended way to run MediaWatch. The container holds no state:
everything the bot persists lives in one bind mount, so an update is a plain container
replacement.

The published image is `ghcr.io/nichtlegacy/mediawatch`:

| Tag | Built from |
| --- | --- |
| `latest` | the newest build of `main`, including every release; what you want unless you have a reason |
| `dev` | the `dev` branch, may break |
| `2.0.0` | a released version; later builds do not move it |
| `sha-…` | one specific build |

This page assumes you already have the token, the Discord IDs and your media server
credentials. If not, start with [Getting started](../getting-started/index.md).

## Deployment directory

Create a directory for the deployment with a `data/` directory for the bot's state. You do
**not** need a clone of the repository.

The bot reads plain environment variables, so it does not matter how Docker passes them
in. Pick one of the two ways below; both behave identically.

=== "`.env` file (recommended)"

    Secrets live in their own file, and `docker-compose.yml` stays free of them, so you can
    paste it into a bug report as it is.

    ```bash
    mkdir -p mediawatch/data && cd mediawatch
    curl -fsSL -o .env https://raw.githubusercontent.com/nichtlegacy/MediaWatch/main/.env.example
    ```

    `docker-compose.yml`:

    ```yaml
    services:
      mediawatch:
        image: ghcr.io/nichtlegacy/mediawatch:latest
        container_name: mediawatch
        restart: unless-stopped
        env_file:
          - .env
        environment:
          # Switches logging to the container output and stops the bot from looking
          # for a .env inside the image. Without it `docker logs` stays empty.
          RUNNING_IN_DOCKER: "true"
          # The container drops to this uid/gid after seeding ./data.
          # Default 1000:1000. Unraid: 99 / 100. See below.
          # PUID: "1000"
          # PGID: "1000"
        volumes:
          - ./data:/app/data
    ```

=== "Everything in the compose file"

    One file holds everything. This is also what an Unraid or Portainer template does:
    every variable is a field, and the template passes it in as an environment variable.

    ```bash
    mkdir -p mediawatch/data && cd mediawatch
    ```

    `docker-compose.yml`:

    ```yaml
    services:
      mediawatch:
        image: ghcr.io/nichtlegacy/mediawatch:latest
        container_name: mediawatch
        restart: unless-stopped
        environment:
          RUNNING_IN_DOCKER: "true"
          DISCORD_TOKEN: "your-bot-token"
          CHANNEL_ID: "123456789012345678"
          DISCORD_GUILD_ID: "123456789012345678"
          DISCORD_AUTHORIZED_USERS: "123456789012345678"
          # Plex
          PLEX_URL: "http://plex:32400"
          PLEX_TOKEN: "your-plex-token"
          # or Jellyfin
          # JELLYFIN_URL: "http://jellyfin:8096"
          # JELLYFIN_API_KEY: "your-api-key"
          # PUID: "1000"
          # PGID: "1000"
        volumes:
          - ./data:/app/data
    ```

    The optional integrations (`TAUTULLI_*`, `SABNZBD_*`, `UPTIME_*`) go into the same
    block; [Environment variables](../configuration/environment.md) lists every name.

    !!! warning "The file now holds your tokens"
        Do not commit it to a public repository and do not paste it into a bug report
        unredacted. If you keep the `env_file: - .env` lines from the other variant, the
        `.env` has to exist, because Compose refuses to start without it.

Create `config.yaml` **before** the first start. Without it the bot runs on defaults,
which means Plex. A Jellyfin setup then stops at the environment check and restarts in
a loop until the file exists:

```bash
mkdir -p data
curl -fsSL -o data/config.yaml https://raw.githubusercontent.com/nichtlegacy/MediaWatch/main/data/config.yaml.example
# edit data/config.yaml: media_server.type and your libraries
```

Then fill in the variables (see [First run](../getting-started/first-run.md)) and start it:

```bash
docker compose up -d
docker logs -f mediawatch
```

On start the entrypoint also copies `config.yaml.example` into `./data` if it is missing.
It never overwrites an existing file, `config.yaml` included.

!!! note "Working on a clone of the repository"
    Its [docker-compose.yml](https://github.com/nichtlegacy/MediaWatch/blob/main/docker-compose.yml)
    is tracked by git and `.env` is not, so keep credentials in `.env` there. An inlined
    `DISCORD_TOKEN` in that file ends up in the next commit.

!!! note "`RUNNING_IN_DOCKER` is not decoration"
    It does two things: logging goes to the container output (stderr) instead of a rotating file, and the bot
    skips `load_dotenv()`: inside the image there is no `.env` to read, because
    `.dockerignore` excludes every `.env*` variant from the build. Forget it and the bot
    still runs, but `docker logs` stays empty and the output disappears into a log file
    inside the container.

The repository's own `docker-compose.yml` builds the image locally (`build: context: .`)
instead of pulling it. That is the development variant; for a deployment use the `image:`
line above.

## The data volume

`./data:/app/data` is the only mount MediaWatch needs. Everything it persists lives there:

| File | Contents |
| --- | --- |
| `config.yaml` | Your configuration |
| `user_mapping.json` | Media server username → display name mapping |
| `dashboard_message_id.json` | The ID of the dashboard message, so a restart edits it instead of posting a new one |
| `runtime_state.json` | The server uptime baseline per platform, plus one-off flags such as whether the 1.x global commands were cleared |

The entrypoint copies missing defaults into the volume on every start and **never**
overwrites an existing file, so your config survives image updates. A 1.x `config.json` in
that directory is converted automatically. See
[Upgrading from 1.x](../operations/upgrading-from-1x.md).

Do not mount `/app` itself. `/app` stays root-owned on purpose so the bot cannot modify
its own code.

## PUID and PGID

The container starts as root, adopts the mounted volume (`chown -R` on `/app/data` and
`/app/logs`), then drops privileges before the bot process ever runs. **The bot itself
never runs as root.**

`PUID` and `PGID` decide which uid/gid it drops to. **Default: `1000:1000`.**

Set them to the account that owns `./data` on the host. Otherwise every start hands the
whole of `./data`, including the `config.yaml` you created, to uid 1000, and you can no
longer edit it from the host:

| Host | Set |
| --- | --- |
| Regular Linux host, first user account | nothing, `1000:1000` is already correct |
| Unraid (share user `nobody:users`) | `PUID: "99"`, `PGID: "100"` |
| Anything else | the output of `id -u` and `id -g` for the account that owns `./data` |

`0` is rejected for either value, because it would keep the bot running as root. The
container then exits before the bot starts and logs:

```
PUID/PGID must not be 0: the bot does not run as root
```

You can confirm what happened in the log; the entrypoint announces it:

```
Starting as mediawatch (99:100)
```

This matters most right after a 1.x upgrade: the automatic `config.json` conversion writes
a new `config.yaml` into the volume, and with the wrong `PUID`/`PGID` that file, like
everything else in `./data`, is owned by the container user and your host user cannot
edit it.

!!! note "A non-root `user:` in compose disables all of this"
    If you start the container with `user: "1000:1000"`, the entrypoint's root branch never
    runs: nothing is chowned, and `PUID`/`PGID` do nothing. The mount then has to be
    writable for that user already.

## Logs

With `RUNNING_IN_DOCKER: "true"` everything goes to the container output (stderr), which `docker logs` shows:

```bash
docker logs -f mediawatch
docker logs --since 10m mediawatch
```

There is no log file inside the container in this mode and no rotation to configure. That
is your Docker daemon's `log-opts`. A [local run](local.md) behaves the opposite way: it
writes `logs/mediawatch_debug.log` and prints nothing.

!!! warning "Logs contain personal data"
    The bot logs at DEBUG level, and the output includes usernames, media titles and player
    names. Read
    [SECURITY.md](https://github.com/nichtlegacy/MediaWatch/blob/main/SECURITY.md) before
    pasting logs into an issue.

## Why there is no HEALTHCHECK

Deliberate, not an oversight. MediaWatch has no HTTP endpoint and emits no heartbeat, so a
health check inside the image could only assert that the process exists, which Docker
already covers: the bot is PID 1, and its exit stops the container, which `restart:
unless-stopped` then handles. A check that cannot fail for a real reason is worse than
none, because it makes `healthy` mean less than it looks.

The failure mode a health check *would* be nice for (the bot is connected to Discord but
the media server is unreachable) is exactly the state the dashboard is designed to
display. Watch the dashboard, or point Uptime Kuma at the media server directly.

## Next

- [Updating and rolling back](updating.md)
- [Configuration reference](../configuration/reference.md)
- [Troubleshooting](../operations/troubleshooting.md)
