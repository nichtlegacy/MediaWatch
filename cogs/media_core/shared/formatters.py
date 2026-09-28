"""
Shared formatting utility functions for MediaWatch.

This module contains all formatting functions for converting raw data
into human-readable strings for Discord embeds. These functions are
platform-agnostic and work with both Plex and Jellyfin data.
"""

import time
from typing import Any, List, Optional, Tuple


# Discord's hard limits for a single embed.
DISCORD_FIELD_VALUE_LIMIT = 1024
DISCORD_EMBED_TOTAL_LIMIT = 6000


def format_watch_time(seconds: int) -> str:
    """Format watch time in seconds to human-readable format.

    Args:
        seconds: Time in seconds

    Returns:
        Formatted string like "2d 3h 45m" or "1h 30m"
    """
    if seconds == 0:
        return "0m"

    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0 or len(parts) == 0:
        parts.append(f"{minutes}m")

    return " ".join(parts)


def format_time_from_ms(milliseconds: int, total_duration_ms: int) -> str:
    """Format milliseconds to time string.

    Args:
        milliseconds: Time in milliseconds
        total_duration_ms: Total duration in milliseconds (determines format)

    Returns:
        Formatted time string (MM:SS for <1h, H:MM:SS for >=1h)
    """
    total_seconds = milliseconds // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    # A stream with an unknown duration reports total_duration_ms == 0 (Plex
    # sessions without a `duration` attribute, live content). Deciding the
    # format on that alone dropped the hours: 3h40m elapsed rendered as "40:00".
    reference_ms = max(total_duration_ms, milliseconds)
    less_than_hour = (reference_ms // 1000) < 3600

    if less_than_hour:
        return f"{minutes:02d}:{seconds:02d}"
    return f"{hours}:{minutes:02d}:{seconds:02d}"


def format_resolution(res: Any) -> str:
    """Format video resolution to standardized string.

    Args:
        res: Resolution value (can be string or int)

    Returns:
        Formatted resolution like "4K", "1080p", etc.
    """
    if not res or res == "Unknown":
        return "Unknown"

    res_str = str(res).lower()

    if res_str in ("4k", "2160", "2160p"):
        return "4K"
    elif res_str in ("sd", "sdp"):
        return "SD"
    elif res_str.isdigit():
        return f"{res_str}p"
    elif res_str.endswith("p"):
        return res_str.upper() if res_str in ("4kp",) else res_str
    else:
        return res_str.upper()


def format_resolution_from_dimensions(width: int, height: int) -> str:
    """Format video resolution from width/height dimensions.

    Used for Jellyfin which provides dimensions instead of resolution string.

    Args:
        width: Video width in pixels
        height: Video height in pixels

    Returns:
        Formatted resolution like "4K", "1080p", "720p", etc.
    """
    if width >= 3840 or height >= 2160:
        return "4K"
    elif width >= 1920 or height >= 1080:
        return "1080p"
    elif width >= 1280 or height >= 720:
        return "720p"
    elif height > 0:
        # Keep the real height below 720p: 576p (PAL) would otherwise be
        # reported as 480p.
        return f"{height}p"
    return "Unknown"


def format_audio_quality(bit_depth: Any, sample_rate_hz: Any) -> str:
    """Format a track's bit depth and sample rate, e.g. ``"24bit 96kHz"``.

    Music has no resolution, so this is what the stream line shows in its
    place. Either half may be missing; 44100 Hz reads ``44.1kHz``, not the
    truncated ``44kHz``.
    """
    parts = []
    try:
        depth = int(bit_depth)
        if depth > 0:
            parts.append(f"{depth}bit")
    except (TypeError, ValueError):
        pass
    try:
        khz = float(sample_rate_hz) / 1000
        if khz > 0:
            parts.append(f"{khz:g}kHz")
    except (TypeError, ValueError):
        pass
    return " ".join(parts)


def format_channels(ch: Any) -> str:
    """Format audio channel configuration to standard notation.

    Args:
        ch: Channel count (can be string or int)

    Returns:
        Formatted channel string like "5.1", "2.0", "7.1"
    """
    if not ch:
        return ""

    ch = str(ch)

    channel_map = {
        "6": "5.1",
        "7": "6.1",
        "2": "2.0",
        "8": "7.1",
        "1": "1.0",
    }

    return channel_map.get(ch, ch)


def normalize_audio_codec_name(codec: Any, profile: Any = None) -> str:
    """Normalize raw audio codec values from APIs to display labels."""
    if codec is None:
        return "Unknown"

    raw_codec = str(codec).strip()
    if not raw_codec:
        return "Unknown"

    normalized_key = raw_codec.lower().replace("-", "_").replace(" ", "_")
    normalized_profile = (
        str(profile).strip().lower().replace("-", "_").replace(" ", "_") if profile else ""
    )
    codec_map = {
        "aac": "AAC",
        "ac3": "AC3",
        "eac3": "EAC3",
        "e_ac3": "EAC3",
        "dts": "DTS",
        "dca": "DTS",
        "dtshd": "DTS-HD",
        "dts_hd": "DTS-HD",
        "dtshd_ma": "DTS-HD MA",
        "dts_hd_ma": "DTS-HD MA",
        "dtshd_hra": "DTS-HD HRA",
        "dts_hd_hra": "DTS-HD HRA",
        "truehd": "TrueHD",
        "flac": "FLAC",
        "alac": "ALAC",
        "opus": "Opus",
        "vorbis": "Vorbis",
        "mp3": "MP3",
        "mp2": "MP2",
        "pcm": "PCM",
        "pcm_bluray": "PCM",
        "pcm_s16le": "PCM",
        "pcm_s24le": "PCM",
        "wmapro": "WMA Pro",
        "wmav2": "WMA v2",
    }

    profile_codec_map = {
        ("dca", "ma"): "DTS-HD MA",
        ("dca", "hra"): "DTS-HD HRA",
        ("dts", "ma"): "DTS-HD MA",
        ("dts", "hra"): "DTS-HD HRA",
        ("pcm", "bluray"): "PCM",
    }

    profile_match = profile_codec_map.get((normalized_key, normalized_profile))
    if profile_match:
        return profile_match

    if normalized_key in codec_map:
        return codec_map[normalized_key]

    token_map = {
        "hd": "HD",
        "ma": "MA",
        "hra": "HRA",
        "lc": "LC",
    }
    parts = []
    for part in normalized_key.split("_"):
        if not part:
            continue
        if part in token_map:
            parts.append(token_map[part])
        elif any(char.isdigit() for char in part) or len(part) <= 4:
            parts.append(part.upper())
        else:
            parts.append(part.capitalize())

    return " ".join(parts) if parts else "Unknown"


def format_audio_stream_label(codec: Any, channels: Any, profile: Any = None) -> str:
    """Format audio codec and channels for stream detail displays."""
    codec_text = normalize_audio_codec_name(codec, profile)
    channel_text = format_channels(channels)

    return f"{codec_text} {channel_text}".strip()


def format_transcoding_subtitle_line(
    action: str, language: str, codec: str, *, forced: bool = False
) -> str:
    """Format the subtitle line for the transcoding block."""
    line = f"**Subtitle:** {action} (`{language} - {codec}`)"
    if forced:
        line += " (`Forced`)"
    return line


def format_audio_direct_stream_line(codec: Any, channels: Any, profile: Any = None) -> str:
    """Format the audio direct stream line with codec and channel details."""
    return f"**Audio:** Direct Stream (`{format_audio_stream_label(codec, channels, profile)}`)"


def format_bitrate(bitrate_kbps: Optional[int]) -> str:
    """Format bitrate in kbps to human-readable format.

    Args:
        bitrate_kbps: Bitrate in kilobits per second

    Returns:
        Formatted string like "5.2 Mbps" or "2500 Kbps"
    """
    if not bitrate_kbps or bitrate_kbps <= 0:
        return ""

    if bitrate_kbps >= 1000:
        return f"{bitrate_kbps / 1000:.1f} Mbps"
    return f"{bitrate_kbps} Kbps"


# ISO 639 codes to display names. Jellyfin reports MediaStream.Language as a
# code ("deu"), while Plex hands us a readable name ("Deutsch") - without this
# the same information looked different depending on the platform.
#
# Both ISO 639-2 variants are listed where they differ: the bibliographic code
# ("ger") and the terminological one ("deu"). Files carry either, depending on
# the tool that muxed them. Two-letter ISO 639-1 codes are included because
# some remuxes use them.
_LANGUAGE_NAMES = {
    "ar": "Arabic",
    "ara": "Arabic",
    "bg": "Bulgarian",
    "bul": "Bulgarian",
    "cs": "Czech",
    "cze": "Czech",
    "ces": "Czech",
    "da": "Danish",
    "dan": "Danish",
    "de": "German",
    "ger": "German",
    "deu": "German",
    "el": "Greek",
    "gre": "Greek",
    "ell": "Greek",
    "en": "English",
    "eng": "English",
    "es": "Spanish",
    "spa": "Spanish",
    "et": "Estonian",
    "est": "Estonian",
    "fa": "Persian",
    "per": "Persian",
    "fas": "Persian",
    "fi": "Finnish",
    "fin": "Finnish",
    "fr": "French",
    "fre": "French",
    "fra": "French",
    "he": "Hebrew",
    "heb": "Hebrew",
    "hi": "Hindi",
    "hin": "Hindi",
    "hr": "Croatian",
    "hrv": "Croatian",
    "hu": "Hungarian",
    "hun": "Hungarian",
    "id": "Indonesian",
    "ind": "Indonesian",
    "is": "Icelandic",
    "ice": "Icelandic",
    "isl": "Icelandic",
    "it": "Italian",
    "ita": "Italian",
    "ja": "Japanese",
    "jpn": "Japanese",
    "ko": "Korean",
    "kor": "Korean",
    "lt": "Lithuanian",
    "lit": "Lithuanian",
    "lv": "Latvian",
    "lav": "Latvian",
    "nb": "Norwegian",
    "nob": "Norwegian",
    "nl": "Dutch",
    "dut": "Dutch",
    "nld": "Dutch",
    "no": "Norwegian",
    "nor": "Norwegian",
    "pl": "Polish",
    "pol": "Polish",
    "pt": "Portuguese",
    "por": "Portuguese",
    "ro": "Romanian",
    "rum": "Romanian",
    "ron": "Romanian",
    "ru": "Russian",
    "rus": "Russian",
    "sk": "Slovak",
    "slo": "Slovak",
    "slk": "Slovak",
    "sl": "Slovenian",
    "slv": "Slovenian",
    "sr": "Serbian",
    "srp": "Serbian",
    "sv": "Swedish",
    "swe": "Swedish",
    "th": "Thai",
    "tha": "Thai",
    "tr": "Turkish",
    "tur": "Turkish",
    "uk": "Ukrainian",
    "ukr": "Ukrainian",
    "vi": "Vietnamese",
    "vie": "Vietnamese",
    "zh": "Chinese",
    "chi": "Chinese",
    "zho": "Chinese",
    "af": "Afrikaans",
    "afr": "Afrikaans",
    "sq": "Albanian",
    "alb": "Albanian",
    "sqi": "Albanian",
    "am": "Amharic",
    "amh": "Amharic",
    "hy": "Armenian",
    "arm": "Armenian",
    "hye": "Armenian",
    "az": "Azerbaijani",
    "aze": "Azerbaijani",
    "eu": "Basque",
    "baq": "Basque",
    "eus": "Basque",
    "be": "Belarusian",
    "bel": "Belarusian",
    "bn": "Bengali",
    "ben": "Bengali",
    "bs": "Bosnian",
    "bos": "Bosnian",
    "my": "Burmese",
    "bur": "Burmese",
    "mya": "Burmese",
    "ca": "Catalan",
    "cat": "Catalan",
    "cy": "Welsh",
    "wel": "Welsh",
    "cym": "Welsh",
    "eo": "Esperanto",
    "epo": "Esperanto",
    "gl": "Galician",
    "glg": "Galician",
    "ka": "Georgian",
    "geo": "Georgian",
    "kat": "Georgian",
    "ga": "Irish",
    "gle": "Irish",
    "gu": "Gujarati",
    "guj": "Gujarati",
    "ha": "Hausa",
    "hau": "Hausa",
    "kk": "Kazakh",
    "kaz": "Kazakh",
    "km": "Khmer",
    "khm": "Khmer",
    "kn": "Kannada",
    "kan": "Kannada",
    "ku": "Kurdish",
    "kur": "Kurdish",
    "la": "Latin",
    "lat": "Latin",
    "lb": "Luxembourgish",
    "ltz": "Luxembourgish",
    "mk": "Macedonian",
    "mac": "Macedonian",
    "mkd": "Macedonian",
    "ml": "Malayalam",
    "mal": "Malayalam",
    "mn": "Mongolian",
    "mon": "Mongolian",
    "mr": "Marathi",
    "mar": "Marathi",
    "ms": "Malay",
    "may": "Malay",
    "msa": "Malay",
    "mt": "Maltese",
    "mlt": "Maltese",
    "ne": "Nepali",
    "nep": "Nepali",
    "nn": "Norwegian Nynorsk",
    "nno": "Norwegian Nynorsk",
    "pa": "Punjabi",
    "pan": "Punjabi",
    "ps": "Pashto",
    "pus": "Pashto",
    "si": "Sinhala",
    "sin": "Sinhala",
    "sw": "Swahili",
    "swa": "Swahili",
    "ta": "Tamil",
    "tam": "Tamil",
    "te": "Telugu",
    "tel": "Telugu",
    "tl": "Tagalog",
    "tgl": "Tagalog",
    "fil": "Filipino",
    "ur": "Urdu",
    "urd": "Urdu",
    "uz": "Uzbek",
    "uzb": "Uzbek",
    "yue": "Cantonese",
    "zu": "Zulu",
    "zul": "Zulu",
    "qaa": "Undetermined",
    "mul": "Multiple",
    "und": "Undetermined",
    "zxx": "No dialogue",
}


def format_language_name(value: Any, default: str = "Unknown") -> str:
    """Turn an ISO 639 language code into a readable name.

    Jellyfin reports `MediaStream.Language` as a code, Plex hands over a name
    already. Anything that is not a known code is passed through unchanged, so
    a name stays a name and an unmapped code is still shown rather than hidden.

    Args:
        value: Raw language value from the media server
        default: Returned when the value is empty or None

    Returns:
        A readable language name, the original value, or `default`
    """
    text = str(value).strip() if value is not None else ""
    if not text:
        return default
    return _LANGUAGE_NAMES.get(text.lower(), text)


def format_progress_bar(percent: float, width: int = 10, *, show_percent: bool = True) -> str:
    """Create a text-based progress bar.

    Args:
        percent: Progress percentage (0-100)
        width: Number of characters for the bar
        show_percent: Append the percentage. The stream details leave it off:
            their inline field is too narrow for bar and number on one line,
            and the time below already says how far along the stream is.

    Returns:
        String like "[▓▓▓▓▓░░░░░] 50.0%", or "[▓▓▓▓▓░░░░░]" without the percentage
    """
    # Plex reports view_offset_ms > duration_ms at the end of a stream and for
    # live content, which produced a negative `empty` and a bar wider than
    # `width` - that shifts every following line in the dashboard code block.
    percent = min(100.0, max(0.0, percent))
    filled = int(percent / (100 / width))
    empty = width - filled
    bar = f"[{'▓' * filled}{'░' * empty}]"
    return f"{bar} {percent:.1f}%" if show_percent else bar


def sanitize_code_block_text(value: Any, *, max_length: int = 100) -> str:
    """Make a media-server-provided string safe inside a Discord code block.

    Titles, usernames and player names are passed through from the media
    server, and some of them are freely chosen by the client (a Plex player
    picks its own ``X-Plex-Device-Name``). A backtick would close the code
    fence and let such a value inject markdown or links into the public
    dashboard; newlines would break the block layout; unbounded length pushes
    the field over Discord's 1024 character limit.

    Args:
        value: Raw value from the media server
        max_length: Maximum characters kept, the rest is replaced by an ellipsis

    Returns:
        Single-line text without backticks, at most ``max_length`` characters
    """
    text = " ".join(str("" if value is None else value).split()).replace("`", "'")
    if len(text) > max_length:
        text = text[: max_length - 1].rstrip() + "\u2026"
    return text


def join_within_limit(
    blocks: List[str],
    limit: int = DISCORD_FIELD_VALUE_LIMIT,
    separator: str = " ",
) -> Tuple[str, int]:
    """Join as many blocks as fit into ``limit`` characters.

    Discord rejects the whole embed when one field value exceeds 1024
    characters. In the dashboard loop that failure is only logged, so the
    dashboard would silently stop updating for as long as too many streams run.

    Args:
        blocks: Preformatted blocks, in display order
        limit: Maximum length of the joined value
        separator: Separator inserted between blocks

    Returns:
        Tuple of (joined value, number of blocks included)
    """
    parts: List[str] = []
    used = 0
    for block in blocks:
        cost = len(block) + (len(separator) if parts else 0)
        if used + cost > limit:
            break
        parts.append(block)
        used += cost

    if not parts and blocks and limit > 0:
        # A single oversized block still beats an empty dashboard section.
        return blocks[0][:limit], 1

    return separator.join(parts), len(parts)


def embed_field_budget(embed: Any, field_name: str, reserve: int = 0) -> int:
    """Return how many characters are left for one field value of ``embed``.

    Honours both Discord limits: 1024 per field value and 6000 for the whole
    embed. ``reserve`` keeps room for fields that are added afterwards.
    """
    available = DISCORD_EMBED_TOTAL_LIMIT - len(embed) - len(field_name) - reserve
    return max(0, min(DISCORD_FIELD_VALUE_LIMIT, available))


def format_stream_summary(stream: Any) -> str:
    """Format one active stream as the code block shown on the dashboard.

    Title, user name and player name come from the media server and are
    sanitized before they reach the block - see
    :func:`sanitize_code_block_text`.

    Args:
        stream: An :class:`~..models.ActiveStream`

    Returns:
        Discord markdown block describing the stream
    """
    content_emoji = {"track": "\U0001f3b5", "episode": "\U0001f4fa"}.get(
        stream.media_type.value, "\U0001f3a5"
    )

    if stream.is_paused:
        progress_display = "\u23f8\ufe0f"
    else:
        progress_display = format_progress_bar(stream.progress_percent)

    current_time = format_time_from_ms(stream.view_offset_ms, stream.duration_ms)
    total_time = format_time_from_ms(stream.duration_ms, stream.duration_ms)

    quality = sanitize_code_block_text(
        stream.video_resolution or stream.audio_quality or "Audio", max_length=20
    )
    transcode_emoji = "\U0001f504" if stream.is_transcoding else "\u23ef\ufe0f"
    bitrate = format_bitrate(stream.display_bitrate_kbps)

    title = sanitize_code_block_text(stream.get_formatted_title())
    username = sanitize_code_block_text(stream.username, max_length=40)
    player = sanitize_code_block_text(stream.player_name, max_length=40)

    return (
        f"**```{content_emoji} {title} | {username}\n"
        f"\u2514\u2500 {progress_display} | {current_time}/{total_time}\n"
        f" \u2514\u2500 {transcode_emoji} {quality} {bitrate} | {player}```**"
    )


def format_uptime(start_timestamp: Optional[float]) -> str:
    """Format server uptime from start timestamp.

    Args:
        start_timestamp: Unix timestamp when server started

    Returns:
        Formatted uptime string like "12:34" or "2 Days 05:30"
    """
    if not start_timestamp:
        return "Offline"

    total_minutes = int((time.time() - start_timestamp) / 60)
    days = total_minutes // 1440
    remaining_minutes = total_minutes % 1440
    hours = remaining_minutes // 60
    minutes = remaining_minutes % 60

    if days > 0:
        day_label = "Day" if days == 1 else "Days"
        return f"{days} {day_label} {hours:02d}:{minutes:02d}"

    return f"{hours:02d}:{minutes:02d}"


def format_number(number: int, use_dots: bool = True, separator: Optional[str] = None) -> str:
    """Format a number with thousand separators.

    The separator was hardcoded to a dot for both the dashboard and the
    presence, which reads as a decimal point to anyone outside the
    dot-grouping locales. `display.thousands_separator` now drives it.

    Args:
        number: The number to format
        use_dots: Legacy switch, kept for callers that predate `separator`
        separator: The thousands separator to use; overrides `use_dots`.
            An empty string groups nothing.

    Returns:
        Formatted string like "1.234.567", "1,234,567" or "1234567"
    """
    formatted = f"{number:,}"
    if separator is None:
        separator = "." if use_dots else ","
    if separator != ",":
        formatted = formatted.replace(",", separator)
    return formatted


def resolve_user_display_name(
    user_mapping: Any, *candidate_names: Any, fallback: str = "Unknown"
) -> str:
    """Resolve the best display name from mapped and raw username candidates."""
    cleaned_candidates = []
    for candidate in candidate_names:
        if candidate is None:
            continue

        candidate_text = str(candidate).strip()
        if candidate_text and candidate_text not in cleaned_candidates:
            cleaned_candidates.append(candidate_text)

    mapping = user_mapping if isinstance(user_mapping, dict) else {}

    # Tolerate a platform-keyed wrapper ({"plex": {...}, "jellyfin": {...}}).
    # A username -> display name mapping never has dict values, so nested
    # values are unambiguous. Unwrapping only the "plex" key would silently
    # treat every other wrapper as the mapping itself.
    if mapping and all(isinstance(value, dict) for value in mapping.values()):
        merged = {}
        for platform_mapping in mapping.values():
            merged.update(platform_mapping)
        mapping = merged

    for candidate in cleaned_candidates:
        mapped_name = mapping.get(candidate)
        if mapped_name is None:
            continue

        mapped_text = str(mapped_name).strip()
        if mapped_text:
            return mapped_text

    if cleaned_candidates:
        return cleaned_candidates[0]

    return fallback


def format_stats_time_range_label(time_range: Any) -> str:
    """Return a compact human-readable time range label for statistics views."""
    if time_range == "all":
        return "All time"

    try:
        days = int(time_range)
    except (TypeError, ValueError):
        return "All time"

    if days <= 0:
        return "All time"

    return f"Last {days} days"


def truncate_to_sentence_boundary(
    text: str,
    max_length: int = 300,
    hard_limit: int = 1024,
) -> str:
    """Truncate text at a sentence boundary, preferring the next period after a soft limit.

    The function keeps the text intact up to ``max_length`` and then extends to
    the next period. To stay within Discord embed limits, it falls back to the
    last period before ``hard_limit`` when necessary.

    Args:
        text: The text to truncate
        max_length: Preferred soft limit before looking for the next sentence end
        hard_limit: Absolute upper bound to avoid exceeding embed field limits

    Returns:
        Text ending at a sentence boundary when possible
    """
    normalized = text.strip()
    if len(normalized) <= max_length:
        return normalized

    next_period = normalized.find(".", max_length - 1)
    if next_period != -1 and next_period + 1 <= hard_limit:
        return normalized[: next_period + 1].rstrip()

    # Only fall back to an earlier sentence end if it keeps a useful amount of
    # text. "Dr. " at the start of a 2000 character summary would otherwise cut
    # the whole description down to "Dr.".
    fallback_period = normalized.rfind(".", 0, min(len(normalized), hard_limit))
    if fallback_period != -1 and fallback_period + 1 >= max_length // 2:
        return normalized[: fallback_period + 1].rstrip()

    return normalized[:hard_limit].rstrip()
