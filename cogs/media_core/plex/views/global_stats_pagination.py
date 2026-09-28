"""
Global Stats Pagination View for Plex integration.

This module contains the paginated view for displaying global server statistics
across multiple pages with a dark-mode styled peak hours chart.
"""

import discord
import logging
import io
from typing import Dict, Any, Optional

from ...shared.formatters import format_stats_time_range_label, resolve_user_display_name
from .chart_rendering import render_chart


logger = logging.getLogger("mediawatch_bot.media_core.plex.global_stats_pagination")


class GlobalStatsPaginationView(discord.ui.View):
    """Pagination view for global statistics with multiple pages."""

    def __init__(self, plex_core_instance, global_stats: Dict[str, Any]):
        super().__init__(timeout=180)
        self.plex_core = plex_core_instance
        self.global_stats = global_stats
        self.current_page = 0
        self.pages = []
        self.page_files = {}
        self.cached_chart = None
        self.logger = logger

    def _resolve_display_name(self, *candidate_names: Any) -> str:
        """Resolve a consistent display name using the shared Plex user mapping."""
        return resolve_user_display_name(
            getattr(self.plex_core, "user_mapping", {}),
            *candidate_names,
        )

    async def create_pages(self):
        """Create all pages for pagination."""
        self.pages = [
            await self._create_page_1(),
            await self._create_page_2(),
            await self._create_page_3(),
        ]

        chart_file = await self.generate_peak_hours_chart()
        if chart_file:
            self.page_files[1] = [chart_file]
            self.pages[1].set_image(url="attachment://peak_hours.png")

    async def _create_page_1(self) -> discord.Embed:
        """Page 1: Time stats, top movies, and top TV shows."""
        from ..utils import format_watch_time

        dashboard_config = self.plex_core.config.get("dashboard", {})
        icon_url = dashboard_config.get("icon_url", "")

        embed = discord.Embed(
            title="🌐 Global Server Statistics - Overview",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )

        dashboard_name = dashboard_config.get("name", "Plex Dashboard")
        if icon_url:
            embed.set_author(name=dashboard_name, icon_url=icon_url)
            embed.set_thumbnail(url=icon_url)

        watch_time = self.global_stats.get("watch_time", {})

        for period_key, period_name in [
            ("last_24h", "⏱️ Last 24h"),
            ("last_7d", "📅 Last 7 days"),
            ("last_30d", "📆 Last 30 days"),
        ]:
            if period_key in watch_time:
                stat = watch_time[period_key]
                plays = stat.get("total_plays", 0)
                time_seconds = stat.get("total_time", 0)
                if plays > 0 or time_seconds > 0:
                    time_formatted = format_watch_time(time_seconds)
                    value = f"**{plays} plays**\n`{time_formatted}`"
                    embed.add_field(name=period_name, value=value, inline=True)

        if "all_time" in watch_time and watch_time["all_time"].get("total_plays", 0) > 0:
            stat = watch_time["all_time"]
            plays = stat.get("total_plays", 0)
            time_seconds = stat.get("total_time", 0)
            time_formatted = format_watch_time(time_seconds)
            embed.add_field(
                name="🌍 All Time", value=f"**{plays} plays**\n`{time_formatted}`", inline=True
            )

            if "last_30d" in watch_time:
                stat_30d = watch_time["last_30d"]
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

            embed.add_field(name="\u200b", value="\u200b", inline=True)

        popular_movies = self.global_stats.get("popular_movies", [])
        if popular_movies:
            movies_lines = []
            for idx, movie in enumerate(popular_movies[:5], 1):
                title = movie.get("title", "Unknown")
                year = movie.get("year") or ""
                plays = movie.get("total_plays") or movie.get("plays") or movie.get("count") or 0
                if len(title) > 45:
                    title = title[:42] + "..."
                title_str = f"{title} ({year})" if year else title
                movies_lines.append(f"{idx}. **{title_str}** - **`{plays} plays`**")

            if movies_lines:
                embed.add_field(
                    name="🎬 Most Popular Movies (Last 30 days)",
                    value="\n".join(movies_lines),
                    inline=False,
                )

        top_tv = self.global_stats.get("top_tv", [])
        if top_tv:
            tv_lines = []
            for idx, show in enumerate(top_tv[:5], 1):
                title = show.get("title") or show.get("grandparent_title", "Unknown")
                year = show.get("year") or ""
                plays = show.get("total_plays") or show.get("plays") or show.get("count") or 0
                duration_seconds = show.get("total_duration", 0) or 0
                time_formatted = format_watch_time(duration_seconds)
                if len(title) > 40:
                    title = title[:37] + "..."
                title_str = f"{title} ({year})" if year else title
                tv_lines.append(
                    f"{idx}. **{title_str}** - **`{plays} plays`** | **`{time_formatted}`**"
                )

            if tv_lines:
                embed.add_field(
                    name="📺 Top TV Shows (Last 30 days)", value="\n".join(tv_lines), inline=False
                )

        footer_icon = dashboard_config.get("footer_icon_url", "")
        embed.set_footer(text="Page 1/3 • Global Server Statistics", icon_url=footer_icon)

        return embed

    async def _create_page_2(self) -> discord.Embed:
        """Page 2: Active user count, peak hours, and most active day."""
        dashboard_config = self.plex_core.config.get("dashboard", {})
        icon_url = dashboard_config.get("icon_url", "")

        embed = discord.Embed(
            title="🌐 Global Server Statistics - Activity",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        dashboard_name = dashboard_config.get("name", "Plex Dashboard")
        if icon_url:
            embed.set_author(name=dashboard_name, icon_url=icon_url)
            embed.set_thumbnail(url=icon_url)

        page2_time_range = self.global_stats.get("page2_time_range", 30)
        time_range_text = format_stats_time_range_label(page2_time_range)

        active_users = self.global_stats.get("active_users", 0)
        embed.add_field(
            name=f"👥 Active Users ({time_range_text})",
            value=f"**`{active_users}`** unique users",
            inline=False,
        )

        peak_hours = self.global_stats.get("peak_hours", {})
        if peak_hours:
            peak_hour = peak_hours.get("hour", "N/A")
            peak_count = peak_hours.get("count", 0)
            embed.add_field(
                name="⏰ Peak Hour",
                value=f"**`{peak_hour}:00`** with **`{peak_count}`** plays",
                inline=True,
            )

        most_active_day = self.global_stats.get("most_active_day", {})
        if most_active_day:
            day_name = most_active_day.get("day", "N/A")
            day_count = most_active_day.get("count", 0)
            embed.add_field(
                name="📅 Most Active Day",
                value=f"**`{day_name}`** with **`{day_count}`** plays",
                inline=True,
            )

        hourly_data = self.global_stats.get("hourly_activity", {})
        if hourly_data:
            embed.add_field(name="📊 Hourly Activity Chart", value="", inline=False)

        footer_icon = dashboard_config.get("footer_icon_url", "")
        embed.set_footer(text="Page 2/3 • Activity Statistics", icon_url=footer_icon)

        return embed

    async def _create_page_3(self) -> discord.Embed:
        """Page 3: Top 10 users by watchtime."""
        from ..utils import format_watch_time

        dashboard_config = self.plex_core.config.get("dashboard", {})
        icon_url = dashboard_config.get("icon_url", "")

        embed = discord.Embed(
            title=f"🌐 Top 10 Users by Watch Time ({format_stats_time_range_label(self.global_stats.get('page2_time_range', 30))})",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )

        dashboard_name = dashboard_config.get("name", "Plex Dashboard")
        if icon_url:
            embed.set_author(name=dashboard_name, icon_url=icon_url)
            embed.set_thumbnail(url=icon_url)

        top_users = self.global_stats.get("top_users", [])
        if top_users:
            user_lines = []
            for idx, user in enumerate(top_users[:10], 1):
                possible_usernames = [
                    user.get("user"),
                    user.get("username"),
                    user.get("friendly_name"),
                ]

                display_name = self._resolve_display_name(*possible_usernames)

                watch_time = user.get("total_duration", 0)
                plays = user.get("total_plays", 0)
                time_formatted = format_watch_time(watch_time)

                rank_emoji = ["🥇", "🥈", "🥉"][idx - 1] if idx <= 3 else "🔹"
                user_lines.append(
                    f"{rank_emoji} **{idx}.** **{display_name}**\n"
                    f"`{time_formatted}` • `{plays} plays`"
                )

            if user_lines:
                embed.add_field(name="\u200b", value="\n".join(user_lines), inline=False)
        else:
            embed.add_field(name="\u200b", value="No user data available", inline=False)

        footer_icon = dashboard_config.get("footer_icon_url", "")
        embed.set_footer(text="Page 3/3 • Top Users", icon_url=footer_icon)

        return embed

    async def generate_peak_hours_chart(self) -> Optional[discord.File]:
        """Generate a stacked bar chart for peak hours by media type."""
        return await render_chart(self._generate_peak_hours_chart)

    def _generate_peak_hours_chart(self) -> Optional[discord.File]:
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            if self.cached_chart is not None:
                self.cached_chart.seek(0)
                return discord.File(self.cached_chart, filename="peak_hours.png")

            hourly_data_by_type = self.global_stats.get("hourly_activity_by_type", {})
            page2_time_range = self.global_stats.get("page2_time_range", 30)

            if not hourly_data_by_type:
                return None

            hours = list(range(24))
            tv_counts = [hourly_data_by_type.get("tv", {}).get(str(h), 0) for h in hours]
            movie_counts = [hourly_data_by_type.get("movies", {}).get(str(h), 0) for h in hours]
            music_counts = [hourly_data_by_type.get("music", {}).get(str(h), 0) for h in hours]
            has_music = sum(music_counts) > 0

            plt.style.use("dark_background")
            fig, ax = plt.subplots(figsize=(14, 6.5), facecolor="#2b2b2b")
            ax.set_facecolor("#2b2b2b")

            legend_labels = []
            legend_colors = []

            if has_music:
                ax.bar(
                    hours,
                    music_counts,
                    color="#e85d75",
                    edgecolor="#2b2b2b",
                    linewidth=0.5,
                    width=0.85,
                )
                bottom_movies = music_counts
                legend_labels.append("Music")
                legend_colors.append("#e85d75")
            else:
                bottom_movies = [0] * len(hours)

            ax.bar(
                hours,
                movie_counts,
                bottom=bottom_movies,
                color="#f0f0f0",
                edgecolor="#2b2b2b",
                linewidth=0.5,
                width=0.85,
            )
            legend_labels.insert(0, "Movies")
            legend_colors.insert(0, "#f0f0f0")

            bottom_tv = [bottom_movies[i] + movie_counts[i] for i in range(len(hours))]
            ax.bar(
                hours,
                tv_counts,
                bottom=bottom_tv,
                color="#e5a00d",
                edgecolor="#2b2b2b",
                linewidth=0.5,
                width=0.85,
            )
            legend_labels.insert(0, "TV")
            legend_colors.insert(0, "#e5a00d")

            time_range_text = format_stats_time_range_label(page2_time_range)

            ax.text(
                0.005,
                1.02,
                "Play count by hour of day",
                transform=ax.transAxes,
                fontsize=14,
                color="#ffffff",
                fontweight="normal",
                verticalalignment="bottom",
            )
            ax.text(
                0.205,
                1.02,
                time_range_text,
                transform=ax.transAxes,
                fontsize=14,
                color="#999999",
                fontweight="normal",
                verticalalignment="bottom",
            )

            subtitle_text = "The combined total of tv, movies"
            if has_music:
                subtitle_text += ", and music"
            subtitle_text += " played per hour of the day."
            ax.text(
                0.005,
                1,
                subtitle_text,
                transform=ax.transAxes,
                fontsize=11,
                color="#999999",
                verticalalignment="top",
            )

            ax.set_xlabel("")
            ax.set_ylabel("")
            ax.set_xticks(hours)
            ax.set_xticklabels([f"{h:02d}" for h in hours], fontsize=9, color="#999999")
            ax.grid(axis="y", alpha=0.15, linestyle="-", color="#555555", linewidth=0.5)
            ax.set_axisbelow(True)
            ax.tick_params(axis="x", colors="#999999", length=0)
            ax.tick_params(axis="y", colors="#999999", labelsize=9, length=0)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.spines["left"].set_visible(False)
            ax.spines["bottom"].set_color("#555555")
            ax.spines["bottom"].set_linewidth(0.5)

            legend_handles = [
                plt.Rectangle((0, 0), 1, 1, facecolor=color, edgecolor="none")
                for color in legend_colors
            ]
            legend = ax.legend(
                legend_handles,
                legend_labels,
                loc="upper center",
                bbox_to_anchor=(0.5, -0.08),
                ncol=len(legend_labels),
                frameon=False,
                fontsize=10,
                handlelength=1.5,
                handleheight=1.0,
            )
            for text in legend.get_texts():
                text.set_color("#999999")

            plt.subplots_adjust(left=0.05, right=0.98, top=0.88, bottom=0.12)

            buf = io.BytesIO()
            plt.savefig(buf, format="png", facecolor="#2b2b2b", dpi=100, bbox_inches="tight")
            buf.seek(0)
            plt.close(fig)

            self.cached_chart = buf
            buf.seek(0)
            return discord.File(buf, filename="peak_hours.png")

        except Exception as e:
            self.logger.error(f"Error generating peak hours chart: {e}", exc_info=True)
            return None

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
