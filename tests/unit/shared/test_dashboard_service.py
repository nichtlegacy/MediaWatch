from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from cogs.media_core.shared.dashboard_service import (
    DashboardService,
    calculate_total_download_size,
)


CONFIG = {
    "dashboard": {"name": "Dashboard", "icon_url": "", "footer_icon_url": ""},
    "plex": {"sections": {}, "show_all": True},
}


def _service(cogs=None, platform="plex", config=None):
    bot = SimpleNamespace(get_cog=lambda name: (cogs or {}).get(name))
    return DashboardService(bot, config or CONFIG, platform)


def _online_info(stream_count):
    return {
        "status": "🟢 Online",
        "uptime": "01:00",
        "library_stats": {},
        "active_users": ["x" * 161] * stream_count,
    }


@pytest.mark.asyncio
async def test_dashboard_embed_stays_within_the_discord_field_limit():
    embed = await _service().create_dashboard_embed(_online_info(8))

    streams_field = next(f for f in embed.fields if "Stream" in f.name)
    assert len(streams_field.value) <= 1024
    assert "showing 6 of 8" in streams_field.name
    assert len(embed) <= 6000


@pytest.mark.asyncio
async def test_dashboard_embed_shows_all_streams_when_they_fit():
    embed = await _service().create_dashboard_embed(_online_info(3))

    streams_field = next(f for f in embed.fields if "Stream" in f.name)
    assert streams_field.name == "3 current Streams:"
    assert "showing" not in streams_field.name


@pytest.mark.asyncio
async def test_dashboard_embed_trims_downloads_to_the_remaining_budget():
    class FakeSabnzbd:
        def format_download_info(self, download, index):
            return "d" * 400

    info = _online_info(4)
    info["downloads"] = {
        "configured": True,
        "downloads": [{"size": "1.00 GB"}] * 4,
        "free_space": "1 TB",
        "total_space": "2 TB",
    }

    embed = await _service({"SABnzbd": FakeSabnzbd()}).create_dashboard_embed(info)

    downloads_field = next(f for f in embed.fields if "Download" in f.name and ":" in f.name)
    assert len(downloads_field.value) <= 1024
    assert len(embed) <= 6000


@pytest.mark.asyncio
async def test_dashboard_embed_orders_library_sections_by_config_on_jellyfin():
    config = {
        "dashboard": {"name": "Dashboard", "icon_url": "", "footer_icon_url": ""},
        "jellyfin": {
            "sections": {"Movies": {}, "Shows": {}},
            "show_all": True,
        },
    }
    info = {
        "status": "🟢 Online",
        "uptime": "01:00",
        "library_stats": {
            "Music": {
                "count": 1,
                "episodes": 0,
                "display_name": "Music",
                "emoji": "🎵",
                "show_episodes": False,
            },
            "Shows": {
                "count": 2,
                "episodes": 9,
                "display_name": "Shows",
                "emoji": "📺",
                "show_episodes": True,
            },
            "Movies": {
                "count": 3,
                "episodes": 0,
                "display_name": "Movies",
                "emoji": "🎥",
                "show_episodes": False,
            },
        },
        "active_users": [],
    }

    embed = await _service(platform="jellyfin", config=config).create_dashboard_embed(info)

    library_names = [
        f.name for f in embed.fields if f.name.startswith(("Movies", "Shows", "Music"))
    ]
    assert library_names == ["Movies 🎥", "Shows 📺", "Shows Episodes 📺", "Music 🎵"]


@pytest.mark.asyncio
async def test_dashboard_embed_caps_the_number_of_library_fields():
    config = {
        "dashboard": {"name": "Dashboard", "icon_url": "", "footer_icon_url": ""},
        "plex": {"sections": {}, "show_all": True},
    }
    info = {
        "status": "🟢 Online",
        "uptime": "01:00",
        "library_stats": {
            f"Library {i}": {
                "count": i,
                "episodes": 0,
                "display_name": f"Library {i}",
                "emoji": "🎬",
                "show_episodes": False,
            }
            for i in range(30)
        },
        "active_users": [],
    }

    embed = await _service(config=config).create_dashboard_embed(info)

    assert len(embed.fields) <= 25


def test_calculate_total_download_size_skips_downloads_without_a_size():
    assert (
        calculate_total_download_size([{}, {"size": "Unknown"}, {"size": "512.00 MB"}])
        == "512.00 MB"
    )


def test_calculate_total_download_size_sums_mixed_units():
    assert calculate_total_download_size([{"size": "1.00 GB"}, {"size": "1024.00 MB"}]) == "2.00 GB"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "credential"),
    [("plex", "PLEX_TOKEN"), ("jellyfin", "JELLYFIN_API_KEY")],
)
async def test_dashboard_embed_names_the_rejected_credential(platform, credential):
    config = {
        "dashboard": {"name": "Dashboard", "icon_url": "", "footer_icon_url": ""},
        platform: {"sections": {}, "show_all": True},
    }
    info = {"status": "🔴 Offline", "auth_failed": True, "library_stats": {}, "active_users": []}

    embed = await _service(platform=platform, config=config).create_dashboard_embed(info)

    assert "rejected the credentials" in embed.title
    assert not any("Offline since" in f.name for f in embed.fields)
    assert credential in embed.fields[0].value


@pytest.mark.asyncio
async def test_dashboard_embed_still_reports_a_plain_outage_as_offline():
    info = {"status": "🔴 Offline", "auth_failed": False, "library_stats": {}, "active_users": []}

    embed = await _service().create_dashboard_embed(info)

    assert "Offline" in embed.title
    assert embed.fields[0].name == "Offline since:"


def _offline_info(**extra):
    info = {"status": "🔴 Offline", "auth_failed": False, "library_stats": {}, "active_users": []}
    info.update(extra)
    return info


def _field(embed, name):
    return next(f for f in embed.fields if f.name == name)


@pytest.mark.asyncio
async def test_offline_embed_reports_when_the_outage_started():
    offline_since = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)

    embed = await _service().create_dashboard_embed(_offline_info(offline_since=offline_since))

    timestamp = int(offline_since.timestamp())
    assert _field(embed, "Offline since:").value == (
        f"**Since:** <t:{timestamp}:f>\n**Duration:** <t:{timestamp}:R>"
    )


@pytest.mark.asyncio
async def test_offline_embed_admits_it_when_the_outage_start_is_unknown():
    embed = await _service().create_dashboard_embed(_offline_info())

    assert _field(embed, "Offline since:").value == (
        "**Since:** Unknown\n**Duration:** Unknown duration"
    )


@pytest.mark.asyncio
async def test_offline_embed_shows_the_uptime_kuma_numbers():
    service = _service(cogs={"Uptime": object()})
    info = _offline_info(uptime_24h="99.9%", uptime_7d="98.5%", uptime_30d="97.0%")

    embed = await service.create_dashboard_embed(info)

    assert _field(embed, "Uptime (24h)").value == "```99.9%```"
    assert _field(embed, "Uptime (7 days)").value == "```98.5%```"
    assert _field(embed, "Uptime (30 days)").value == "```97.0%```"


@pytest.mark.asyncio
async def test_offline_embed_omits_the_uptime_block_without_the_uptime_cog():
    info = _offline_info(uptime_24h="99.9%", uptime_7d="98.5%", uptime_30d="97.0%")

    embed = await _service().create_dashboard_embed(info)

    assert not any(f.name.startswith("Uptime (") for f in embed.fields)


@pytest.mark.asyncio
async def test_offline_embed_omits_the_uptime_block_when_kuma_has_no_data():
    service = _service(cogs={"Uptime": object()})

    embed = await service.create_dashboard_embed(_offline_info(uptime_24h="No data"))

    assert not any(f.name.startswith("Uptime (") for f in embed.fields)


async def test_dashboard_embed_says_when_libraries_had_to_be_dropped():
    """Discord caps an embed at 25 fields, so many sections get truncated.

    Dropping them silently sends the user looking for the mistake in their
    config; the streams block already names its own cap the same way.
    """
    config = {
        "dashboard": {"name": "Dashboard", "icon_url": "", "footer_icon_url": ""},
        "jellyfin": {"sections": {}, "show_all": True},
    }
    info = {
        "status": "🟢 Online",
        "uptime": "01:00",
        "library_stats": {
            f"Library {index}": {
                "count": index,
                "episodes": 0,
                "display_name": f"Library {index}",
                "emoji": "🎬",
                "show_episodes": False,
            }
            for index in range(20)
        },
        "active_users": [],
    }

    embed = await _service(platform="jellyfin", config=config).create_dashboard_embed(info)

    assert any("showing 15 of 20 libraries" in field.name for field in embed.fields)
    assert len(embed) <= 6000
    assert len(embed.fields) <= 25


async def test_dashboard_embed_stays_quiet_when_every_library_fits():
    config = {
        "dashboard": {"name": "Dashboard", "icon_url": "", "footer_icon_url": ""},
        "jellyfin": {"sections": {}, "show_all": True},
    }
    info = {
        "status": "🟢 Online",
        "uptime": "01:00",
        "library_stats": {
            "Movies": {
                "count": 3,
                "episodes": 0,
                "display_name": "Movies",
                "emoji": "🎥",
                "show_episodes": False,
            }
        },
        "active_users": [],
    }

    embed = await _service(platform="jellyfin", config=config).create_dashboard_embed(info)

    assert not any("showing" in field.name for field in embed.fields)


async def test_dashboard_embed_says_when_downloads_had_to_be_dropped():
    """The queue is capped at four entries; the header must admit it.

    The streams field already does this. Without it a queue of six sits behind
    a header reading "6 current Downloads:" with four blocks under it, which
    reads like the section is broken rather than truncated.
    """

    class FakeSabnzbd:
        @staticmethod
        def format_download_info(download, index):
            return f"`{download['name']}`"

    config = {
        "dashboard": {"name": "Dashboard", "icon_url": "", "footer_icon_url": ""},
        "jellyfin": {"sections": {}, "show_all": True},
    }
    info = {
        "status": "🟢 Online",
        "uptime": "01:00",
        "library_stats": {},
        "active_users": [],
        "downloads": {
            "configured": True,
            "downloads": [{"name": f"Release.{i}", "size": "1 GB"} for i in range(6)],
            "free_space": "100 GB",
            "total_space": "500 GB",
        },
    }
    service = _service(platform="jellyfin", config=config)
    service.bot = SimpleNamespace(get_cog=lambda name: FakeSabnzbd() if name == "SABnzbd" else None)

    embed = await service.create_dashboard_embed(info)

    header = next(f.name for f in embed.fields if "current Download" in (f.name or ""))
    assert "showing 4 of 6" in header
