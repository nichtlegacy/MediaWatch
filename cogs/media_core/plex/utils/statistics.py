"""
Statistics calculation utilities for MediaWatch.

This module contains functions for calculating various statistics
from user watch history and playback data.

Note: This feature requires Tautulli to be configured and enabled.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional


def calculate_watch_streak(history: List[Dict[str, Any]]) -> int:
    """Calculate consecutive days watched from history.

    Args:
        history: List of playback history entries from Tautulli

    Returns:
        Number of consecutive days the user has watched content
    """
    if not history:
        return 0

    # Get unique dates when user watched something
    watched_dates = set()
    for item in history:
        date_str = item.get("date", 0)
        if date_str:
            try:
                play_date = datetime.fromtimestamp(int(date_str))
                # Only count date, not time
                watched_dates.add(play_date.date())
            except (ValueError, TypeError):
                continue

    if not watched_dates:
        return 0

    # Sort dates in descending order
    sorted_dates = sorted(watched_dates, reverse=True)

    # Calculate streak starting from today or yesterday
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)

    # Determine starting point: today if watched today, otherwise yesterday if watched
    if today in sorted_dates:
        current_date = today
        streak = 1
    elif yesterday in sorted_dates:
        current_date = yesterday
        streak = 1
    else:
        return 0

    # Count consecutive days backwards from starting point
    expected_date = current_date - timedelta(days=1)
    for watched_date in sorted_dates:
        if watched_date == expected_date:
            streak += 1
            expected_date -= timedelta(days=1)
        elif watched_date < expected_date:
            # Gap found, streak broken
            break

    return streak


def calculate_favorite_genre(history: List[Dict[str, Any]]) -> Optional[str]:
    """Calculate favorite genre based on watch time.

    Args:
        history: List of playback history entries from Tautulli

    Returns:
        Name of the most-watched genre, or None if no data
    """
    if not history:
        return None

    genre_watch_time: Dict[str, int] = {}

    for item in history:
        genres = item.get("genres", [])
        duration = item.get("duration", 0) or 0

        if genres and duration > 0:
            # Tautulli returns genres as comma-separated string or list
            if isinstance(genres, str):
                genre_list = [g.strip() for g in genres.split(",")]
            elif isinstance(genres, list):
                genre_list = genres
            else:
                continue

            # Add watch time to each genre
            for genre in genre_list:
                if genre:
                    genre_watch_time[genre] = genre_watch_time.get(genre, 0) + duration

    if not genre_watch_time:
        return None

    # Return genre with most watch time
    favorite_genre = max(genre_watch_time.items(), key=lambda x: x[1])
    return favorite_genre[0]


def calculate_previous_period_stats(history: List[Dict[str, Any]], days: int) -> Dict[str, Any]:
    """Calculate stats for the previous period (e.g., previous 7 days before last 7 days).

    Args:
        history: List of playback history entries from Tautulli
        days: Number of days in the period

    Returns:
        Dictionary with total_plays and total_time for the previous period
    """
    if not history:
        return {"total_plays": 0, "total_time": 0}

    now = datetime.now()
    period_end = now - timedelta(days=days)
    period_start = period_end - timedelta(days=days)

    total_plays = 0
    total_time = 0

    for item in history:
        date_str = item.get("date", 0)
        duration = item.get("duration", 0) or 0

        if date_str:
            try:
                play_date = datetime.fromtimestamp(int(date_str))

                # Check if play is in previous period
                if period_start <= play_date < period_end:
                    total_plays += 1
                    total_time += duration
            except (ValueError, TypeError):
                continue

    return {"total_plays": total_plays, "total_time": total_time}


def calculate_period_comparison(
    current_stats: Dict[str, Any], previous_stats: Dict[str, Any], period: str
) -> Optional[str]:
    """Calculate percentage change between current and previous period.

    Args:
        current_stats: Statistics for current period
        previous_stats: Statistics for previous period
        period: Period label (e.g., "7d", "30d")

    Returns:
        Formatted comparison string like "↑ 25%" or "↓ 10%", or None if no comparison possible
    """
    if not current_stats or not previous_stats:
        return None

    current_time = current_stats.get("total_time", 0)
    previous_time = previous_stats.get("total_time", 0)

    if previous_time == 0:
        if current_time > 0:
            return "New period"
        return None

    change_percent = ((current_time - previous_time) / previous_time) * 100

    if abs(change_percent) < 0.1:  # Less than 0.1% change
        return "≈ 0%"

    arrow = "↑" if change_percent > 0 else "↓"
    return f"{arrow} {abs(change_percent):.0f}%"
