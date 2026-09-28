# Getting Started

Three pages take a fresh install from nothing to a live dashboard. Follow them in order:
each one ends with the values the next one needs. Budget about ten minutes.

## Before you start

| You need | Details |
| --- | --- |
| A Discord server you administrate | You have to invite a bot and read three IDs from it. Being a plain member is not enough. |
| A reachable Plex **or** Jellyfin server | Reachable from wherever MediaWatch runs, by IP or hostname, not through plex.tv. |
| Docker, or Python 3.12 | Docker Compose is the recommended way. A local run needs Python 3.12; the image is built on `python:3.12-slim`. |

MediaWatch monitors **one** platform per deployment. Decide now whether this install
watches Plex or Jellyfin: the credentials you collect and the value of
`media_server.type` follow from that. Running both means running two containers with two
`data/` directories and two Discord channels.

!!! note "Optional extras"
    Tautulli (Plex only) adds stream details and statistics, SABnzbd a download queue
    block, and Uptime Kuma uptime history on the offline dashboard. All three
    are optional and none of them is needed to get a first dashboard on screen. Skip them
    for now. You can add them later without a reinstall.

## The three steps

1. **[Discord bot](discord-bot.md)**: create the application, copy the token, enable the
   one intent MediaWatch needs, invite the bot with five permissions, and collect the
   three Discord IDs.
2. **[Media server](media-server.md)**: get your Plex token or your Jellyfin API key,
   and the URL the bot will reach the server on.
3. **[First run](first-run.md)**: write `.env` and `data/config.yaml`, set
   `media_server.type`, start the bot, and confirm it worked from the log.

After that, pick how you want to run it permanently:
[Docker](../deployment/docker.md) or [locally](../deployment/local.md).

Upgrading an existing PlexWatch 1.x install instead of starting fresh? Read
[Upgrading from 1.x](../operations/upgrading-from-1x.md) first: some of the steps below
are already done for you, and `DISCORD_GUILD_ID` is a new requirement.
