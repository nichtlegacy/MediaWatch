import logging
from types import SimpleNamespace

import pytest

from cogs.media_core.plex.services import stream_service
from cogs.media_core.plex.services.stream_service import StreamService


class _FakeResponse:
    status = 500

    async def read(self):
        return b""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class _FakeHTTPSession:
    def get(self, url):
        return _FakeResponse()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


@pytest.mark.asyncio
async def test_download_image_file_never_logs_the_plex_token(monkeypatch, caplog):
    token_url = "http://plex.local:32400/library/metadata/1/thumb?X-Plex-Token=SUPERSECRET"
    plex = SimpleNamespace(url=lambda path, includeToken=False: token_url)
    service = StreamService(plex)

    monkeypatch.setattr(stream_service.aiohttp, "ClientSession", lambda **_: _FakeHTTPSession())

    with caplog.at_level(logging.DEBUG, logger="mediawatch_bot.media_core.plex.stream_service"):
        result = await service.download_image_file("/library/metadata/1/thumb")

    assert result is None
    assert "SUPERSECRET" not in caplog.text
    assert "/library/metadata/1/thumb" in caplog.text


async def test_download_image_file_times_out_to_no_thumbnail(monkeypatch, caplog):
    plex = SimpleNamespace(url=lambda path, includeToken=False: "http://plex:32400/thumb")
    service = StreamService(plex)
    seen = {}

    class _HangingSession(_FakeHTTPSession):
        def get(self, url):
            raise TimeoutError

    def fake_session(**kwargs):
        seen.update(kwargs)
        return _HangingSession()

    monkeypatch.setattr(stream_service.aiohttp, "ClientSession", fake_session)

    with caplog.at_level(logging.WARNING, logger="mediawatch_bot.media_core.plex.stream_service"):
        result = await service.download_image_file("/library/metadata/1/thumb")

    assert result is None
    assert seen["timeout"].total == 10
    assert "Timed out after 10s" in caplog.text
