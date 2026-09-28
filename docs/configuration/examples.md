# Configuration examples

Complete `data/config.yaml` files, not fragments. Copy one whole, then adjust. Anything a
block does not mention keeps its [default](reference.md).

All of them assume the matching credentials are already in
[`.env`](environment.md). None of these files contain a secret.

!!! warning "Library names must match the server exactly"

    Every key under `sections` is looked up on the media server verbatim, including
    capitalisation. `TV shows` does not match a library called `TV Shows`, and a name
    that matches nothing is skipped without an error.

## Minimal: Plex, show every library

The shortest useful configuration. No `sections` map, so every library the server reports
appears in the dashboard under its own name. The bot's status lists no libraries until you
add [`presence.libraries`](reference.md#libraries).

```yaml
# Plex, everything the server reports, nothing customised.
media_server:
  type: "plex"

dashboard:
  name: "Media Server Dashboard"
  icon_url: ""
  footer_icon_url: ""

plex:
  # No sections listed, so this shows whatever Plex reports, in server order.
  # At most 15 embed fields fit; beyond that the dashboard says how many it dropped.
  show_all: true
  sections: {}
```

## Minimal: Jellyfin, show every library

Identical apart from the two keys that select the platform. `PLEX_*` may stay empty.

```yaml
# Jellyfin, everything the server reports, nothing customised.
media_server:
  type: "jellyfin"

dashboard:
  name: "Media Server Dashboard"
  icon_url: ""
  footer_icon_url: ""

jellyfin:
  # Emoji and episode counts are derived from each library's type when not listed:
  # TV libraries get 📺 and an episode count, movie libraries 🎥 and none.
  show_all: true
  sections: {}
```

## Selected libraries with their own names and emojis

Only what is listed appears, in exactly this order. Everything else on the server is
hidden from the dashboard.

=== "Plex"

    ```yaml
    media_server:
      type: "plex"

    dashboard:
      name: "Home Media"
      icon_url: "https://mediawatch.nichtlegacy.com/logo.png"
      footer_icon_url: "https://mediawatch.nichtlegacy.com/logo.png"

    plex:
      # false = the listed libraries and nothing else. A name that does not exist
      # on the server is skipped silently, so check spelling if one is missing.
      show_all: false
      sections:
        Movies:
          display_name: "Movies"
          emoji: "🎥"
          show_episodes: false
        "TV Shows":
          display_name: "Series"
          emoji: "📺"
          # Adds a second embed field with the episode count, so this library
          # costs two of the 15 available field slots.
          show_episodes: true
        Documentaries:
          display_name: "Docs"
          emoji: "📚"
          show_episodes: false

    presence:
      # Shown in the bot's status while nothing is playing. Names only: display
      # name and emoji come from the sections above. ":episodes" counts episodes.
      libraries: ["Movies", "TV Shows:episodes"]
      offline_text: "🔴 Server Offline!"
      stream_text: "{count} active Stream{s} 🟢"
    ```

=== "Jellyfin"

    ```yaml
    media_server:
      type: "jellyfin"

    dashboard:
      name: "Home Media"
      icon_url: "https://mediawatch.nichtlegacy.com/logo.png"
      footer_icon_url: "https://mediawatch.nichtlegacy.com/logo.png"

    jellyfin:
      show_all: false
      sections:
        Movies:
          display_name: "Movies"
          emoji: "🎥"
          show_episodes: false
        "TV Shows":
          display_name: "Series"
          emoji: "📺"
          show_episodes: true
        Music:
          display_name: "Music"
          emoji: "🎵"
          show_episodes: false

    presence:
      # Shown in the bot's status while nothing is playing. Names only: display
      # name and emoji come from the sections above. ":episodes" counts episodes.
      libraries: ["Movies", "TV Shows:episodes"]
      offline_text: "🔴 Server Offline!"
      stream_text: "{count} active Stream{s} 🟢"
    ```

## Privacy-conscious

For a dashboard in a channel other people can read. All three restrictions default to
`false`, so this is an opt-in.

```yaml
media_server:
  type: "plex"

dashboard:
  name: "Media Server Dashboard"
  icon_url: ""
  footer_icon_url: ""

plex:
  show_all: true
  sections: {}

stream_details:
  # Nobody sees client IPs. Even with this on, only DISCORD_AUTHORIZED_USERS would.
  show_ip_for_authorized_users: false
  # Only DISCORD_AUTHORIZED_USERS may open the "Stream N - User" buttons.
  # Everyone else gets an ephemeral rejection instead of the details.
  restrict_to_authorized: true

global_stats:
  # Separate switch on purpose: this one guards server-wide watch history,
  # including a top-users-by-watch-time leaderboard, not just current playback.
  restrict_to_authorized: true
  button_location: "stream_details"
  page_2:
    time_range: 30

user_stats:
  # One user's whole watch history. Closed separately, so the live stream details
  # above could stay open while this stays locked.
  restrict_to_authorized: true
```

!!! warning "This does not hide the dashboard itself"

    The embed is a normal message: the server state, library totals and who is
    currently watching what stay visible to everyone who can read the channel. Only
    channel permissions change that. See
    [Privacy and visibility](../usage/privacy.md).

## With Tautulli statistics

Plex plus Tautulli, with `TAUTULLI_URL` and `TAUTULLI_API_KEY` set in `.env`. Without
those two the statistics buttons do not exist, and everything here except
`cache.library_update_interval` has no effect.

```yaml
media_server:
  type: "plex"

dashboard:
  name: "Media Server Dashboard"
  icon_url: ""
  footer_icon_url: ""

plex:
  show_all: true
  sections: {}

cache:
  library_update_interval: 900
  # TTL for Tautulli user history and player lookups. Raise it if Tautulli
  # is slow; 0 turns the cache off and every button press hits the API.
  user_stats_ttl: 60

global_stats:
  # "both" puts the Global Stats button on the dashboard as well, where every
  # channel member sees it - pair it with restrict_to_authorized if that matters.
  button_location: "both"
  restrict_to_authorized: false
  page_2:
    # Days covered by peak hours, active users, most active day and the
    # top-users leaderboard. A positive integer, or "all" for all time.
    time_range: 90

user_stats:
  enabled: true
  pages:
    behavior: true
    devices: true
    top_content: true
  # 0 = all time.
  time_range: 0
  # Shows on page 3, 0-10. 0 hides that section entirely.
  top_tv_count: 10
```

## With SABnzbd

Needs `SABNZBD_URL` and `SABNZBD_API_KEY` in `.env`; without both, the download block
never appears no matter what is configured here.

```yaml
media_server:
  type: "plex"

dashboard:
  name: "Media Server Dashboard"
  icon_url: ""
  footer_icon_url: ""

plex:
  show_all: true
  sections: {}

sabnzbd:
  # false hides the block while the queue is empty, instead of showing a
  # permanent "no active downloads" row on a mostly idle server.
  show_when_empty: false
  show_status_icons: true
  # Which SABnzbd value is reported: diskspace1 is the download directory,
  # diskspace2 the completed directory. A key your SABnzbd does not return
  # is logged as a warning at startup, and the dashboard shows "Unknown" for it.
  diskspace_free_key: "diskspace1"
  diskspace_total_key: "diskspacetotal1"
  # Download names are cut where the earliest of these appears, to keep release
  # tags out of the embed. A name that starts with a keyword is left whole.
  # Writing this list replaces the built-in one completely.
  keywords:
    - "German"
    - "GERMAN"
    - "DL"
    - "1080p"
    - "2160p"
    - "4K"
    - "UHD"
    - "HDR"
    - "x264"
    - "x265"
    - "HEVC"
    - "WEB"
    - "BluRay"
    - "REPACK"
    - "Remux"
```

## Tolerating a maintenance window

Not a full file: drop this block into any of the above. Worth knowing about if your
server reboots nightly.

```yaml
server:
  # Seconds an unreachable server is tolerated before the dashboard turns red
  # and the bot's status flips to offline_text. 300 covers a normal restart;
  # 0 reports every hiccup immediately. Rejected credentials are reported at
  # once regardless, as an auth failure rather than an outage.
  offline_threshold: 1800
```
