# Media Server Credentials

MediaWatch talks to exactly one media server. Follow the section for the platform this
deployment monitors and skip the other one. You will leave its variables empty in `.env`.

## Which URL to use

Both platforms need a base URL **including the port**, and it has to be reachable from
where MediaWatch runs, not from your desktop browser:

| MediaWatch runs | Use |
| --- | --- |
| On the same host as the media server | The host's LAN address, `http://192.168.1.10:32400`. Inside a container, `localhost` is the container, not the host |
| In the same Docker network as the media server | The service name: `http://plex:32400`, `http://jellyfin:8096` |
| On a different machine in the LAN | The server's LAN address: `http://192.168.1.10:32400` |

Use the direct address, **not** `https://app.plex.tv` and not a Cloudflare-tunnelled
public hostname. The bot polls the server every minute, and a round trip through the
internet buys nothing. No trailing slash.

=== "Plex"

    You need `PLEX_URL` and `PLEX_TOKEN`.

    **`PLEX_URL`**: the LAN address of the Plex Media Server, port `32400` unless you
    changed it:

    ```bash
    PLEX_URL=http://192.168.1.10:32400
    ```

    **`PLEX_TOKEN`**: your `X-Plex-Token`. The fastest way to read it:

    1. Open Plex Web and pick any item in a library.
    2. Click **⋯ → Get Info → View XML**.
    3. A new browser tab opens with an XML document. Copy the value of `X-Plex-Token=` out
       of that tab's address bar.

    ```bash
    PLEX_TOKEN=xxxxxxxxxxxxxxxxxxxx
    ```

    Plex documents the full procedure, including alternatives for headless setups, in
    [Finding an authentication token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).

    !!! note "The token is tied to your Plex account"
        It grants the same access to the server that you have. Read it from the account
        that owns the server: only the owner sees every user's sessions and can stop them.

    ### Optional: Tautulli

    Tautulli is what turns "who is watching" into history and statistics. With
    `TAUTULLI_URL` and `TAUTULLI_API_KEY` set, MediaWatch adds stream details, per-user
    statistics and global statistics with charts. Without it, the dashboard and the
    kill-stream action still work; the buttons that need history tell you so:

    ```
    Detailed stream information needs Tautulli. Set TAUTULLI_URL and TAUTULLI_API_KEY to enable it.
    ```

    The API key is in Tautulli under **Settings → Web Interface → API**:

    ```bash
    TAUTULLI_URL=http://192.168.1.10:8181
    TAUTULLI_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    ```

    Both or neither. Setting only one leaves the integration disabled and logs a warning
    at startup:

    ```text
    Tautulli is only partially configured (missing: TAUTULLI_API_KEY). The integration stays disabled until all of TAUTULLI_URL, TAUTULLI_API_KEY are set.
    ```

=== "Jellyfin"

    You need `JELLYFIN_URL` and `JELLYFIN_API_KEY`.

    **`JELLYFIN_URL`**: the server address, port `8096` for plain HTTP unless you changed
    it:

    ```bash
    JELLYFIN_URL=http://192.168.1.10:8096
    ```

    **`JELLYFIN_API_KEY`**: created in the Jellyfin web UI:

    1. **Dashboard → Advanced → API Keys**.
    2. Click **+**, name it `MediaWatch`, confirm.
    3. Copy the generated key. Unlike the Discord token you can read it again later on the
       same page.

    ```bash
    JELLYFIN_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    ```

    The key is sent as the `X-Emby-Token` header and has full API access and is not
    scoped to read-only. Delete it on that same page when you decommission the bot.

    !!! warning "Tautulli is Plex-only"
        There is no Jellyfin equivalent wired up, so user statistics and global statistics
        are not available on Jellyfin. Setting `TAUTULLI_*` while
        `media_server.type: "jellyfin"` is ignored, and MediaWatch says so at startup:

        ```text
        TAUTULLI_* is set but media_server.type is 'jellyfin'. Tautulli is a Plex-only integration and will be ignored.
        ```

## What happens if the credentials are wrong

Missing values are caught before the bot connects to Discord, with a message naming the
variable. A value that is present but wrong is not. An unreachable URL turns the dashboard
to "Server is currently Offline!" once `server.offline_threshold` (default 300 seconds) has
passed. A token or API key the server rejects shows "Server rejected the credentials!"
right away. See [Troubleshooting](../operations/troubleshooting.md) for both.

---

Next: [write the configuration and start the bot](first-run.md).
