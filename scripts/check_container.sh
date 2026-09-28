#!/usr/bin/env bash
# Exercise the real entrypoint without Discord credentials or host data mounts.
set -euo pipefail

image="${1:?usage: check_container.sh IMAGE}"
check='
import json
import os
from pathlib import Path

import cogs.media_core.plex
import cogs.media_core.jellyfin
import cogs.sabnzbd
import cogs.uptime
import cogs.user_mapping
from cogs.media_core.shared.config_utils import write_json_atomic

assert os.getuid() == int(os.environ["EXPECTED_UID"])
assert os.getgid() == int(os.environ["EXPECTED_GID"])
assert not os.access("/app/main.py", os.W_OK)
assert Path("/app/data/config.yaml.example").is_file()
write_json_atomic("/app/data/smoke.json", {"ok": True})
assert json.loads(Path("/app/data/smoke.json").read_text()) == {"ok": True}
Path("/app/logs/smoke.log").write_text("ok")
'

docker run --rm --network none \
  -e EXPECTED_UID=1000 -e EXPECTED_GID=1000 "$image" python -c "$check"
docker run --rm --network none \
  -e PUID=1234 -e PGID=1234 -e EXPECTED_UID=1234 -e EXPECTED_GID=1234 \
  "$image" python -c "$check"
docker run --rm --network none --user 1000:1000 \
  -e EXPECTED_UID=1000 -e EXPECTED_GID=1000 "$image" python -c "$check"
