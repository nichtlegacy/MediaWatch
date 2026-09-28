import pytest

from cogs.media_core.jellyfin.embeds.stream_embeds import (
    _is_private_endpoint,
)


@pytest.mark.parametrize(
    "endpoint",
    [
        "192.168.1.5:53124",
        "10.0.0.8",
        "127.0.0.1:8096",
        "172.20.0.5:44212",
        "[fd00::1]:8096",
        "::1",
    ],
)
def test_is_private_endpoint_accepts_local_addresses(endpoint):
    assert _is_private_endpoint(endpoint) is True


@pytest.mark.parametrize(
    "endpoint",
    ["93.184.216.34:51234", "[2606:2800:220:1::1]:8096", "not-an-ip", "", None],
)
def test_is_private_endpoint_rejects_remote_and_invalid_addresses(endpoint):
    assert _is_private_endpoint(endpoint) is False
