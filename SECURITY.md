# Security Policy

## Reporting a vulnerability

**Do not open a public issue for a security problem.**

Use GitHub's private vulnerability reporting:
[Security → Report a vulnerability](https://github.com/nichtlegacy/MediaWatch/security/advisories/new).
That channel is private between you and the maintainer.

If that link is unavailable, open a normal issue containing nothing but
"security report, need a private channel" (no details) and wait for a reply.

Please include:

- what an attacker can do, not just what looks wrong
- the affected file or command, and the version or commit
- Plex or Jellyfin, and whether the setup is Docker, Unraid or a local run
- reproduction steps

MediaWatch is maintained by a single person. Expect a first reply within a few
days, not within hours. You will be credited in the release notes unless you
ask not to be.

## Supported versions

| Version | Supported |
|---------|-----------|
| 2.x (`ghcr.io/nichtlegacy/mediawatch`) | yes |
| 1.x (`ghcr.io/nichtlegacy/plexwatch`)  | no, see [the upgrade guide](docs/operations/upgrading-from-1x.md) |

Fixes go into the next 2.x release. There are no backports to 1.x.

## What MediaWatch is

A self-hosted Discord bot. You run it, you own the host, you own the Discord
server, and you hold the credentials. There is no MediaWatch service, no
hosted component and no telemetry. Nothing is sent anywhere except to your
Discord server, your media server and the optional integrations you configure
(Tautulli, SABnzbd, Uptime Kuma).

That means the interesting questions are about the boundaries below, not about
"can a stranger on the internet reach it": nothing here listens on a port.

## Trust boundaries

Be honest with yourself about who is in your Discord server before you read
this as a list of guarantees.

### Everyone who can read the dashboard channel

The dashboard is a normal message in a normal channel. Anyone who can read that
channel sees who is currently watching what.

By default they can also press the buttons under it:

- **Stream details**: device, player, quality, transcode info for a running
  stream. Gate it with `stream_details.restrict_to_authorized: true`.
- **User stats** (Plex with Tautulli, inside the stream details): the whole
  watch history of the user behind a stream. Gating stream details closes it
  too; gate it on its own with `user_stats.restrict_to_authorized: true`.
- **Global stats**: server-wide statistics including the top-users
  leaderboard, i.e. historical viewing habits, not just what is running now.
  Gate it with `global_stats.restrict_to_authorized: true`.

**All three options default to `false`**, which is the behaviour every existing
install already had. If your channel is not restricted to people who are
allowed to see this, set all three to `true`. There is no way to make a Discord
message visible to fewer people than the channel it sits in; channel
permissions are the actual control.

Client IP addresses are a separate, stricter case: they are only shown when
`stream_details.show_ip_for_authorized_users` is `true` **and** the viewer is
in `DISCORD_AUTHORIZED_USERS`. The default is `false`.

### Authorized users

`DISCORD_AUTHORIZED_USERS` is a comma-separated list of Discord user IDs. It is
the only authorization mechanism in the bot: there are no roles, no
per-command permissions and no audit log.

Everyone on that list can:

- terminate other people's streams (`Kill Stream`)
- read and edit the username mapping (`/mapping`)
- load, unload and reload cogs, and reload the config at runtime
- see client IP addresses, if the option above is enabled

Treat the list like a root account list. Keep it short.

### Secrets

All credentials come from environment variables, never from `data/config.yaml`:
`DISCORD_TOKEN`, `PLEX_TOKEN`, `JELLYFIN_API_KEY`, `TAUTULLI_API_KEY`,
`SABNZBD_API_KEY`, `UPTIME_PASSWORD`.

`.gitignore` ignores every `.env*` file except `.env.example`, and the tracked
`docker-compose.yml` loads them via `env_file:` instead of inlining them. Do
not put secrets into `docker-compose.yml` or `config.yaml`.

### Logs

The bot logs at DEBUG level. Logs contain usernames, media titles, player
names and error responses from your media server. They are not secret-free by
design, so check them before pasting them into an issue. See the note in the bug
report template.

## In scope

- Bypassing the `DISCORD_AUTHORIZED_USERS` check on any privileged action
- Credentials (Discord token, Plex token, Jellyfin API key, Tautulli or SABnzbd
  key) leaking into logs, Discord messages, embeds or the built Docker image
- Data reachable by a channel member that neither the default config nor the
  documented options are supposed to expose
- Input from the media server, Tautulli, SABnzbd or Discord that crashes the
  bot, wedges the dashboard, or is rendered in a way that misleads a reader
- Anything in the published container image that a container should not carry
  (real `data/` contents, credentials, root-only assumptions)
- Unsafe file handling: config, user mapping and runtime state writes

## Out of scope

- Your Discord channel permissions. If untrusted people can read your dashboard
  channel, that is a configuration decision, not a bug. See the options above.
- The three `restrict_to_authorized` options defaulting to `false`. That is
  deliberate backwards compatibility and it is documented here and in
  `data/config.yaml.example`.
- Vulnerabilities in Plex, Jellyfin, Tautulli, SABnzbd, Uptime Kuma or Discord
  themselves. Report those to their projects.
- Vulnerabilities in dependencies with no MediaWatch-specific impact. Those are
  handled by dependency updates, not advisories.
- Exposing your media server or the bot host to the internet.
- Anything requiring an attacker who already has your Discord bot token, shell
  access to the host, or write access to `data/`.
