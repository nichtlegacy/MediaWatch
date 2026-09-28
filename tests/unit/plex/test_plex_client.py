"""Tests for the Plex connection layer.

`auth_failed` is the only signal that separates "the token was rejected" from
"the server is unreachable". If it were always False the dashboard would blame
the media server for a wrong PLEX_TOKEN; if it were always True a network
outage would tell the user their credentials were refused.
"""

from unittest.mock import Mock

import pytest
from plexapi.exceptions import BadRequest, Unauthorized

from cogs.media_core.plex.plex_client import PlexClient


def _client_raising(monkeypatch, error):
    def fake_plex_server(url, token, session=None):
        raise error

    monkeypatch.setattr("cogs.media_core.plex.plex_client.PlexServer", fake_plex_server)
    return PlexClient("http://plex:32400", "token")


@pytest.mark.parametrize(
    "error",
    [
        Unauthorized("401 Unauthorized"),
        BadRequest("(403) forbidden; http://plex:32400/ Not authorized"),
    ],
    ids=["unauthorized", "forbidden"],
)
def test_connect_flags_rejected_credentials(monkeypatch, error):
    client = _client_raising(monkeypatch, error)

    assert client.connect() is None
    assert client.auth_failed is True
    assert client.is_connected() is False


@pytest.mark.parametrize(
    "error",
    [
        ConnectionError("Connection refused"),
        BadRequest("(500) internal_server_error; http://plex:32400/"),
    ],
    ids=["unreachable", "server-error"],
)
def test_connect_does_not_blame_credentials_for_an_outage(monkeypatch, error):
    client = _client_raising(monkeypatch, error)

    assert client.connect() is None
    assert client.auth_failed is False
    assert client.is_connected() is False


def test_connect_clears_a_previous_auth_failure_on_success(monkeypatch):
    client = _client_raising(monkeypatch, Unauthorized("401 Unauthorized"))
    client.connect()
    assert client.auth_failed is True

    server = object()
    monkeypatch.setattr(
        "cogs.media_core.plex.plex_client.PlexServer", lambda url, token, session=None: server
    )

    assert client.connect() is server
    assert client.auth_failed is False
    assert client.is_connected() is True


@pytest.mark.parametrize("error", [ConnectionError("offline"), Unauthorized("401 Unauthorized")])
def test_connection_reuses_pool_probes_and_recovers(monkeypatch, error):
    pool = Mock()
    first = Mock()
    first.query.side_effect = [{"friendlyName": "Updated name", "version": "2"}, error]
    recovered = Mock()
    factory = Mock(side_effect=[first, recovered])
    monkeypatch.setattr("cogs.media_core.plex.plex_client.requests.Session", lambda: pool)
    monkeypatch.setattr("cogs.media_core.plex.plex_client.PlexServer", factory)
    client = PlexClient("http://plex:32400", "token")

    assert client.connect() is first
    baseline = client.start_time
    assert client.connect() is first
    assert client.start_time == baseline
    assert client.get_server_name() == "Updated name"
    assert client.get_server_version() == "2"
    factory.assert_called_once_with("http://plex:32400", "token", session=pool)
    first.query.assert_called_once_with("/")

    assert client.connect() is None
    assert not client.is_connected()
    assert client.auth_failed == isinstance(error, Unauthorized)
    pool.close.assert_called_once()
    assert client.connect() is recovered
    assert not client.auth_failed
    assert factory.call_count == 2
    assert factory.call_args.kwargs["session"] is pool
    client.disconnect()
    assert not client.is_connected()
    assert client.start_time is None
    assert pool.close.call_count == 2


def test_get_library_sections_reports_failure_as_none_not_empty():
    client = PlexClient("http://plex:32400", "token")
    assert client.get_library_sections() is None

    client._server = Mock()
    client._server.library.sections.side_effect = ConnectionError("offline")
    assert client.get_library_sections() is None

    client._server.library.sections.side_effect = None
    client._server.library.sections.return_value = []
    assert client.get_library_sections() == {}
