"""
Low-level Plex server client for MediaWatch.

This module handles the direct connection to Plex Media Server
using the PlexAPI library.
"""

import time
import logging
import threading
import requests
from typing import Optional, List, Any
from plexapi.exceptions import Unauthorized
from plexapi.server import PlexServer


logger = logging.getLogger("mediawatch_bot.media_core.plex.client")


class PlexClient:
    """Low-level client for Plex server API connection."""

    def __init__(self, plex_url: str, plex_token: str):
        """Initialize Plex client.

        Args:
            plex_url: URL to Plex server
            plex_token: Plex authentication token
        """
        self.plex_url = plex_url
        self.plex_token = plex_token

        # Server state tracking
        self._server: Optional[PlexServer] = None
        self._start_time: Optional[float] = None
        self._auth_failed: bool = False

        self._session = requests.Session()
        self._connection_lock = threading.Lock()
        self.logger = logger

    @property
    def server(self) -> Optional[PlexServer]:
        """Get the current PlexServer instance."""
        return self._server

    @property
    def auth_failed(self) -> bool:
        """Whether the last connection attempt was rejected by Plex.

        A rejected token looks exactly like an unreachable server otherwise, so
        the dashboard would blame the media server for a wrong PLEX_TOKEN.
        """
        return self._auth_failed

    @property
    def start_time(self) -> Optional[float]:
        """Get the server start timestamp."""
        return self._start_time

    def connect(self) -> Optional[PlexServer]:
        """Attempt to establish a connection to the Plex server.

        Returns:
            PlexServer instance or None if connection fails
        """
        with self._connection_lock:
            try:
                server = self._server
                if server is None:
                    server = PlexServer(self.plex_url, self.plex_token, session=self._session)
                else:
                    # Keep the pool, but still probe Plex on every status tick.
                    data = server.query("/")
                    server.friendlyName = data.get("friendlyName", "")
                    server.version = data.get("version", "")
                if self._start_time is None:
                    self._start_time = time.time()
                self._server = server
                self._auth_failed = False
                return server
            except Exception as e:
                # plexapi raises Unauthorized for 401 and a generic BadRequest that
                # carries the status code in its message for 403.
                self._auth_failed = isinstance(e, Unauthorized) or "(403)" in str(e)
                if self._auth_failed:
                    self.logger.error("Plex rejected the configured PLEX_TOKEN (HTTP 401/403)")
                else:
                    self.logger.error(f"Failed to connect to Plex server: {e}")
                self._start_time = None
                self._server = None
                self._session.close()
                return None

    def disconnect(self) -> None:
        """Release the owned HTTP pool after callers have stopped their work."""
        with self._connection_lock:
            self._server = None
            self._start_time = None
            self._session.close()

    def is_connected(self) -> bool:
        """Check if connected to Plex server.

        Returns:
            True if connected, False otherwise
        """
        return self._server is not None

    def get_sessions(self) -> List[Any]:
        """Get active sessions from Plex server.

        Returns:
            List of active session objects, empty list if not connected
        """
        if not self._server:
            return []
        try:
            return self._server.sessions()
        except Exception as e:
            self.logger.error(f"Failed to get sessions: {e}")
            return []

    def get_library_sections(self) -> Optional[dict]:
        """Get library sections from Plex server.

        Returns:
            Dictionary mapping section title to section object, or None when the
            fetch failed - an empty dict would read as "no libraries" and get cached
        """
        if not self._server:
            return None
        try:
            return {section.title: section for section in self._server.library.sections()}
        except Exception as e:
            self.logger.error(f"Failed to get library sections: {e}")
            return None

    def get_server_name(self) -> str:
        """Get the server's friendly name.

        Returns:
            Server name or empty string if not connected
        """
        if not self._server:
            return ""
        return self._server.friendlyName

    def get_server_version(self) -> str:
        """Get the server version.

        Returns:
            Server version or empty string if not connected
        """
        if not self._server:
            return ""
        return self._server.version
