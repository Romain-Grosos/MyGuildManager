import asyncio
import logging
import os
import signal
import sys
import time
from collections import defaultdict, deque
from functools import wraps
from logging.handlers import TimedRotatingFileHandler
from typing import Final, Dict, Any, Optional

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, current_dir)
sys.path.insert(0, parent_dir)

import aiohttp
import discord
from discord.ext import commands

import config
from db import run_db_query
from scheduler import setup_task_scheduler
from cache import get_global_cache, start_cache_maintenance_task
from cache_loader import get_cache_loader
from core.translation import translations
from core.rate_limiter import start_cleanup_task
from core.performance_profiler import get_profiler
from core.reliability import setup_reliability_system

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False
    logging.warning("[Bot] psutil not available - resource monitoring disabled")

# #################################################################################### #
#                               Logging Configuration
# #################################################################################### #
log_level: int = logging.DEBUG if config.DEBUG else logging.INFO
logging.root.handlers.clear()
logging.getLogger().setLevel(log_level)

file_handler = TimedRotatingFileHandler(
    config.LOG_FILE, when="midnight", interval=1, backupCount=7, encoding="utf-8"
)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)
logging.getLogger().addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logging.getLogger().addHandler(console_handler)

def _global_exception_hook(exc_type, exc_value, exc_tb):
    """
    Global exception handler for uncaught exceptions.
    
    Args:
        exc_type: Exception type
        exc_value: Exception value
        exc_tb: Exception traceback
    """
    logging.critical("UNCAUGHT EXCEPTION", exc_info=(exc_type, exc_value, exc_tb))

sys.excepthook = _global_exception_hook

logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
logging.captureWarnings(True)

logging.debug("[Bot] Log initialization with daily rotation.")

# #################################################################################### #
#                            Bot Optimization Classes
# #################################################################################### #
class BotOptimizer:
    """Integrated optimizer for the main bot."""
    
    def __init__(self, bot):
        """
        Initialize bot optimizer with caching and metrics.
        
        Args:
            bot: Discord bot instance
        """
        self.bot = bot
        
        self._member_cache = {}
        self._channel_cache = {}
        self._guild_cache = {}
        self._cache_ttl = 300
        self._cache_times = {}
        
        self.metrics = {
            'commands_executed': 0,
            'api_calls_cached': 0,
            'api_calls_total': 0,
            'db_queries_count': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }
        
        self._rate_limits = defaultdict(lambda: deque(maxlen=100))
        
        logging.info("[BotOptimizer] Initialized with Discord API caching and metrics")
    
    def is_cache_valid(self, key: str) -> bool:
        """
        Check if cache entry is still valid based on TTL.
        
        Args:
            key: Cache key to validate
            
        Returns:
            True if cache entry is valid, False otherwise
        """
        if key not in self._cache_times:
            return False
        return time.time() - self._cache_times[key] < self._cache_ttl
    
    def set_cache(self, cache_dict: dict, key: str, value: Any):
        """
        Store value in cache with timestamp for TTL tracking.
        
        Args:
            cache_dict: Cache dictionary to store in
            key: Cache key
            value: Value to cache
        """
        cache_dict[key] = value
        self._cache_times[key] = time.time()
    
    def get_cached_member(self, guild_id: int, member_id: int) -> Optional[Any]:
        """
        Get member from cache or return None if not found/expired.
        
        Args:
            guild_id: Discord guild ID
            member_id: Discord member ID
            
        Returns:
            Cached member object or None
        """
        key = f"member_{guild_id}_{member_id}"
        if key in self._member_cache and self.is_cache_valid(key):
            self.metrics['cache_hits'] += 1
            return self._member_cache[key]
        self.metrics['cache_misses'] += 1
        return None
    
    async def get_member_optimized(self, guild, member_id: int):
        """
        Optimized get_member with caching and fallback to API.
        
        Args:
            guild: Discord guild object
            member_id: Discord member ID
            
        Returns:
            Member object or None if not found
        """
        cached = self.get_cached_member(guild.id, member_id)
        if cached:
            return cached
        
        try:
            member = guild.get_member(member_id)
            if member is None:
                member = await guild.fetch_member(member_id)
            
            if member:
                key = f"member_{guild.id}_{member_id}"
                self.set_cache(self._member_cache, key, member)
                self.metrics['api_calls_cached'] += 1
            
            self.metrics['api_calls_total'] += 1
            return member
            
        except Exception as e:
            logging.warning(f"[BotOptimizer] Failed to fetch member {member_id}: {e}")
            return None
    
    async def get_channel_optimized(self, channel_id: int):
        """
        Optimized get_channel with caching and fallback to API.
        
        Args:
            channel_id: Discord channel ID
            
        Returns:
            Channel object or None if not found
        """
        key = f"channel_{channel_id}"
        
        if key in self._channel_cache and self.is_cache_valid(key):
            self.metrics['cache_hits'] += 1
            return self._channel_cache[key]
        
        try:
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(channel_id)
            
            if channel:
                self.set_cache(self._channel_cache, key, channel)
                self.metrics['api_calls_cached'] += 1
            
            self.metrics['api_calls_total'] += 1
            self.metrics['cache_misses'] += 1
            return channel
            
        except Exception as e:
            logging.warning(f"[BotOptimizer] Failed to fetch channel {channel_id}: {e}")
            return None
    
    def track_command_execution(self, command_name: str, execution_time: float):
        """
        Track command execution metrics and log slow commands.
        
        Args:
            command_name: Name of the executed command
            execution_time: Execution time in milliseconds
        """
        self.metrics['commands_executed'] += 1
        
        if execution_time > 5000:
            logging.warning(f"[BotOptimizer] Slow command detected: {command_name} took {execution_time:.0f}ms")
    
    def track_db_query(self):
        """
        Track database query execution for metrics.
        """
        self.metrics['db_queries_count'] += 1
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive performance statistics.
        
        Returns:
            Dictionary containing performance metrics
        """
        total_api_calls = self.metrics['api_calls_total']
        cache_hit_rate = 0
        if total_api_calls > 0:
            cache_hit_rate = (self.metrics['cache_hits'] / (self.metrics['cache_hits'] + self.metrics['cache_misses'])) * 100
        
        return {
            'commands_executed': self.metrics['commands_executed'],
            'api_calls_total': total_api_calls,
            'api_calls_cached': self.metrics['api_calls_cached'],
            'db_queries_count': self.metrics['db_queries_count'],
            'cache_hit_rate': round(cache_hit_rate, 2),
            'cache_size': len(self._member_cache) + len(self._channel_cache),
            'uptime_hours': (time.time() - getattr(self.bot, '_start_time', time.time())) / 3600
        }
    
    def cleanup_cache(self):
        """
        Clean expired cache entries based on TTL.
        """
        current_time = time.time()
        expired_keys = []
        
        for key, timestamp in self._cache_times.items():
            if current_time - timestamp > self._cache_ttl:
                expired_keys.append(key)
        
        for key in expired_keys:
            self._member_cache.pop(key, None)
            self._channel_cache.pop(key, None)
            self._guild_cache.pop(key, None)
            del self._cache_times[key]
        
        if expired_keys:
            logging.debug(f"[BotOptimizer] Cleaned {len(expired_keys)} expired cache entries")


def optimize_command(func):
    """
    Decorator that automatically adds metrics tracking to commands.
    
    Args:
        func: Command function to decorate
        
    Returns:
        Wrapped function with metrics tracking
    """
    @wraps(func)
    async def wrapper(self, ctx, *args, **kwargs):
        if not hasattr(self.bot, 'optimizer'):
            return await func(self, ctx, *args, **kwargs)
        
        start_time = time.time()
        command_name = func.__name__
        
        try:
            result = await func(self, ctx, *args, **kwargs)
            execution_time = (time.time() - start_time) * 1000
            self.bot.optimizer.track_command_execution(command_name, execution_time)
            return result
            
        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            self.bot.optimizer.track_command_execution(f"{command_name}_ERROR", execution_time)
            raise
    
    return wrapper


async def optimized_run_db_query(original_func, bot, query: str, params: tuple = (), **kwargs):
    """
    Optimized wrapper for run_db_query with metrics and slow query detection.
    
    Args:
        original_func: Original database query function
        bot: Discord bot instance
        query: SQL query string
        params: Query parameters tuple
        **kwargs: Additional keyword arguments
        
    Returns:
        Query result from original function
    """
    if hasattr(bot, 'optimizer'):
        bot.optimizer.track_db_query()
    
    start_time = time.time()
    
    try:
        result = await original_func(query, params, **kwargs)
        execution_time = (time.time() - start_time) * 1000
        
        if execution_time > 100:
            query_preview = query[:100] + "..." if len(query) > 100 else query
            logging.warning(f"[DB] Slow query ({execution_time:.0f}ms): {query_preview}")
        
        return result
        
    except Exception as e:
        execution_time = (time.time() - start_time) * 1000
        logging.error(f"[DB] Query failed after {execution_time:.0f}ms: {str(e)}")
        raise

# #################################################################################### #
#                            Discord Bot Startup
# #################################################################################### #
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# #################################################################################### #
#                            Discord Bot Initialization
# #################################################################################### #
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True
intents.members = True

def validate_token():
    """
    Validate Discord bot token format and return masked version for logging.
    
    Returns:
        Validated Discord token
        
    Raises:
        SystemExit: If token is invalid or missing
    """
    token = config.TOKEN
    if not token or len(token) < 50:
        logging.critical("[Bot] Invalid or missing Discord token")
        sys.exit(1)
    masked_token = f"{token[:10]}...{token[-4:]}"
    logging.debug(f"[Bot] Using token: {masked_token}")
    return token

bot = discord.Bot(intents=intents, loop=loop)
bot.translations = translations
bot.global_command_cooldown = set()
bot.max_commands_per_minute = 100

bot.optimizer = BotOptimizer(bot)
bot.profiler = get_profiler()
bot.reliability_system = setup_reliability_system(bot)
bot._start_time = time.time()

original_run_db_query = run_db_query
bot.run_db_query = lambda *args, **kwargs: optimized_run_db_query(
    original_run_db_query, bot, *args, **kwargs
)

bot.get_member_optimized = bot.optimizer.get_member_optimized
bot.get_channel_optimized = bot.optimizer.get_channel_optimized

bot.scheduler = setup_task_scheduler(bot)
bot.cache = get_global_cache(bot)
bot.cache_loader = get_cache_loader(bot)

# #################################################################################### #
#                           Command Groups Creation
# #################################################################################### #
def create_command_groups(bot: discord.Bot) -> None:
    """
    Create all slash command groups and inject them into bot instance.
    Must be called BEFORE loading cogs to ensure groups are available.
    
    Args:
        bot: Discord bot instance
    """
    logging.info("[Bot] Creating slash command groups")

    ADMIN_DATA = translations.get("commands", {})
    ABSENCE_DATA = translations.get("absence", {})
    LOOT_DATA = translations.get("loot_wishlist", {})
    MEMBER_DATA = translations.get("members", {})
    STAFF_DATA = translations.get("staff", {})
    EVENTS_DATA = translations.get("events", {})
    STATICS_DATA = translations.get("statics", {})

    bot.admin_group = discord.SlashCommandGroup(
        name=ADMIN_DATA.get("group", {}).get("name", {}).get("en-US", "admin_bot"),
        description=ADMIN_DATA.get("group", {}).get("description", {}).get("en-US", "Bot administration commands"),
        name_localizations=ADMIN_DATA.get("group", {}).get("name", {}),
        description_localizations=ADMIN_DATA.get("group", {}).get("description", {}),
        default_member_permissions=discord.Permissions(administrator=True)
    )

    bot.absence_group = discord.SlashCommandGroup(
        name=ABSENCE_DATA.get("group", {}).get("name", {}).get("en-US", "absence"),
        description=ABSENCE_DATA.get("group", {}).get("description", {}).get("en-US", "Manage member absence status"),
        name_localizations=ABSENCE_DATA.get("group", {}).get("name", {}),
        description_localizations=ABSENCE_DATA.get("group", {}).get("description", {}),
        default_member_permissions=discord.Permissions(manage_guild=True)
    )

    bot.member_group = discord.SlashCommandGroup(
        name=MEMBER_DATA.get("group", {}).get("name", {}).get("en-US", "member"),
        description=MEMBER_DATA.get("group", {}).get("description", {}).get("en-US", "Member profile and stats management"),
        name_localizations=MEMBER_DATA.get("group", {}).get("name", {}),
        description_localizations=MEMBER_DATA.get("group", {}).get("description", {}),
        default_member_permissions=discord.Permissions(manage_guild=True)
    )

    bot.loot_group = discord.SlashCommandGroup(
        name=LOOT_DATA.get("group", {}).get("name", {}).get("en-US", "loot"),
        description=LOOT_DATA.get("group", {}).get("description", {}).get("en-US", "Epic T2 loot wishlist management"),
        name_localizations=LOOT_DATA.get("group", {}).get("name", {}),
        description_localizations=LOOT_DATA.get("group", {}).get("description", {}),
        default_member_permissions=discord.Permissions(send_messages=True)
    )

    bot.staff_group = discord.SlashCommandGroup(
        name=STAFF_DATA.get("group", {}).get("name", {}).get("en-US", "staff"),
        description=STAFF_DATA.get("group", {}).get("description", {}).get("en-US", "Staff management commands"),
        name_localizations=STAFF_DATA.get("group", {}).get("name", {}),
        description_localizations=STAFF_DATA.get("group", {}).get("description", {}),
        default_member_permissions=discord.Permissions(manage_roles=True)
    )

    bot.events_group = discord.SlashCommandGroup(
        name=EVENTS_DATA.get("group", {}).get("name", {}).get("en-US", "events"),
        description=EVENTS_DATA.get("group", {}).get("description", {}).get("en-US", "Guild event management"),
        name_localizations=EVENTS_DATA.get("group", {}).get("name", {}),
        description_localizations=EVENTS_DATA.get("group", {}).get("description", {}),
        default_member_permissions=discord.Permissions(manage_events=True)
    )

    bot.statics_group = discord.SlashCommandGroup(
        name=STATICS_DATA.get("group", {}).get("name", {}).get("en-US", "statics"),
        description=STATICS_DATA.get("group", {}).get("description", {}).get("en-US", "Static group management"),
        name_localizations=STATICS_DATA.get("group", {}).get("name", {}),
        description_localizations=STATICS_DATA.get("group", {}).get("description", {}),
        default_member_permissions=discord.Permissions(manage_roles=True)
    )

    groups = [
        ("admin_bot", bot.admin_group),
        ("absence", bot.absence_group),
        ("member", bot.member_group),
        ("loot", bot.loot_group),
        ("staff", bot.staff_group),
        ("events", bot.events_group),
        ("statics", bot.statics_group)
    ]
    
    for group_name, group in groups:
        try:
            bot.add_application_command(group)
            logging.debug(f"[Bot] Registered {group_name} command group")
        except Exception as e:
            logging.error(f"[Bot] Failed to register {group_name} group: {e}", exc_info=True)
    
    logging.info(f"[Bot] Successfully created and registered {len(groups)} command groups")

def setup_global_group_error_handlers(bot: discord.Bot) -> None:
    """
    Setup centralized error handlers for all slash command groups.
    
    Args:
        bot: Discord bot instance
    """
    from core.functions import get_user_message

    groups = [
        ("admin_bot", bot.admin_group),
        ("absence", bot.absence_group),
        ("member", bot.member_group),
        ("loot", bot.loot_group),
        ("staff", bot.staff_group),
        ("events", bot.events_group),
        ("statics", bot.statics_group)
    ]
    
    async def global_group_error_handler(ctx: discord.ApplicationContext, error: Exception):
        """
        Centralized error handler for all slash command groups.
        
        Args:
            ctx: Discord application context
            error: Exception that occurred during command execution
        """

        group_name = "unknown"
        command_name = "unknown"
        
        if hasattr(ctx.command, 'parent') and ctx.command.parent:
            group_name = ctx.command.parent.name
            command_name = ctx.command.name
        elif hasattr(ctx.command, 'name'):
            command_name = ctx.command.name
        
        logging.error(f"[Bot] Error in {group_name}/{command_name} command for guild {ctx.guild.id if ctx.guild else 'DM'}: {error}", exc_info=True)

        error_key = "global_errors.unknown"
        error_params = {"group": group_name, "command": command_name}
        
        if isinstance(error, discord.Forbidden):
            error_key = "global_errors.forbidden"
        elif isinstance(error, discord.NotFound):
            error_key = "global_errors.not_found"
        elif isinstance(error, discord.HTTPException):
            error_key = "global_errors.http_exception"
        elif isinstance(error, commands.MissingPermissions):
            error_key = "global_errors.missing_permissions"
        elif isinstance(error, commands.BotMissingPermissions):
            error_key = "global_errors.bot_missing_permissions"
        elif isinstance(error, commands.CommandOnCooldown):
            error_key = "global_errors.cooldown"
            error_params["retry_after"] = f"{error.retry_after:.1f}"

        error_message = get_user_message(ctx, bot.translations, error_key, **error_params)

        if not error_message:
            fallback_messages = {
                "global_errors.forbidden": "❌ Missing permissions to execute this command",
                "global_errors.not_found": "❌ Required resource not found (channel, role, or message)",
                "global_errors.http_exception": "❌ Discord API error occurred. Please try again",
                "global_errors.missing_permissions": "❌ You don't have the necessary permissions",
                "global_errors.bot_missing_permissions": "❌ The bot doesn't have the necessary permissions",
                "global_errors.cooldown": f"❌ Command on cooldown. Try again in {error_params.get('retry_after', '?')}s",
                "global_errors.unknown": f"❌ Unexpected error in {group_name}/{command_name}"
            }
            error_message = fallback_messages.get(error_key, "❌ An unexpected error occurred")
        
        try:
            if ctx.response.is_done():
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.respond(error_message, ephemeral=True)
        except Exception as send_error:
            logging.error(f"[Bot] Failed to send error message: {send_error}")

    for group_name, group in groups:
        try:
            group.error(global_group_error_handler)
            logging.debug(f"[Bot] Added global error handler to {group_name} group")
        except Exception as e:
            logging.error(f"[Bot] Failed to add error handler to {group_name}: {e}")
    
    logging.info("[Bot] Global group error handlers setup completed")

create_command_groups(bot)
setup_global_group_error_handlers(bot)

EXTENSIONS: Final["list[str]"] = [
    "cogs.core",
    "cogs.llm",
    "cogs.guild_init",
    "cogs.notification",
    "cogs.profile_setup",
    "cogs.guild_members",
    "cogs.absence",
    "cogs.dynamic_voice",
    "cogs.contract",
    "cogs.guild_events",
    "cogs.guild_attendance",
    "cogs.guild_ptb",
    "cogs.epic_items_scraper",
    "cogs.loot_wishlist",
    "cogs.autorole"
]

def load_extensions():
    """
    Load all Discord bot extensions (cogs) with error handling.
    
    Raises:
        SystemExit: If too many extensions fail to load
    """
    failed_extensions = []
    for ext in EXTENSIONS:
        try:
            bot.load_extension(ext)
            logging.debug(f"[Bot] Extension loaded: {ext}")
        except Exception as e:
            failed_extensions.append(ext)
            logging.exception(f"[Bot] Failed to load extension {ext}")
    
    if failed_extensions:
        logging.warning(f"[Bot] {len(failed_extensions)} extensions failed to load: {failed_extensions}")
    
    if len(failed_extensions) >= len(EXTENSIONS) // 2:
        logging.critical("[Bot] Too many extensions failed. Shutting down.")
        sys.exit(1)

# #################################################################################### #
#                            Extra Event Hooks
# #################################################################################### #
@bot.event
async def on_disconnect() -> None:
    """
    Handle Discord gateway disconnection event.
    """
    logging.warning("[Discord] Gateway disconnected")


@bot.event
async def on_resumed() -> None:
    """
    Handle Discord gateway resume event.
    """
    logging.info("[Discord] Gateway resume OK")


@bot.before_invoke
async def global_rate_limit(ctx):
    """
    Global rate limiting before command execution.
    
    Args:
        ctx: Discord command context
        
    Raises:
        CommandOnCooldown: If rate limit is exceeded
    """
    now = time.time()
    bot.global_command_cooldown = {
        timestamp for timestamp in bot.global_command_cooldown 
        if now - timestamp < 60
    }
    
    if len(bot.global_command_cooldown) >= bot.max_commands_per_minute:
        logging.warning(f"[Bot] Global rate limit exceeded ({len(bot.global_command_cooldown)} commands/min)")
        cooldown = commands.Cooldown(1, 60)
        raise commands.CommandOnCooldown(cooldown, 60, commands.BucketType.default)
    
    bot.global_command_cooldown.add(now)

@bot.event
async def on_ready() -> None:
    """
    Handle bot ready event and initialize background tasks.
    """
    logging.info("[Discord] Connected as %s (%s)", bot.user, bot.user.id)

    if not hasattr(bot, '_background_tasks'):
        bot._background_tasks = []

    if not hasattr(bot, '_cache_loaded'):
        bot._cache_loaded = True
        try:
            await bot.cache_loader.load_all_shared_data()
            logging.info("[Bot] Cache loader: shared data loaded successfully")
        except Exception as e:
            logging.error(f"[Bot] Error loading shared cache data: {e}", exc_info=True)
    
    if PSUTIL_AVAILABLE and not hasattr(bot, '_monitor_task'):
        bot._monitor_task = asyncio.create_task(monitor_resources())
        bot._background_tasks.append(bot._monitor_task)
        logging.debug("[Bot] Resource monitoring started")
    
    if not hasattr(bot, '_optimization_setup_done'):
        bot._optimization_setup_done = True
        
        async def cache_cleanup_task():
            try:
                while True:
                    await asyncio.sleep(600)
                    bot.optimizer.cleanup_cache()
            except asyncio.CancelledError:
                logging.debug("[Bot] Cache cleanup task cancelled")
                raise
        
        cleanup_task = asyncio.create_task(cache_cleanup_task())
        bot._background_tasks.append(cleanup_task)
        
        await start_cache_maintenance_task(bot)
        await start_cleanup_task(bot)

        await bot.cache_loader.load_all_shared_data()
        logging.info("[BotOptimizer] Optimization setup completed - intelligent cache system with smart features started")


@bot.slash_command(name="perf", description="Show bot performance stats")
@discord.default_permissions(administrator=True)
async def performance_stats(ctx):
    """
    Display comprehensive bot performance statistics.
    
    Args:
        ctx: Discord slash command context
    """
    await ctx.defer(ephemeral=True)
    
    stats = bot.optimizer.get_performance_stats()
    smart_cache_stats = bot.cache.get_smart_stats() if hasattr(bot.cache, 'get_smart_stats') else {}
    
    embed = discord.Embed(
        title="📊 Bot Performance",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="🎯 Commands",
        value=f"{stats['commands_executed']} executed",
        inline=True
    )
    
    embed.add_field(
        name="🌐 Discord API",
        value=f"{stats['api_calls_total']} calls\n{stats['api_calls_cached']} cached",
        inline=True
    )

    if smart_cache_stats:
        embed.add_field(
            name="🧠 Smart Cache", 
            value=f"Size: {smart_cache_stats.get('cache_size', 0)}\nHit Rate: {smart_cache_stats.get('hit_rate', 0):.1f}%\nHot Keys: {smart_cache_stats.get('hot_keys', 0)}", 
            inline=True
        )
        embed.add_field(
            name="🔮 Predictions", 
            value=f"Accuracy: {smart_cache_stats.get('prediction_accuracy', 0):.1f}%\nPreload Efficiency: {smart_cache_stats.get('preload_efficiency', 0):.1f}%\nActive Tasks: {smart_cache_stats.get('active_preload_tasks', 0)}", 
            inline=True
        )
    
    embed.add_field(
        name="💾 Cache",
        value=f"{stats['cache_hit_rate']}% hit rate\n{stats['cache_size']} entries",
        inline=True
    )
    
    embed.add_field(
        name="🗄️ Database",
        value=f"{stats['db_queries_count']} queries",
        inline=True
    )
    
    embed.add_field(
        name="⏱️ Uptime",
        value=f"{stats['uptime_hours']:.1f} hours",
        inline=True
    )
    
    performance_score = "Excellent" if stats['cache_hit_rate'] > 70 else "Good" if stats['cache_hit_rate'] > 50 else "Needs improvement"
    embed.add_field(
        name="🏆 Overall Score",
        value=performance_score,
        inline=True
    )
    
    await ctx.followup.send(embed=embed, ephemeral=True)

# #################################################################################### #
#                            Resource Monitoring
# #################################################################################### #
async def monitor_resources():
    """
    Monitor system resources (CPU, memory) and log warnings for high usage.
    """
    try:
        while True:
            try:
                if PSUTIL_AVAILABLE and psutil:
                    process = psutil.Process()
                    memory_mb = process.memory_info().rss / 1024 / 1024
                    cpu_percent = process.cpu_percent()
                    
                    if memory_mb > config.MAX_MEMORY_MB:
                        logging.warning(f"[Bot] High memory usage: {memory_mb:.1f}MB (limit: {config.MAX_MEMORY_MB}MB)")
                    if cpu_percent > config.MAX_CPU_PERCENT:
                        logging.warning(f"[Bot] High CPU usage: {cpu_percent:.1f}% (limit: {config.MAX_CPU_PERCENT}%)")
                        
                    if int(time.time()) % 3600 == 0:
                        logging.info(f"[Bot] Resource usage - Memory: {memory_mb:.1f}MB, CPU: {cpu_percent:.1f}%")
                        
                await asyncio.sleep(300)
            except Exception as e:
                logging.error(f"[Bot] Resource monitoring error: {e}")
                await asyncio.sleep(300)
    except asyncio.CancelledError:
        logging.debug("[Bot] Resource monitoring task cancelled")
        raise

# #################################################################################### #
#                            Resilient runner
# #################################################################################### #
async def run_bot():
    """
    Main bot runner with retry logic for resilient startup.
    """
    load_extensions()
    max_retries = config.MAX_RECONNECT_ATTEMPTS
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            await bot.start(validate_token())
        except aiohttp.ClientError as e:
            retry_count += 1
            logging.exception(f"Network error (attempt {retry_count}/{max_retries}) - retrying in 15s")
            if retry_count >= max_retries:
                logging.critical("[Bot] Max retries reached. Shutting down.")
                break
            await bot.close()
            await asyncio.sleep(15)
        except Exception as e:
            logging.critical(f"[Bot] Critical error during startup: {e}", exc_info=True)
            break
        else:
            break

async def cleanup_background_tasks():
    """
    Cancel all background tasks properly during shutdown.
    """
    if hasattr(bot, '_scheduler_loop') and bot._scheduler_loop:
        if bot._scheduler_loop.is_running():
            logging.debug("[Bot] Stopping scheduler loop")
            bot._scheduler_loop.cancel()
        bot._scheduler_loop = None

    if hasattr(bot, '_background_tasks'):
        logging.debug(f"[Bot] Cancelling {len(bot._background_tasks)} background tasks")
        for task in bot._background_tasks:
            if not task.done():
                task.cancel()

        if bot._background_tasks:
            await asyncio.gather(*bot._background_tasks, return_exceptions=True)
        bot._background_tasks.clear()
        logging.debug("[Bot] Background tasks cleanup completed")

def _graceful_exit(sig_name):
    """
    Handle graceful shutdown on system signals.
    
    Args:
        sig_name: Signal name that triggered shutdown
    """
    logging.warning("[Bot] Signal %s received - closing the bot", sig_name)
    
    async def shutdown():
        await cleanup_background_tasks()
        await bot.close()

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(shutdown())
    except RuntimeError:
        asyncio.run(shutdown())

if __name__ == "__main__":
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _graceful_exit, sig.name)
        except NotImplementedError:
           signal.signal(sig, lambda *_: _graceful_exit(sig.name))

    try:
        loop.run_until_complete(run_bot())
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        logging.shutdown()
        loop.close()
