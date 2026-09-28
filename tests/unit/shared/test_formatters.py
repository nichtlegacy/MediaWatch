from cogs.media_core.shared.formatters import (
    embed_field_budget,
    format_audio_quality,
    format_audio_direct_stream_line,
    format_audio_stream_label,
    format_language_name,
    format_progress_bar,
    format_resolution,
    format_resolution_from_dimensions,
    format_stream_summary,
    format_time_from_ms,
    format_transcoding_subtitle_line,
    join_within_limit,
    normalize_audio_codec_name,
    resolve_user_display_name,
    sanitize_code_block_text,
    truncate_to_sentence_boundary,
)
from cogs.media_core.shared.models import ActiveStream, MediaType


def test_truncate_to_sentence_boundary_keeps_short_text():
    text = "Short sentence. Another one."

    assert truncate_to_sentence_boundary(text, max_length=300) == text


def test_truncate_to_sentence_boundary_stops_at_last_complete_sentence_within_limit():
    text = "First sentence. Second sentence is complete. Third sentence continues beyond the limit."
    limit = len("First sentence. Second sentence is complete. Third sente")

    assert truncate_to_sentence_boundary(text, max_length=limit) == text


def test_truncate_to_sentence_boundary_falls_back_to_last_period_before_hard_limit():
    text = "A" * 900 + "." + "B" * 200

    result = truncate_to_sentence_boundary(text, max_length=300, hard_limit=1024)

    assert result == "A" * 900 + "."


def test_truncate_to_sentence_boundary_keeps_next_sentence_end_after_soft_limit():
    text = "A" * 305 + ". More text that should not be included."

    assert truncate_to_sentence_boundary(text, max_length=300) == "A" * 305 + "."


def test_format_audio_stream_label_formats_codec_and_channels():
    assert format_audio_stream_label("ac3", 6) == "AC3 5.1"


def test_format_audio_stream_label_handles_missing_channels():
    assert format_audio_stream_label("dts", None) == "DTS"


def test_format_audio_stream_label_uses_profile_for_dts_hd_ma():
    assert format_audio_stream_label("dca", 6, "ma") == "DTS-HD MA 5.1"


def test_format_audio_stream_label_handles_dts_hd_ma_stereo():
    assert format_audio_stream_label("dca", 2, "ma") == "DTS-HD MA 2.0"


def test_format_audio_stream_label_handles_truehd_five_one():
    assert format_audio_stream_label("truehd", 6) == "TrueHD 5.1"


def test_format_audio_stream_label_handles_six_one_channel_layouts():
    assert format_audio_stream_label("eac3", 7) == "EAC3 6.1"


def test_normalize_audio_codec_name_handles_live_tautulli_values():
    assert normalize_audio_codec_name("ac3") == "AC3"
    assert normalize_audio_codec_name("eac3") == "EAC3"


def test_normalize_audio_codec_name_handles_common_surround_variants():
    assert normalize_audio_codec_name("dca") == "DTS"
    assert normalize_audio_codec_name("dtshd_ma") == "DTS-HD MA"
    assert normalize_audio_codec_name("truehd") == "TrueHD"


def test_normalize_audio_codec_name_uses_profile_when_present():
    assert normalize_audio_codec_name("dca", "ma") == "DTS-HD MA"
    assert normalize_audio_codec_name("dca", "hra") == "DTS-HD HRA"


def test_format_resolution_keeps_sd_without_p_suffix():
    assert format_resolution("SD") == "SD"
    assert format_resolution("sdp") == "SD"


def _stream(**overrides):
    defaults = dict(
        session_id="1",
        session_key="1",
        username="alice",
        media_type=MediaType.MOVIE,
        title="Movie",
        view_offset_ms=60_000,
        duration_ms=1_200_000,
        video_resolution="1080p",
        video_bitrate_kbps=4000,
        player_name="Plex Web",
    )
    defaults.update(overrides)
    return ActiveStream(**defaults)


def test_sanitize_code_block_text_removes_backticks_and_newlines():
    injected = "Movie```\n[click me](http://evil.example)"

    result = sanitize_code_block_text(injected)

    assert "`" not in result
    assert "\n" not in result


def test_sanitize_code_block_text_caps_length():
    result = sanitize_code_block_text("A" * 300, max_length=20)

    assert len(result) == 20


def test_join_within_limit_drops_blocks_that_exceed_the_field_limit():
    blocks = ["x" * 161] * 7

    value, shown = join_within_limit(blocks, limit=1024)

    assert shown == 6
    assert len(value) <= 1024


def test_join_within_limit_truncates_a_single_oversized_block():
    value, shown = join_within_limit(["x" * 2000], limit=1024)

    assert shown == 1
    assert len(value) == 1024


def test_embed_field_budget_shrinks_with_the_total_embed_limit():
    class FakeEmbed:
        def __len__(self):
            return 5800

    assert embed_field_budget(FakeEmbed(), "Streams:", reserve=0) == 6000 - 5800 - len("Streams:")
    assert embed_field_budget(FakeEmbed(), "Streams:", reserve=500) == 0


def test_format_stream_summary_sanitizes_the_player_name():
    summary = format_stream_summary(_stream(player_name="Plex for ```[x](http://evil.example)"))

    assert summary.count("```") == 2


def test_format_stream_summary_uses_the_transcode_bitrate_while_transcoding():
    summary = format_stream_summary(
        _stream(is_transcoding=True, video_bitrate_kbps=8000, transcode_bitrate_kbps=2000)
    )

    assert "2.0 Mbps" in summary


def test_format_transcoding_subtitle_line_wraps_values_in_code():
    line = format_transcoding_subtitle_line("Burn", "German", "ASS", forced=True)

    assert line == "**Subtitle:** Burn (`German - ASS`) (`Forced`)"


def test_format_audio_direct_stream_line_includes_codec_and_channels():
    assert format_audio_direct_stream_line("ac3", 6) == "**Audio:** Direct Stream (`AC3 5.1`)"
    assert format_audio_direct_stream_line("eac3", 6) == "**Audio:** Direct Stream (`EAC3 5.1`)"


def test_format_audio_direct_stream_line_uses_profile_for_dts_hd_ma():
    assert (
        format_audio_direct_stream_line("dca", 6, "ma")
        == "**Audio:** Direct Stream (`DTS-HD MA 5.1`)"
    )
    assert (
        format_audio_direct_stream_line("dca", 2, "ma")
        == "**Audio:** Direct Stream (`DTS-HD MA 2.0`)"
    )


def test_format_resolution_normalizes_all_4k_spellings():
    assert format_resolution("4k") == "4K"
    assert format_resolution("2160") == "4K"
    assert format_resolution("2160p") == "4K"


def test_format_resolution_from_dimensions_keeps_uncommon_heights():
    assert format_resolution_from_dimensions(3840, 2160) == "4K"
    assert format_resolution_from_dimensions(1280, 720) == "720p"
    # PAL DVD material: reporting this as 480p would be wrong.
    assert format_resolution_from_dimensions(720, 576) == "576p"
    assert format_resolution_from_dimensions(854, 480) == "480p"


def test_resolve_user_display_name_uses_a_flat_mapping():
    assert resolve_user_display_name({"alice": "Alice A."}, "alice") == "Alice A."


def test_resolve_user_display_name_unwraps_any_platform_wrapper():
    assert resolve_user_display_name({"plex": {"alice": "Alice A."}}, "alice") == "Alice A."
    assert resolve_user_display_name({"jellyfin": {"bob": "Bob B."}}, "bob") == "Bob B."


def test_resolve_user_display_name_falls_back_to_the_raw_name():
    assert resolve_user_display_name({"plex": {}}, "carol") == "carol"
    assert resolve_user_display_name(None, fallback="Unknown") == "Unknown"


def test_format_time_from_ms_keeps_hours_when_the_duration_is_unknown():
    """A stream without a reported duration must not lose its hours.

    Plex sessions with no `duration` attribute and live content report
    total_duration_ms == 0. Deciding the format on that value alone rendered
    3h40m elapsed as "40:00".
    """
    elapsed = (3 * 3600 + 40 * 60) * 1000

    assert format_time_from_ms(elapsed, 0) == "3:40:00"
    # A genuinely short stream still uses the compact form.
    assert format_time_from_ms(40 * 60 * 1000, 0) == "40:00"


def test_format_progress_bar_can_leave_the_percentage_off():
    assert format_progress_bar(62.9) == "[▓▓▓▓▓▓░░░░] 62.9%"
    assert format_progress_bar(62.9, show_percent=False) == "[▓▓▓▓▓▓░░░░]"
    assert format_progress_bar(116.7, show_percent=False) == "[▓▓▓▓▓▓▓▓▓▓]"


def test_format_progress_bar_clamps_out_of_range_values():
    """Plex reports >100% at the end of a stream and for live content."""
    assert format_progress_bar(116.7) == "[▓▓▓▓▓▓▓▓▓▓] 100.0%"
    assert format_progress_bar(-5.0) == "[░░░░░░░░░░] 0.0%"
    # The bar never changes width, which is what keeps the code block aligned.
    assert len(format_progress_bar(116.7).split("]")[0]) == len("[") + 10


def test_truncate_to_sentence_boundary_ignores_a_useless_early_period():
    """An abbreviation at the start must not shrink the whole summary.

    The fallback takes the last period before hard_limit; with "Dr. " as the
    only early period that cut a 2000 character description down to "Dr.".
    """
    text = "Dr. " + "x" * 2000

    result = truncate_to_sentence_boundary(text, max_length=300)

    assert result != "Dr."
    assert len(result) >= 150


def test_format_language_name_maps_iso_codes():
    """Jellyfin reports codes, Plex reports names - both must read the same."""
    assert format_language_name("deu") == "German"
    # Bibliographic and terminological ISO 639-2 both occur, depending on the
    # tool that muxed the file.
    assert format_language_name("ger") == "German"
    assert format_language_name("eng") == "English"
    assert format_language_name("fre") == format_language_name("fra") == "French"
    assert format_language_name("de") == "German"
    assert format_language_name("DEU") == "German"
    assert format_language_name(" eng ") == "English"
    # Beyond the western European set that prompted this.
    assert format_language_name("tam") == "Tamil"
    assert format_language_name("yue") == "Cantonese"
    assert format_language_name("fil") == "Filipino"


def test_format_language_name_passes_names_through():
    """Plex already hands over a readable name; it must survive untouched."""
    assert format_language_name("Deutsch") == "Deutsch"
    assert format_language_name("English") == "English"
    # An unmapped code is still shown rather than swallowed.
    assert format_language_name("zzz") == "zzz"


def test_format_language_name_handles_missing_values():
    assert format_language_name(None) == "Unknown"
    assert format_language_name("") == "Unknown"
    assert format_language_name("   ") == "Unknown"
    # The transcode line passes an empty default so it can skip the segment.
    assert format_language_name(None, "") == ""


def test_format_audio_quality_shows_bit_depth_and_sample_rate():
    assert format_audio_quality(24, 96000) == "24bit 96kHz"
    assert format_audio_quality(16, 44100) == "16bit 44.1kHz"
    assert format_audio_quality(None, 48000) == "48kHz"
    assert format_audio_quality(24, None) == "24bit"
    assert format_audio_quality(None, None) == ""
    assert format_audio_quality("bad", 0) == ""


def test_stream_summary_shows_the_audio_quality_of_a_track():
    track = _stream(media_type=MediaType.TRACK, video_resolution="", audio_quality="24bit 96kHz")
    no_quality = _stream(media_type=MediaType.TRACK, video_resolution="", audio_quality="")

    assert "24bit 96kHz" in format_stream_summary(track)
    assert "Audio" in format_stream_summary(no_quality)
