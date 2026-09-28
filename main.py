import discord
from discord.ext import commands
import os
import logging
import inspect
from logging.handlers import TimedRotatingFileHandler
from dotenv import load_dotenv
import asyncio
import platform
import signal
from typing import List, Optional
import version
from cogs.media_core.shared import runtime_state
from cogs.media_core.shared.config import ConfigError, ensure_config_yaml, load_config
from cogs.media_core.shared.config_utils import get_config_path
from cogs.media_core.shared.env_validation import parse_authorized_users, validate_environment

# Configure event loop policy for Windows compatibility
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

RUNNING_IN_DOCKER = os.getenv("RUNNING_IN_DOCKER", "false").lower() == "true"

if not RUNNING_IN_DOCKER:
    load_dotenv()  # Load environment variables from .env file

TOKEN = os.getenv("DISCORD_TOKEN")
AUTHORIZED_USERS: List[int] = parse_authorized_users(os.getenv("DISCORD_AUTHORIZED_USERS"))
GUILD_ID = os.getenv("DISCORD_GUILD_ID")


def get_media_server_type() -> str:
    """Get the media server type from config.yaml.

    Uses centralized config utility from media_core.shared.

    Returns:
        Server type string ('plex' or 'jellyfin'), defaults to 'plex'
    """
    try:
        from cogs.media_core.shared.config_utils import get_server_type

        return get_server_type()
    except ImportError:
        # Fallback if media_core not yet loaded
        import yaml

        config_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data", "config.yaml"
        )

        if not os.path.exists(config_file):
            return "plex"

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            server_type = config.get("media_server", {}).get("type", "").lower()
            return server_type if server_type in ("plex", "jellyfin") else "plex"
        except Exception:
            return "plex"


# Setup logging with rotation
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
bot_logger = logging.getLogger("mediawatch_bot")
bot_logger.setLevel(logging.DEBUG)

formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

if RUNNING_IN_DOCKER:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    bot_logger.addHandler(console_handler)
else:
    file_handler = TimedRotatingFileHandler(
        filename=os.path.join(LOG_DIR, "mediawatch_debug.log"),
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    bot_logger.addHandler(file_handler)


# Initialize bot with intents and command prefix
class MediaWatchBot(commands.Bot):
    """Bot subclass that coordinates graceful cog shutdown."""

    async def setup_hook(self) -> None:
        """Load extensions before the websocket connects and sync commands to the configured guild."""
        global cogs_loaded

        async with startup_lock:
            if not cogs_loaded:
                await load_cogs()
                cogs_loaded = True

            try:
                sync_guild = get_command_guild()
                if sync_guild is not None:
                    # Publishes the global tree into the configured guild only.
                    await sync_command_tree(guild=sync_guild)
                    await clear_stale_global_commands()
            except Exception as e:
                # setup_hook runs inside login(); anything escaping here stops the
                # bot from ever coming online. A failed command sync must degrade
                # to "commands are stale" instead of "the dashboard is dead".
                bot_logger.error(f"Failed to sync command tree during setup: {e}")

    async def close(self) -> None:
        """Attempt to flush cog-specific cleanup before closing Discord connections."""
        for cog_name, cog in list(self.cogs.items()):
            shutdown = getattr(cog, "shutdown", None)
            if shutdown is None:
                continue

            try:
                result = shutdown()
                if inspect.isawaitable(result):
                    await result
                bot_logger.info(f"Gracefully shut down cog: {cog_name}")
            except Exception as e:
                bot_logger.error(f"Error while shutting down cog {cog_name}: {e}")

        await super().close()


# Only message_content is privileged here; it is required for the `!sync` prefix command.
# members/presences are not used anywhere, so they stay off.
intents = discord.Intents.default()
intents.message_content = True
bot = MediaWatchBot(command_prefix="!", intents=intents, max_messages=None)
tree = bot.tree
startup_lock = asyncio.Lock()
cogs_loaded = False
commands_synced = False

# Resolved from this file, not the working directory: load_cogs() only logs a
# failure, so a bot started from elsewhere would come up with zero cogs and no
# obvious error. Docker sets WORKDIR, a local `python /path/to/main.py` does not.
COGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cogs")

MEDIA_CORE_PACKAGE = "cogs.media_core"
MEDIA_CORE_ALIASES = {"media_core", "media-core", "mediacore"}
SUPPORTED_MEDIA_SERVER_TYPES = {"plex", "jellyfin"}


def is_authorized(interaction: discord.Interaction) -> bool:
    """Check if the user is authorized to execute privileged commands."""
    return interaction.user.id in AUTHORIZED_USERS


def normalize_cog_name(cog_name: str) -> str:
    """Normalize user-facing cog names into internal identifiers."""
    normalized = cog_name.strip().lower().replace("-", "_")
    if normalized in MEDIA_CORE_ALIASES:
        return "media_core"
    return normalized


def get_configured_media_core_extension() -> str:
    """Return the media core extension path implied by config.yaml."""
    return f"{MEDIA_CORE_PACKAGE}.{get_media_server_type()}"


def get_active_media_core_extension(bot_instance: Optional[commands.Bot] = None) -> Optional[str]:
    """Return the currently loaded media core extension, if any."""
    bot_instance = bot_instance or bot
    for extension_name in bot_instance.extensions:
        if not extension_name.startswith(f"{MEDIA_CORE_PACKAGE}."):
            continue

        platform_name = extension_name.rsplit(".", 1)[-1]
        if platform_name in SUPPORTED_MEDIA_SERVER_TYPES:
            return extension_name
    return None


def resolve_extension_name(
    cog_name: str,
    *,
    prefer_configured_media_core: bool = False,
    bot_instance: Optional[commands.Bot] = None,
) -> str:
    """Resolve a user-facing cog name into the concrete extension path."""
    normalized = normalize_cog_name(cog_name)
    if normalized == "media_core":
        if prefer_configured_media_core:
            return get_configured_media_core_extension()
        return (
            get_active_media_core_extension(bot_instance) or get_configured_media_core_extension()
        )
    return f"cogs.{normalized}"


def is_cog_loaded(cog_name: str, *, bot_instance: Optional[commands.Bot] = None) -> bool:
    """Check whether the resolved extension for a cog is currently loaded."""
    bot_instance = bot_instance or bot
    return resolve_extension_name(cog_name, bot_instance=bot_instance) in bot_instance.extensions


def get_cog_display_name(cog_name: str, *, bot_instance: Optional[commands.Bot] = None) -> str:
    """Build the display label used in `/cogs` output."""
    normalized = normalize_cog_name(cog_name)
    base_name = normalized.replace("_", " ").title()

    if normalized != "media_core":
        return base_name

    resolved_extension = resolve_extension_name(normalized, bot_instance=bot_instance)
    platform_name = resolved_extension.rsplit(".", 1)[-1]
    if platform_name in SUPPORTED_MEDIA_SERVER_TYPES:
        return f"{base_name} ({platform_name.title()})"
    return base_name


def get_command_guild() -> Optional[discord.Object]:
    """Return the configured guild that should receive all application commands."""
    if not GUILD_ID:
        return None

    try:
        return discord.Object(id=int(GUILD_ID))
    except ValueError:
        bot_logger.error(f"Invalid DISCORD_GUILD_ID: {GUILD_ID}")
        return None


async def reload_runtime_config(bot_instance: Optional[commands.Bot] = None) -> List[str]:
    """Reload config-driven cogs without restarting the whole bot.

    Raises:
        ConfigError: config.yaml is unusable. Raised before any extension is
            touched, so the running cogs keep their current configuration.
    """
    bot_instance = bot_instance or bot
    load_config(get_config_path())

    actions: List[str] = []
    active_media_extension = get_active_media_core_extension(bot_instance)
    desired_media_extension = get_configured_media_core_extension()

    if active_media_extension == desired_media_extension:
        if desired_media_extension in bot_instance.extensions:
            await bot_instance.reload_extension(desired_media_extension)
            actions.append(f"reloaded `{desired_media_extension}`")
        else:
            await bot_instance.load_extension(desired_media_extension)
            actions.append(f"loaded `{desired_media_extension}`")
    else:
        if active_media_extension:
            await bot_instance.unload_extension(active_media_extension)
            actions.append(f"unloaded `{active_media_extension}`")

        try:
            await bot_instance.load_extension(desired_media_extension)
            actions.append(f"loaded `{desired_media_extension}`")
        except Exception:
            if active_media_extension:
                await bot_instance.load_extension(active_media_extension)
                actions.append(f"restored `{active_media_extension}`")
            raise

    if "cogs.sabnzbd" in bot_instance.extensions:
        await bot_instance.reload_extension("cogs.sabnzbd")
        actions.append("reloaded `cogs.sabnzbd`")

    return actions


async def _unregister_global_commands() -> List[discord.app_commands.AppCommand]:
    """Drop the global command registration at Discord without emptying the local tree.

    `tree.clear_commands(guild=None)` also removes the commands from the
    in-process tree, and nothing ever puts them back: after the startup cleanup
    a single `!sync clear` would leave both containers empty, so `!sync copy`
    copies nothing and the bot has no slash commands until it is restarted.

    Overwriting the global scope with an empty payload is the exact request
    `tree.sync()` sends for an empty tree, minus the local mutation.
    """
    if bot.application_id is None:
        raise discord.app_commands.MissingApplicationID

    await bot.http.bulk_upsert_global_commands(bot.application_id, [])
    return []


async def sync_command_tree(
    *,
    guild: Optional[discord.abc.Snowflake] = None,
    clear_guild_commands: bool = False,
    clear_global_commands: bool = False,
) -> List[discord.app_commands.AppCommand]:
    """Push the current application command tree to Discord."""
    global commands_synced

    if clear_guild_commands and guild is None:
        raise ValueError("clear_guild_commands requires a guild target")
    if clear_global_commands and guild is not None:
        raise ValueError("clear_global_commands cannot be combined with a guild target")

    if guild is not None and not clear_guild_commands:
        # Every command lives in the global container - cogs register there
        # (commands.GroupCog does), and nothing in MediaWatch ever registers a
        # guild-only command. A guild sync that skips this would publish the
        # snapshot taken at startup, so a command added by /load would never
        # appear and one removed by /unload would never disappear.
        #
        # Clearing first matters: copy_global_to() merges into the existing
        # guild container and never removes, so an unloaded command would
        # survive there forever. Clear + copy makes the guild scope an exact
        # mirror of the local global tree.
        tree.clear_commands(guild=guild)
        tree.copy_global_to(guild=guild)
    if clear_guild_commands:
        tree.clear_commands(guild=guild)

    if clear_global_commands:
        synced: List[discord.app_commands.AppCommand] = await _unregister_global_commands()
    else:
        synced = await tree.sync(guild=guild)
    commands_synced = True
    scope = f"guild {guild.id}" if guild is not None else "global"
    bot_logger.info(f"Command tree synced ({scope})")
    return synced


async def clear_stale_global_commands() -> bool:
    """Unregister the globally published commands left over from MediaWatch 1.x.

    1.x called `tree.sync()` without a guild, so every command was registered
    globally. 2.0 publishes guild-scoped, which would leave an upgraded bot
    showing each command twice - once from 1.x, once from 2.0.

    Runs after the guild sync, so `copy_global_to()` has already put the
    commands into the guild scope and only the global registration is dropped.
    The outcome is persisted in data/runtime_state.json, so this costs exactly
    one extra API call per installation instead of one per start.

    Returns:
        True if the global scope was cleared during this call
    """
    if runtime_state.global_commands_cleared():
        return False

    await sync_command_tree(clear_global_commands=True)
    runtime_state.mark_global_commands_cleared()
    bot_logger.info(
        "Cleared globally registered slash commands (1.x leftovers); "
        "commands are published to the configured guild from now on."
    )
    return True


async def load_cogs() -> None:
    """Load all Python files and packages in the 'cogs' directory as bot extensions.

    Special handling for media_core: loads the appropriate platform-specific cog
    based on media_server.type in config.yaml (plex or jellyfin).
    """
    # Get the configured media server type
    media_server_type = get_media_server_type()
    bot_logger.info(f"Media server type: {media_server_type}")

    # Skip list for cogs handled specially
    skip_cogs = {"media_core"}  # media_core loaded specially based on config

    for filename in sorted(os.listdir(COGS_DIR)):
        # Skip specially handled cogs
        if filename.replace(".py", "") in skip_cogs:
            continue

        # Load .py files (excluding __init__.py and __pycache__)
        if filename.endswith(".py") and not filename.startswith("__"):
            ext_name = f"cogs.{filename[:-3]}"
            if ext_name in bot.extensions:
                continue
            try:
                await bot.load_extension(ext_name)
                bot_logger.info(f"Loaded cog: {filename[:-3]}")
            except commands.ExtensionError as e:
                bot_logger.error(f"Failed to load cog {filename[:-3]}: {e}")

        # Load packages (directories with __init__.py)
        elif os.path.isdir(os.path.join(COGS_DIR, filename)) and not filename.startswith("__"):
            # Skip specially handled directories
            if filename in skip_cogs:
                continue

            init_file = os.path.join(COGS_DIR, filename, "__init__.py")
            if os.path.exists(init_file):
                ext_name = f"cogs.{filename}"
                if ext_name in bot.extensions:
                    continue
                try:
                    await bot.load_extension(ext_name)
                    bot_logger.info(f"Loaded cog package: {filename}")
                except commands.ExtensionError as e:
                    bot_logger.error(f"Failed to load cog package {filename}: {e}")

    # Load the appropriate media core cog based on configuration
    media_cog_path = f"{MEDIA_CORE_PACKAGE}.{media_server_type}"
    if media_cog_path in bot.extensions:
        return
    try:
        await bot.load_extension(media_cog_path)
        bot_logger.info(f"Loaded media core cog: {media_cog_path}")
    except commands.ExtensionError as e:
        bot_logger.error(f"Failed to load media core cog {media_cog_path}: {e}")


@bot.event
async def on_ready() -> None:
    """Handle bot startup logging after setup work has finished."""
    bot_logger.info(
        f"{version.__project_name__} v{version.__version__} is online as {bot.user.name}"
    )
    bot_logger.info(f"GitHub: {version.__github_url__}")


def _create_embed(title: str, description: str, color: discord.Color) -> discord.Embed:
    """Create a standardized embed for responses."""
    embed = discord.Embed(
        title=title, description=description, color=color, timestamp=discord.utils.utcnow()
    )
    embed.set_footer(text=f"{version.__project_name__} v{version.__version__}")
    # Use bot icon as author
    if bot.user:
        embed.set_author(name="MediaWatch System", icon_url=bot.user.display_avatar.url)
    return embed


def _command_sync_hint() -> str:
    """Return a short hint describing how to publish local slash-command changes."""
    return "If this changes slash commands, publish them with `!sync guild`."


@bot.command(name="sync")
async def sync_prefix_command(ctx: commands.Context, scope: Optional[str] = None) -> None:
    """Manually sync application commands to Discord."""
    if ctx.author.id not in AUTHORIZED_USERS:
        await ctx.send("❌ You are not authorized to execute this command.")
        return

    # guild, not global: the commands already live in the guild scope, so a
    # global sync would show each of them twice in this server.
    scope = (scope or "guild").lower()

    try:
        if scope in {"global", "g"}:
            synced = await sync_command_tree()
            await ctx.send(f"Synced {len(synced)} global commands.")
            return

        if scope in {"guild", "~"}:
            if ctx.guild is None:
                await ctx.send("❌ `guild` sync requires running this command inside a server.")
                return
            synced = await sync_command_tree(guild=ctx.guild)
            await ctx.send(f"Synced {len(synced)} commands to guild `{ctx.guild.id}`.")
            return

        if scope in {"copy", "*"}:
            if ctx.guild is None:
                await ctx.send("❌ `copy` sync requires running this command inside a server.")
                return
            synced = await sync_command_tree(guild=ctx.guild)
            await ctx.send(
                f"Copied global commands and synced {len(synced)} commands to guild `{ctx.guild.id}`."
            )
            return

        if scope in {"clear", "^"}:
            if ctx.guild is None:
                await ctx.send("❌ `clear` sync requires running this command inside a server.")
                return
            await sync_command_tree(guild=ctx.guild, clear_guild_commands=True)
            await ctx.send(
                f"Cleared guild commands for `{ctx.guild.id}` and synced the empty guild tree."
            )
            return

        if scope in {"clearglobal", "clear-global", "^^"}:
            await sync_command_tree(clear_global_commands=True)
            await ctx.send("Cleared globally registered commands and synced the empty global tree.")
            return

        await ctx.send(
            "❌ Unknown sync scope. Use `global`, `guild`, `copy`, `clear`, or `clearglobal`."
        )
    except discord.HTTPException as e:
        await ctx.send(f"❌ Failed to sync commands.\n```\n{e}\n```")
        bot_logger.error(f"Error syncing command tree via prefix command: {e}")


@tree.command(name="load", description="Load a specific cog")
async def load(interaction: discord.Interaction, cog: str) -> None:
    """Load a specified cog if the user is authorized."""
    await interaction.response.defer(ephemeral=True)
    if not is_authorized(interaction):
        await interaction.followup.send("❌ You are not authorized to execute this command.")
        return

    cog_name = normalize_cog_name(cog)
    extension_name = resolve_extension_name(cog_name, prefer_configured_media_core=True)
    try:
        await bot.load_extension(extension_name)
        embed = _create_embed(
            "Cog Loaded",
            f"✅ Extension `{extension_name}` has been successfully loaded.\n\n{_command_sync_hint()}",
            discord.Color.green(),
        )
        await interaction.followup.send(embed=embed)
        bot_logger.info(f"Cog {extension_name} loaded by {interaction.user}")
    except commands.ExtensionError as e:
        embed = _create_embed(
            "Load Error",
            f"❌ Failed to load `{extension_name}`.\n```\n{e}\n```",
            discord.Color.red(),
        )
        await interaction.followup.send(embed=embed)
        bot_logger.error(f"Error loading cog {extension_name}: {e}")


@tree.command(name="unload", description="Unload a specific cog")
async def unload(interaction: discord.Interaction, cog: str) -> None:
    """Unload a specified cog if the user is authorized."""
    await interaction.response.defer(ephemeral=True)
    if not is_authorized(interaction):
        await interaction.followup.send("❌ You are not authorized to execute this command.")
        return

    cog_name = normalize_cog_name(cog)
    extension_name = resolve_extension_name(cog_name)
    try:
        await bot.unload_extension(extension_name)
        embed = _create_embed(
            "Cog Unloaded",
            f"✅ Extension `{extension_name}` has been successfully unloaded.\n\n{_command_sync_hint()}",
            discord.Color.orange(),
        )
        await interaction.followup.send(embed=embed)
        bot_logger.info(f"Cog {extension_name} unloaded by {interaction.user}")
    except commands.ExtensionError as e:
        embed = _create_embed(
            "Unload Error",
            f"❌ Failed to unload `{extension_name}`.\n```\n{e}\n```",
            discord.Color.red(),
        )
        await interaction.followup.send(embed=embed)
        bot_logger.error(f"Error unloading cog {extension_name}: {e}")


@tree.command(name="reload", description="Reload a specific cog")
async def reload(interaction: discord.Interaction, cog: str) -> None:
    """Reload a specified cog if the user is authorized."""
    await interaction.response.defer(ephemeral=True)
    if not is_authorized(interaction):
        await interaction.followup.send("❌ You are not authorized to execute this command.")
        return

    cog_name = normalize_cog_name(cog)
    extension_name = resolve_extension_name(cog_name)
    try:
        await bot.reload_extension(extension_name)
        embed = _create_embed(
            "Cog Reloaded",
            f"✅ Extension `{extension_name}` has been successfully reloaded.\n\n{_command_sync_hint()}",
            discord.Color.green(),
        )
        await interaction.followup.send(embed=embed)
        bot_logger.info(f"Cog {extension_name} reloaded by {interaction.user}")
    except commands.ExtensionError as e:
        # If not loaded, try to load it instead
        if "has not been loaded" in str(e):
            try:
                load_extension_name = resolve_extension_name(
                    cog_name, prefer_configured_media_core=True
                )
                await bot.load_extension(load_extension_name)
                embed = _create_embed(
                    "Cog Loaded",
                    f"✅ Extension `{load_extension_name}` was not loaded, so it has been loaded.\n\n{_command_sync_hint()}",
                    discord.Color.green(),
                )
                await interaction.followup.send(embed=embed)
                return
            except Exception as load_error:
                e = load_error

        embed = _create_embed(
            "Reload Error",
            f"❌ Failed to reload `{extension_name}`.\n```\n{e}\n```",
            discord.Color.red(),
        )
        await interaction.followup.send(embed=embed)
        bot_logger.error(f"Error reloading cog {extension_name}: {e}")


@tree.command(
    name="reload_config", description="Reload config.yaml-driven cogs without restarting the bot"
)
async def reload_config(interaction: discord.Interaction) -> None:
    """Reload runtime configuration for media core and dependent config cogs."""
    await interaction.response.defer(ephemeral=True)
    if not is_authorized(interaction):
        await interaction.followup.send("❌ You are not authorized to execute this command.")
        return

    try:
        async with startup_lock:
            actions = await reload_runtime_config()

        action_text = (
            "\n".join(f"- {action}" for action in actions)
            if actions
            else "- No config-driven cogs needed reloading."
        )
        embed = _create_embed(
            "Config Reloaded",
            f"✅ Applied config reload.\n{action_text}\n\n{_command_sync_hint()}",
            discord.Color.green(),
        )
        await interaction.followup.send(embed=embed)
        bot_logger.info(f"Runtime config reloaded by {interaction.user}: {actions}")
    except ConfigError as e:
        embed = _create_embed(
            "Config Reload Error",
            "❌ Config not reloaded, the running configuration is unchanged. "
            f"Fix the file and run /reload_config again.\n```\n{e}\n```",
            discord.Color.red(),
        )
        await interaction.followup.send(embed=embed)
        bot_logger.error(f"Config reload rejected: {e}")
    except Exception as e:
        embed = _create_embed(
            "Config Reload Error",
            f"❌ Failed to reload runtime config.\n```\n{e}\n```",
            discord.Color.red(),
        )
        await interaction.followup.send(embed=embed)
        bot_logger.error(f"Error reloading runtime config: {e}")


@tree.command(name="cogs", description="List all available cogs")
async def list_cogs(interaction: discord.Interaction) -> None:
    """Display a list of available and loaded cogs in an embed."""
    if not is_authorized(interaction):
        await interaction.response.send_message(
            "❌ You are not authorized to execute this command.", ephemeral=True
        )
        return

    cogs_list = []
    for f in sorted(os.listdir(COGS_DIR)):
        if f.endswith(".py") and not f.startswith("__"):
            cogs_list.append(f[:-3])
        elif os.path.isdir(os.path.join(COGS_DIR, f)) and not f.startswith("__"):
            if os.path.exists(os.path.join(COGS_DIR, f, "__init__.py")):
                cogs_list.append(f)
    loaded_extensions = bot.extensions.keys()

    cogs_list.sort()

    description_lines = []

    for cog_file in cogs_list:
        ext_name = resolve_extension_name(cog_file)
        cog_name_title = get_cog_display_name(cog_file)

        if ext_name in loaded_extensions:
            status = "🟢"
            # Try to get the Cog instance to read the description/docstring
            # Pass 1: Try exact title case match of filename (jellyseerr -> Jellyseerr)
            cog_instance = bot.get_cog(cog_file.title())
            # Pass 2: Look for any loaded cog that matches the module or submodule
            if not cog_instance:
                for c in bot.cogs.values():
                    if c.__module__ == ext_name or c.__module__.startswith(ext_name + "."):
                        cog_instance = c
                        break

            doc = (
                cog_instance.description
                if cog_instance and cog_instance.description
                else (
                    cog_instance.__doc__
                    if cog_instance and cog_instance.__doc__
                    else "No description available."
                )
            )
            # Take first line of docstring
            doc = doc.strip().split("\n")[0] if doc else "Active and running."
        else:
            status = "🔴"
            doc = "Not loaded."

        description_lines.append(f"{status} **{cog_name_title}**\n└─ *{doc}*")

    embed = _create_embed(
        "🧩 Extension Manager", "\n\n".join(description_lines), discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


def ensure_config_usable() -> None:
    """Stop the bot when config.yaml exists but cannot be parsed.

    The cogs would otherwise fail one by one with the same error, or - worse -
    a platform guess would load the wrong media server and report missing
    environment variables that are not the actual problem.
    """
    try:
        load_config(get_config_path())
    except ConfigError as e:
        bot_logger.error(str(e))
        raise SystemExit(f"Bot stopped: {e}. Fix the file and start the bot again.") from None


async def run_bot() -> None:
    """Start the bot and shut it down cleanly on SIGTERM.

    `bot.run()` installs no signal handlers - discord.py 2.x leaves that to the
    caller. Under Docker that meant SIGTERM killed the process outright:
    `MediaWatchBot.close()` never ran, so no cog shutdown, no aiohttp session
    close, and no `last_seen` write, which in turn made every restart discard
    the persisted uptime baseline. `docker stop` then waited out its ten second
    grace period and sent SIGKILL.

    Signal handlers need a running loop and are not available on Windows, so
    they are installed here rather than at import, and only where supported.
    """
    loop = asyncio.get_running_loop()
    stopping = False

    def request_stop() -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        bot_logger.info("Shutdown signal received, closing down.")
        loop.create_task(bot.close())

    for signal_name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, signal_name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, request_stop)
        except NotImplementedError:
            # Windows: fall back to the default KeyboardInterrupt handling.
            pass

    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    # A 1.x deployment only ships data/config.json. Convert it before anything
    # else reads the configuration, so cog loading and the env validation below
    # already see the migrated settings.
    ensure_config_yaml()
    ensure_config_usable()

    # Fail fast with an explicit message instead of running into a permanently
    # offline dashboard because of a missing token or channel ID.
    validate_environment(server_type=get_media_server_type())

    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        bot_logger.info("Interrupted, shutting down.")
    except discord.LoginFailure as e:
        bot_logger.error(f"Failed to start bot: Invalid token - {e}")
    except Exception as e:
        bot_logger.error(f"Unexpected error starting bot: {e}")
