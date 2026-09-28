from discord.ext import commands
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from uptime_kuma_api import UptimeKumaApi, UptimeKumaException
from typing import Tuple, Optional
from dotenv import load_dotenv

RUNNING_IN_DOCKER = os.getenv("RUNNING_IN_DOCKER", "false").lower() == "true"

if not RUNNING_IN_DOCKER:
    load_dotenv()


EMPTY_UPTIME = (None, None, None, None, None, None)


def _beat_time(beat: dict) -> Optional[datetime]:
    """Parse a beat timestamp; Uptime Kuma stores them in UTC without an offset."""
    try:
        parsed = datetime.fromisoformat(str(beat["time"]))
    except (KeyError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _uptime_and_online_minutes(beats: list, period_hours: int) -> Tuple[float, float]:
    up_count = sum(1 for beat in beats if beat["status"].name == "UP")
    uptime_percent = (up_count / len(beats)) * 100 if beats else 0.0
    online_minutes = up_count * (period_hours * 60 / len(beats)) if beats else 0
    return uptime_percent, online_minutes


def uptime_windows(beats_30d: list, now: datetime) -> Tuple[float, ...]:
    """Split one 30-day beat list into the 24h/7d/30d windows Kuma would return."""
    result: Tuple[float, ...] = ()
    for hours in (24, 7 * 24):
        cutoff = now - timedelta(hours=hours)
        beats = [b for b in beats_30d if (t := _beat_time(b)) is not None and t > cutoff]
        result += _uptime_and_online_minutes(beats, hours)
    return result + _uptime_and_online_minutes(beats_30d, 30 * 24)


class Uptime(commands.Cog):
    """Cog for displaying Uptime Kuma statistics in the dashboard."""

    CACHE_TTL_SECONDS = 300

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger = logging.getLogger("mediawatch_bot.uptime")
        self.api_url = os.getenv("UPTIME_URL")
        self.username = os.getenv("UPTIME_USERNAME")
        self.password = os.getenv("UPTIME_PASSWORD")
        monitor_id_raw = os.getenv("UPTIME_MONITOR_ID")
        self.monitor_id = self._parse_monitor_id(monitor_id_raw)
        self.enabled = all(
            [
                self.api_url,
                self.username,
                self.password,
                self.monitor_id is not None,
            ]
        )
        self._cache_lock = threading.Lock()
        self._cached_data = None
        self._cache_expires_at = 0.0

        # Uptime integration is optional. If not fully configured, keep cog inactive.
        if not self.enabled and any([self.api_url, self.username, self.password, monitor_id_raw]):
            self.logger.warning(
                "Uptime integration disabled due to incomplete/invalid configuration. "
                "Set UPTIME_URL, UPTIME_USERNAME, UPTIME_PASSWORD, UPTIME_MONITOR_ID."
            )

    def _parse_monitor_id(self, monitor_id_raw: Optional[str]) -> Optional[int]:
        """Parse and validate monitor ID from environment."""
        if not monitor_id_raw:
            return None
        try:
            return int(monitor_id_raw)
        except (TypeError, ValueError):
            self.logger.error(f"Invalid UPTIME_MONITOR_ID: '{monitor_id_raw}'. Must be an integer.")
            return None

    def get_uptime_data(
        self,
    ) -> Tuple[
        Optional[float],
        Optional[float],
        Optional[float],
        Optional[float],
        Optional[float],
        Optional[float],
    ]:
        """Fetch 24h/7d/30d uptime and online minutes for the configured monitor.

        Failures are cached too: while Kuma is down, every dashboard tick would
        otherwise wait on a fresh connection attempt.
        """
        if not self.enabled:
            return EMPTY_UPTIME
        with self._cache_lock:
            if self._cached_data is not None and time.monotonic() < self._cache_expires_at:
                return self._cached_data

            try:
                with UptimeKumaApi(self.api_url) as api:
                    api.login(self.username, self.password)
                    # One 30-day query covers the shorter windows as well.
                    beats_30d = api.get_monitor_beats(self.monitor_id, 30 * 24)
                self._cached_data = uptime_windows(beats_30d, datetime.now(timezone.utc))
            except UptimeKumaException as e:
                self.logger.error(f"Uptime Kuma API error: {e}")
                self._cached_data = EMPTY_UPTIME
            except Exception as e:
                # Connection refused/timeout/DNS errors are not UptimeKumaExceptions.
                # Without this they escape into the dashboard loop and cancel the whole
                # dashboard update instead of just dropping the uptime section.
                self.logger.error(f"Failed to fetch Uptime Kuma data: {e}")
                self._cached_data = EMPTY_UPTIME
            self._cache_expires_at = time.monotonic() + self.CACHE_TTL_SECONDS
            return self._cached_data

    def format_online_time(self, minutes: float) -> str:
        """Convert online time in minutes to a human-readable hours and minutes string."""
        hours = int(minutes // 60)
        remaining_minutes = int(minutes % 60)
        return f"{hours}h {remaining_minutes}m" if hours > 0 else f"{remaining_minutes}m"


async def setup(bot: commands.Bot) -> None:
    """Set up the Uptime cog for the bot."""
    await bot.add_cog(Uptime(bot))
