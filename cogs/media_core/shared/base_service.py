"""
Base service protocol for MediaWatch multi-platform support.

Defines the MediaService protocol that both Plex and Jellyfin
implementations must adhere to.
"""

from typing import Protocol, Dict, List
import discord

from .models import ServerType, ServerStatus, ActiveStream, LibraryStats


class MediaService(Protocol):
    """Protocol defining the interface for media server services.

    Both PlexMediaService and JellyfinMediaService must implement
    this protocol to ensure consistent behavior across platforms.
    """

    @property
    def server_type(self) -> ServerType:
        """Return the type of media server this service handles."""
        ...

    @property
    def embed_color(self) -> discord.Color:
        """Return the brand color for embeds (Plex orange, Jellyfin purple)."""
        ...

    @property
    def server_name(self) -> str:
        """Return the configured server name."""
        ...

    async def get_server_status(self) -> ServerStatus:
        """Get current server status including online state and uptime.

        Returns:
            ServerStatus object with current server state
        """
        ...

    async def get_active_streams(self) -> List[ActiveStream]:
        """Get list of currently active streaming sessions.

        Returns:
            List of ActiveStream objects representing current streams
        """
        ...

    async def get_library_stats(self) -> Dict[str, LibraryStats]:
        """Get statistics for all configured library sections.

        Returns:
            Dictionary mapping section titles to LibraryStats objects
        """
        ...

    async def close(self) -> None:
        """Clean up resources and close connections.

        Called when the cog is unloaded or bot is shutting down.
        """
        ...

    def is_connected(self) -> bool:
        """Check if the service has an active connection to the server.

        Returns:
            True if connected, False otherwise
        """
        ...
