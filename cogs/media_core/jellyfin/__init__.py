"""
Jellyfin implementation for MediaWatch multi-platform support.

This package contains the Jellyfin-specific implementation including:
- JellyfinClient: Low-level Jellyfin API connection
- JellyfinMediaService: MediaService protocol implementation
- JellyfinCore: Discord Cog for Jellyfin functionality
"""

from .core import JellyfinCore, setup

__all__ = ["JellyfinCore", "setup"]
