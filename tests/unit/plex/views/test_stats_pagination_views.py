import asyncio
import threading
from types import SimpleNamespace

import pytest

from cogs.media_core.plex.views.global_stats_pagination import GlobalStatsPaginationView
from cogs.media_core.plex.views.chart_rendering import render_chart
from cogs.media_core.plex.views.user_stats_pagination import UserStatsPaginationView


def _make_core(user_mapping):
    return SimpleNamespace(
        config={
            "dashboard": {
                "name": "Plex Dashboard",
                "icon_url": "https://example.com/plex.png",
                "footer_icon_url": "https://example.com/footer.png",
            },
            "user_stats": {
                "pages": {
                    "behavior": True,
                    "devices": True,
                    "top_content": True,
                },
            },
        },
        user_mapping=user_mapping,
    )


@pytest.mark.asyncio
async def test_chart_rendering_runs_off_event_loop():
    event_loop_thread = threading.get_ident()

    rendered_thread = await render_chart(threading.get_ident)

    assert rendered_thread != event_loop_thread


@pytest.mark.asyncio
async def test_user_chart_cache_evicts_oldest_entry(monkeypatch):
    monkeypatch.setattr(UserStatsPaginationView, "_daily_chart_cache", {})
    monkeypatch.setattr(UserStatsPaginationView, "MAX_CHART_CACHE_ENTRIES", 1)
    stats = {
        "player_stats": [{"player_name": "TV", "total_time": 60}],
        "content_breakdown": {"tv": {"plays": 1, "time": 60}},
        "time_range": 30,
    }

    first = UserStatsPaginationView(_make_core({}), "user-1", "User 1", stats)
    second = UserStatsPaginationView(_make_core({}), "user-2", "User 2", stats)
    await first.generate_dual_pie_chart()
    await second.generate_dual_pie_chart()

    assert len(UserStatsPaginationView._daily_chart_cache) == 1
    assert next(iter(UserStatsPaginationView._daily_chart_cache))[0] == "user-2"


@pytest.mark.asyncio
async def test_user_stats_behavior_page_uses_mapped_display_name():
    core = _make_core({"raw_user_1": "Mapped User"})
    view = UserStatsPaginationView(
        core,
        user_id="user-1",
        user_display="raw_user_1",
        stats_data={"watch_time_stats": {}, "time_range": 30},
    )

    embed = await view._create_page_behavior()

    assert embed.title == "📊 User Statistics: Mapped User"


@pytest.mark.asyncio
async def test_global_stats_page_3_uses_dynamic_title_and_mapped_names():
    core = _make_core({"plex": {"raw_user_1": "Mapped User"}})
    view = GlobalStatsPaginationView(
        core,
        {
            "page2_time_range": 90,
            "top_users": [
                {
                    "user": "raw_user_1",
                    "friendly_name": "Friendly Label",
                    "total_duration": 7200,
                    "total_plays": 4,
                }
            ],
        },
    )

    embed = await view._create_page_3()

    assert embed.title == "🌐 Top 10 Users by Watch Time (Last 90 days)"
    assert embed.fields[0].name == "\u200b"
    assert "Mapped User" in embed.fields[0].value
    assert "raw_user_1" not in embed.fields[0].value


@pytest.mark.asyncio
async def test_global_stats_page_1_uses_popular_movies_payload():
    core = _make_core({})
    view = GlobalStatsPaginationView(
        core,
        {
            "watch_time": {"last_30d": {"total_plays": 10, "total_time": 7200}},
            "popular_movies": [
                {"title": "Movie A", "year": 2024, "total_plays": 3},
                {"title": "Movie B", "year": 2023, "total_plays": 2},
            ],
        },
    )

    embed = await view._create_page_1()

    movies_field = next(
        field for field in embed.fields if field.name == "🎬 Most Popular Movies (Last 30 days)"
    )
    assert "Movie A (2024)" in movies_field.value
    assert "3 plays" in movies_field.value


@pytest.mark.asyncio
async def test_user_stats_footer_page_numbers_follow_enabled_pages():
    core = _make_core({})
    core.config["user_stats"]["pages"]["behavior"] = False
    view = UserStatsPaginationView(
        core,
        user_id="user-1",
        user_display="raw_user_1",
        stats_data={"watch_time_stats": {}, "time_range": 30, "top_shows": []},
    )

    devices = await view._create_page_devices()
    top_content = await view._create_page_top_content()

    assert devices.footer.text == "Page 1/2 • Activity & Devices"
    assert top_content.footer.text == "Page 2/2 • Top Content"


@pytest.mark.asyncio
async def test_top_content_page_respects_top_tv_count():
    core = _make_core({})
    core.config["user_stats"]["top_tv_count"] = 2
    top_shows = [
        {"title": f"Show {i}", "total_plays": i, "total_duration": 60} for i in range(1, 6)
    ]
    view = UserStatsPaginationView(
        core,
        user_id="user-1",
        user_display="raw_user_1",
        stats_data={"watch_time_stats": {}, "time_range": 30, "top_shows": top_shows},
    )

    embed = await view._create_page_top_content()
    value = embed.fields[0].value

    assert "Show 1" in value and "Show 2" in value
    assert "Show 3" not in value


@pytest.mark.parametrize("cancel_running", [False, True])
async def test_chart_queue_does_not_occupy_workers_while_waiting(monkeypatch, cancel_running):
    from cogs.media_core.plex.views import chart_rendering

    monkeypatch.setattr(chart_rendering, "_render_slot", asyncio.Lock())
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    submitted = []
    to_thread = asyncio.to_thread

    async def tracked_to_thread(function, *args):
        submitted.append(function)
        return await to_thread(function, *args)

    def slow_render():
        loop.call_soon_threadsafe(started.set)
        if not release.wait(5):
            raise TimeoutError("test did not release renderer")
        return "first"

    monkeypatch.setattr(chart_rendering.asyncio, "to_thread", tracked_to_thread)
    first = asyncio.create_task(render_chart(slow_render))
    await asyncio.wait_for(started.wait(), 1)
    waiting = [asyncio.create_task(render_chart(lambda: "next")) for _ in range(3)]
    try:
        await asyncio.sleep(0)
        assert len(submitted) == 1
        waiting[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting[0]
        if cancel_running:
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            await asyncio.sleep(0)
            assert len(submitted) == 1
        release.set()
        assert await asyncio.wait_for(asyncio.gather(*waiting[1:]), 2) == ["next", "next"]
        assert len(submitted) == 3
        if not cancel_running:
            assert await first == "first"
    finally:
        release.set()
        await asyncio.gather(first, *waiting, return_exceptions=True)


async def test_chart_queue_releases_slot_after_render_failure(monkeypatch):
    from cogs.media_core.plex.views import chart_rendering

    monkeypatch.setattr(chart_rendering, "_render_slot", asyncio.Lock())

    def fail():
        raise ValueError("render failed")

    with pytest.raises(ValueError, match="render failed"):
        await render_chart(fail)
    assert await asyncio.wait_for(render_chart(lambda: "recovered"), 1) == "recovered"
