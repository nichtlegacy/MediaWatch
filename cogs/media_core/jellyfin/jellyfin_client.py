"""
Low-level Jellyfin server client for MediaWatch.

This module handles the direct connection to Jellyfin Media Server
using aiohttp for REST API calls.
"""

import aiohttp
import logging
from typing import Optional, List, Dict, Any


logger = logging.getLogger("mediawatch_bot.media_core.jellyfin.client")


class JellyfinClient:
    """Low-level client for Jellyfin server API connection.

    Uses a shared aiohttp.ClientSession for efficient connection pooling.
    """

    def __init__(self, jellyfin_url: str, jellyfin_api_key: str):
        """Initialize Jellyfin client.

        Args:
            jellyfin_url: URL to Jellyfin server
            jellyfin_api_key: Jellyfin API key
        """
        self.jellyfin_url = jellyfin_url.rstrip("/")
        self.api_key = jellyfin_api_key

        # Server state
        self._is_connected: bool = False
        self._server_info: Optional[Dict[str, Any]] = None
        self._auth_failed: bool = False

        # Shared session for connection pooling (created on first use)
        self._session: Optional[aiohttp.ClientSession] = None

        self.logger = logger

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests."""
        return {
            "X-Emby-Token": self.api_key,
            "Content-Type": "application/json",
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the shared aiohttp session.

        Returns:
            Active aiohttp.ClientSession
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers=self._get_headers(), timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def connect(self) -> bool:
        """Test connection to Jellyfin server and fetch server info.

        Returns:
            True if connected successfully, False otherwise
        """
        try:
            session = await self._get_session()
            url = f"{self.jellyfin_url}/System/Info"
            async with session.get(url) as response:
                if response.status == 200:
                    self._server_info = await response.json()
                    # The status loop probes every tick; only a state change is news.
                    log = self.logger.debug if self._is_connected else self.logger.info
                    self._is_connected = True
                    self._auth_failed = False
                    log(f"Connected to Jellyfin: {self._server_info.get('ServerName', 'Unknown')}")
                    return True
                else:
                    self._auth_failed = response.status in (401, 403)
                    if self._auth_failed:
                        self.logger.error(
                            f"Jellyfin rejected the configured JELLYFIN_API_KEY (HTTP {response.status})"
                        )
                    else:
                        self.logger.error(f"Failed to connect to Jellyfin: HTTP {response.status}")
                    self._is_connected = False
                    return False
        except Exception as e:
            self.logger.error(f"Failed to connect to Jellyfin server: {e}")
            self._auth_failed = False
            self._is_connected = False
            return False

    async def disconnect(self) -> None:
        """Reset connection state and close session."""
        self._is_connected = False
        self._server_info = None
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def is_connected(self) -> bool:
        """Check if connected to Jellyfin server."""
        return self._is_connected

    @property
    def auth_failed(self) -> bool:
        """Whether the last connection attempt was rejected by Jellyfin.

        A rejected API key looks exactly like an unreachable server otherwise,
        so the dashboard would blame Jellyfin for a wrong JELLYFIN_API_KEY.
        """
        return self._auth_failed

    @property
    def server_name(self) -> str:
        """Get the server's friendly name."""
        if self._server_info:
            return self._server_info.get("ServerName", "Jellyfin Server")
        return "Jellyfin Server"

    @property
    def server_version(self) -> str:
        """Get the server version."""
        if self._server_info:
            return self._server_info.get("Version", "")
        return ""

    async def get_sessions(self) -> List[Dict[str, Any]]:
        """Get active sessions from Jellyfin server.

        Returns:
            List of active session dictionaries with full MediaSources including People data
        """
        try:
            session = await self._get_session()
            url = f"{self.jellyfin_url}/Sessions"

            # Add query parameters to include additional fields
            params = {
                "Fields": "MediaSources,People,Overview,PrimaryImageAspectRatio",
            }

            async with session.get(url, params=params) as response:
                if response.status == 200:
                    sessions = await response.json()
                    # Filter to only sessions that have NowPlayingItem
                    return [s for s in sessions if s.get("NowPlayingItem")]
                else:
                    self.logger.error(f"Failed to get sessions: HTTP {response.status}")
                    return []
        except Exception as e:
            self.logger.error(f"Failed to get sessions: {e}")
            return []

    async def get_library_sections(self) -> Optional[List[Dict[str, Any]]]:
        """Get library sections (virtual folders) from Jellyfin.

        Returns:
            List of library section dictionaries, or None when the fetch failed -
            an empty list would read as "no libraries" and get cached
        """
        try:
            session = await self._get_session()
            url = f"{self.jellyfin_url}/Library/VirtualFolders"
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                self.logger.error(f"Failed to get library sections: HTTP {response.status}")
                return None
        except Exception as e:
            self.logger.error(f"Failed to get library sections: {e}")
            return None

    async def _count_items(self, parent_id: str, item_types: str) -> Optional[int]:
        """Count items of the given types below a library.

        Returns None on failure so a network error is not cached as a real 0.
        """
        try:
            session = await self._get_session()
            url = f"{self.jellyfin_url}/Items"
            params = {
                "ParentId": parent_id,
                "Recursive": "true",
                "Limit": 0,
                "IncludeItemTypes": item_types,
            }
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("TotalRecordCount", 0)
                self.logger.error(f"Failed to count {item_types} items: HTTP {response.status}")
                return None
        except Exception as e:
            self.logger.error(f"Failed to count {item_types} items: {e}")
            return None

    async def get_item_counts(self, parent_id: str) -> Optional[int]:
        """Get item count for a library section, or None on failure."""
        return await self._count_items(parent_id, "Movie,Series,Episode,MusicAlbum,Audio")

    async def get_episodes_count(self, parent_id: str) -> Optional[int]:
        """Get episode count for a TV library, or None on failure."""
        return await self._count_items(parent_id, "Episode")

    async def get_series_count(self, parent_id: str) -> Optional[int]:
        """Get series count for a TV library, or None on failure."""
        return await self._count_items(parent_id, "Series")

    def get_thumbnail_url(self, item_id: str, image_type: str = "Primary") -> Optional[str]:
        """Get thumbnail URL for an item.

        Args:
            item_id: The item ID
            image_type: Type of image (Primary, Backdrop, etc.)

        Returns:
            Full URL to the image
        """
        if not item_id:
            return None
        return f"{self.jellyfin_url}/Items/{item_id}/Images/{image_type}"

    async def send_message(
        self,
        session_id: str,
        text: str,
        header: str = "MediaWatch",
        timeout_ms: int = 10000,
    ) -> bool:
        """Display a message on the client of an active session.

        Jellyfin's playstate endpoints take no body, so a reason has to be
        delivered separately as a DisplayMessage command. Clients that do not
        support DisplayMessage ignore it silently.

        Args:
            session_id: The session ID to send the message to
            text: Message body shown to the user
            header: Message title shown to the user
            timeout_ms: How long the client should display the message

        Returns:
            True if the server accepted the message, False otherwise
        """
        try:
            session = await self._get_session()
            url = f"{self.jellyfin_url}/Sessions/{session_id}/Message"
            payload = {"Text": text, "Header": header, "TimeoutMs": timeout_ms}

            async with session.post(url, json=payload) as response:
                if response.status in [200, 204]:
                    return True
                self.logger.warning(
                    f"Failed to send message to session {session_id}: HTTP {response.status}"
                )
                return False
        except Exception as e:
            self.logger.warning(f"Failed to send message to session {session_id}: {e}")
            return False

    async def stop_session(self, session_id: str) -> bool:
        """Stop a playback session.

        Note: ``/Sessions/{id}/Playing/Stop`` accepts no request body. Use
        :meth:`send_message` to tell the user why playback was stopped.

        Args:
            session_id: The session ID to stop

        Returns:
            True if session was stopped successfully, False otherwise
        """
        try:
            session = await self._get_session()
            # Use the session ID directly in the URL path
            url = f"{self.jellyfin_url}/Sessions/{session_id}/Playing/Stop"

            async with session.post(url) as response:
                if response.status in [200, 204]:
                    self.logger.info(f"Successfully stopped session {session_id}")
                    return True
                else:
                    self.logger.error(f"Failed to stop session: HTTP {response.status}")
                    return False
        except Exception as e:
            self.logger.error(f"Failed to stop session: {e}")
            return False

    async def get_item_library(
        self, item_id: str, user_id: Optional[str] = None
    ) -> Optional[Dict[str, str]]:
        """Return the library an item actually lives in.

        The media type alone cannot answer this: a server with "Filme" and
        "Filme 4K" has two libraries of type ``movies``, and picking the first
        one shows the wrong name. ``/Items/{id}/Ancestors`` walks up to the
        CollectionFolder, which is the library itself.

        ``user_id`` is required in practice. Without it Jellyfin answers with
        the *physical* folder chain - the mount path, ``/data/movies`` - and
        never a CollectionFolder, so the lookup silently finds nothing.

        Args:
            item_id: The item currently playing
            user_id: The session's user; libraries are a per-user view

        Returns:
            ``{"id": ..., "name": ...}`` of the owning library, or None
        """
        if not item_id:
            return None
        try:
            session = await self._get_session()
            url = f"{self.jellyfin_url}/Items/{item_id}/Ancestors"
            params = {"userId": user_id} if user_id else None
            async with session.get(url, params=params) as response:
                if response.status != 200:
                    return None
                for ancestor in await response.json():
                    if ancestor.get("Type") == "CollectionFolder":
                        return {
                            "id": ancestor.get("Id") or "",
                            "name": ancestor.get("Name") or "",
                        }
            return None
        except Exception as e:
            self.logger.debug(f"Could not resolve the library for {item_id}: {e}")
            return None

    async def get_item_details(
        self, item_id: str, user_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific item including People data.

        Args:
            item_id: The item ID
            user_id: Optional user ID for user-specific context. If not provided, uses first available user.

        Returns:
            Item details dictionary with People data or None if failed
        """
        try:
            session = await self._get_session()

            # If no user_id provided, get the first user from the server
            if not user_id:
                users_url = f"{self.jellyfin_url}/Users"
                async with session.get(users_url) as users_response:
                    if users_response.status == 200:
                        users = await users_response.json()
                        if users:
                            user_id = users[0].get("Id")

                    if not user_id:
                        return None

            # Use the user-specific endpoint to get full item details including People
            url = f"{self.jellyfin_url}/Users/{user_id}/Items/{item_id}"

            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                return None
        except Exception as e:
            self.logger.debug(f"Could not get item details: {e}")
            return None
