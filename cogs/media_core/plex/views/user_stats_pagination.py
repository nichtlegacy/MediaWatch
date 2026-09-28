"""
User Stats Pagination View for Plex integration.

This module contains the paginated view for displaying user statistics
across multiple pages with behavior, devices, and top content information.
"""

import discord
import logging
import io
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

from ...shared.formatters import format_stats_time_range_label, resolve_user_display_name
from .chart_rendering import render_chart


logger = logging.getLogger("mediawatch_bot.media_core.plex.user_stats_pagination")


class UserStatsPaginationView(discord.ui.View):
    """Pagination view for user statistics with multiple pages."""

    MAX_CHART_CACHE_ENTRIES = 100
    _daily_chart_cache: Dict[Tuple[str, int, str], bytes] = {}

    def __init__(
        self, plex_core_instance, user_id: str, user_display: str, stats_data: Dict[str, Any]
    ):
        super().__init__(timeout=180)
        self.plex_core = plex_core_instance
        self.user_id = user_id
        self.user_display = resolve_user_display_name(
            getattr(plex_core_instance, "user_mapping", {}),
            user_display,
            fallback=f"User {user_id}",
        )
        self.stats_data = stats_data
        self.current_page = 0
        self.pages = []
        self.page_files = {}
        self.cached_chart = None
        self.logger = logger

        from ..utils.config_helper import UserStatsConfig

        self.config = UserStatsConfig(plex_core_instance.config)

    def _footer_text(self, page_name: str, label: str) -> str:
        """Build the footer text with the page position among the enabled pages."""
        enabled_pages = self.config.get_enabled_pages()
        position = enabled_pages.index(page_name) + 1 if page_name in enabled_pages else 1
        return f"Page {position}/{len(enabled_pages)} • {label}"

    async def create_pages(self):
        """Create all pages for pagination based on enabled pages in config."""
        enabled_pages = self.config.get_enabled_pages()

        page_creators = {
            "behavior": self._create_page_behavior,
            "devices": self._create_page_devices,
            "top_content": self._create_page_top_content,
        }

        page_index = 0
        for page_name in enabled_pages:
            if page_name in page_creators:
                page = await page_creators[page_name]()
                if page:
                    self.pages.append(page)
                    # Add chart file for devices page
                    if page_name == "devices":
                        chart_file = await self.generate_dual_pie_chart()
                        if chart_file:
                            self.page_files[page_index] = [chart_file]
                            self.pages[-1].set_image(url="attachment://user_stats_chart.png")
                    page_index += 1

    async def _create_page_behavior(self) -> Optional[discord.Embed]:
        """Page 1: Watch Behavior & Streak."""
        from ..utils import format_watch_time, calculate_avg_session_length

        dashboard_config = self.plex_core.config.get("dashboard", {})
        icon_url = dashboard_config.get("icon_url", "")
        dashboard_name = dashboard_config.get("name", "Plex Dashboard")

        embed = discord.Embed(
            title=f"📊 User Statistics: {self.user_display}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        if icon_url:
            embed.set_author(name=dashboard_name, icon_url=icon_url)
            embed.set_thumbnail(url=icon_url)

        watch_time_stats = self.stats_data.get("watch_time_stats", {})

        # Time stats row 1: 24h, 7d, 30d (like global stats)
        for period_key, period_name in [
            ("last_24h", "⏱️ Last 24h"),
            ("last_7d", "📅 Last 7 days"),
            ("last_30d", "📆 Last 30 days"),
        ]:
            if period_key in watch_time_stats:
                stat = watch_time_stats[period_key]
                plays = stat.get("total_plays", 0)
                time_seconds = stat.get("total_time", 0)
                if plays > 0 or time_seconds > 0:
                    time_formatted = format_watch_time(time_seconds)
                    value = f"**{plays} plays**\n`{time_formatted}`"
                    embed.add_field(name=period_name, value=value, inline=True)

        # Row 2: All Time, Avg per day, Avg Session (like global stats)
        if (
            "all_time" in watch_time_stats
            and watch_time_stats["all_time"].get("total_plays", 0) > 0
        ):
            stat = watch_time_stats["all_time"]
            plays = stat.get("total_plays", 0)
            time_seconds = stat.get("total_time", 0)
            time_formatted = format_watch_time(time_seconds)
            embed.add_field(
                name="🌍 All Time", value=f"**{plays} plays**\n`{time_formatted}`", inline=True
            )

            # Avg per day from 30d
            if "last_30d" in watch_time_stats:
                stat_30d = watch_time_stats["last_30d"]
                plays_30d = stat_30d.get("total_plays", 0)
                time_30d = stat_30d.get("total_time", 0)
                avg_plays = plays_30d / 30 if plays_30d > 0 else 0
                avg_time = time_30d / 30 if time_30d > 0 else 0
                avg_time_formatted = format_watch_time(int(avg_time))
                embed.add_field(
                    name="📊 Avg per day",
                    value=f"**{avg_plays:.1f} plays**\n`{avg_time_formatted}`",
                    inline=True,
                )

            # Avg Session
            avg_session = calculate_avg_session_length(time_seconds, plays)
            if avg_session > 0:
                avg_session_formatted = format_watch_time(avg_session)
                embed.add_field(
                    name="⏱️ Avg Session", value=f"`{avg_session_formatted}`", inline=True
                )

        # Streak and Genre at the end
        watch_streak = self.stats_data.get("watch_streak")
        favorite_genre = self.stats_data.get("favorite_genre")

        if watch_streak and watch_streak > 0:
            embed.add_field(name="🔥 Watch Streak", value=f"**{watch_streak} days**", inline=True)

        if favorite_genre:
            embed.add_field(name="🎭 Favorite Genre", value=f"**{favorite_genre}**", inline=True)

        if watch_streak or favorite_genre:
            embed.add_field(name="\u200b", value="\u200b", inline=True)

        footer_icon = dashboard_config.get("footer_icon_url", "")
        embed.set_footer(text=self._footer_text("behavior", "Watch Behavior"), icon_url=footer_icon)

        return embed

    async def _create_page_devices(self) -> Optional[discord.Embed]:
        """Page 2: Devices & Content Types with pie charts."""
        dashboard_config = self.plex_core.config.get("dashboard", {})
        icon_url = dashboard_config.get("icon_url", "")
        dashboard_name = dashboard_config.get("name", "Plex Dashboard")
        time_range = self.stats_data.get("time_range", 0)
        time_range_text = format_stats_time_range_label(time_range)

        embed = discord.Embed(
            title=f"📊 User Statistics: {self.user_display}",
            description=f"**Activity & Devices** • {time_range_text}",
            color=discord.Color.purple(),
            timestamp=discord.utils.utcnow(),
        )

        if icon_url:
            embed.set_author(name=dashboard_name, icon_url=icon_url)

        peak_hour = self.stats_data.get("peak_hour")
        if peak_hour:
            embed.add_field(
                name="⏰ Peak Hour",
                value=f"**`{peak_hour['hour']:02d}:00`**\n`{peak_hour['count']} plays`",
                inline=True,
            )

        most_active_day = self.stats_data.get("most_active_day")
        if most_active_day:
            embed.add_field(
                name="📅 Most Active Day",
                value=f"**{most_active_day['day']}**\n`{most_active_day['count']} plays`",
                inline=True,
            )

        most_active_device = self.stats_data.get("most_active_device")
        if most_active_device:
            from ..utils import format_watch_time

            device_time = format_watch_time(int(most_active_device.get("total_time", 0)))
            device_name = most_active_device.get("name", "Unknown")
            if len(device_name) > 22:
                device_name = device_name[:19] + "..."

            embed.add_field(
                name="📱 Most Active Device",
                value=f"**{device_name}**\n`{device_time}`",
                inline=True,
            )

        top_content_type = self.stats_data.get("top_content_type")
        if top_content_type:
            from ..utils import format_watch_time

            content_time = format_watch_time(int(top_content_type.get("time", 0)))
            embed.add_field(
                name="🎬 Top Content Type",
                value=f"**{top_content_type['label']}**\n`{top_content_type['percentage']:.1f}% • {content_time}`",
                inline=True,
            )

        if len(embed.fields) % 3 != 0:
            while len(embed.fields) % 3 != 0:
                embed.add_field(name="\u200b", value="\u200b", inline=True)

        footer_icon = dashboard_config.get("footer_icon_url", "")
        embed.set_footer(
            text=self._footer_text("devices", "Activity & Devices"), icon_url=footer_icon
        )

        return embed

    async def generate_dual_pie_chart(self) -> Optional[discord.File]:
        """Generate dual pie charts for devices and content types."""
        return await render_chart(self._generate_dual_pie_chart)

    def _generate_dual_pie_chart(self) -> Optional[discord.File]:
        try:
            import matplotlib
            import numpy as np

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            from ..utils import format_watch_time

            player_stats = self.stats_data.get("player_stats", [])
            content_breakdown = self.stats_data.get("content_breakdown", {})
            time_range = self.stats_data.get("time_range", 0)

            if not player_stats and not content_breakdown:
                return None

            cache_date = datetime.utcnow().strftime("%Y-%m-%d")
            cache_key = (self.user_id, time_range, cache_date)

            # Keep cache daily. Old charts auto-drop when day changes.
            stale_keys = [key for key in self._daily_chart_cache if key[2] != cache_date]
            for key in stale_keys:
                self._daily_chart_cache.pop(key, None)

            cached_bytes = self._daily_chart_cache.get(cache_key)
            if cached_bytes is not None:
                self.cached_chart = io.BytesIO(cached_bytes)
                self.cached_chart.seek(0)
                return discord.File(io.BytesIO(cached_bytes), filename="user_stats_chart.png")
            if self.cached_chart is not None:
                self.cached_chart.seek(0)
                return discord.File(self.cached_chart, filename="user_stats_chart.png")

            # Setup matplotlib with dark theme like global stats
            plt.style.use("dark_background")
            fig, axes = plt.subplots(1, 2, figsize=(14, 7), facecolor="#2b2b2b")

            # Time range text like global stats
            time_range_text = format_stats_time_range_label(time_range)

            fig.text(
                0.055,
                0.945,
                "Watch time distribution by device and content type",
                fontsize=14,
                color="#ffffff",
                fontweight="normal",
                ha="left",
                va="bottom",
            )
            fig.text(
                0.545,
                0.945,
                time_range_text,
                fontsize=14,
                color="#999999",
                fontweight="normal",
                ha="left",
                va="bottom",
            )
            fig.text(
                0.055,
                0.905,
                "Share of total watch time split across playback devices and media types.",
                fontsize=11,
                color="#999999",
                fontweight="normal",
                ha="left",
                va="bottom",
            )

            # Colors matching global stats for content
            content_colors = {
                "tv": "#e5a00d",  # Gold for TV
                "movie": "#f0f0f0",  # White for Movies
                "music": "#e85d75",  # Pink for Music
            }

            # Device colors - distinct rainbow palette
            device_colors = ["#4a9eff", "#9b59b6", "#2ecc71", "#e74c3c", "#f39c12"]

            # Left pie: Top Devices
            ax1 = axes[0]
            ax1.set_facecolor("#2b2b2b")

            if player_stats:
                device_labels = []
                device_times = []
                for player in player_stats[:5]:
                    name = (
                        player.get("player_name")
                        or player.get("platform")
                        or player.get("product")
                        or "Unknown"
                    )
                    time_sec = player.get("total_time", 0) or player.get("total_duration", 0) or 0
                    if time_sec > 0:
                        device_labels.append(name)
                        device_times.append(time_sec)

                if device_times:
                    total_time = sum(device_times)
                    wedges, _ = ax1.pie(
                        device_times,
                        colors=device_colors[: len(device_times)],
                        startangle=90,
                        wedgeprops={"edgecolor": "#2b2b2b", "linewidth": 2},
                        radius=1.0,
                    )
                    legend_labels = []
                    for label, time_sec in zip(device_labels, device_times, strict=True):
                        pct = time_sec / total_time * 100
                        time_fmt = format_watch_time(time_sec)

                        if pct < 0.1 and pct > 0:
                            pct_str = "< 0.1%"
                        else:
                            pct_str = f"{pct:.1f}%"

                        legend_labels.append(f"{label} ({pct_str} • {time_fmt})")

                    legend = ax1.legend(
                        wedges,
                        legend_labels,
                        loc="upper center",
                        bbox_to_anchor=(0.5, -0.12),
                        ncol=1,
                        frameon=False,
                        fontsize=9,
                        handlelength=1.3,
                        handleheight=1.0,
                    )
                    for text in legend.get_texts():
                        text.set_color("#999999")

                    for wedge, time_sec in zip(wedges, device_times, strict=True):
                        pct = time_sec / total_time * 100

                        if pct >= 5:
                            angle = (wedge.theta2 + wedge.theta1) / 2
                            x = 0.6 * np.cos(np.deg2rad(angle))
                            y = 0.6 * np.sin(np.deg2rad(angle))
                            ax1.text(
                                x,
                                y,
                                f"{pct:.1f}%",
                                ha="center",
                                va="center",
                                fontsize=10,
                                fontweight="bold",
                                color="#2b2b2b",
                            )
                else:
                    ax1.text(
                        0.5,
                        0.5,
                        "No device data",
                        ha="center",
                        va="center",
                        color="#999999",
                        fontsize=12,
                        transform=ax1.transAxes,
                    )
            else:
                ax1.text(
                    0.5,
                    0.5,
                    "No device data",
                    ha="center",
                    va="center",
                    color="#999999",
                    fontsize=12,
                    transform=ax1.transAxes,
                )

            ax1.set_title("Devices", color="#ffffff", fontsize=13, fontweight="normal", pad=15)

            # Right pie: Content Types
            ax2 = axes[1]
            ax2.set_facecolor("#2b2b2b")

            if content_breakdown:
                type_names = {"tv": "TV Shows", "movie": "Movies", "music": "Music"}
                content_labels = []
                content_times = []
                colors_used = []

                for content_type, data in content_breakdown.items():
                    plays = data.get("plays", 0)
                    time_sec = data.get("time", 0)
                    if plays > 0:
                        content_labels.append(
                            type_names.get(content_type, content_type.capitalize())
                        )
                        content_times.append(time_sec)
                        colors_used.append(content_colors.get(content_type, "#888888"))

                if content_times:
                    total_time = sum(content_times)
                    wedges, _ = ax2.pie(
                        content_times,
                        colors=colors_used,
                        startangle=90,
                        wedgeprops={"edgecolor": "#2b2b2b", "linewidth": 2},
                        radius=1.0,
                    )
                    legend_labels = []
                    for label, time_sec in zip(content_labels, content_times, strict=True):
                        pct = time_sec / total_time * 100
                        time_fmt = format_watch_time(time_sec)

                        if pct < 0.1 and pct > 0:
                            pct_str = "< 0.1%"
                        else:
                            pct_str = f"{pct:.1f}%"

                        legend_labels.append(f"{label} ({pct_str} • {time_fmt})")

                    legend = ax2.legend(
                        wedges,
                        legend_labels,
                        loc="upper center",
                        bbox_to_anchor=(0.5, -0.12),
                        ncol=1,
                        frameon=False,
                        fontsize=9,
                        handlelength=1.3,
                        handleheight=1.0,
                    )
                    for text in legend.get_texts():
                        text.set_color("#999999")

                    for wedge, time_sec in zip(wedges, content_times, strict=True):
                        pct = time_sec / total_time * 100

                        if pct >= 5:
                            angle = (wedge.theta2 + wedge.theta1) / 2
                            x = 0.6 * np.cos(np.deg2rad(angle))
                            y = 0.6 * np.sin(np.deg2rad(angle))
                            ax2.text(
                                x,
                                y,
                                f"{pct:.1f}%",
                                ha="center",
                                va="center",
                                fontsize=10,
                                fontweight="bold",
                                color="#2b2b2b",
                            )
                else:
                    ax2.text(
                        0.5,
                        0.5,
                        "No content data",
                        ha="center",
                        va="center",
                        color="#999999",
                        fontsize=12,
                        transform=ax2.transAxes,
                    )
            else:
                ax2.text(
                    0.5,
                    0.5,
                    "No content data",
                    ha="center",
                    va="center",
                    color="#999999",
                    fontsize=12,
                    transform=ax2.transAxes,
                )

            ax2.set_title(
                "Content Types", color="#ffffff", fontsize=13, fontweight="normal", pad=15
            )

            plt.tight_layout(rect=[0.02, 0.08, 0.98, 0.86])

            # Save to buffer
            buf = io.BytesIO()
            plt.savefig(buf, format="png", facecolor="#2b2b2b", dpi=100, bbox_inches="tight")
            buf.seek(0)
            plt.close(fig)

            chart_bytes = buf.getvalue()
            self._daily_chart_cache[cache_key] = chart_bytes
            while len(self._daily_chart_cache) > self.MAX_CHART_CACHE_ENTRIES:
                self._daily_chart_cache.pop(next(iter(self._daily_chart_cache)))
            self.cached_chart = io.BytesIO(chart_bytes)
            self.cached_chart.seek(0)
            return discord.File(io.BytesIO(chart_bytes), filename="user_stats_chart.png")

        except Exception as e:
            self.logger.error(f"Error generating dual pie chart: {e}", exc_info=True)
            return None

    async def _create_page_top_content(self) -> Optional[discord.Embed]:
        """Page 3: Top TV Shows."""
        from ..utils import format_watch_time

        dashboard_config = self.plex_core.config.get("dashboard", {})
        icon_url = dashboard_config.get("icon_url", "")
        dashboard_name = dashboard_config.get("name", "Plex Dashboard")

        # Get time range for display
        time_range = self.stats_data.get("time_range", 0)
        time_range_text = format_stats_time_range_label(time_range)

        embed = discord.Embed(
            title=f"📊 User Statistics: {self.user_display}",
            description=f"**Top TV Shows** • {time_range_text}",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )

        if icon_url:
            embed.set_author(name=dashboard_name, icon_url=icon_url)
            embed.set_thumbnail(url=icon_url)

        # Top TV Shows - Main content
        top_shows = self.stats_data.get("top_shows", [])
        if top_shows:
            max_shows = min(self.config.get_top_tv_count(), len(top_shows))
            tv_lines = []

            for idx, show in enumerate(top_shows[:max_shows], 1):
                title = show.get("title", "Unknown")
                plays = show.get("total_plays") or show.get("plays", 0)
                duration = show.get("total_duration", 0)
                time_formatted = format_watch_time(duration)

                if len(title) > 40:
                    title = title[:37] + "..."

                # Top 3: Prominent ANSI blocks
                if idx == 1:
                    tv_lines.append(
                        f"```ansi\n\u001b[1;33m🥇 1. {title}\u001b[0m\n\u001b[0;37m   {plays} plays • {time_formatted}\u001b[0m\n```"
                    )
                elif idx == 2:
                    tv_lines.append(
                        f"```ansi\n\u001b[1;37m🥈 2. {title}\u001b[0m\n\u001b[0;37m   {plays} plays • {time_formatted}\u001b[0m\n```"
                    )
                elif idx == 3:
                    tv_lines.append(
                        f"```ansi\n\u001b[0;33m🥉 3. {title}\u001b[0m\n\u001b[0;37m   {plays} plays • {time_formatted}\u001b[0m\n```"
                    )
                # 4-10: Compact with emoji indicators
                else:
                    rank_emoji = "🏅" if idx <= 5 else "📊"
                    tv_lines.append(
                        f"{rank_emoji} **{idx}.** `{title}` — **{time_formatted}** • `{plays} plays`"
                    )

            if tv_lines:
                embed.add_field(
                    name="📺 Most Watched Shows", value="\n".join(tv_lines), inline=False
                )
        else:
            embed.add_field(
                name="📺 Most Watched Shows", value="No TV show data available", inline=False
            )

        footer_icon = dashboard_config.get("footer_icon_url", "")
        embed.set_footer(text=self._footer_text("top_content", "Top Content"), icon_url=footer_icon)

        return embed

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary, disabled=True)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go to previous page."""
        await interaction.response.defer()
        self.current_page = max(0, self.current_page - 1)
        await self.update_message(interaction)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go to next page."""
        await interaction.response.defer()
        self.current_page = min(len(self.pages) - 1, self.current_page + 1)
        await self.update_message(interaction)

    async def update_message(self, interaction: discord.Interaction):
        """Update the message with the current page."""
        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == len(self.pages) - 1

        embed = self.pages[self.current_page]
        files = self.page_files.get(self.current_page, [])

        if files:
            new_files = []
            for f in files:
                f.fp.seek(0)
                new_files.append(discord.File(f.fp, filename=f.filename))
            await interaction.edit_original_response(embed=embed, view=self, attachments=new_files)
        else:
            await interaction.edit_original_response(embed=embed, view=self, attachments=[])
