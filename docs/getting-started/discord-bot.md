# Discord Bot

This page produces four values: the bot token and the three Discord IDs MediaWatch needs
to start. Keep a scratch file open: you will paste all four into `.env` in
[First run](first-run.md).

## 1. Create the application and the bot

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and
   click **New Application**. The name and avatar you pick here are what members see in
   the channel.
2. Go to **Bot** in the sidebar.
3. Click **Reset Token**, confirm, and copy the token. It is shown exactly once. If you
   lose it, reset it again and update `.env`. This value becomes `DISCORD_TOKEN`.
4. Optional but recommended: turn **Public Bot** off, so nobody else can invite your bot.

!!! warning "Treat the token like a password"
    Anyone who has it controls the bot account. Keep it out of anything you share: a
    public repository, a pasted compose file, a screenshot attached to a bug report. If you leaked
    it, reset it in the portal. The old token stops working immediately.

## 2. Enable the Message Content intent

Still under **Bot**, scroll to **Privileged Gateway Intents** and enable exactly one:

- **Message Content Intent** (required)

Leave **Server Members Intent** and **Presence Intent** **off**.

MediaWatch starts from `discord.Intents.default()` and adds only `message_content`, which
the `!sync` prefix command needs. Nothing in the bot reads member lists or presences.

!!! note "Coming from PlexWatch 1.x? This is less, not more"
    If you had all three intents enabled for an older build, you can switch Server Members
    and Presence **off** after upgrading. The bot does not use them, so there is no reason
    to keep them on.

## 3. Invite the bot

Under **OAuth2 → URL Generator**, select the scopes:

- `bot`
- `applications.commands`

Then select these bot permissions:

| Permission | Why MediaWatch needs it |
| --- | --- |
| View Channel | See the dashboard channel at all |
| Send Messages | Post the dashboard message and reply to `!sync` |
| Embed Links | The dashboard is an embed |
| Attach Files | Stream thumbnails and the statistics charts are uploads |
| Read Message History | Fetch and edit the existing dashboard message after a restart |

That is the complete set. **Do not grant Administrator.** MediaWatch never deletes
messages, never manages members and never touches channels, so nothing beyond those five
permissions is ever exercised.

The five add up to the permission integer `117760`, so you can also build the invite URL
by hand:

```
https://discord.com/api/oauth2/authorize?client_id=YOUR_APPLICATION_ID&permissions=117760&scope=bot%20applications.commands
```

Replace `YOUR_APPLICATION_ID` with the **Application ID** from the portal's **General
Information** page. Open the URL, pick your server, authorize.

!!! warning "Check the channel, not just the server"
    A channel-level permission override can still block a bot that holds the permission
    server-wide. After inviting, open the dashboard channel's **Edit Channel →
    Permissions** and confirm the bot's role is not denied **View Channel**,
    **Send Messages**, **Embed Links**, **Attach Files** or **Read Message History** there.

## 4. Collect the three Discord IDs

Enable Developer Mode once: **Discord → User Settings → Advanced → Developer Mode**. The
"Copy ID" entries below only appear when it is on.

| Variable | How to get it |
| --- | --- |
| `DISCORD_GUILD_ID` | Right-click your server name in the server list → **Copy Server ID** |
| `CHANNEL_ID` | Right-click the channel the dashboard should live in → **Copy Channel ID** |
| `DISCORD_AUTHORIZED_USERS` | Right-click a user → **Copy User ID**. Several IDs are comma-separated |

All of them are plain numbers, 17–20 digits:

```bash
DISCORD_GUILD_ID=123456789012345678
CHANNEL_ID=234567890123456789
DISCORD_AUTHORIZED_USERS=345678901234567890,456789012345678901
```

Pasting a mention (`<#234567890123456789>`) or a channel link instead of the bare ID is
the single most common setup mistake. MediaWatch refuses to start and says so:

```text
CHANNEL_ID must be a numeric Discord ID, got '<#234567890123456789>'. Enable Developer Mode in Discord and copy the ID via right-click -> Copy ID.
```

### Why each one is mandatory

`DISCORD_GUILD_ID` publishes the slash commands. MediaWatch registers its command tree
guild-scoped, so without the guild there is nowhere to publish to and you get no slash
commands at all. This is required since 2.0.

`CHANNEL_ID` is where the dashboard message is posted and then edited in place.

`DISCORD_AUTHORIZED_USERS` is the **only** authorization mechanism in the bot. Everyone on
that list can terminate streams, edit the user mapping and load or reload cogs at runtime.
Keep the list short. See
[SECURITY.md](https://github.com/nichtlegacy/MediaWatch/blob/main/SECURITY.md) and
[Privacy and Visibility](../usage/privacy.md).

A list that parses to zero usable IDs is rejected too, because every admin command would
be dead:

```text
DISCORD_AUTHORIZED_USERS is set to ',,', which contains no user ID - nobody could use the admin commands. Use a comma-separated list of numeric Discord user IDs, e.g. 123456789012345678,987654321098765432.
```

---

Next: [get your media server credentials](media-server.md).
