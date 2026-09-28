"""
Stream Embed Generator for Jellyfin integration.

This module contains functions to create detailed Discord embeds for Jellyfin streams,
including transcoding information, media details, and thumbnails.
"""

import discord
import io
import ipaddress
import logging
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple

from ...shared.embeds import create_stream_error_embed as _create_stream_error_embed
from ...shared.formatters import (
    format_language_name,
    format_audio_direct_stream_line,
    format_channels,
    format_progress_bar,
    format_resolution_from_dimensions,
    format_transcoding_subtitle_line,
    normalize_audio_codec_name,
    resolve_user_display_name,
    sanitize_code_block_text,
    truncate_to_sentence_boundary,
)


logger = logging.getLogger("mediawatch_bot.media_core.jellyfin.stream_embeds")

# Jellyfin item type -> (library collection type, fallback display name)
_LIBRARY_BY_MEDIA_TYPE = {
    "Episode": ("tvshows", "TV Shows"),
    "Audio": ("music", "Music"),
    "Movie": ("movies", "Movies"),
}


def _null_default(value: Any, default: str) -> str:
    """Return ``default`` when a key is missing *or* explicitly ``null``.

    ``dict.get(key, default)`` only covers the missing key. Jellyfin sends
    ``null`` for ``Container``, ``Codec`` and ``Language`` whenever it could not
    probe them, which used to blow up the whole detail embed on ``.upper()``.
    An empty string is kept as-is so nothing about the current output changes.
    """
    return default if value is None else str(value)


def _endpoint_host(remote_endpoint: Any) -> str:
    """Return the bare host of a Jellyfin ``RemoteEndPoint``.

    Handles the ``ip:port`` and ``[ipv6]:port`` shapes Jellyfin reports.
    """
    host = str(remote_endpoint or "").strip()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    if host.count(":") == 1:
        return host.split(":", 1)[0]
    return host


def _is_private_endpoint(remote_endpoint: Any) -> bool:
    """Return True when a Jellyfin ``RemoteEndPoint`` points into a local network.

    Anything unparsable counts as remote.
    """
    try:
        return ipaddress.ip_address(_endpoint_host(remote_endpoint)).is_private
    except ValueError:
        return False


def _select_active_subtitle_stream(
    play_state: Dict[str, Any],
    media_streams: list,
) -> Optional[Dict[str, Any]]:
    """Return the subtitle stream the viewer actually selected.

    ``PlayState.SubtitleStreamIndex`` is -1 (or absent) when subtitles are off;
    a default track in the file says nothing about what is on screen.
    """
    index = play_state.get("SubtitleStreamIndex")
    if not isinstance(index, int) or index < 0:
        return None
    return next(
        (s for s in media_streams if s.get("Type") == "Subtitle" and s.get("Index") == index),
        None,
    )


def create_stream_error_embed(
    jellyfin_core,
    description: str,
    *,
    title: str = "❌ Stream Details Unavailable",
    footer_text: str = "Jellyfin Stream Details",
) -> discord.Embed:
    """Create a styled error embed for Jellyfin stream detail failures."""
    return _create_stream_error_embed(
        jellyfin_core,
        description,
        platform_name="Jellyfin",
        title=title,
        footer_text=footer_text,
    )


async def create_detailed_stream_embed(
    session: Dict[str, Any],
    jellyfin_core,
    *,
    show_connection_ip: bool = False,
) -> Tuple[discord.Embed, Optional[discord.File]]:
    """Create a detailed embed with stream information from Jellyfin.

    Args:
        session: Jellyfin session dictionary
        jellyfin_core: JellyfinCore instance
        show_connection_ip: Include the client IP in the connection block

    Returns:
        Tuple of (embed, file) where file is the thumbnail or None
    """
    file = None
    try:
        if not session:
            raise ValueError("Session object is invalid")

        now_playing = session.get("NowPlayingItem", {})
        if not now_playing:
            raise ValueError("No media currently playing")

        user = session.get("UserName", "Unknown")
        displayed_user = resolve_user_display_name(jellyfin_core.user_mapping, user)

        media_type = now_playing.get("Type", "Movie")
        year = now_playing.get("ProductionYear", "")

        # Build title based on media type
        if media_type == "Episode":
            show_name = now_playing.get("SeriesName", "")
            season = int(now_playing.get("ParentIndexNumber") or 0)
            episode = int(now_playing.get("IndexNumber") or 0)
            episode_title = now_playing.get("Name", "")
            title = f"{show_name} - S{season:02d}E{episode:02d} - {episode_title}"
            emoji = "📺"
        elif media_type == "Audio":
            artists = now_playing.get("Artists") or []
            artist = now_playing.get("AlbumArtist") or (artists[0] if artists else "Unknown")
            track = now_playing.get("Name", "")
            title = f"{artist} - {track}"
            emoji = "🎵"
        else:  # Movie
            movie_title = now_playing.get("Name", "Unknown")
            title = f"{movie_title} ({year})" if year else movie_title
            emoji = "🎥"

        embed = discord.Embed(
            title=f"{emoji} {title}",
            # Brand color of the active platform; falls back to blue for callers
            # that do not carry a media service.
            color=getattr(
                getattr(jellyfin_core, "jellyfin_service", None),
                "embed_color",
                discord.Color.blue(),
            ),
            timestamp=discord.utils.utcnow(),
        )

        # Get thumbnail - use series poster for episodes, item poster for others
        if media_type == "Episode":
            item_id = now_playing.get("SeriesId") or now_playing.get("Id")
        else:
            item_id = now_playing.get("Id")

        if item_id:
            thumbnail_url = jellyfin_core.jellyfin_client.get_thumbnail_url(item_id, "Primary")
            if thumbnail_url:
                try:
                    # Download thumbnail
                    session_http = await jellyfin_core.jellyfin_client._get_session()
                    async with session_http.get(thumbnail_url) as response:
                        if response.status == 200:
                            image_data = await response.read()
                            file = discord.File(fp=io.BytesIO(image_data), filename="poster.jpg")
                            embed.set_thumbnail(url="attachment://poster.jpg")
                except Exception as e:
                    logger.warning(f"Failed to fetch thumbnail: {e}")

        # Add description for non-music content
        summary = now_playing.get("Overview", "")
        if summary and media_type != "Audio":
            summary = truncate_to_sentence_boundary(summary, max_length=300)
            embed.add_field(name="📝 Description", value=summary, inline=False)

        # Add metadata fields based on media type
        if media_type != "Audio":
            rating = now_playing.get("CommunityRating")
            has_rating = False
            if rating:
                try:
                    embed.add_field(
                        name="⭐ Rating", value=f"`{float(rating):.1f}/10`", inline=True
                    )
                    has_rating = True
                except (ValueError, TypeError):
                    pass

            if media_type == "Movie":
                fields_count = 1 if has_rating else 0

                # Get director from item details
                director_name = None
                item_id = now_playing.get("Id")
                user_id = session.get("UserId")

                if item_id and user_id:
                    try:
                        item_details = await jellyfin_core.jellyfin_client.get_item_details(
                            item_id, user_id
                        )
                        if item_details and "People" in item_details:
                            people = item_details.get("People", [])
                            directors = [
                                p.get("Name") for p in people if p.get("Type") == "Director"
                            ]
                            if directors:
                                director_name = directors[0]
                    except Exception as e:
                        logger.debug(f"Could not fetch director for movie {item_id}: {e}")

                if director_name:
                    embed.add_field(
                        name="🎬 Director",
                        value=f"`{sanitize_code_block_text(director_name)}`",
                        inline=True,
                    )
                else:
                    embed.add_field(name="🎬 Director", value="\u200b", inline=True)
                fields_count += 1

                # Fill to 3 columns
                while fields_count < 3:
                    embed.add_field(name="\u200b", value="\u200b", inline=True)
                    fields_count += 1

            elif media_type == "Episode":
                fields_count = 1 if has_rating else 0

                # Season title
                season_name = now_playing.get("SeasonName", "")
                if season_name:
                    embed.add_field(
                        name="📺 Season",
                        value=f"`{sanitize_code_block_text(season_name)}`",
                        inline=True,
                    )
                else:
                    embed.add_field(name="\u200b", value="\u200b", inline=True)
                fields_count += 1

                # Get writer from item details (fallback to director if no writer)
                writer_name = None
                item_id = now_playing.get("Id")
                user_id = session.get("UserId")

                if item_id and user_id:
                    try:
                        item_details = await jellyfin_core.jellyfin_client.get_item_details(
                            item_id, user_id
                        )
                        if item_details and "People" in item_details:
                            people = item_details.get("People", [])
                            writers = [p.get("Name") for p in people if p.get("Type") == "Writer"]
                            if writers:
                                writer_name = writers[0]
                            else:
                                # Fallback to director if no writer found
                                directors = [
                                    p.get("Name") for p in people if p.get("Type") == "Director"
                                ]
                                if directors:
                                    writer_name = directors[0]
                    except Exception as e:
                        logger.debug(f"Could not fetch writer for episode {item_id}: {e}")

                if writer_name:
                    embed.add_field(
                        name="✍️ Writer",
                        value=f"`{sanitize_code_block_text(writer_name)}`",
                        inline=True,
                    )
                else:
                    embed.add_field(name="\u200b", value="\u200b", inline=True)
                fields_count += 1

                while fields_count < 3:
                    embed.add_field(name="\u200b", value="\u200b", inline=True)
                    fields_count += 1

        # Player and library info
        play_state = session.get("PlayState", {})
        client = session.get("Client", "Unknown")
        device_name = session.get("DeviceName", "Unknown")
        player_name = f"{client} - {device_name}" if client != device_name else client

        # Get library name from the configured libraries instead of guessing
        collection_type, default_library_name = _LIBRARY_BY_MEDIA_TYPE.get(
            media_type, ("movies", "Movies")
        )
        library_name = await jellyfin_core.jellyfin_service.resolve_library_display_name(
            now_playing.get("Id", ""),
            collection_type,
            default_library_name,
            session.get("UserId"),
        )

        # These three carry server-provided text into a code block: a Jellyfin
        # client picks its own DeviceName, so a backtick would close the fence
        # and an overlong value would blow the 1024 character field limit.
        embed.add_field(
            name="👤 User", value=f"`{sanitize_code_block_text(displayed_user)}`", inline=True
        )
        embed.add_field(
            name="📱 Player", value=f"`{sanitize_code_block_text(player_name)}`", inline=True
        )
        embed.add_field(
            name="📚 Library", value=f"`{sanitize_code_block_text(library_name)}`", inline=True
        )

        # Progress and status
        position_ticks = play_state.get("PositionTicks") or 0
        runtime_ticks = now_playing.get("RunTimeTicks") or 0
        is_paused = play_state.get("IsPaused", False)

        state_emoji = "⏸️" if is_paused else "▶️"
        state_text = "Paused" if is_paused else "Playing"
        status_info = f"`{state_emoji} {state_text}`"

        # Connection info
        remote_endpoint = session.get("RemoteEndPoint")
        is_local = _is_private_endpoint(remote_endpoint)
        location_emoji = "🏠" if is_local else "🌐"
        location_text = "LAN" if is_local else "WAN"
        connection_info = f"`{location_emoji} {location_text}`"
        client_ip = _endpoint_host(remote_endpoint)
        if show_connection_ip and client_ip:
            connection_info += f"\n`📡 {client_ip}`"

        # Progress bar
        if runtime_ticks > 0:
            progress_percent = position_ticks / runtime_ticks * 100

            # Convert ticks to timedelta (10,000 ticks = 1 millisecond)
            current_time = str(timedelta(milliseconds=position_ticks // 10000)).split(".")[0]
            total_time = str(timedelta(milliseconds=runtime_ticks // 10000)).split(".")[0]

            if current_time.startswith("0:"):
                current_time = current_time[2:]
            if total_time.startswith("0:"):
                total_time = total_time[2:]

            progress_value = f"`{format_progress_bar(progress_percent, show_percent=False)}`\n`{current_time} / {total_time}`"
        else:
            progress_value = "`N/A`"

        embed.add_field(name="📊 Progress", value=progress_value, inline=True)
        embed.add_field(name="⏯️ Status", value=status_info, inline=True)
        embed.add_field(name="🌍 Connection", value=connection_info, inline=True)

        # Media stream info
        media_streams = now_playing.get("MediaStreams", [])
        media_sources = now_playing.get("MediaSources", [])

        # Get video resolution
        video_stream = next((s for s in media_streams if s.get("Type") == "Video"), None)
        resolution = "Unknown"
        if video_stream:
            resolution = format_resolution_from_dimensions(
                video_stream.get("Width") or 0,
                video_stream.get("Height") or 0,
            )

        # Get bitrate - try multiple sources
        bitrate = "Unknown"
        bitrate_val = 0

        # First try MediaSources
        if media_sources:
            bitrate_val = media_sources[0].get("Bitrate") or 0

        # Fallback to MediaStreams video bitrate
        if not bitrate_val and video_stream:
            bitrate_val = video_stream.get("BitRate") or 0

        # Fallback to NowPlayingItem
        if not bitrate_val:
            bitrate_val = now_playing.get("Bitrate") or 0

        if bitrate_val > 0:
            bitrate = f"{bitrate_val / 1000000:.1f} Mbps"

        # Get container and file size
        container = _null_default(now_playing.get("Container"), "Unknown").upper()

        if media_type == "Audio":
            audio_stream = next((s for s in media_streams if s.get("Type") == "Audio"), None)
            audio_bitrate = "Unknown"
            if audio_stream:
                audio_bitrate_val = audio_stream.get("BitRate") or 0
                if audio_bitrate_val > 0:
                    audio_bitrate = f"{audio_bitrate_val // 1000} kbps"

            embed.add_field(name="🎵 Audio Quality", value=f"`{audio_bitrate}`", inline=True)
            embed.add_field(name="📊 Bitrate", value=f"`{bitrate}`", inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)
        else:
            embed.add_field(name="📺 Resolution", value=f"`{resolution}`", inline=True)
            embed.add_field(name="📊 Bitrate", value=f"`{bitrate}`", inline=True)

            if media_sources:
                size = media_sources[0].get("Size") or 0
                if size > 0:
                    size_gb = size / (1024**3)
                    embed.add_field(
                        name="📁 File", value=f"`{size_gb:.2f} GB • {container}`", inline=True
                    )
                else:
                    embed.add_field(name="📁 Container", value=f"`{container}`", inline=True)
            else:
                embed.add_field(name="📁 Container", value=f"`{container}`", inline=True)

        # Transcoding info
        play_method = session.get("PlayState", {}).get("PlayMethod", "DirectPlay")
        transcode_info = session.get("TranscodingInfo")

        if transcode_info or play_method == "Transcode":
            transcode_text = []

            # Check if actually transcoding (not just remuxing)
            is_video_direct = transcode_info.get("IsVideoDirect", True) if transcode_info else True
            is_audio_direct = transcode_info.get("IsAudioDirect", True) if transcode_info else True

            # Jellyfin exposes no throttling state: TranscodeReasons says *why* the
            # server transcodes, not that playback is being slowed down.
            transcode_text.append("**Stream:** Transcode")

            # Container decision
            if transcode_info:
                transcode_container = _null_default(
                    transcode_info.get("Container"), "Unknown"
                ).upper()
                if (
                    transcode_container
                    and transcode_container != container
                    and transcode_container != "UNKNOWN"
                ):
                    transcode_text.append(
                        f"**Container:** Converting (`{container}` → `{transcode_container}`)"
                    )
                else:
                    transcode_text.append(f"**Container:** `{container}` (Direct Stream)")
            else:
                transcode_text.append(f"**Container:** `{container}` (Direct Stream)")

            # Video transcoding
            if video_stream:
                video_codec = _null_default(video_stream.get("Codec"), "Unknown").upper()

                # Normalize codec names to match Plex style
                if video_codec == "H264":
                    video_codec = "H264"
                elif video_codec in ["HEVC", "H265"]:
                    video_codec = "HEVC"

                if transcode_info and not is_video_direct:
                    transcode_video_codec = _null_default(
                        transcode_info.get("VideoCodec"), video_codec
                    ).upper()
                    if transcode_video_codec == "H264":
                        transcode_video_codec = "H264"
                    elif transcode_video_codec in ["HEVC", "H265"]:
                        transcode_video_codec = "HEVC"

                    is_hw = transcode_info.get("HardwareAccelerationType") is not None
                    hw_text = " (HW)" if is_hw else ""

                    transcode_height = transcode_info.get("Height") or video_stream.get("Height")
                    if transcode_height:
                        if transcode_height >= 2160:
                            transcode_res = "4K"
                        elif transcode_height >= 1080:
                            transcode_res = "1080p"
                        elif transcode_height >= 720:
                            transcode_res = "720p"
                        else:
                            transcode_res = f"{transcode_height}p"
                    else:
                        transcode_res = resolution

                    video_from = f"{video_codec} {resolution}".strip()
                    video_to = f"{transcode_video_codec}{hw_text} {transcode_res}".strip()
                    transcode_text.append(f"**Video:** Transcode (`{video_from}` → `{video_to}`)")
                else:
                    video_info = f"{video_codec} {resolution}".strip()
                    transcode_text.append(f"**Video:** Direct Stream (`{video_info}`)")

            # Audio transcoding
            audio_stream = next((s for s in media_streams if s.get("Type") == "Audio"), None)
            if audio_stream:
                audio_codec = normalize_audio_codec_name(
                    audio_stream.get("Codec"),
                    audio_stream.get("Profile"),
                )

                audio_channels = audio_stream.get("Channels", 2)
                audio_language = format_language_name(audio_stream.get("Language"), "")
                audio_profile = audio_stream.get("Profile")

                audio_ch = format_channels(audio_channels)

                if transcode_info and not is_audio_direct:
                    transcode_audio_codec = normalize_audio_codec_name(
                        transcode_info.get("AudioCodec") or audio_codec,
                        transcode_info.get("AudioProfile"),
                    )

                    transcode_channels = transcode_info.get("AudioChannels") or audio_channels
                    transcode_ch = format_channels(transcode_channels)

                    audio_from_parts = []
                    if audio_language:
                        audio_from_parts.append(audio_language)
                        audio_from_parts.append("-")
                    audio_from_parts.append(audio_codec)
                    if audio_ch:
                        audio_from_parts.append(audio_ch)
                    audio_from = " ".join(audio_from_parts)

                    audio_to = f"{transcode_audio_codec} {transcode_ch}".strip()
                    transcode_text.append(f"**Audio:** Transcode (`{audio_from}` → `{audio_to}`)")
                else:
                    transcode_text.append(
                        format_audio_direct_stream_line(
                            audio_stream.get("Codec") or audio_codec,
                            audio_channels,
                            audio_profile,
                        )
                    )

            # Subtitle info (only if transcoding)
            subtitle_stream = _select_active_subtitle_stream(play_state, media_streams)
            if subtitle_stream:
                sub_codec = _null_default(subtitle_stream.get("Codec"), "Unknown").upper()
                sub_lang = format_language_name(subtitle_stream.get("Language"))
                is_forced = bool(subtitle_stream.get("IsForced"))

                # Check if subtitle is being burned in (common during video transcode)
                if transcode_info and not is_video_direct:
                    # Jellyfin burns in subtitles when transcoding if they're not text-based
                    if sub_codec in ["DVDSUB", "PGSSUB", "VOBSUB"]:
                        transcode_text.append(
                            format_transcoding_subtitle_line(
                                "Burn",
                                sub_lang,
                                sub_codec,
                                forced=is_forced,
                            )
                        )
                    else:
                        transcode_text.append(
                            format_transcoding_subtitle_line(
                                "Direct Stream",
                                sub_lang,
                                sub_codec,
                                forced=is_forced,
                            )
                        )
                else:
                    transcode_text.append(
                        format_transcoding_subtitle_line(
                            "Direct Stream",
                            sub_lang,
                            sub_codec,
                            forced=is_forced,
                        )
                    )
            # No subtitle, nothing to add to transcode_text

            embed.add_field(
                name="🔄 Transcoding",
                value="\n".join(transcode_text) if transcode_text else "`Active`",
                inline=False,
            )
        else:
            # Direct Play
            embed.add_field(name="⏯️ Playback Mode", value="`Direct Play`", inline=True)

            # Audio language
            audio_stream = next((s for s in media_streams if s.get("Type") == "Audio"), None)
            if audio_stream:
                audio_language = format_language_name(audio_stream.get("Language"))
                embed.add_field(
                    name="🌐 Language",
                    value=f"`{sanitize_code_block_text(audio_language)}`",
                    inline=True,
                )
            else:
                embed.add_field(name="\u200b", value="\u200b", inline=True)

            # Subtitle info
            subtitle_stream = _select_active_subtitle_stream(play_state, media_streams)
            if subtitle_stream:
                sub_lang = format_language_name(subtitle_stream.get("Language"))
                sub_codec = _null_default(subtitle_stream.get("Codec"), "Unknown").upper()
                subtitle_text = f"{sub_lang} ({sub_codec})"
                embed.add_field(
                    name="📝 Subtitle",
                    value=f"`{sanitize_code_block_text(subtitle_text)}`",
                    inline=True,
                )
            else:
                embed.add_field(name="\u200b", value="\u200b", inline=True)

        # Footer: the viewer, like the Plex side. The media title is already
        # the embed title, repeating it in the footer said nothing new.
        dashboard_config = jellyfin_core.config.get("dashboard", {})
        embed.set_footer(text=displayed_user, icon_url=dashboard_config.get("footer_icon_url", ""))

        dashboard_name = dashboard_config.get("name", "Jellyfin Dashboard")
        icon_url = dashboard_config.get("icon_url", "")
        if icon_url:
            embed.set_author(name=dashboard_name, icon_url=icon_url)

        return embed, file

    except Exception as e:
        logger.error(f"Error creating detailed embed: {e}", exc_info=True)
        embed = create_stream_error_embed(
            jellyfin_core,
            "Unable to load stream details from Jellyfin right now. Please try again.",
            footer_text="Jellyfin Stream Details Error",
        )
        return embed, None
