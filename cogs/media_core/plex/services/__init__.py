"""
Service layer for Plex integration.

This package contains service classes that encapsulate business logic
for Plex server interactions, library management, and stream handling.
"""

from .stream_service import StreamService

__all__ = [
    "StreamService",
]
