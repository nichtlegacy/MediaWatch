"""
Plex implementation for MediaWatch multi-platform support.

This package contains the Plex-specific implementation including:
- PlexClient: Low-level Plex API connection
- TautulliClient: Tautulli API integration for enhanced statistics
- PlexMediaService: MediaService protocol implementation
- PlexCore: Discord Cog for Plex functionality
"""

from .core import PlexCore, setup

__all__ = ["PlexCore", "setup"]
