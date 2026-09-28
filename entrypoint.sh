#!/bin/sh
set -e

CONFIG_DIR="/app/data"
APP_USER="mediawatch"
APP_UID="${PUID:-1000}"
APP_GID="${PGID:-1000}"

# Ensure config directory exists
mkdir -p "$CONFIG_DIR"

# Copy any missing default files without overwriting existing runtime data
for path in /app/defaults/*; do
    [ -e "$path" ] || continue

    target="$CONFIG_DIR/$(basename "$path")"
    if [ ! -e "$target" ]; then
        echo "Copying missing default $(basename "$path") to $CONFIG_DIR"
        cp -r "$path" "$target"
    fi
done

# The bot itself must not run as root. When the container starts as root (the
# default), take ownership of the mounted volume first - an upgraded 1.x
# install has root-owned files in there - and then drop privileges. The bot
# writes config.yaml, user_mapping.json, dashboard_message_id.json and
# runtime_state.json, and its atomic writes need the directory writable too.
#
# PUID/PGID keep the host-side ownership under the operator's control: set them
# to the account that owns ./data (Unraid: PUID=99, PGID=100) so files stay
# editable over a share. -o allows an id that already exists in the image.
#
# If the container was started as a non-root user already (compose `user:`),
# nothing is dropped and the mount must already be writable for that user.
if [ "$(id -u)" = "0" ]; then
    # PUID=0 would silently keep the bot running as root.
    if [ "$APP_UID" = "0" ] || [ "$APP_GID" = "0" ]; then
        echo "PUID/PGID must not be 0: the bot does not run as root" >&2
        exit 1
    fi
    [ "$(id -g "$APP_USER")" = "$APP_GID" ] || groupmod -o -g "$APP_GID" "$APP_USER"
    [ "$(id -u "$APP_USER")" = "$APP_UID" ] || usermod -o -u "$APP_UID" "$APP_USER"

    chown -R "$APP_USER:$APP_USER" "$CONFIG_DIR" /app/logs
    echo "Starting as $APP_USER ($APP_UID:$APP_GID)"
    exec setpriv --reuid="$APP_USER" --regid="$APP_USER" --init-groups "$@"
fi

# Start the main process
exec "$@"
