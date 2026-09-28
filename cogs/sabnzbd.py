from discord.ext import commands
import aiohttp
import asyncio
import logging
import os
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

from cogs.media_core.shared.config import load_config
from cogs.media_core.shared.formatters import format_progress_bar, sanitize_code_block_text

RUNNING_IN_DOCKER = os.getenv("RUNNING_IN_DOCKER", "false").lower() == "true"

if not RUNNING_IN_DOCKER:
    load_dotenv()


class SABnzbd(commands.Cog):
    """Cog for displaying SABnzbd download queue and status."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger = logging.getLogger("mediawatch_bot.sabnzbd")
        self.SABNZBD_URL = os.getenv("SABNZBD_URL")
        self.SABNZBD_API_KEY = os.getenv("SABNZBD_API_KEY")

        self.current_dir = os.path.dirname(os.path.abspath(__file__))
        self.CONFIG_FILE = os.path.join(self.current_dir, "..", "data", "config.yaml")
        self.config = self._load_config()
        self._session: Optional[aiohttp.ClientSession] = None
        self._validation_task: Optional[asyncio.Task] = None
        self._shutdown_started = False

    async def cog_load(self) -> None:
        """Validate configuration after the bot is ready."""
        if self.is_configured() and (self._validation_task is None or self._validation_task.done()):
            self._validation_task = self.bot.loop.create_task(self._validate_config_async())

    @property
    def keywords(self) -> List[str]:
        """Get keywords from config."""
        return self.config.get("keywords") or []

    @property
    def show_when_empty(self) -> bool:
        """Show 'No active downloads' message when queue is empty."""
        return self.config.get("show_when_empty", False)

    @property
    def show_status_icons(self) -> bool:
        """Show status icons before download names."""
        return self.config.get("show_status_icons", True)

    @property
    def diskspace_free_key(self) -> str:
        """SABnzbd API key for free disk space (diskspace1 or diskspace2)."""
        return self.config.get("diskspace_free_key", "diskspace1")

    @property
    def diskspace_total_key(self) -> str:
        """SABnzbd API key for total disk space (diskspacetotal1 or diskspacetotal2)."""
        return self.config.get("diskspace_total_key", "diskspacetotal1")

    def is_configured(self) -> bool:
        """Check if SABnzbd is properly configured."""
        return bool(self.SABNZBD_URL and self.SABNZBD_API_KEY)

    @property
    def api_url(self) -> str:
        """Full SABnzbd API endpoint, preserving any base path of SABNZBD_URL."""
        return f"{(self.SABNZBD_URL or '').rstrip('/')}/api"

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the shared HTTP session for SABnzbd requests."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        return self._session

    def _load_config(self) -> Dict[str, Any]:
        """Load the SABnzbd section from the shared config loader.

        shared/config.py owns the defaults; this cog only picks its section out
        of the merged result so both stay in sync.
        """
        return load_config(self.CONFIG_FILE).get("sabnzbd", {})

    async def _validate_config_async(self):
        """Validate SABnzbd configuration asynchronously at startup."""
        await self.bot.wait_until_ready()

        # Give SABnzbd more time to be ready at startup
        await asyncio.sleep(5)

        # Retry up to 3 times with increasing delays
        max_retries = 3
        for attempt in range(max_retries):
            try:
                session = await self._get_session()
                async with session.get(
                    self.api_url,
                    params={"mode": "queue", "output": "json", "apikey": self.SABNZBD_API_KEY},
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        queue = data.get("queue", {})

                        # Check if configured keys exist
                        available_keys = list(queue.keys())

                        if self.diskspace_free_key not in queue:
                            self.logger.warning(
                                f"⚠️ SABnzbd config: 'diskspace_free_key' is set to '{self.diskspace_free_key}' "
                                f"but this key was not found in SABnzbd API response. "
                                f"Available disk space keys: {[k for k in available_keys if 'disk' in k.lower()]}"
                            )

                        if self.diskspace_total_key not in queue:
                            self.logger.warning(
                                f"⚠️ SABnzbd config: 'diskspace_total_key' is set to '{self.diskspace_total_key}' "
                                f"but this key was not found in SABnzbd API response. "
                                f"Available disk space keys: {[k for k in available_keys if 'disk' in k.lower()]}"
                            )

                        self.logger.info("✅ SABnzbd configuration validated successfully")
                        return

                    self.logger.warning(
                        f"Could not validate SABnzbd config: API returned status {response.status}"
                    )
                    return
            except asyncio.TimeoutError:
                if attempt < max_retries - 1:
                    self.logger.debug(
                        f"SABnzbd validation attempt {attempt + 1} timed out, retrying..."
                    )
                    await asyncio.sleep(5 * (attempt + 1))  # Wait 5s, 10s, 15s
                else:
                    self.logger.info(
                        "SABnzbd config validation skipped - service may be starting slowly (will work when available)"
                    )
            except asyncio.CancelledError:
                return
            except Exception as e:
                self.logger.warning(f"Could not validate SABnzbd configuration: {e}")
                return  # Non-timeout error, don't retry

    async def get_sabnzbd_info(self) -> Dict[str, Any]:
        """Fetch download queue and disk space information from SABnzbd API."""
        # Return empty if not configured
        if not self.is_configured():
            return {
                "downloads": [],
                "diskspace1": "Unknown",
                "diskspacetotal1": "Unknown",
                "configured": False,
            }

        url = self.api_url
        params = {"apikey": self.SABNZBD_API_KEY, "output": "json", "mode": "queue"}
        try:
            session = await self._get_session()
            async with session.get(url, params=params) as response:
                if not response.ok:
                    error_text = await response.text()
                    self.logger.error(f"SABnzbd API error - Status {response.status}: {error_text}")
                    return {
                        "downloads": [],
                        "diskspace1": "Unknown",
                        "diskspacetotal1": "Unknown",
                        "configured": True,
                    }
                data = await response.json()

            queue = data.get("queue", {})
            slots = queue.get("slots", [])

            disk_space = self._format_size_diskspace(queue.get(self.diskspace_free_key, "Unknown"))
            total_disk_space = self._format_size_diskspace(
                queue.get(self.diskspace_total_key, "Unknown")
            )

            if not slots:
                return {
                    "downloads": [],
                    "diskspace1": disk_space,
                    "diskspacetotal1": total_disk_space,
                    "configured": True,
                    "show_when_empty": self.show_when_empty,
                }

            # Check if entire queue is paused
            queue_paused = queue.get("paused", False)

            downloads = [
                {
                    "name": item.get("filename", "Unknown"),
                    # SABnzbd sends "" for a slot that has not started yet
                    "progress": float(item.get("percentage") or 0),
                    "timeleft": item.get("timeleft", "Unknown"),
                    "speed": self._format_speed_from_kbps(queue.get("kbpersec", "0")),
                    "size": self._format_mb(item.get("mbleft", "0")),
                    "status": item.get("status", "Queued"),
                    "queue_paused": queue_paused,
                }
                for item in slots
            ]
            return {
                "downloads": downloads,
                "free_space": disk_space,
                "total_space": total_disk_space,
                "configured": True,
                "show_when_empty": self.show_when_empty,
            }
        except aiohttp.ClientError as e:
            self.logger.error(f"SABnzbd API request failed: {e}")
            return {
                "downloads": [],
                "free_space": "Unknown",
                "total_space": "Unknown",
                "configured": True,
            }
        except asyncio.TimeoutError:
            self.logger.warning("SABnzbd API request timed out")
            return {
                "downloads": [],
                "free_space": "Unknown",
                "total_space": "Unknown",
                "configured": True,
            }
        except Exception as e:
            # SABnzbd is an optional integration: an unexpected payload must not
            # bubble up into update_dashboard, or server status, streams and
            # libraries would freeze together with it.
            self.logger.error(f"Unexpected SABnzbd response, skipping section: {e}")
            return {
                "downloads": [],
                "free_space": "Unknown",
                "total_space": "Unknown",
                "configured": True,
            }

    async def shutdown(self) -> None:
        """Cancel validation work and close the shared HTTP session."""
        if self._shutdown_started:
            return

        self._shutdown_started = True

        if self._validation_task and not self._validation_task.done():
            self._validation_task.cancel()
            try:
                await self._validation_task
            except asyncio.CancelledError:
                pass

        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def cog_unload(self) -> None:
        """Schedule cleanup when the cog is unloaded."""
        if self.bot.loop.is_running():
            self.bot.loop.create_task(self.shutdown())

    def _format_mb(self, size_mb: str) -> str:
        """Convert size (MB) to human-readable format (MB, GB, TB)."""
        try:
            size_float = float(size_mb)
            for unit in ["MB", "GB", "TB"]:
                if size_float < 1024:
                    return f"{size_float:.2f} {unit}"
                size_float /= 1024
            return f"{size_float:.2f} TB"
        except (ValueError, TypeError):
            return f"{size_mb} MB" if size_mb else "Unknown"

    def _format_speed_from_kbps(self, kbpersec: str) -> str:
        """Convert speed from KB/s to human-readable format."""
        try:
            speed_float = float(kbpersec)
            for unit in ["KB", "MB", "GB", "TB"]:
                if speed_float < 1024:
                    return f"{speed_float:.2f} {unit}/s"
                speed_float /= 1024
            return f"{speed_float:.2f} TB/s"
        except (ValueError, TypeError):
            return f"{kbpersec} KB/s" if kbpersec else "Unknown"

    def _format_size_diskspace(self, size: str) -> str:
        """Format disk space size dynamically (GB or TB). Input is in GB."""
        try:
            size_float = float(size)
            if size_float >= 1024:
                return f"{size_float / 1024:.2f} TB"
            return f"{size_float:.2f} GB"
        except (ValueError, TypeError):
            return size if size else "Unknown"

    def _get_status_icon(self, status: str) -> str:
        """Get status icon emoji based on download status."""
        status_icons = {
            "Paused": "⏸️",
            "Checking": "🔍",
            "Propagating": "⏳",
            "Fetching": "📦",
            "Downloading": "📥",
            "Queued": "📥",
        }
        return status_icons.get(status, "📥")

    def format_download_info(self, download: Dict[str, Any], index: int) -> str:
        """Format download details into a Discord-friendly string."""
        try:
            progress_percent = float(download["progress"])
            name = download["name"]
            # Cut the release name before the first quality keyword. A keyword at
            # position 0 (e.g. "German.Movie...") would leave nothing, so only
            # truncate when there is something in front of it.
            min_pos = min([name.find(kw) for kw in self.keywords if kw in name], default=0)
            if min_pos > 0:
                name = name[:min_pos]
            # The NZB name is attacker-controlled enough to close the code
            # fence with a backtick or a newline, which would render the rest
            # of the dashboard message as markdown.
            name = sanitize_code_block_text(name.strip(), max_length=40)

            # Optional status icon prefix
            prefix = ""
            if self.show_status_icons:
                # Check if queue is paused (common case)
                if download.get("queue_paused", False):
                    icon = "⏸️"
                else:
                    status = download.get("status", "Queued")
                    icon = self._get_status_icon(status)
                prefix = f"{icon} "

            # Show "Paused" instead of time when queue is paused
            # Show "Checking" instead of time when verifying (no time provided by SABnzbd)
            if download.get("queue_paused", False):
                time_info = "Paused"
            elif download.get("status") == "Checking":
                time_info = "Checking"
            else:
                time_info = f"{download['timeleft']} remaining"

            # During checking, hide the entire speed/size line (verification doesn't download)
            if download.get("status") == "Checking":
                info_line = ""
            else:
                info_line = f"\n └─ 📊 {download['speed']} | Remaining: {download['size']}"

            return (
                f"**```{prefix}{name}\n"
                f"└─ {format_progress_bar(progress_percent)} | {time_info}{info_line}```**"
            )
        except Exception as e:
            self.logger.error(f"Error formatting download info: {e}")
            return "```❓ Download could not be loaded```"


async def setup(bot: commands.Bot) -> None:
    """Set up the SABnzbd cog for the bot."""
    await bot.add_cog(SABnzbd(bot))
