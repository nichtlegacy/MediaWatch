"""
Additional statistics utility functions for user statistics feature.

This module contains helper functions for calculating content type breakdown,
formatting recent activity, and other user statistics calculations.

Note: This feature requires Tautulli to be configured and enabled.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional


def filter_history_by_time_range(history: List[Dict[str, Any]], days: int) -> List[Dict[str, Any]]:
    """Filter history entries to only include those within the specified time range.

    Args:
        history: List of playback history entries from Tautulli
        days: Number of days to include (0 = no filter, returns all)

    Returns:
        Filtered list of history entries
    """
    if not history or days == 0:
        return history

    cutoff_timestamp = int((datetime.now() - timedelta(days=days)).timestamp())

    return [item for item in history if int(item.get("date", 0)) >= cutoff_timestamp]


def calculate_content_type_breakdown(history: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """Calculate breakdown of watch time and plays by content type.

    Args:
        history: List of playback history entries from Tautulli

    Returns:
        Dictionary with content types as keys and their stats (plays, time, percentage)
    """
    if not history:
        return {}

    breakdown = {
        "tv": {"plays": 0, "time": 0},
        "movie": {"plays": 0, "time": 0},
        "music": {"plays": 0, "time": 0},
    }

    total_plays = 0

    for item in history:
        media_type = item.get("media_type", "")
        duration = item.get("duration", 0) or 0

        if media_type == "episode":
            breakdown["tv"]["plays"] += 1
            breakdown["tv"]["time"] += duration
            total_plays += 1
        elif media_type == "movie":
            breakdown["movie"]["plays"] += 1
            breakdown["movie"]["time"] += duration
            total_plays += 1
        elif media_type == "track":
            breakdown["music"]["plays"] += 1
            breakdown["music"]["time"] += duration
            total_plays += 1

    # Remove types with 0 plays (dynamic hiding)
    breakdown = {k: v for k, v in breakdown.items() if v["plays"] > 0}

    # Calculate percentages
    if total_plays > 0:
        for content_type in breakdown:
            breakdown[content_type]["percentage"] = (
                breakdown[content_type]["plays"] / total_plays
            ) * 100

    return breakdown


def calculate_avg_session_length(total_time: int, total_plays: int) -> int:
    """Calculate average session length from total time and plays.

    Args:
        total_time: Total watch time in seconds
        total_plays: Total number of plays

    Returns:
        Average session length in seconds
    """
    if total_plays == 0:
        return 0
    return total_time // total_plays


def calculate_top_shows(history: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
    """Calculate top watched TV shows from user history.

    Since Tautulli's get_home_stats with user_id returns empty rows,
    we calculate top shows from the user's playback history.

    Args:
        history: List of playback history entries from Tautulli
        limit: Maximum number of shows to return

    Returns:
        List of top shows with title, plays, and duration
    """
    if not history:
        return []

    # Aggregate by show (grandparent_title for episodes)
    shows = {}

    for item in history:
        media_type = item.get("media_type", "")

        # Only count TV episodes
        if media_type == "episode":
            show_title = item.get("grandparent_title", "")
            if not show_title:
                continue

            duration = item.get("duration", 0) or 0

            if show_title not in shows:
                shows[show_title] = {"title": show_title, "total_plays": 0, "total_duration": 0}

            shows[show_title]["total_plays"] += 1
            shows[show_title]["total_duration"] += duration

    # Filter out shows with only 1 play (not meaningful for top shows)
    meaningful_shows = {k: v for k, v in shows.items() if v["total_plays"] >= 2}

    # Sort by plays (descending) and take top N
    sorted_shows = sorted(meaningful_shows.values(), key=lambda x: x["total_plays"], reverse=True)[
        :limit
    ]

    return sorted_shows


def calculate_peak_hour(history: List[Dict[str, Any]]) -> Optional[Dict[str, int]]:
    """Calculate hour with most plays from history."""
    if not history:
        return None

    hourly_counts: Dict[int, int] = {}

    for item in history:
        date_str = item.get("date", 0)
        if not date_str:
            continue

        try:
            play_date = datetime.fromtimestamp(int(date_str))
        except (ValueError, TypeError):
            continue

        hour = play_date.hour
        hourly_counts[hour] = hourly_counts.get(hour, 0) + 1

    if not hourly_counts:
        return None

    peak_hour = max(hourly_counts.items(), key=lambda entry: entry[1])
    return {"hour": peak_hour[0], "count": peak_hour[1]}


def calculate_most_active_day(history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Calculate weekday with most plays from history."""
    if not history:
        return None

    daily_counts: Dict[str, int] = {}

    for item in history:
        date_str = item.get("date", 0)
        if not date_str:
            continue

        try:
            play_date = datetime.fromtimestamp(int(date_str))
        except (ValueError, TypeError):
            continue

        day_name = play_date.strftime("%A")
        daily_counts[day_name] = daily_counts.get(day_name, 0) + 1

    if not daily_counts:
        return None

    most_active_day = max(daily_counts.items(), key=lambda entry: entry[1])
    return {"day": most_active_day[0], "count": most_active_day[1]}


def calculate_most_active_device(player_stats: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Calculate device with most watch time."""
    if not player_stats:
        return None

    best_device: Optional[Dict[str, Any]] = None

    for player in player_stats:
        total_time = (
            player.get("total_time", 0)
            or player.get("total_duration", 0)
            or player.get("duration", 0)
            or 0
        )
        total_plays = (
            player.get("total_plays", 0) or player.get("plays", 0) or player.get("count", 0) or 0
        )
        device_name = (
            player.get("player_name")
            or player.get("platform")
            or player.get("product")
            or "Unknown"
        )

        if total_time <= 0 and total_plays <= 0:
            continue

        candidate = {
            "name": device_name,
            "total_time": total_time,
            "total_plays": total_plays,
        }

        if best_device is None or (
            candidate["total_time"],
            candidate["total_plays"],
        ) > (
            best_device["total_time"],
            best_device["total_plays"],
        ):
            best_device = candidate

    return best_device


def calculate_top_content_type(
    content_breakdown: Dict[str, Dict[str, int]],
) -> Optional[Dict[str, Any]]:
    """Calculate most-used content type by watch time."""
    if not content_breakdown:
        return None

    type_names = {
        "tv": "TV Shows",
        "movie": "Movies",
        "music": "Music",
    }

    best_type: Optional[Dict[str, Any]] = None

    for content_type, data in content_breakdown.items():
        total_time = data.get("time", 0) or 0
        total_plays = data.get("plays", 0) or 0
        percentage = data.get("percentage", 0) or 0

        if total_time <= 0 and total_plays <= 0:
            continue

        candidate = {
            "label": type_names.get(content_type, content_type.capitalize()),
            "time": total_time,
            "plays": total_plays,
            "percentage": percentage,
        }

        if best_type is None or (
            candidate["time"],
            candidate["plays"],
        ) > (
            best_type["time"],
            best_type["plays"],
        ):
            best_type = candidate

    return best_type
