import importlib
from pathlib import Path
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def import_main_module(monkeypatch):
    """Import `main` with deterministic env vars for tests."""

    def _import():
        # Docker mode keeps the import side effects out of the developer's
        # machine: no `load_dotenv()` leaking a real PLEX_TOKEN/CHANNEL_ID into
        # os.environ for the rest of the session, and a StreamHandler instead of
        # a TimedRotatingFileHandler writing into the real logs/ directory.
        monkeypatch.setenv("RUNNING_IN_DOCKER", "true")
        monkeypatch.setenv("DISCORD_TOKEN", "test-token")
        monkeypatch.setenv("DISCORD_AUTHORIZED_USERS", "123,456")

        sys.modules.pop("main", None)
        importlib.invalidate_caches()
        return importlib.import_module("main")

    return _import


@pytest.fixture(autouse=True)
def isolate_runtime_state(monkeypatch, tmp_path):
    """Keep every test out of the repository's own `data/runtime_state.json`.

    Mocking the individual persistence calls per test does not hold: the suite
    already mocked `persist_online_since`, then `persist_last_seen` was added to
    `close()` and the tests started writing the real file again. Redirecting the
    path once covers whatever gets persisted next.

    This is not only about a dirty working tree. On a machine that also runs the
    bot, a test run would overwrite the live uptime baseline and the
    `global_commands_cleared` flag.
    """
    monkeypatch.setattr(
        "cogs.media_core.shared.runtime_state.get_runtime_state_path",
        lambda: tmp_path / "runtime_state.json",
    )
    # The refresh throttle is module state; one test's write must not suppress
    # the next test's.
    monkeypatch.setattr("cogs.media_core.shared.runtime_state._last_seen_refreshed", {})
