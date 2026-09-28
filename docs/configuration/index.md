# Configuration

MediaWatch reads its settings from two files, and the split between them is deliberate.

| File | Holds | Contains secrets |
| --- | --- | --- |
| `.env` | Credentials and Discord IDs: bot token, channel, guild, authorized users, the media server URL and its token or API key, plus the optional integrations | **yes** |
| `data/config.yaml` | Behaviour and presentation: which libraries appear, what the embed is called, how long an unreachable server is tolerated, whether buttons are limited to authorized users | no |

No secret is ever read from `config.yaml`. The only presentation value read from the
environment is `TZ`, the clock in Plex stream details. That is what makes `config.yaml` safe to paste into a bug report and `.env` not.

- [Environment variables](environment.md): every variable, when it becomes mandatory
- [Configuration reference](reference.md): every `config.yaml` option with its default
- [Examples](examples.md): complete blocks to copy

## Where the files live

=== "Docker"

    ```text
    docker-compose.yml
    .env                 <- loaded by compose via env_file
    data/
      config.yaml        <- bind-mounted to /app/data
      config.yaml.example
    ```

    The shipped `docker-compose.yml` sets `RUNNING_IN_DOCKER=true`, and MediaWatch then
    does **not** parse `.env` itself. Compose injects the values as real environment
    variables. A `.env` inside the `data/` volume is never read.

=== "Local"

    ```text
    main.py
    .env                 <- read by python-dotenv at startup
    data/
      config.yaml
      config.yaml.example
    ```

    `.env` has to sit next to `main.py`, not next to `config.yaml`.

## What happens at startup when a file is missing

**`.env` missing, or a required value empty**: the bot stops before it connects to
Discord. Empty and unset are treated identically. The log names every missing value:

```text
MediaWatch cannot start: required configuration is missing
```

The full list and the exact wording per variable is on
[Environment variables](environment.md).

**`data/config.yaml` missing**: the bot starts anyway, on built-in defaults:

```text
No config.yaml found. Please copy config.yaml.example to config.yaml and customize.
No config.yaml found. Using defaults.
```

That means Plex, every library shown, and an empty `presence.libraries`, so the idle
presence reads `No streams or libraries configured`. It is a usable first run, but almost
certainly not what you want long-term. In Docker the container copies
`data/config.yaml.example` into the volume whenever it is missing, so you have something to
copy from; it never creates `config.yaml` for you.

**`data/config.json` from 1.x present and no `config.yaml`**: the old file is converted
automatically and left untouched on disk. If the conversion fails, the bot stops with
`Config migration failed. Bot stopped. See <log location>.`, and `config.json` is not
modified. See [Upgrading from 1.x](../operations/upgrading-from-1x.md).

!!! warning "A broken `config.yaml` stops the bot"

    Invalid YAML is never replaced by the defaults, because that would silently switch off
    options like `stream_details.restrict_to_authorized`. At startup the bot stops and
    names the spot:

    ```text
    Bot stopped: /app/data/config.yaml is not valid YAML at line 5, column 13: mapping values are not allowed here. Fix the file and start the bot again.
    ```

    `/reload_config` rejects the same file and keeps the running configuration:

    ```text
    ❌ Config not reloaded, the running configuration is unchanged. Fix the file and run /reload_config again.
    ```

    A file whose every line is commented out counts as empty and runs on the defaults.
    So does a block with every option commented out, such as a bare `display:`.

## You only write down what you change

Every option has a built-in default. Missing keys are merged in from the defaults on
each load, so a three-line `config.yaml` is a valid `config.yaml`, and options added in a
later release start working without you editing anything.

The merge is per option, not per block: setting `stream_details.restrict_to_authorized`
does not reset `stream_details.show_ip_for_authorized_users`. Two exceptions are worth
knowing:

- **Lists are replaced, not merged.** Your own `sabnzbd.keywords` list replaces the
  built-in one completely.
- **`sections` is yours alone.** There is no default library map, so what you write is
  exactly what you get.

## Applying changes

`config.yaml` changes need `/reload_config`, which re-reads the file and reloads the
config-driven cogs without dropping the bot's Discord connection. It also switches
platforms when you changed `media_server.type`, and it is restricted to
`DISCORD_AUTHORIZED_USERS`.

`.env` changes need a **restart**. `/reload_config` never picks up a changed value.
