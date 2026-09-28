from datetime import datetime

from cogs.media_core.plex.utils.user_stats_utils import (
    calculate_most_active_day,
    calculate_most_active_device,
    calculate_peak_hour,
    calculate_top_content_type,
)


def _timestamp(year: int, month: int, day: int, hour: int) -> int:
    return int(datetime(year, month, day, hour, 0, 0).timestamp())


def test_calculate_peak_hour_returns_busiest_hour():
    history = [
        {"date": _timestamp(2026, 4, 14, 20)},
        {"date": _timestamp(2026, 4, 15, 20)},
        {"date": _timestamp(2026, 4, 16, 18)},
    ]

    assert calculate_peak_hour(history) == {"hour": 20, "count": 2}


def test_calculate_most_active_day_returns_busiest_weekday():
    history = [
        {"date": _timestamp(2026, 4, 14, 20)},  # Tuesday
        {"date": _timestamp(2026, 4, 21, 21)},  # Tuesday
        {"date": _timestamp(2026, 4, 28, 22)},  # Tuesday
        {"date": _timestamp(2026, 4, 15, 18)},  # Wednesday
    ]

    assert calculate_most_active_day(history) == {"day": "Tuesday", "count": 3}


def test_calculate_most_active_device_prefers_watch_time_then_plays():
    player_stats = [
        {"platform": "Web", "total_time": 3600, "total_plays": 10},
        {"player_name": "Apple TV", "total_time": 7200, "total_plays": 4},
        {"product": "iPhone", "total_time": 7200, "total_plays": 2},
    ]

    assert calculate_most_active_device(player_stats) == {
        "name": "Apple TV",
        "total_time": 7200,
        "total_plays": 4,
    }


def test_calculate_top_content_type_uses_watch_time():
    content_breakdown = {
        "tv": {"plays": 8, "time": 10000, "percentage": 55.5},
        "movie": {"plays": 3, "time": 7000, "percentage": 38.9},
        "music": {"plays": 4, "time": 1000, "percentage": 5.6},
    }

    assert calculate_top_content_type(content_breakdown) == {
        "label": "TV Shows",
        "time": 10000,
        "plays": 8,
        "percentage": 55.5,
    }


def test_new_stat_helpers_return_none_for_empty_inputs():
    assert calculate_peak_hour([]) is None
    assert calculate_most_active_day([]) is None
    assert calculate_most_active_device([]) is None
    assert calculate_top_content_type({}) is None
