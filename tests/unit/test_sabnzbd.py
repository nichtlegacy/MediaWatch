import logging
from types import SimpleNamespace

import pytest

from cogs.sabnzbd import SABnzbd


def make_cog(url="http://host:8080/sabnzbd", config=None):
    """Build a SABnzbd instance without __init__ side effects (env, config file)."""
    cog = SABnzbd.__new__(SABnzbd)
    cog.bot = SimpleNamespace()
    cog.logger = logging.getLogger("test.sabnzbd")
    cog.SABNZBD_URL = url
    cog.SABNZBD_API_KEY = "secret"
    cog.config = config if config is not None else {}
    cog._session = None
    return cog


class FakeResponse:
    ok = True
    status = 200

    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.requested_urls = []

    def get(self, url, params=None):
        self.requested_urls.append(url)
        return FakeResponse(self.payload)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://host:8080", "http://host:8080/api"),
        ("http://host:8080/", "http://host:8080/api"),
        ("http://host:8080/sabnzbd", "http://host:8080/sabnzbd/api"),
        ("http://host:8080/sabnzbd/", "http://host:8080/sabnzbd/api"),
    ],
)
def test_api_url_keeps_base_path(url, expected):
    assert make_cog(url).api_url == expected


@pytest.mark.asyncio
async def test_get_sabnzbd_info_requests_the_same_url_as_validation(monkeypatch):
    cog = make_cog()
    session = FakeSession({"queue": {"slots": [], "diskspace1": "10", "diskspacetotal1": "100"}})

    async def fake_get_session():
        return session

    monkeypatch.setattr(cog, "_get_session", fake_get_session)
    result = await cog.get_sabnzbd_info()

    assert session.requested_urls == ["http://host:8080/sabnzbd/api"]
    assert result["configured"] is True


def make_download(name, **overrides):
    download = {
        "name": name,
        "progress": 50.0,
        "timeleft": "0:10:00",
        "speed": "1.00 MB/s",
        "size": "500.00 MB",
        "status": "Downloading",
    }
    download.update(overrides)
    return download


def test_format_download_info_keeps_name_when_keyword_is_first():
    cog = make_cog(config={"keywords": ["German", "1080p", "x264"], "show_status_icons": False})

    output = cog.format_download_info(make_download("German.Movie.2024.1080p.x264-GRP"), 0)

    assert "German.Movie.2024.1080p.x264-GRP" in output


def test_format_download_info_truncates_at_first_keyword():
    cog = make_cog(config={"keywords": ["German", "1080p", "x264"], "show_status_icons": False})

    output = cog.format_download_info(make_download("Some.Movie.2024.German.1080p"), 0)

    assert "Some.Movie.2024." in output
    assert "German" not in output


def test_format_download_info_keeps_name_without_keyword_match():
    cog = make_cog(config={"keywords": ["German"], "show_status_icons": False})

    output = cog.format_download_info(make_download("Some.Movie.2024"), 0)

    assert "Some.Movie.2024" in output


def shared_sabnzbd_defaults(tmp_path):
    from cogs.media_core.shared.config import load_config

    return load_config(str(tmp_path / "missing.yaml"))["sabnzbd"]


def test_load_config_uses_shared_defaults_and_user_overrides(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "sabnzbd:\n  show_when_empty: true\n  keywords:\n    - Custom\n", encoding="utf-8"
    )
    cog = make_cog()
    cog.CONFIG_FILE = str(tmp_path / "config.yaml")

    config = cog._load_config()

    assert config["keywords"] == ["Custom"]
    assert config["show_when_empty"] is True
    # untouched keys still come from the shared defaults
    assert config["diskspace_free_key"] == shared_sabnzbd_defaults(tmp_path)["diskspace_free_key"]


def test_load_config_defaults_match_shared_config(tmp_path):
    """Pin the values, not `shared == shared`.

    Comparing the cog against load_config() compared the implementation with
    itself: changing a default in shared/config.py changed both sides and the
    test stayed green. The point of this test is to notice when the cog stops
    reading the central defaults - or when someone reintroduces a local copy.
    """
    cog = make_cog()
    cog.CONFIG_FILE = str(tmp_path / "config.yaml")

    config = cog._load_config()

    assert config["diskspace_free_key"] == "diskspace1"
    assert config["diskspace_total_key"] == "diskspacetotal1"
    assert config["show_when_empty"] is False
    assert config["show_status_icons"] is True
    assert {"German", "GERMAN", "English", "ENGLISH", "1080p", "x265"} <= set(config["keywords"])
    # Still identical to the central defaults - that is the drift guard.
    assert config == shared_sabnzbd_defaults(tmp_path)


@pytest.mark.asyncio
async def test_get_sabnzbd_info_survives_broken_payload(monkeypatch):
    """A malformed SABnzbd payload must not bubble up into update_dashboard."""
    cog = make_cog()
    session = FakeSession(
        {
            "queue": {
                "diskspace1": None,
                "diskspacetotal1": None,
                "kbpersec": None,
                "slots": [{"filename": "Broken", "percentage": "", "mbleft": None}],
            }
        }
    )

    async def fake_get_session():
        return session

    monkeypatch.setattr(cog, "_get_session", fake_get_session)
    result = await cog.get_sabnzbd_info()

    # Empty percentage and null size fields are tolerated, the section still renders
    assert result["configured"] is True
    assert result["downloads"][0]["progress"] == 0.0
    assert result["free_space"] == "Unknown"


@pytest.mark.asyncio
async def test_get_sabnzbd_info_returns_empty_dict_on_unexpected_error(monkeypatch):
    """Any other parse error degrades to the empty result instead of raising."""
    cog = make_cog()

    class ExplodingSession(FakeSession):
        def get(self, url, params=None):
            return FakeResponse({"queue": {"slots": [{"percentage": "not-a-number"}]}})

    async def fake_get_session():
        return ExplodingSession(None)

    monkeypatch.setattr(cog, "_get_session", fake_get_session)
    result = await cog.get_sabnzbd_info()

    assert result == {
        "downloads": [],
        "free_space": "Unknown",
        "total_space": "Unknown",
        "configured": True,
    }


def test_format_download_info_sanitizes_backticks_and_newlines():
    """A backtick or newline in the NZB name would close the code fence."""
    cog = make_cog(config={"keywords": ["1080p"], "show_status_icons": False})

    output = cog.format_download_info(
        make_download("Some.Movie```\n@everyone [click](http://evil)\n.1080p"), 0
    )

    name_line = output.split("\n")[0]
    # the name stays inside the fence: no stray backticks, no extra line break
    assert name_line.startswith("**```Some.Movie")
    assert "`" not in name_line.removeprefix("**```")
    assert output.count("```") == 2
    # keyword truncation still applies
    assert "1080p" not in output


def test_example_config_keywords_match_the_built_in_defaults():
    """The example is meant to be copied, and the list replaces the default.

    Two keywords were missing from it, so anyone starting from the example
    silently lost them. A drift guard is cheaper than noticing that again.
    """
    import pathlib

    import yaml

    example = yaml.safe_load(pathlib.Path("data/config.yaml.example").read_text(encoding="utf-8"))
    from cogs.media_core.shared.config import load_config

    defaults = load_config("/nonexistent-config.yaml")["sabnzbd"]["keywords"]

    assert set(example["sabnzbd"]["keywords"]) == set(defaults)
