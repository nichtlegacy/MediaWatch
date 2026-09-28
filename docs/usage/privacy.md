# Privacy and Visibility

The dashboard is a normal Discord message in a normal channel. Anyone who can read that
channel sees the embed, and by default anyone who can read it can also press the buttons
under it.

Read this before you put the dashboard in a channel with people you would not show your
watch history to. Nothing here is a bug. It is the default, and it is the same default
every 1.x install already had.

## What everyone in the channel sees

Without pressing anything: the server state, the library totals, and the current streams,
which means who is watching what, right now, by display name. If you set up
[user mappings](commands.md#mapping), that display name is the one you chose, not the
media server account name.

## What everyone in the channel can open, by default

| Button | Reveals |
| --- | --- |
| `Stream N - User` | Device, player, playback quality, transcode decision, subtitle and audio track of a running stream. Needs Tautulli on Plex; Jellyfin serves it directly. |
| `User Stats` (Plex with Tautulli, inside the stream details) | The watch history of the user behind that stream: watch time, streaks, top content, devices. |
| `Global Stats` (Plex with Tautulli) | Server-wide statistics including a **Top 10 Users by Watch Time** leaderboard and peak-hour charts: the historical viewing behaviour of every user on the server, not just what is playing now. |

All three open as ephemeral replies, so the *result* is visible only to the person who clicked.
That is not a restriction on *who may click*. By default, that is everyone.

## Closing it down

Three options in `data/config.yaml`, all `false` unless you change them:

```yaml
# Who may open the per-stream detail view.
# Default: false - every member of the dashboard channel may open it.
# With true, a non-authorized click is answered with a refusal and nothing else.
stream_details:
  restrict_to_authorized: true

# Who may open one user's watch history (Plex with Tautulli). The button sits
# inside the stream details, so restricting those closes it too; this option
# locks it on its own while the live stream details stay open.
# Default: false.
user_stats:
  restrict_to_authorized: true

# Who may open the server-wide statistics, including the top-users leaderboard.
# Default: false. Deliberately separate from the other two: each view reveals
# something different, so each has its own switch.
global_stats:
  restrict_to_authorized: true
```

Apply with `/reload_config`; a restart is not needed.

"Authorized" means a Discord user ID listed in `DISCORD_AUTHORIZED_USERS`. Everyone else
gets an ephemeral refusal:

```
❌ Stream details are restricted to authorized users on this server.
❌ User statistics are restricted to authorized users on this server.
❌ Global statistics are restricted to authorized users on this server.
```

!!! warning "None of the options hides the dashboard itself"

    There is no way to make a Discord message visible to fewer people than the channel it
    sits in. **Channel permissions are the actual control.** If the audience is wrong,
    move the dashboard to a restricted channel. The three options above only close the
    buttons.

`global_stats.button_location` moves the statistics button (`stream_details` by default,
`dashboard`, or `both`) but cannot remove it. The button only disappears without
`TAUTULLI_URL` / `TAUTULLI_API_KEY`, so to keep Tautulli and still hide the statistics,
use `restrict_to_authorized`.

## What is already restricted

- **Client IP addresses** need two things at once:
  `stream_details.show_ip_for_authorized_users: true` **and** the viewer being in
  `DISCORD_AUTHORIZED_USERS`. The default is `false`, so IPs are shown to nobody until
  you opt in, and opting in never exposes them to the channel at large.
- **The `Kill Stream` button** is only attached for authorized users, and the action
  re-checks authorization when it is invoked, so a stale button cannot be replayed by
  someone else.
- **Every command** (`/mapping`, `/reload_config`, `/load`, `/unload`, `/reload`,
  `/cogs` and `!sync`) is restricted to `DISCORD_AUTHORIZED_USERS`. So is the username
  autocomplete on `/mapping`, which would otherwise hand out the whole mapping through a
  dropdown.

`DISCORD_AUTHORIZED_USERS` is the only authorization mechanism in the bot: no roles, no
per-command permissions, no audit log. Treat it like a root account list and keep it
short. It is read once at startup, so changes need a restart.

## What leaves your infrastructure

Nothing. There is no MediaWatch service, no hosted component and no telemetry. Data goes
to your Discord server, your media server, and the optional integrations you configure.

One thing worth knowing: the bot logs at DEBUG level, and those logs contain usernames,
media titles and player names. Check them before pasting them into an issue.

[SECURITY.md](https://github.com/nichtlegacy/MediaWatch/blob/main/SECURITY.md) covers the
same trust boundaries from the security side, including what is in and out of scope for a
vulnerability report.
