"""
Tautulli API client for MediaWatch.

This module handles all interactions with the Tautulli API for fetching
statistics, session data, user information, and media thumbnails.
"""

import asyncio
import aiohttp
import discord
import io
import logging
import time
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime


logger = logging.getLogger("mediawatch_bot.media_core.plex.tautulli")


class TautulliClient:
    """Client for Tautulli API interactions."""

    HISTORY_PAGE_SIZE = 1000
    MAX_HISTORY_PAGES = 1000
    USER_THUMB_TTL = 60 * 60 * 24
    # A global stats click walks the entire Tautulli history: 19k rows over 20
    # paginated requests, 2.6s measured against a real server, and it grows with
    # the history. The button sits on the public dashboard, so without a cache
    # every click repeats all of it. Server-wide numbers barely move in five
    # minutes, so this costs nothing in accuracy.
    GLOBAL_STATS_TTL = 300

    def __init__(
        self, tautulli_url: Optional[str], tautulli_api_key: Optional[str], config: Dict[str, Any]
    ):
        """Initialize Tautulli client.

        Args:
            tautulli_url: Base URL of Tautulli server
            tautulli_api_key: API key for Tautulli
            config: Configuration dictionary
        """
        self.tautulli_url = tautulli_url
        self.tautulli_api_key = tautulli_api_key
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None
        cache_config = config.get("cache", {})
        raw_ttl = cache_config.get("user_stats_ttl", 60)
        try:
            # bool is an int subclass: `true` would silently mean one second.
            if isinstance(raw_ttl, bool):
                raise TypeError(raw_ttl)
            self.user_stats_ttl = max(0, int(raw_ttl))
        except (TypeError, ValueError):
            # Raising here would keep the whole Plex cog from loading over a
            # cache setting, taking the dashboard down with it.
            logger.warning(
                "cache.user_stats_ttl must be a number of seconds, got %r; using 60.", raw_ttl
            )
            self.user_stats_ttl = 60
        self._user_watch_time_stats_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._user_history_cache: Dict[Tuple[str, int], Tuple[float, List[Dict[str, Any]]]] = {}
        self._user_player_stats_cache: Dict[
            Tuple[str, int], Tuple[float, List[Dict[str, Any]]]
        ] = {}
        self._user_name_cache: Dict[str, Tuple[float, str]] = {}
        self._user_thumb_cache: Dict[str, Tuple[float, Tuple[bytes, str]]] = {}
        self._global_stats_lock = asyncio.Lock()
        self._global_stats_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self.logger = logger

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create a shared aiohttp session for connection pooling."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self._session

    async def close(self) -> None:
        """Close shared HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def _get_cached_value(self, cache: Dict[Any, Tuple[float, Any]], key: Any) -> Optional[Any]:
        """Return cached value when still valid."""
        if self.user_stats_ttl <= 0:
            return None

        cached_entry = cache.get(key)
        if not cached_entry:
            return None

        expires_at, value = cached_entry
        if time.time() >= expires_at:
            cache.pop(key, None)
            return None

        return value

    def _set_cached_value(self, cache: Dict[Any, Tuple[float, Any]], key: Any, value: Any) -> None:
        """Store value in TTL cache."""
        self._set_cached_value_with_ttl(cache, key, value, self.user_stats_ttl)

    def _get_cached_value_with_ttl(
        self,
        cache: Dict[Any, Tuple[float, Any]],
        key: Any,
        ttl_seconds: int,
    ) -> Optional[Any]:
        """Return a cached value using a custom TTL instead of the user-stats TTL."""
        if ttl_seconds <= 0:
            return None

        cached_entry = cache.get(key)
        if not cached_entry:
            return None

        expires_at, value = cached_entry
        if time.time() >= expires_at:
            cache.pop(key, None)
            return None

        return value

    def _set_cached_value_with_ttl(
        self,
        cache: Dict[Any, Tuple[float, Any]],
        key: Any,
        value: Any,
        ttl_seconds: int,
    ) -> None:
        """Store a cached value using a custom TTL."""
        if ttl_seconds <= 0:
            return

        now = time.time()
        for expired_key in [key for key, (expires_at, _) in cache.items() if now >= expires_at]:
            cache.pop(expired_key, None)
        cache[key] = (now + ttl_seconds, value)

    async def _fetch_home_stats_rows(
        self,
        stat_id: str,
        time_range: int,
        stats_count: int,
        stats_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch a single home stats card from Tautulli."""
        if not self.is_configured:
            return []

        try:
            base_url = self.tautulli_url.rstrip("/")
            url = f"{base_url}/api/v2"
            params = {
                "apikey": self.tautulli_api_key,
                "cmd": "get_home_stats",
                "stat_id": stat_id,
                "time_range": time_range,
                "stats_count": stats_count,
            }
            if stats_type:
                params["stats_type"] = stats_type

            session = await self._get_session()
            async with session.get(url, params=params) as response:
                if response.status != 200:
                    return []

                data = await response.json()
                if data.get("response", {}).get("result") != "success":
                    return []

                stats_array = data["response"]["data"]
                if isinstance(stats_array, list):
                    for stat_obj in stats_array:
                        if stat_obj.get("stat_id") == stat_id:
                            return stat_obj.get("rows", [])
                elif isinstance(stats_array, dict):
                    return stats_array.get("rows", [])
        except Exception as e:
            self.logger.error(f"Error fetching {stat_id} home stats: {e}")

        return []

    @property
    def is_configured(self) -> bool:
        """Check if Tautulli is configured."""
        return bool(self.tautulli_url and self.tautulli_api_key)

    async def fetch_session(self, session_key: str) -> Optional[Dict[str, Any]]:
        """Async fetch of Tautulli session data.

        Args:
            session_key: Plex session key

        Returns:
            Session data dictionary or None if not found
        """
        if not self.is_configured:
            return None

        try:
            base_url = self.tautulli_url.rstrip("/")
            url = f"{base_url}/api/v2"
            params = {"apikey": self.tautulli_api_key, "cmd": "get_activity"}

            session = await self._get_session()
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("response", {}).get("result") == "success":
                        sessions = data["response"]["data"]["sessions"]
                        for s in sessions:
                            if str(s.get("session_key")) == str(session_key):
                                return s
            return None
        except Exception as e:
            self.logger.error(f"Error fetching from Tautulli: {e}")
            return None

    async def get_thumbnail(self, tautulli_data: Dict[str, Any]) -> Optional[discord.File]:
        """Fetch thumbnail image from Tautulli's image proxy.

        Args:
            tautulli_data: Tautulli session or media data

        Returns:
            Discord File object with thumbnail or None if unavailable
        """
        if not self.is_configured:
            return None

        try:
            media_type = tautulli_data.get("media_type", "")

            if media_type == "episode":
                thumb = tautulli_data.get("grandparent_thumb", "") or tautulli_data.get("thumb", "")
            else:
                thumb = tautulli_data.get("thumb", "") or tautulli_data.get("art", "")

            if not thumb:
                return None

            base_url = self.tautulli_url.rstrip("/")
            url = f"{base_url}/pms_image_proxy"
            params = {
                "img": thumb,
                "width": 300,
                "height": 450,
                "fallback": "poster",
                "apikey": self.tautulli_api_key,
            }

            session = await self._get_session()
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    content_type = response.headers.get("Content-Type", "")
                    if not content_type.startswith("image/"):
                        self.logger.warning(
                            f"Tautulli thumbnail proxy returned non-image content ({content_type or 'unknown'})."
                        )
                        return None
                    data = await response.read()
                    if data:
                        return discord.File(io.BytesIO(data), filename="poster.jpg")
            return None
        except Exception as e:
            self.logger.error(f"Error fetching thumbnail from Tautulli: {e}")
            return None

    async def get_cached_user_thumb_file(self, user_thumb_url: str) -> Optional[discord.File]:
        """Fetch and cache a Tautulli user avatar for embed footer reuse."""
        if not user_thumb_url:
            return None

        cached = self._get_cached_value_with_ttl(
            self._user_thumb_cache,
            user_thumb_url,
            self.USER_THUMB_TTL,
        )
        if cached:
            data, filename = cached
            return discord.File(io.BytesIO(data), filename=filename)

        try:
            session = await self._get_session()
            async with session.get(user_thumb_url) as response:
                if response.status != 200:
                    return None

                content_type = (
                    response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                )
                if not content_type.startswith("image/"):
                    self.logger.warning(
                        f"Tautulli user thumb returned non-image content ({content_type or 'unknown'})."
                    )
                    return None

                data = await response.read()
                if not data:
                    return None

                extension_map = {
                    "image/jpeg": ".jpg",
                    "image/jpg": ".jpg",
                    "image/png": ".png",
                    "image/webp": ".webp",
                    "image/gif": ".gif",
                }
                filename = f"user_avatar{extension_map.get(content_type, '.png')}"
                cached_value = (data, filename)
                self._set_cached_value_with_ttl(
                    self._user_thumb_cache,
                    user_thumb_url,
                    cached_value,
                    self.USER_THUMB_TTL,
                )
                return discord.File(io.BytesIO(data), filename=filename)
        except Exception as e:
            self.logger.error(f"Error fetching cached user thumb from Tautulli: {e}")
            return None

    async def fetch_user_watch_time_stats(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Fetch user watch time statistics from Tautulli.

        Args:
            user_id: Tautulli user ID

        Returns:
            Dictionary with watch time stats for different periods
        """
        if not self.is_configured:
            return None

        cache_key = str(user_id)
        cached_stats = self._get_cached_value(self._user_watch_time_stats_cache, cache_key)
        if cached_stats is not None:
            return cached_stats

        try:
            base_url = self.tautulli_url.rstrip("/")
            url = f"{base_url}/api/v2"
            params = {
                "apikey": self.tautulli_api_key,
                "cmd": "get_user_watch_time_stats",
                "user_id": user_id,
                "query_days": "1,7,30,0",
            }

            session = await self._get_session()
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("response", {}).get("result") == "success":
                        stats_list = data["response"]["data"]
                        stats_dict = {}
                        for stat in stats_list:
                            query_days = stat.get("query_days", 0)
                            if query_days == 0:
                                stats_dict["all_time"] = stat
                            elif query_days == 1:
                                stats_dict["last_24h"] = stat
                            elif query_days == 7:
                                stats_dict["last_7d"] = stat
                            elif query_days == 30:
                                stats_dict["last_30d"] = stat
                        self._set_cached_value(
                            self._user_watch_time_stats_cache, cache_key, stats_dict
                        )
                        return stats_dict
            return None
        except Exception as e:
            self.logger.error(f"Error fetching user watch time stats from Tautulli: {e}")
            return None

    async def fetch_user_name(self, user_id: str) -> Optional[str]:
        """Fetch the best available Plex username from Tautulli by user_id.

        Args:
            user_id: Tautulli user ID

        Returns:
            Plex username/user identifier, falling back to friendly name, or None.
        """
        if not self.is_configured:
            return None

        cache_key = str(user_id)
        cached_name = self._get_cached_value(self._user_name_cache, cache_key)
        if cached_name is not None:
            return cached_name

        try:
            base_url = self.tautulli_url.rstrip("/")
            url = f"{base_url}/api/v2"
            params = {"apikey": self.tautulli_api_key, "cmd": "get_user_names"}

            session = await self._get_session()
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("response", {}).get("result") == "success":
                        users = data["response"]["data"]
                        for user in users:
                            if str(user.get("user_id")) == str(user_id):
                                preferred_name = (
                                    user.get("username")
                                    or user.get("user")
                                    or user.get("friendly_name")
                                )
                                if preferred_name:
                                    self._set_cached_value(
                                        self._user_name_cache, cache_key, preferred_name
                                    )
                                return preferred_name
            return None
        except Exception as e:
            self.logger.error(f"Error fetching user name from Tautulli: {e}")
            return None

    async def fetch_user_top_shows(
        self, user_id: str, limit: int = 5
    ) -> Optional[List[Dict[str, Any]]]:
        """Fetch user's top watched TV shows from Tautulli.

        Args:
            user_id: Tautulli user ID
            limit: Maximum number of shows to return

        Returns:
            List of top show dictionaries or None if error
        """
        if not self.is_configured:
            return None

        try:
            base_url = self.tautulli_url.rstrip("/")
            url = f"{base_url}/api/v2"
            params = {
                "apikey": self.tautulli_api_key,
                "cmd": "get_home_stats",
                "stat_id": "top_tv",
                "user_id": user_id,
                "time_range": 0,
                "stats_count": limit,
            }

            session = await self._get_session()
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    self.logger.debug(f"fetch_user_top_shows response: {data}")
                    if data.get("response", {}).get("result") == "success":
                        stats_array = data["response"]["data"]
                        if isinstance(stats_array, list):
                            for stat_obj in stats_array:
                                if stat_obj.get("stat_id") == "top_tv":
                                    rows = stat_obj.get("rows", [])
                                    self.logger.debug(f"Found top_tv rows: {len(rows)} items")
                                    return rows
                        elif isinstance(stats_array, dict):
                            rows = stats_array.get("rows", [])
                            self.logger.debug(f"Found top_tv dict rows: {len(rows)} items")
                            return rows
                else:
                    self.logger.warning(f"fetch_user_top_shows status: {response.status}")
            return None
        except Exception as e:
            self.logger.error(f"Error fetching user top shows from Tautulli: {e}")
            return None

    async def fetch_user_history(
        self, user_id: str, length: int = 10000
    ) -> Optional[List[Dict[str, Any]]]:
        """Fetch user's playback history from Tautulli.

        Args:
            user_id: Tautulli user ID
            length: Maximum number of history entries to fetch

        Returns:
            List of history entry dictionaries or None if error
        """
        if not self.is_configured:
            return None

        cache_key = (str(user_id), int(length))
        cached_history = self._get_cached_value(self._user_history_cache, cache_key)
        if cached_history is not None:
            return cached_history

        try:
            base_url = self.tautulli_url.rstrip("/")
            url = f"{base_url}/api/v2"
            params = {
                "apikey": self.tautulli_api_key,
                "cmd": "get_history",
                "user_id": user_id,
                "length": length,
            }

            session = await self._get_session()
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("response", {}).get("result") == "success":
                        history_data = data["response"]["data"]
                        if isinstance(history_data, dict):
                            history = history_data.get("data", [])
                            self._set_cached_value(self._user_history_cache, cache_key, history)
                            return history
                        elif isinstance(history_data, list):
                            self._set_cached_value(
                                self._user_history_cache, cache_key, history_data
                            )
                            return history_data
            return None
        except Exception as e:
            self.logger.error(f"Error fetching user history from Tautulli: {e}")
            return None

    async def _fetch_history_stats(
        self, active_users_days: int | str
    ) -> Optional[Tuple[Dict[str, Any], set[str]]]:
        """Aggregate each page so memory grows with users, not playback history."""
        if not self.is_configured:
            return None

        try:
            base_url = self.tautulli_url.rstrip("/")
            url = f"{base_url}/api/v2"
            session = await self._get_session()
            now = datetime.now().timestamp()
            stats_24h = {"total_plays": 0, "total_time": 0}
            stats_7d = {"total_plays": 0, "total_time": 0}
            stats_30d = {"total_plays": 0, "total_time": 0}
            stats_all = {"total_plays": 0, "total_time": 0}
            active_users = set()
            active_users_max_days = (
                float("inf") if active_users_days == "all" else int(active_users_days)
            )
            start = 0
            page_size = self.HISTORY_PAGE_SIZE
            total_count: Optional[int] = None

            for _ in range(self.MAX_HISTORY_PAGES):
                params = {
                    "apikey": self.tautulli_api_key,
                    "cmd": "get_history",
                    "length": page_size,
                    "start": start,
                    "media_type": "",
                }

                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        self.logger.warning(f"fetch_complete_history status: {response.status}")
                        return None

                    data = await response.json()
                    if data.get("response", {}).get("result") != "success":
                        return None

                    history_data = data["response"]["data"]

                if isinstance(history_data, dict):
                    batch = history_data.get("data", [])
                    raw_total_count = history_data.get(
                        "recordsFiltered", history_data.get("recordsTotal")
                    )
                    if raw_total_count is not None:
                        try:
                            total_count = int(raw_total_count)
                        except (TypeError, ValueError):
                            total_count = None
                elif isinstance(history_data, list):
                    batch = history_data
                else:
                    batch = []

                if not batch:
                    break

                for item in batch:
                    date_str = item.get("date", 0)
                    duration = item.get("duration", 0) or 0
                    user_id = item.get("user_id", "")

                    if date_str:
                        try:
                            age_seconds = now - int(date_str)
                            if age_seconds < 0:
                                continue

                            stats_all["total_plays"] += 1
                            stats_all["total_time"] += duration

                            if age_seconds <= active_users_max_days * 86400 and user_id:
                                active_users.add(user_id)

                            if age_seconds <= 30 * 86400:
                                stats_30d["total_plays"] += 1
                                stats_30d["total_time"] += duration

                            if age_seconds <= 7 * 86400:
                                stats_7d["total_plays"] += 1
                                stats_7d["total_time"] += duration

                            if age_seconds <= 86400:
                                stats_24h["total_plays"] += 1
                                stats_24h["total_time"] += duration
                        except (ValueError, TypeError):
                            continue
                start += len(batch)

                if total_count is not None and start >= total_count:
                    break

                if len(batch) < page_size:
                    break
            else:
                self.logger.warning(
                    "Stopped history pagination after %s pages; discarding incomplete statistics.",
                    self.MAX_HISTORY_PAGES,
                )
                return None

            return {
                "last_24h": stats_24h,
                "last_7d": stats_7d,
                "last_30d": stats_30d,
                "all_time": stats_all,
            }, active_users
        except Exception as e:
            self.logger.error(f"Error fetching complete history from Tautulli: {e}")
            return None

    async def fetch_user_player_stats(
        self, user_id: str, time_range: int = 0
    ) -> Optional[List[Dict[str, Any]]]:
        """Fetch user's player/device statistics from Tautulli.

        Args:
            user_id: Tautulli user ID
            time_range: Number of days to include (0 = all time)

        Returns:
            List of player statistics dictionaries or None if error
        """
        if not self.is_configured:
            return None

        cache_key = (str(user_id), int(time_range))
        cached_stats = self._get_cached_value(self._user_player_stats_cache, cache_key)
        if cached_stats is not None:
            return cached_stats

        try:
            base_url = self.tautulli_url.rstrip("/")
            url = f"{base_url}/api/v2"
            params = {
                "apikey": self.tautulli_api_key,
                "cmd": "get_user_player_stats",
                "user_id": user_id,
                "grouping": 0,
            }

            # Only add time_range if not 0 (all time)
            if time_range > 0:
                params["time_range"] = time_range

            session = await self._get_session()
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("response", {}).get("result") == "success":
                        player_stats = data["response"]["data"]
                        self._set_cached_value(
                            self._user_player_stats_cache, cache_key, player_stats
                        )
                        return player_stats
            return None
        except Exception as e:
            self.logger.error(f"Error fetching user player stats from Tautulli: {e}")
            return None

    async def fetch_global_server_stats(self) -> Optional[Dict[str, Any]]:
        """Let concurrent clicks share the cache populated by the first request."""
        async with self._global_stats_lock:
            return await self._fetch_global_server_stats()

    async def _fetch_global_server_stats(self) -> Optional[Dict[str, Any]]:
        """Fetch global server statistics from Tautulli (all users combined).

        Returns:
            Dictionary containing comprehensive server statistics
        """
        if not self.is_configured:
            return None

        cached = self._get_cached_value_with_ttl(
            self._global_stats_cache, "global", self.GLOBAL_STATS_TTL
        )
        if cached is not None:
            return cached

        try:
            base_url = self.tautulli_url.rstrip("/")
            url = f"{base_url}/api/v2"

            popular_movies = []
            top_tv = []
            top_users = []

            page2_time_range_raw = (
                self.config.get("global_stats", {}).get("page_2", {}).get("time_range", 30)
            )

            if page2_time_range_raw == "all":
                page2_time_range = "all"
            elif isinstance(page2_time_range_raw, (int, float)):
                page2_time_range = int(page2_time_range_raw)
                if page2_time_range not in [7, 30, 90, 365] and page2_time_range < 1:
                    page2_time_range = 30
            else:
                page2_time_range = 30

            top_users_time_range = 0 if page2_time_range == "all" else int(page2_time_range)

            session = await self._get_session()
            # Get most popular movies
            try:
                popular_movies = await self._fetch_home_stats_rows(
                    "popular_movies",
                    time_range=30,
                    stats_count=5,
                )
            except Exception as e:
                self.logger.error(f"Error fetching popular movies: {e}")

            # Get top TV shows
            try:
                top_tv = await self._fetch_home_stats_rows("top_tv", time_range=30, stats_count=5)
            except Exception as e:
                self.logger.error(f"Error fetching top TV shows: {e}")

            # Fetch top users by watch time
            try:
                top_users = await self._fetch_home_stats_rows(
                    "top_users",
                    time_range=top_users_time_range,
                    stats_count=10,
                    stats_type="duration",
                )
            except Exception as e:
                self.logger.error(f"Error fetching top users: {e}")

            # Initialize activity tracking
            hourly_activity_by_type = {
                "tv": {str(h): 0 for h in range(24)},
                "movies": {str(h): 0 for h in range(24)},
                "music": {str(h): 0 for h in range(24)},
            }
            hourly_activity = {str(h): 0 for h in range(24)}
            daily_activity = {}
            watch_time = {}
            active_users = set()

            try:
                # Fetch hourly activity data
                params_hourly = {
                    "apikey": self.tautulli_api_key,
                    "cmd": "get_plays_by_hourofday",
                    "time_range": str(page2_time_range) if page2_time_range != "all" else "0",
                    "y_axis": "plays",
                }

                session = await self._get_session()
                async with session.get(url, params=params_hourly) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("response", {}).get("result") == "success":
                            hourly_data = data["response"]["data"]

                            for series in hourly_data.get("series", []):
                                series_name = series.get("name", "").lower()
                                series_data = series.get("data", [])

                                if series_name == "tv":
                                    for hour_idx, count in enumerate(series_data):
                                        if hour_idx < 24:
                                            hourly_activity_by_type["tv"][str(hour_idx)] = (
                                                count or 0
                                            )
                                            hourly_activity[str(hour_idx)] += count or 0
                                elif series_name == "movies":
                                    for hour_idx, count in enumerate(series_data):
                                        if hour_idx < 24:
                                            hourly_activity_by_type["movies"][str(hour_idx)] = (
                                                count or 0
                                            )
                                            hourly_activity[str(hour_idx)] += count or 0
                                elif series_name == "music":
                                    for hour_idx, count in enumerate(series_data):
                                        if hour_idx < 24:
                                            hourly_activity_by_type["music"][str(hour_idx)] = (
                                                count or 0
                                            )
                                            hourly_activity[str(hour_idx)] += count or 0

                # Fetch day of week activity
                params_daily = {
                    "apikey": self.tautulli_api_key,
                    "cmd": "get_plays_by_dayofweek",
                    "time_range": str(page2_time_range) if page2_time_range != "all" else "0",
                    "y_axis": "plays",
                }

                async with session.get(url, params=params_daily) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("response", {}).get("result") == "success":
                            daily_data = data["response"]["data"]
                            categories = daily_data.get("categories", [])

                            for day_idx, day_name in enumerate(categories):
                                total_plays = 0
                                for series in daily_data.get("series", []):
                                    series_data = series.get("data", [])
                                    if day_idx < len(series_data):
                                        total_plays += series_data[day_idx] or 0

                                if total_plays > 0:
                                    daily_activity[day_name] = total_plays

                history_stats = await self._fetch_history_stats(page2_time_range)
                if history_stats is not None:
                    watch_time, active_users = history_stats
            except Exception as e:
                self.logger.error(f"Error fetching watch time stats: {e}")

            # Find peak hour
            peak_hours = {}
            # hourly_activity is pre-seeded with 24 zeros, so a plain truthiness
            # check would report "peak hour 0:00 with 0 plays" on a fresh server.
            if any(hourly_activity.values()):
                max_hour = max(hourly_activity, key=hourly_activity.get)
                peak_hours = {"hour": int(max_hour), "count": hourly_activity[max_hour]}

            # Find most active day
            most_active_day = {}
            if any(daily_activity.values()):
                max_day = max(daily_activity, key=daily_activity.get)
                most_active_day = {"day": max_day, "count": daily_activity[max_day]}

            stats = {
                "popular_movies": popular_movies,
                "top_tv": top_tv,
                "top_users": top_users,
                "watch_time": watch_time,
                "active_users": len(active_users),
                "hourly_activity": hourly_activity,
                "hourly_activity_by_type": hourly_activity_by_type,
                "page2_time_range": page2_time_range,
                "peak_hours": peak_hours,
                "most_active_day": most_active_day,
            }
            self._set_cached_value_with_ttl(
                self._global_stats_cache, "global", stats, self.GLOBAL_STATS_TTL
            )
            return stats
        except Exception as e:
            self.logger.error(f"Error fetching global server stats from Tautulli: {e}")
            return None
