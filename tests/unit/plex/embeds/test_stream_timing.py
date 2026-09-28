from datetime import datetime
from zoneinfo import ZoneInfo

from cogs.media_core.plex.embeds.stream_embeds import (
    _build_timing_row,
    _normalize_detail_value,
    _parse_session_started,
)


TZ = ZoneInfo("Europe/Berlin")


def test_parse_session_started_accepts_epoch_seconds_string():
    started = _parse_session_started("1713200000", TZ)

    assert started == datetime(2024, 4, 15, 18, 53, 20, tzinfo=TZ)


def test_parse_session_started_accepts_epoch_milliseconds():
    started = _parse_session_started("1713200000000", TZ)

    assert started == datetime(2024, 4, 15, 18, 53, 20, tzinfo=TZ)


def test_parse_session_started_accepts_common_datetime_string():
    started = _parse_session_started("2026-04-15 20:14:00", TZ)

    assert started == datetime(2026, 4, 15, 20, 14, 0, tzinfo=TZ)


def test_parse_session_started_returns_none_for_unparsable_values():
    assert _parse_session_started("", TZ) is None
    assert _parse_session_started(None, TZ) is None
    assert _parse_session_started("not a date", TZ) is None


def test_build_timing_row_includes_start_and_estimated_end():
    started = datetime(2026, 4, 15, 20, 14, 0)

    row = _build_timing_row(
        started,
        duration_ms=90 * 60 * 1000,
        view_offset_ms=30 * 60 * 1000,
        now=datetime(2026, 4, 15, 21, 0, 0, tzinfo=TZ),
    )

    # 60 minutes of the 90 are left, so the stream ends an hour after `now`.
    assert row == "▶ 20:14 | ■ 22:00"


def test_build_timing_row_derives_the_start_from_the_view_offset():
    row = _build_timing_row(
        None,
        duration_ms=90 * 60 * 1000,
        view_offset_ms=30 * 60 * 1000,
        now=datetime(2026, 4, 15, 21, 0, 0, tzinfo=TZ),
    )

    # No reported start, but 30 minutes are already watched: it began at 20:30.
    assert row == "▶ 20:30 | ■ 22:00"


def test_build_timing_row_omits_the_start_when_nothing_has_been_watched():
    row = _build_timing_row(
        None,
        duration_ms=60 * 60 * 1000,
        view_offset_ms=0,
        now=datetime(2026, 4, 15, 21, 0, 0, tzinfo=TZ),
    )

    assert row == "■ 22:00"


def test_build_timing_row_omits_the_end_for_an_unknown_duration():
    row = _build_timing_row(
        datetime(2026, 4, 15, 20, 14, 0),
        duration_ms=0,
        view_offset_ms=30 * 60 * 1000,
        now=datetime(2026, 4, 15, 21, 0, 0, tzinfo=TZ),
    )

    assert row == "▶ 20:14"


def test_build_timing_row_returns_none_without_any_timing_information():
    assert (
        _build_timing_row(
            None,
            duration_ms=0,
            view_offset_ms=0,
            now=datetime(2026, 4, 15, 21, 0, 0, tzinfo=TZ),
        )
        is None
    )


def test_normalize_detail_value_falls_back_for_blank_values():
    assert _normalize_detail_value("") == "Unknown"
    assert _normalize_detail_value("   ") == "Unknown"
    assert _normalize_detail_value(None) == "Unknown"
