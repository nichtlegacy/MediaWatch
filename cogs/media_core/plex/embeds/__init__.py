"""
Discord Embeds for Plex integration.

Contains embed generators for stream details, user statistics,
and dashboard displays.
"""

from .stream_embeds import create_detailed_stream_embed

__all__ = [
    "create_detailed_stream_embed",
]
