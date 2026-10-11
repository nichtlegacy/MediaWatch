FROM python:3.12-slim

# /app stays root-owned so the bot cannot modify its own code, so HOME and the
# matplotlib font cache (written on first import) point at a writable path.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app

COPY requirements.txt ./

RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . .

# Only the shipped example is a default. Copying all of /app/data would
# duplicate a real config into the image on local builds (see .dockerignore).
# /app/logs is created here because main.py creates it relative to the CWD.
# COPY keeps the checkout's file modes, and a runner that checks out with
# umask 000 (Forgejo's does) would leave the code writable for the bot. Strip
# group and other write bits so /app is read-only for it however it was built.
RUN chmod -R go-w /app \
    && mkdir -p /app/defaults /app/logs \
    && cp /app/data/config.yaml.example /app/defaults/ \
    && chmod +x entrypoint.sh \
    && groupadd --gid 1000 mediawatch \
    && useradd --uid 1000 --gid 1000 --no-create-home --home-dir /tmp \
       --shell /usr/sbin/nologin mediawatch \
    && chown -R mediawatch:mediawatch /app/data /app/logs

# No HEALTHCHECK: the bot has no HTTP endpoint and emits no heartbeat, so a
# check here could only assert "the process exists" - which Docker already
# covers, since the bot is PID 1 and its exit stops the container. A check that
# cannot fail for a real reason is worse than none. See .planning/NOTES.md.

# Starts as root to adopt the mounted volume, then drops to mediawatch
# (PUID/PGID, default 1000:1000). Starting the container with a non-root
# `user:` skips the root step entirely.
ENTRYPOINT ["/bin/sh", "/app/entrypoint.sh"]

CMD ["python", "main.py"]
