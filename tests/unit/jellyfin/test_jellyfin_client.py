import pytest

from cogs.media_core.jellyfin.jellyfin_client import JellyfinClient


class _FakeResponse:
    def __init__(self, status=204):
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def make_client(status=204):
    client = JellyfinClient("http://jellyfin/", "api-key")
    calls = []

    class _FakeSession:
        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return _FakeResponse(status)

    async def _get_session():
        return _FakeSession()

    client._get_session = _get_session
    return client, calls


@pytest.mark.asyncio
async def test_stop_session_posts_without_body():
    client, calls = make_client()

    assert await client.stop_session("session-1") is True
    assert calls == [("http://jellyfin/Sessions/session-1/Playing/Stop", {})]


@pytest.mark.asyncio
async def test_send_message_posts_display_message_command():
    client, calls = make_client()

    assert await client.send_message("session-1", "Please stop") is True

    url, kwargs = calls[0]
    assert url == "http://jellyfin/Sessions/session-1/Message"
    assert kwargs["json"] == {
        "Text": "Please stop",
        "Header": "MediaWatch",
        "TimeoutMs": 10000,
    }


@pytest.mark.asyncio
async def test_send_message_reports_failure():
    client, _ = make_client(status=404)

    assert await client.send_message("session-1", "Please stop") is False


class _FakeGetResponse:
    def __init__(self, status):
        self.status = status

    async def json(self):
        return {"ServerName": "Home"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def make_connecting_client(status):
    client = JellyfinClient("http://jellyfin/", "api-key")

    class _FakeSession:
        def get(self, url, **kwargs):
            return _FakeGetResponse(status)

    async def _get_session():
        return _FakeSession()

    client._get_session = _get_session
    return client


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.asyncio
async def test_connect_flags_a_rejected_api_key(status):
    # Without this the dashboard reports the server as offline and the user
    # goes looking for the fault on Jellyfin instead of in JELLYFIN_API_KEY.
    client = make_connecting_client(status)

    assert await client.connect() is False
    assert client.auth_failed is True


@pytest.mark.asyncio
async def test_connect_does_not_blame_the_api_key_for_a_server_error():
    client = make_connecting_client(500)

    assert await client.connect() is False
    assert client.auth_failed is False


@pytest.mark.asyncio
async def test_connect_does_not_blame_the_api_key_when_the_server_is_unreachable():
    client = JellyfinClient("http://jellyfin/", "api-key")
    client._auth_failed = True

    async def _get_session():
        raise ConnectionError("Connection refused")

    client._get_session = _get_session

    assert await client.connect() is False
    assert client.auth_failed is False


@pytest.mark.asyncio
async def test_connect_clears_a_previous_auth_failure_on_success():
    client = make_connecting_client(401)
    await client.connect()
    assert client.auth_failed is True

    client._get_session = make_connecting_client(200)._get_session

    assert await client.connect() is True
    assert client.auth_failed is False
    assert client.is_connected() is True


class _FakeCountResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def make_library_client(status, payload):
    client = JellyfinClient("http://jellyfin/", "api-key")

    class _FakeSession:
        def get(self, url, **kwargs):
            return _FakeCountResponse(status, payload)

    async def _get_session():
        return _FakeSession()

    client._get_session = _get_session
    return client


@pytest.mark.parametrize("method", ["get_item_counts", "get_series_count", "get_episodes_count"])
async def test_counts_distinguish_a_failure_from_a_real_zero(method):
    ok = make_library_client(200, {"TotalRecordCount": 0})
    assert await getattr(ok, method)("lib") == 0

    failed = make_library_client(500, {})
    assert await getattr(failed, method)("lib") is None


async def test_library_sections_report_failure_as_none_not_empty():
    assert await make_library_client(200, []).get_library_sections() == []
    assert await make_library_client(503, []).get_library_sections() is None

    client = JellyfinClient("http://jellyfin/", "api-key")

    async def _get_session():
        raise ConnectionError("Connection refused")

    client._get_session = _get_session
    assert await client.get_library_sections() is None
    assert await client.get_item_counts("lib") is None


async def test_connect_logs_info_only_on_a_state_change(caplog):
    caplog.set_level("DEBUG", logger="mediawatch_bot.media_core.jellyfin.client")
    client = make_connecting_client(200)

    def connected_levels():
        levels = [r.levelname for r in caplog.records if "Connected to" in r.getMessage()]
        caplog.clear()
        return levels

    await client.connect()
    assert connected_levels() == ["INFO"]
    await client.connect()
    assert connected_levels() == ["DEBUG"]

    client._get_session = make_connecting_client(500)._get_session
    await client.connect()
    client._get_session = make_connecting_client(200)._get_session
    await client.connect()
    assert connected_levels() == ["INFO"]
