"""
Stream Embed Generator for Plex integration.

This module contains functions to create detailed Discord embeds for Plex streams,
including full transcoding information, media details, and thumbnails.
"""

import discord
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ...shared.config_helper import StreamDetailsConfig
from ...shared.embeds import create_stream_error_embed as _create_stream_error_embed
from ..utils.links import build_plex_web_url, web_rating_key
from ...shared.formatters import (
    format_language_name,
    format_audio_direct_stream_line,
    format_bitrate,
    format_channels,
    format_progress_bar,
    format_resolution,
    format_transcoding_subtitle_line,
    normalize_audio_codec_name,
    resolve_user_display_name,
    sanitize_code_block_text,
    truncate_to_sentence_boundary,
)


logger = logging.getLogger("mediawatch_bot.media_core.plex.stream_embeds")


def _normalize_detail_value(value: Any, *, fallback: str = "Unknown") -> str:
    """Return a non-empty display value for embed fields."""
    if value is None:
        return fallback

    text = str(value).strip()
    return text or fallback


def _null_default(value: Any, default: str) -> str:
    """Return ``default`` when a key is missing *or* explicitly ``null``.

    ``dict.get(key, default)`` only covers the missing key. Tautulli currently
    reports unknown fields as "" rather than null, so an empty string keeps its
    current behaviour here and only the null case is hardened - unlike
    :func:`_normalize_detail_value`, which also replaces empty values.
    """
    return default if value is None else str(value)


def _plex_web_url(plex_core, session) -> Optional[str]:
    """Return the Plex Web link for the played item, or ``None``."""
    config = StreamDetailsConfig(getattr(plex_core, "config", None) or {})
    if not config.link_enabled("plex"):
        return None

    return build_plex_web_url(
        getattr(getattr(plex_core, "plex", None), "machineIdentifier", None),
        web_rating_key(session),
        config.link_base_url("plex"),
    )


def create_stream_error_embed(
    plex_core,
    description: str,
    *,
    title: str = "❌ Stream Details Unavailable",
    footer_text: str = "Plex Stream Details",
) -> discord.Embed:
    """Create a styled error embed for Plex stream detail failures."""
    return _create_stream_error_embed(
        plex_core,
        description,
        platform_name="Plex",
        title=title,
        footer_text=footer_text,
    )


def _format_connection_info(
    location: Any,
    secure: Any,
    relay: Any,
    *,
    ip_address: Any = None,
    show_ip_address: bool = False,
) -> str:
    """Format the connection block, optionally including the client IP."""
    location_text_raw = str(location or "").strip().lower()
    is_lan = location_text_raw == "lan"
    secure_enabled = bool(secure)
    relay_enabled = bool(relay)

    location_emoji = "🏠" if is_lan else "🌐"
    location_text = "LAN" if is_lan else "WAN"
    secure_emoji = "🔒" if secure_enabled else "🔓"
    relay_text = " 🔀" if relay_enabled else ""

    lines = [f"`{location_emoji} {location_text} {secure_emoji}{relay_text}`"]

    ip_text = str(ip_address or "").strip()
    if show_ip_address and ip_text:
        lines.append(f"`📡 {ip_text}`")

    return "\n".join(lines)


def _format_dynamic_range_label(tautulli_data: Dict[str, Any]) -> str:
    """Format HDR/Dolby Vision flags using Tautulli session fields."""
    raw_values = [
        tautulli_data.get("stream_video_dynamic_range"),
        tautulli_data.get("video_dynamic_range"),
    ]
    normalized_values = [
        str(value).strip().lower() for value in raw_values if str(value or "").strip()
    ]

    labels: List[str] = []

    def add_label(label: str) -> None:
        if label not in labels:
            labels.append(label)

    for value in normalized_values:
        if value == "sdr":
            continue
        has_hdr10_plus = "hdr10+" in value
        has_hdr10 = "hdr10" in value
        has_generic_hdr = "hdr" in value

        if has_hdr10_plus:
            add_label("HDR10+")
        elif has_hdr10:
            add_label("HDR10")
        elif has_generic_hdr:
            add_label("HDR")
        if "hlg" in value:
            add_label("HLG")
        if "dolby vision" in value or "dovi" in value:
            add_label("DoVi")

    dovi_keys = (
        "stream_video_dovi_present",
        "video_dovi_present",
        "stream_video_dovi",
        "video_dovi",
    )
    if any(
        str(tautulli_data.get(key, "")).strip().lower() in {"1", "true", "yes"} for key in dovi_keys
    ):
        add_label("DoVi")

    return "/".join(labels)


def _get_display_timezone():
    """Resolve the timezone used for stream clock displays."""
    tz_name = os.getenv("TZ", "").strip()
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            logger.warning("Invalid TZ value %r; falling back to UTC for stream timing.", tz_name)
    return timezone.utc


def _parse_session_started(raw_started: Any, display_tz) -> Optional[datetime]:
    """Parse Tautulli's session start value into a local datetime.

    Tautulli commonly returns epoch seconds as a string, but this parser is
    intentionally tolerant so the embed does not break on format changes.
    """
    if raw_started in (None, ""):
        return None

    if isinstance(raw_started, (int, float)):
        timestamp = float(raw_started)
    else:
        raw_text = str(raw_started).strip()

        try:
            timestamp = float(raw_text)
        except ValueError:
            timestamp = None

        if timestamp is None:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return datetime.strptime(raw_text, fmt).replace(tzinfo=display_tz)
                except ValueError:
                    continue

            try:
                return datetime.fromisoformat(raw_text.replace("Z", "+00:00")).astimezone(
                    display_tz
                )
            except ValueError:
                return None

    if timestamp > 1_000_000_000_000:
        timestamp /= 1000

    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(display_tz)
    except (OverflowError, OSError, ValueError):
        return None


def _format_clock_time(value: Optional[datetime]) -> Optional[str]:
    """Return a compact HH:MM display string."""
    if value is None:
        return None
    return value.strftime("%H:%M")


def _build_timing_row(
    started_at: Optional[datetime],
    duration_ms: int,
    view_offset_ms: int,
    now: Optional[datetime] = None,
) -> Optional[str]:
    """Build the compact third timing row for the progress block."""
    parts = []
    now = now or datetime.now(timezone.utc)

    if started_at is None and view_offset_ms > 0:
        started_at = now - timedelta(milliseconds=view_offset_ms)

    start_text = _format_clock_time(started_at)
    if start_text:
        parts.append(f"▶ {start_text}")

    if duration_ms > 0:
        remaining_ms = max(duration_ms - view_offset_ms, 0)
        end_text = _format_clock_time(now + timedelta(milliseconds=remaining_ms))
        if end_text:
            parts.append(f"■ {end_text}")

    return " | ".join(parts) if parts else None


async def create_detailed_stream_embed(
    session,
    plex_core,
    tautulli_client,
    *,
    show_connection_ip: bool = False,
) -> Tuple[discord.Embed, Optional[discord.File | List[discord.File]]]:
    """Create a detailed embed with stream information from Tautulli.

    Returns:
        Tuple of (embed, attachment payload) where the payload is either a
        single file, a file list, or None.
    """
    attachments: List[discord.File] = []
    try:
        if not session or not hasattr(session, "sessionKey"):
            raise ValueError("Session object is invalid")

        tautulli_data = await tautulli_client.fetch_session(str(session.sessionKey))
        if not tautulli_data:
            raise ValueError("Could not fetch data from Tautulli")

        user = (
            session.usernames[0]
            if hasattr(session, "usernames") and session.usernames
            else "Unknown"
        )
        displayed_user = resolve_user_display_name(
            getattr(plex_core, "user_mapping", {}),
            user,
        )

        media_type = tautulli_data.get("media_type", "movie")
        year = tautulli_data.get("year", "")

        if media_type == "episode":
            show_name = tautulli_data.get("grandparent_title", "")
            season = int(tautulli_data.get("parent_media_index") or 0)
            episode = int(tautulli_data.get("media_index") or 0)
            episode_title = tautulli_data.get("title", "")
            title = f"{show_name} - S{season:02d}E{episode:02d} - {episode_title}"
            emoji = "📺"
        elif media_type == "track":
            artist = tautulli_data.get("grandparent_title", "")
            track = tautulli_data.get("title", "")
            title = f"{artist} - {track}"
            emoji = "🎵"
        else:
            movie_title = tautulli_data.get("title", "Unknown")
            title = f"{movie_title} ({year})" if year else movie_title
            emoji = "🎥"

        section_title = _null_default(tautulli_data.get("library_name"), "Unknown")

        embed = discord.Embed(
            title=f"{emoji} {title}",
            # The title links where the Plex button does. Turning the button off
            # turns the link off too, otherwise the switch would be a half truth.
            url=_plex_web_url(plex_core, session),
            # Brand color of the active platform; falls back to blue for callers
            # that do not carry a media service.
            color=getattr(
                getattr(plex_core, "plex_service", None), "embed_color", discord.Color.blue()
            ),
            timestamp=discord.utils.utcnow(),
        )

        thumbnail_file = await tautulli_client.get_thumbnail(tautulli_data)
        if (
            not thumbnail_file
            and hasattr(plex_core, "stream_service")
            and hasattr(plex_core.stream_service, "get_stream_thumbnail_file")
        ):
            thumbnail_file = await plex_core.stream_service.get_stream_thumbnail_file(session)

        if thumbnail_file:
            attachments.append(thumbnail_file)
            embed.set_thumbnail(url=f"attachment://{thumbnail_file.filename}")

        summary = tautulli_data.get("summary", "")
        if summary and media_type != "track":
            summary = truncate_to_sentence_boundary(summary, max_length=300)
            embed.add_field(name="📝 Description", value=summary, inline=False)

        if media_type != "track":
            rating = tautulli_data.get("rating")
            has_rating = False
            if rating:
                try:
                    embed.add_field(
                        name="⭐ Rating", value=f"`{float(rating):.1f}/10`", inline=True
                    )
                    has_rating = True
                except (ValueError, TypeError):
                    pass

            if media_type == "movie":
                fields_count = 1 if has_rating else 0

                directors = tautulli_data.get("directors", [])
                if directors:
                    director = (
                        directors[0]
                        if isinstance(directors, list)
                        else directors.split(",")[0].strip()
                    )
                    embed.add_field(
                        name="🎬 Director",
                        value=f"`{sanitize_code_block_text(director)}`",
                        inline=True,
                    )
                else:
                    embed.add_field(name="🎬 Director", value="\u200b", inline=True)
                fields_count += 1

                while fields_count < 3:
                    embed.add_field(name="\u200b", value="\u200b", inline=True)
                    fields_count += 1
            elif media_type == "episode":
                fields_count = 1 if has_rating else 0

                season_title = tautulli_data.get("parent_title", "")
                if season_title:
                    embed.add_field(
                        name="📺 Season",
                        value=f"`{sanitize_code_block_text(season_title)}`",
                        inline=True,
                    )
                else:
                    embed.add_field(name="\u200b", value="\u200b", inline=True)
                fields_count += 1

                writers = tautulli_data.get("writers", [])
                if writers:
                    writer = (
                        writers[0] if isinstance(writers, list) else writers.split(",")[0].strip()
                    )
                    embed.add_field(
                        name="✍️ Writer",
                        value=f"`{sanitize_code_block_text(writer)}`",
                        inline=True,
                    )
                else:
                    embed.add_field(name="\u200b", value="\u200b", inline=True)
                fields_count += 1

                while fields_count < 3:
                    embed.add_field(name="\u200b", value="\u200b", inline=True)
                    fields_count += 1

        player_name = _null_default(tautulli_data.get("player"), "Unknown")
        product_name = _null_default(tautulli_data.get("product"), "") or player_name
        product_name = product_name.replace("Plex for ", "").replace("Infuse-Library", "Infuse")
        player_value = player_name
        if product_name and product_name.lower() != player_name.lower():
            player_value += f" ({product_name})"

        # These three carry server-provided text into a code block: a Plex
        # client picks its own X-Plex-Device-Name, so a backtick would close the
        # fence and an overlong value would blow the 1024 character field limit.
        embed.add_field(
            name="👤 User", value=f"`{sanitize_code_block_text(displayed_user)}`", inline=True
        )
        embed.add_field(
            name="📱 Player", value=f"`{sanitize_code_block_text(player_value)}`", inline=True
        )
        embed.add_field(
            name="📚 Library", value=f"`{sanitize_code_block_text(section_title)}`", inline=True
        )

        view_offset = int(tautulli_data.get("view_offset", 0) or 0)
        duration = int(tautulli_data.get("duration", 0) or 0)

        location = tautulli_data.get("location", "")
        secure = tautulli_data.get("secure", 0)
        relay = tautulli_data.get("relay", 0)
        state = _null_default(tautulli_data.get("state"), "playing")

        state_emoji = "▶️" if state == "playing" else ("⏸️" if state == "paused" else "⏳")
        state_text = state.capitalize()
        status_info = f"`{state_emoji} {state_text}`"

        connection_info = _format_connection_info(
            location,
            secure,
            relay,
            ip_address=tautulli_data.get("ip_address"),
            show_ip_address=show_connection_ip,
        )

        display_tz = _get_display_timezone()
        now = datetime.now(display_tz)
        started_at = _parse_session_started(tautulli_data.get("started"), display_tz)
        if started_at is None:
            started_at = _parse_session_started(tautulli_data.get("date"), display_tz)
        timing_row = _build_timing_row(started_at, duration, view_offset, now=now)

        if duration > 0:
            progress_percent = view_offset / duration * 100

            current_time = str(timedelta(milliseconds=view_offset)).split(".")[0]
            total_time = str(timedelta(milliseconds=duration)).split(".")[0]

            if current_time.startswith("0:"):
                current_time = current_time[2:]
            if total_time.startswith("0:"):
                total_time = total_time[2:]

            progress_value = f"`{format_progress_bar(progress_percent, show_percent=False)}`\n`{current_time} / {total_time}`"
        else:
            progress_value = "`N/A`"

        if timing_row:
            status_info += f"\n`{timing_row}`"

        embed.add_field(name="📊 Progress", value=progress_value, inline=True)
        embed.add_field(name="⏯️ Status", value=status_info, inline=True)
        embed.add_field(name="🌍 Connection", value=connection_info, inline=True)

        resolution = tautulli_data.get("video_resolution", "Unknown")

        resolution = format_resolution(resolution)
        dynamic_range = _format_dynamic_range_label(tautulli_data)
        resolution_value = resolution if not dynamic_range else f"{resolution} • {dynamic_range}"

        try:
            bitrate_value = int(tautulli_data.get("bitrate", 0) or 0)
        except (TypeError, ValueError):
            bitrate_value = 0

        try:
            bandwidth_value = int(tautulli_data.get("bandwidth", 0) or 0)
        except (TypeError, ValueError):
            bandwidth_value = 0

        bitrate = format_bitrate(bitrate_value) or "Unknown"
        bandwidth = format_bitrate(bandwidth_value)
        if bandwidth:
            # Drop the first unit only when both values already share it,
            # otherwise "800 Kbps" would be rendered as "800" next to "5.0 Mbps".
            if bitrate.endswith(bandwidth.rsplit(" ", 1)[-1]):
                bitrate = bitrate.rsplit(" ", 1)[0]
            bitrate = f"{bitrate} / {bandwidth}"

        file_size = tautulli_data.get("file_size", 0)
        container = _null_default(tautulli_data.get("container"), "Unknown").upper()

        if media_type == "track":
            audio_bitrate = _null_default(tautulli_data.get("audio_bitrate"), "Unknown")
            embed.add_field(name="🎵 Audio Quality", value=f"`{audio_bitrate} kbps`", inline=True)
            embed.add_field(name="📊 Bitrate", value=f"`{bitrate}`", inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)
        else:
            embed.add_field(name="📺 Resolution", value=f"`{resolution_value}`", inline=True)
            embed.add_field(name="📊 Bitrate", value=f"`{bitrate}`", inline=True)
            if file_size:
                try:
                    size_gb = int(file_size) / (1024**3)
                    embed.add_field(
                        name="📁 File", value=f"`{size_gb:.2f} GB • {container}`", inline=True
                    )
                except (ValueError, TypeError):
                    embed.add_field(name="📁 Container", value=f"`{container}`", inline=True)
            else:
                embed.add_field(name="📁 Container", value=f"`{container}`", inline=True)

        transcode_text = []
        is_transcoding = tautulli_data.get("transcode_decision") == "transcode"

        is_throttled = tautulli_data.get("transcode_throttled", 0)
        throttled_text = " (`Throttled`)" if is_throttled else ""

        if is_transcoding:
            hw_decode = tautulli_data.get("transcode_hw_decoding", 0)
            hw_encode = tautulli_data.get("transcode_hw_encoding", 0)
            hw_text = " (HW)" if (hw_decode or hw_encode) else ""

            transcode_text.append(f"**Stream:** Transcode{throttled_text}")

            stream_container = _null_default(
                tautulli_data.get("stream_container"), "Unknown"
            ).upper()
            container_decision = tautulli_data.get("stream_container_decision", "copy")

            if container_decision == "transcode":
                transcode_text.append(
                    f"**Container:** Converting (`{container}` → `{stream_container}`)"
                )
            else:
                transcode_text.append(f"**Container:** `{container}` (Direct Stream)")

            video_codec = _null_default(tautulli_data.get("video_codec"), "Unknown").upper()
            stream_video_codec = _null_default(
                tautulli_data.get("stream_video_codec"), "Unknown"
            ).upper()
            video_resolution = tautulli_data.get("video_resolution", "")
            stream_video_resolution = tautulli_data.get("stream_video_resolution", "")
            video_decision = tautulli_data.get("stream_video_decision", "copy")

            video_resolution = format_resolution(video_resolution)
            stream_video_resolution = format_resolution(stream_video_resolution)

            if video_decision == "transcode":
                video_from = f"{video_codec}{hw_text} {video_resolution}".strip()
                video_to = f"{stream_video_codec}{hw_text} {stream_video_resolution}".strip()
                transcode_text.append(f"**Video:** Transcode (`{video_from}` → `{video_to}`)")
            else:
                video_info = f"{video_codec} {video_resolution}".strip()
                transcode_text.append(f"**Video:** Direct Stream (`{video_info}`)")

            audio_codec = normalize_audio_codec_name(
                tautulli_data.get("audio_codec"),
                tautulli_data.get("audio_profile"),
            )
            stream_audio_codec = normalize_audio_codec_name(
                tautulli_data.get("stream_audio_codec"),
                tautulli_data.get("stream_audio_profile"),
            )
            audio_language = format_language_name(tautulli_data.get("audio_language"), "")
            audio_channels = tautulli_data.get("audio_channels", "")
            stream_audio_channels = tautulli_data.get("stream_audio_channels", "")
            audio_profile = tautulli_data.get("audio_profile", "")
            stream_audio_profile = tautulli_data.get("stream_audio_profile", "")
            audio_decision = tautulli_data.get("stream_audio_decision", "copy")

            audio_ch = format_channels(audio_channels)
            stream_audio_ch = format_channels(stream_audio_channels)

            if audio_decision == "transcode":
                audio_from_parts = []
                if audio_language:
                    audio_from_parts.append(audio_language)
                    audio_from_parts.append("-")
                audio_from_parts.append(audio_codec)
                if audio_ch:
                    audio_from_parts.append(audio_ch)
                audio_from = " ".join(audio_from_parts)

                audio_to_parts = [stream_audio_codec]
                if stream_audio_ch:
                    audio_to_parts.append(stream_audio_ch)
                audio_to = " ".join(audio_to_parts)

                transcode_text.append(f"**Audio:** Transcode (`{audio_from}` → `{audio_to}`)")
            else:
                transcode_text.append(
                    format_audio_direct_stream_line(
                        tautulli_data.get("stream_audio_codec") or tautulli_data.get("audio_codec"),
                        stream_audio_channels or audio_channels,
                        stream_audio_profile or audio_profile,
                    )
                )

            speed = tautulli_data.get("transcode_speed")
            if speed:
                try:
                    speed_float = float(speed)
                    if speed_float > 0.0:
                        transcode_text.append(f"**Speed:** `{speed_float:.1f}x`")
                except (ValueError, TypeError):
                    pass

        sub_decision = tautulli_data.get("stream_subtitle_decision")
        subtitle_text = None

        if sub_decision and sub_decision not in ["none", ""]:
            sub_lang = format_language_name(tautulli_data.get("subtitle_language"))
            sub_codec = _normalize_detail_value(tautulli_data.get("subtitle_codec")).upper()
            is_forced = bool(tautulli_data.get("subtitle_forced"))

            if sub_decision == "burn":
                subtitle_text = f"Burn ({sub_lang} - {sub_codec})" + (
                    " (Forced)" if is_forced else ""
                )
            elif sub_decision == "transcode":
                subtitle_text = f"Converting ({sub_lang} - {sub_codec})" + (
                    " (Forced)" if is_forced else ""
                )
            else:
                subtitle_text = f"{sub_lang} ({sub_codec})" + (" (Forced)" if is_forced else "")

            if is_transcoding:
                subtitle_action = (
                    "Burn"
                    if sub_decision == "burn"
                    else "Converting"
                    if sub_decision == "transcode"
                    else "Direct Stream"
                )
                transcode_text.append(
                    format_transcoding_subtitle_line(
                        subtitle_action,
                        sub_lang,
                        sub_codec,
                        forced=is_forced,
                    )
                )
        else:
            pass  # No subtitle, nothing to add to transcode_text

        if is_transcoding:
            embed.add_field(
                name="🔄 Transcoding",
                value="\n".join(transcode_text) if transcode_text else "`Active`",
                inline=False,
            )
        else:
            embed.add_field(name="⏯️ Playback Mode", value="`Direct Play`", inline=True)

            language_value = format_language_name(tautulli_data.get("audio_language"))
            embed.add_field(
                name="🌐 Language",
                value=f"`{sanitize_code_block_text(language_value)}`",
                inline=True,
            )

            if subtitle_text:
                embed.add_field(
                    name="📝 Subtitle",
                    value=f"`{sanitize_code_block_text(subtitle_text)}`",
                    inline=True,
                )
            else:
                embed.add_field(name="\u200b", value="\u200b", inline=True)

        dashboard_config = plex_core.config.get("dashboard", {})
        footer_icon = dashboard_config.get("footer_icon_url", "")
        footer_icon_url = footer_icon or None
        # The avatar is fetched here and attached, never linked. Tautulli hands
        # out image URLs that can carry its API key (pms_image_proxy takes
        # `apikey` as a query parameter), and an embed URL is fetched by
        # Discord and by every client that renders the message. Falling back to
        # the raw URL when the download fails would leak exactly that, so the
        # fallback is the configured icon or nothing.
        user_thumb = str(tautulli_data.get("user_thumb") or "").strip()
        if user_thumb and hasattr(tautulli_client, "get_cached_user_thumb_file"):
            user_thumb_file = await tautulli_client.get_cached_user_thumb_file(user_thumb)
            if user_thumb_file:
                attachments.append(user_thumb_file)
                footer_icon_url = f"attachment://{user_thumb_file.filename}"
        embed.set_footer(text=displayed_user, icon_url=footer_icon_url)

        dashboard_name = dashboard_config.get("name", "Plex Dashboard")
        icon_url = dashboard_config.get("icon_url", "")
        if icon_url:
            embed.set_author(name=dashboard_name, icon_url=icon_url)

        if not attachments:
            return embed, None
        if len(attachments) == 1:
            return embed, attachments[0]
        return embed, attachments

    except Exception as e:
        logger.error(f"Error creating detailed embed: {e}", exc_info=True)
        embed = create_stream_error_embed(
            plex_core,
            "Unable to load stream details from Tautulli right now. Please try again.",
            footer_text="Tautulli Stream Details Error",
        )
        return embed, None
