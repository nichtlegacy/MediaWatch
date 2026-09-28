"""
Stream Service for Plex integration.

Handles stream data gathering, formatting, and transcoding analysis.
"""

import logging
import aiohttp
import discord
import io
from typing import Optional

logger = logging.getLogger("mediawatch_bot.media_core.plex.stream_service")

# The thumbnail is optional decoration on an interaction reply; aiohttp's 300s
# default would let a slow Plex hold the reply past Discord's interaction window.
IMAGE_TIMEOUT = aiohttp.ClientTimeout(total=10)


class StreamService:
    """Service for stream-related operations."""

    def __init__(self, plex):
        """Initialize stream service.

        Args:
            plex: PlexServer instance
        """
        self.plex = plex
        self.logger = logger

    async def get_stream_thumbnail_file(self, session) -> Optional[discord.File]:
        """Download thumbnail and return as Discord File.

        Args:
            session: Plex session object

        Returns:
            Discord File with thumbnail or None
        """
        try:
            if not self.plex:
                return None

            # Determine best thumbnail path
            content_type = getattr(session, "type", "unknown")
            thumb_path = None

            if content_type == "episode":
                # For TV shows, prefer show poster over episode thumbnail
                thumb_path = getattr(session, "grandparentThumb", None) or getattr(
                    session, "thumb", None
                )
            else:
                # For movies and music
                thumb_path = getattr(session, "thumb", None)

            # Fallback to art
            if not thumb_path:
                thumb_path = getattr(session, "art", None)

            if not thumb_path:
                return None

            return await self.download_image_file(thumb_path, filename="poster.jpg")

        except Exception as e:
            self.logger.error(f"Error downloading thumbnail: {e}", exc_info=True)
            return None

    async def download_image_file(
        self, image_path: str, filename: str = "image.jpg"
    ) -> Optional[discord.File]:
        """Download a Plex image path and return it as a Discord attachment."""
        try:
            if not self.plex or not image_path:
                return None

            url = self.plex.url(image_path, includeToken=True)
            # Never log the URL itself: plexapi appends X-Plex-Token to it.
            self.logger.debug("Downloading Plex image: %s", image_path)

            async with aiohttp.ClientSession(timeout=IMAGE_TIMEOUT) as http_session:
                async with http_session.get(url) as response:
                    if response.status == 200:
                        data = await response.read()
                        if data:
                            return discord.File(io.BytesIO(data), filename=filename)

                    self.logger.warning(f"Failed to download image: {response.status}")
                    return None
        except TimeoutError:
            self.logger.warning(
                "Timed out after %ss downloading Plex image %s; sending without it",
                IMAGE_TIMEOUT.total,
                image_path,
            )
            return None
        except Exception as e:
            self.logger.error(f"Error downloading image: {e}", exc_info=True)
            return None
