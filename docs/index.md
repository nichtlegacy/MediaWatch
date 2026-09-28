---
hide:
  - navigation
---

# MediaWatch

A Discord-first monitoring bot for self-hosted media servers. One live dashboard inside
Discord for **Plex** or **Jellyfin**: active streams, library totals and server state,
with optional SABnzbd and Uptime Kuma data.

![The MediaWatch dashboard in a Discord channel](assets/dashboard.png){ loading=lazy }

## Where to start

<div class="grid cards" markdown>

-   :material-rocket-launch: **Set it up**

    ---

    From a fresh Discord application to a running dashboard. The bot token, the one
    privileged intent it needs, invite permissions, and your Plex token or Jellyfin
    API key.

    [Getting started](getting-started/index.md)

-   :material-docker: **Run it**

    ---

    Docker is the recommended way. Compose file, volumes, `PUID`/`PGID`, logs and
    updates, or run it straight from a virtualenv.

    [Deployment](deployment/docker.md)

-   :material-tune: **Configure it**

    ---

    Credentials live in `.env`, behaviour lives in `data/config.yaml`. Every option
    with its default, plus ready-made blocks to copy.

    [Configuration](configuration/index.md)

-   :material-lifebuoy: **Fix it**

    ---

    The common failure modes, grouped by what you actually see, with the exact
    messages MediaWatch writes to the log.

    [Troubleshooting](operations/troubleshooting.md)

</div>

## Two things worth reading first

!!! warning "Everyone in the channel can see more than you might expect"

    By default anyone who can read the dashboard channel can open stream details, and
    on Plex with Tautulli also the global statistics, including a server-wide
    top-users leaderboard. Two config options close that down.

    [Privacy and visibility](usage/privacy.md)

!!! info "Upgrading from PlexWatch 1.x?"

    Three things are not automatic: the container image path changed,
    `DISCORD_GUILD_ID` is now required, and you should check the result of the
    automatic `config.json` conversion. Your old file is never modified.

    [Upgrading from 1.x](operations/upgrading-from-1x.md)

## Platform scope

MediaWatch loads exactly **one** platform at runtime, selected by `media_server.type`.

| Capability | Plex | Jellyfin |
| --- | :---: | :---: |
| Live dashboard and library totals | :material-check: | :material-check: |
| Stream details | With Tautulli | :material-check: |
| Kill Stream | :material-check: | :material-check: |
| SABnzbd and Uptime Kuma | :material-check: | :material-check: |
| User and global statistics | With Tautulli | :material-minus: |
| Open in the media server | With Tautulli | :material-minus: |

Plex has the richer surface because MediaWatch can layer Tautulli on top. Jellyfin
support is intentionally narrower but uses the same dashboard model and the same runtime
architecture. See [Architecture](reference/architecture.md).

## What it is not

Not a web app, not a multi-user control panel, and not a replacement for Tautulli or
Uptime Kuma. It is an operational bot for people who already live in Discord and want
their media server status there.

## How this project is built

MediaWatch is written with extensive help from AI coding assistants. PlexWatch 1.x started
the same way: it worked better than I expected, but its internals were not built to last,
which is what the 2.0 rewrite addresses.

I have run MediaWatch in production on my own server since early 2026, and the features
and fixes since then come from using it every day. CI runs the full test suite on every
push and pull request.
