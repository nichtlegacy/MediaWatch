# First Run

You have the token, the three Discord IDs and your media server credentials. Two files
turn them into a running bot.

## The two files

| File | Contains | Tracked by git |
| --- | --- | --- |
| `.env` | Credentials and Discord IDs, everything secret | No, it is in `.gitignore` |
| `data/config.yaml` | Everything else: platform, libraries, appearance, feature options | No |

Both ship as templates:

```bash
cp .env.example .env
cp data/config.yaml.example data/config.yaml
```

!!! note "Running in Docker?"
    You do not need a clone of the repository. Create a deployment directory with
    `docker-compose.yml`, `.env` and an empty `data/`. The container seeds
    `data/config.yaml.example` on first start, not `config.yaml`: copy it to
    `data/config.yaml` before you edit, otherwise the bot keeps running on built-in
    defaults. See
    [Docker deployment](../deployment/docker.md), then come back here for the contents.

## 1. Fill in `.env`

Only the four Discord values and the pair for your platform are required. Leave the other
platform's variables empty.

```bash
# Discord: all four are required
DISCORD_TOKEN=MTIzNDU2Nzg5MDEyMzQ1Njc4.GaBcDe.EXAMPLE_TOKEN_REPLACE_ME
CHANNEL_ID=234567890123456789
DISCORD_AUTHORIZED_USERS=345678901234567890,456789012345678901
DISCORD_GUILD_ID=123456789012345678

# Plex: required when media_server.type is "plex"
PLEX_URL=http://192.168.1.10:32400
PLEX_TOKEN=xxxxxxxxxxxxxxxxxxxx

# Jellyfin: required when media_server.type is "jellyfin"
JELLYFIN_URL=
JELLYFIN_API_KEY=

# Optional, Plex only: adds stream details, user stats and global stats
TAUTULLI_URL=
TAUTULLI_API_KEY=

# Optional: download queue section
SABNZBD_URL=
SABNZBD_API_KEY=

# Optional: uptime section, all four or none
UPTIME_URL=
UPTIME_USERNAME=
UPTIME_PASSWORD=
UPTIME_MONITOR_ID=
```

Every variable, with its default, is in the
[environment reference](../configuration/environment.md).

## 2. Set the platform in `config.yaml`

`media_server.type` is the switch that decides which half of the code base is loaded. It
lives at the top of `data/config.yaml`. The default is `plex`, which is also used when the
file or the key is missing:

```yaml
media_server:
  type: "plex"    # "plex" or "jellyfin"
```

This value also decides which environment variables are required. Set it to `jellyfin`
and MediaWatch stops asking for `PLEX_URL`/`PLEX_TOKEN` and starts requiring
`JELLYFIN_URL`/`JELLYFIN_API_KEY`.

## 3. Pick your libraries

Configure the block matching your platform. The section keys must match the library names
on your server **exactly**, including case and spaces. Quote anything with a space.

=== "Plex"

    ```yaml
    plex:
      # false = only the sections listed below appear in the dashboard.
      # true  = every library on the server; listed sections keep their order,
      #         display_name and emoji, the rest follow with their server names.
      show_all: false
      sections:
        Movies:
          display_name: "Movies"   # what the dashboard shows; may differ from Plex
          emoji: "🎥"
          show_episodes: false     # movie libraries have no episode count
        "TV Shows":
          display_name: "TV Shows"
          emoji: "📺"
          show_episodes: true      # adds the episode total next to the show count
    ```

=== "Jellyfin"

    ```yaml
    jellyfin:
      # false = only the sections listed below appear in the dashboard.
      # true  = every library on the server; listed sections keep their order,
      #         display_name and emoji, the rest follow with their server names.
      # The shipped example sets true here; this block lists sections, so false.
      show_all: false
      sections:
        Movies:
          display_name: "Movies"
          emoji: "🎥"
          show_episodes: false
        "TV Shows":
          display_name: "TV Shows"
          emoji: "📺"
          show_episodes: true
        Music:
          display_name: "Music"
          emoji: "🎵"
          show_episodes: false
    ```

Set `show_all: true` if you do not want to list libraries by hand. Every remaining option
is documented inline in
[data/config.yaml.example](https://github.com/nichtlegacy/MediaWatch/blob/main/data/config.yaml.example)
and in the [configuration reference](../configuration/reference.md).

!!! note "config.yaml is technically optional"
    Without the file the bot starts on built-in defaults: Plex, all libraries. You almost
    certainly want the file anyway: the defaults cannot know your library names, and
    `media_server.type` is where you would switch to Jellyfin.

## 4. Start it

=== "Docker"

    ```bash
    docker compose up -d
    docker logs -f mediawatch
    ```

=== "Local"

    Create the virtual environment and install the requirements first, as described in
    [Running locally](../deployment/local.md#install).

    ```bash
    source .venv/bin/activate
    python main.py
    ```

    A local run prints nothing to the console while it works. Only a failed startup check
    prints its error block to the terminal. Everything else goes to the log file:

    ```bash
    tail -f logs/mediawatch_debug.log
    ```

Details for both in [Docker](../deployment/docker.md) and
[Running locally](../deployment/local.md).

## 5. Confirm it worked

A successful first start logs these lines, among others. Each line has a timestamp,
the logger name and the level in front:

```text
Environment validation passed (media server: plex)
Media server type: plex
Loaded cog: sabnzbd
Loaded cog: uptime
Loaded cog: user_mapping
Loaded media core cog: cogs.media_core.plex
Command tree synced (guild 123456789012345678)
Command tree synced (global)
Cleared globally registered slash commands (1.x leftovers); commands are published to the configured guild from now on.
MediaWatch v2.0.0 is online as YourBotName
GitHub: https://github.com/nichtlegacy/MediaWatch
New dashboard message created with ID: 567890123456789012
```

The `sabnzbd` and `uptime` cogs are loaded whether or not you configured them; without
their variables they simply contribute nothing to the dashboard. The two global lines
appear on the very first start only: they clear any commands a 1.x install registered
globally, and the result is recorded in `data/runtime_state.json`.

Check them in order. Each line rules out a class of problem:

| Line | What it proves |
| --- | --- |
| `Environment validation passed` | `.env` is complete and the IDs are numeric |
| `Media server type: plex` | The platform the bot chose. `plex` is also the fallback for a missing file or key, and for an unknown value (logged as `Unknown media_server.type …, falling back to 'plex'`). If it says `plex` when you configured `jellyfin`, check the spelling and that the file is `data/config.yaml` next to `main.py` |
| `Loaded media core cog: cogs.media_core.plex` | The platform half loaded without an import error |
| `Command tree synced (guild …)` | `DISCORD_GUILD_ID` is valid and the slash commands are published |
| `… is online as …` | The token is valid and the gateway connection is up |
| `New dashboard message created with ID:` | The bot can post into `CHANNEL_ID` |

From then on the dashboard message is **edited in place** once a minute; library totals
refresh on their own schedule. You will not see a new message per update. The log keeps a
`Status updated:` line every five minutes and a `Library stats updated and cached` line
every 15 minutes.

`New dashboard message created` appears once per installation. After a restart the bot
reads the stored ID from `data/dashboard_message_id.json` and edits the existing message.
If you see the "created" line on every start, something is wiping that file or the old
message was deleted.

## If something is off

Missing configuration stops the bot before it connects, with a block naming every problem
at once:

```
======================================================================
MediaWatch cannot start: required configuration is missing
======================================================================

Active media server (data/config.yaml -> media_server.type): plex

  - PLEX_TOKEN is not set, but media_server.type is 'plex' - Plex authentication token, …
```

A mismatch between the configured platform and the credentials you actually filled in gets
its own message:

```text
media_server.type is 'plex', but none of PLEX_URL / PLEX_TOKEN are set - only JELLYFIN_URL / JELLYFIN_API_KEY found. Either set PLEX_URL and PLEX_TOKEN, or switch media_server.type to 'jellyfin' in data/config.yaml.
```

A `data/config.yaml` that is not valid YAML stops the bot even earlier:

```text
Bot stopped: data/config.yaml is not valid YAML at line N, column M: <problem>. Fix the file and start the bot again.
```

Everything else (an offline dashboard, missing slash commands, an empty library list)
is sorted by symptom in [Troubleshooting](../operations/troubleshooting.md).

---

Before you hand the channel to other people, read
[Privacy and Visibility](../usage/privacy.md): by default everyone who can read the channel
can open stream details.
