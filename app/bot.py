"""
Discord Bot Main Module - Enterprise-grade Discord bot for guild management.

This module provides a comprehensive Discord bot system featuring:

ARCHITECTURE:
- Async/await throughout with high-performance connection pooling
- Event-driven architecture with robust error handling
- Modular cog system for feature separation
- Centralized configuration management with validation
- Enterprise logging with JSON structured output

CORE SYSTEMS:
- BotOptimizer: Intelligent caching and performance monitoring
- TaskScheduler: Automated task orchestration with timezone support
- DatabaseManager: Async MySQL/MariaDB with circuit breaker pattern
- Cache System: Multi-layer caching with smart preloading
- Rate Limiter: Per-guild rate limiting with automatic cleanup

RELIABILITY:
- Circuit breaker pattern for external dependencies
- Graceful shutdown with resource cleanup
- Health monitoring and alerting
- Automatic retry logic with exponential backoff
- Resource monitoring (CPU, memory) with thresholds

OBSERVABILITY:
- Structured JSON logging with correlation IDs
- Performance metrics and SLO tracking
- Real-time health checks and status endpoints
- Command execution tracking and latency histograms
- Background task monitoring with deadlock detection

PERFORMANCE:
- Connection pooling for Discord API and database
- Intelligent caching with TTL and invalidation
- Parallel processing with semaphore-based concurrency
- Memory-efficient data structures and cleanup
- High-resolution timing for accurate metrics

SECURITY:
- Secure credential management (no tokens in logs)
- PII masking in production environments
- Input validation and sanitization
- Role-based permission system integration

The bot handles guild member management, event scheduling, loot distribution,
attendance tracking, and provides comprehensive administrative tools.
"""
from __future__ import annotations

import asyncio
import math
import os
import random
import signal
import socket
import sys
import time
import tracemalloc
import uuid
from collections import defaultdict, deque
from contextvars import ContextVar
from functools import wraps
from typing import Final, Dict, Any, Optional

import aiohttp
import discord
from discord.ext import commands

from . import config
from .db import run_db_query, initialize_db_pool, close_db_pool
from .scheduler import setup_task_scheduler
from .cache import get_global_cache, start_cache_maintenance_task
from .cache_loader import get_cache_loader
from .core.translation import translations
from .core.rate_limiter import start_cleanup_task
from .core.performance_profiler import get_profiler
from .core.logger import ComponentLogger

_bot_logger = ComponentLogger("bot")
_optimizer_logger = ComponentLogger("bot_optimizer") 
_db_logger = ComponentLogger("database")

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False
    _bot_logger.warning("psutil_not_available", message="Resource monitoring disabled")

from .core.reliability import setup_reliability_system

# #################################################################################### #
#                               Logging Configuration
# #################################################################################### #
def _global_exception_hook(exc_type, exc_value, exc_tb):
    """
    Global exception handler for uncaught exceptions.

    Args:
        exc_type: Exception type
        exc_value: Exception value
        exc_tb: Exception traceback
    """
    if config.DEBUG and not config.PRODUCTION:
        _bot_logger.critical("uncaught_exception", exc_info=(exc_type, exc_value, exc_tb))
    else:
        _bot_logger.critical("uncaught_exception", error_type=exc_type.__name__, error_msg=str(exc_value))

sys.excepthook = _global_exception_hook

import logging
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
logging.captureWarnings(True)

_bot_logger.debug("log_initialization_complete", rotation="daily")

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

        self._health_alerts = {
            "cache_not_loaded": {"last_alert": 0, "cooldown": 600},
            "high_reconnections": {"last_alert": 0, "cooldown": 300},
            "watchdog_triggered": {"last_alert": 0, "cooldown": 120},
        }

        self._member_cache = {}
        self._channel_cache = {}
        self._cache_ttl = getattr(config, "CACHE_TTL_SECONDS", 300)
        self._cache_times = {}

        self.metrics = {
            "commands_executed": 0,
            "api_calls_total": 0,
            "db_queries_count": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "rate_limit_denials": 0,
        }

        self._performance_window = deque(maxlen=50)
        self._alert_cooldown = {}
        self._cold_start_until = time.monotonic() + getattr(
            config, "COLD_START_SECONDS", 300
        )
        self._correlation_ids_seen = set()
        self._correlation_collision_count = 0
        self.latency_samples = deque(maxlen=1000)
        self._sorted_cache = None
        self._percentile_dirty = True
        self.latency_buckets = {
            "<=50ms": 0,
            "<=100ms": 0,
            "<=200ms": 0,
            "<=500ms": 0,
            "<=1s": 0,
            "<=2s": 0,
            "<=5s": 0,
            "<=10s": 0,
            ">10s": 0,
        }

        _optimizer_logger.info("bot_optimizer_initialized", features=["discord_api_caching", "metrics"])

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
        return time.monotonic() - self._cache_times[key] < self._cache_ttl

    def set_cache(self, cache_dict: dict, key: str, value: Any):
        """
        Store value in cache with timestamp for TTL tracking.

        Args:
            cache_dict: Cache dictionary to store in
            key: Cache key
            value: Value to cache
        """
        cache_dict[key] = value
        self._cache_times[key] = time.monotonic()

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
            self.metrics["cache_hits"] += 1
            return self._member_cache[key]
        self.metrics["cache_misses"] += 1
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
                self.metrics["api_calls_total"] += 1

            if member:
                key = f"member_{guild.id}_{member_id}"
                self.set_cache(self._member_cache, key, member)

            return member

        except (discord.NotFound, discord.Forbidden) as e:
            key = f"member_{guild.id}_{member_id}"
            self._member_cache.pop(key, None)
            self._cache_times.pop(key, None)
            _optimizer_logger.warning("member_cache_purged",
                member_id=member_id,
                guild_id=guild.id,
                reason="not_found_or_forbidden",
                error=str(e)
            )
            return None
        except Exception as e:
            _optimizer_logger.warning("member_fetch_failed", member_id=member_id, error=str(e))
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
            self.metrics["cache_hits"] += 1
            return self._channel_cache[key]

        self.metrics["cache_misses"] += 1

        try:
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(channel_id)
                self.metrics["api_calls_total"] += 1

            if channel:
                self.set_cache(self._channel_cache, key, channel)

            return channel

        except (discord.NotFound, discord.Forbidden) as e:
            key = f"channel_{channel_id}"
            self._channel_cache.pop(key, None)
            self._cache_times.pop(key, None)
            _optimizer_logger.warning("channel_cache_purged",
                channel_id=channel_id,
                reason="not_found_or_forbidden", 
                error=str(e)
            )
            return None
        except Exception as e:
            _optimizer_logger.warning("channel_fetch_failed", channel_id=channel_id, error=str(e))
            return None

    def track_command_execution(self, command_name: str, execution_time: float):
        """
        Track command execution metrics and log slow commands.

        Args:
            command_name: Name of the executed command
            execution_time: Execution time in milliseconds
        """
        self.metrics["commands_executed"] += 1

        self.latency_samples.append(execution_time)
        self._percentile_dirty = True

        if time.monotonic() > self._cold_start_until:
            self._performance_window.append(
                {
                    "timestamp": time.monotonic(),
                    "latency": execution_time,
                    "fast": execution_time <= 100,
                    "slow": execution_time > 1000,
                }
            )
            self._check_performance_alerts()

        if execution_time <= 50:
            self.latency_buckets["<=50ms"] += 1
        elif execution_time <= 100:
            self.latency_buckets["<=100ms"] += 1
        elif execution_time <= 200:
            self.latency_buckets["<=200ms"] += 1
        elif execution_time <= 500:
            self.latency_buckets["<=500ms"] += 1
        elif execution_time <= 1000:
            self.latency_buckets["<=1s"] += 1
        elif execution_time <= 2000:
            self.latency_buckets["<=2s"] += 1
        elif execution_time <= 5000:
            self.latency_buckets["<=5s"] += 1
        elif execution_time <= 10000:
            self.latency_buckets["<=10s"] += 1
        else:
            self.latency_buckets[">10s"] += 1

        if execution_time > 5000:
            _optimizer_logger.warning("slow_command_detected",
                command=command_name,
                execution_time_ms=int(execution_time)
            )

    def _check_performance_alerts(self):
        """Check performance thresholds and emit alerts if needed."""
        if len(self._performance_window) < 20:
            return

        now = time.monotonic()
        recent_window = [
            p for p in self._performance_window if now - p["timestamp"] <= 900
        ]

        if len(recent_window) < 10:
            return

        fast_count = sum(1 for p in recent_window if p["fast"])
        slow_count = sum(1 for p in recent_window if p["slow"])
        total = len(recent_window)

        fast_pct = (fast_count / total) * 100
        slow_pct = (slow_count / total) * 100

        fast_threshold = getattr(config, "ALERT_FAST_PERCENT_MIN", 60)
        slow_threshold = getattr(config, "ALERT_SLOW_PERCENT_MAX", 10)
        cooldown_seconds = getattr(config, "ALERT_COOLDOWN_SECONDS", 300)

        if fast_pct < fast_threshold:
            alert_key = "fast_drop"
            if now - self._alert_cooldown.get(alert_key, 0) > cooldown_seconds:
                _optimizer_logger.warning("fast_response_rate_drop",
                    fast_percent=round(fast_pct, 1),
                    threshold_percent=fast_threshold
                )
                self._alert_cooldown[alert_key] = int(now)

        if slow_pct > slow_threshold:
            alert_key = "slow_spike"
            if now - self._alert_cooldown.get(alert_key, 0) > cooldown_seconds:
                _optimizer_logger.warning("slow_response_rate_spike",
                    slow_percent=round(slow_pct, 1),
                    threshold_percent=slow_threshold
                )
                self._alert_cooldown[alert_key] = int(now)

    def track_db_query(self):
        """
        Track database query execution for metrics.
        """
        self.metrics["db_queries_count"] += 1

    def get_latency_percentiles(self) -> Dict[str, float]:
        """
        Calculate latency percentiles from samples with robust indexing.

        Returns:
            Dictionary with p50, p95, p99 latencies in milliseconds
        """
        if not self.latency_samples:
            return {"p50": 0, "p95": 0, "p99": 0}

        if self._percentile_dirty or self._sorted_cache is None:
            self._sorted_cache = sorted(self.latency_samples)
            self._percentile_dirty = False

        sorted_samples = self._sorted_cache
        n = len(sorted_samples)

        def get_percentile(samples, p):
            if n == 1:
                return samples[0]
            pos = p * (n - 1)
            idx_low = int(math.floor(pos))
            idx_high = int(math.ceil(pos))
            idx_low = min(max(0, idx_low), n - 1)
            idx_high = min(max(0, idx_high), n - 1)
            if idx_low == idx_high:
                return samples[idx_low]
            else:
                weight = pos - idx_low
                return samples[idx_low] * (1 - weight) + samples[idx_high] * weight

        return {
            "p50": get_percentile(sorted_samples, 0.50),
            "p95": get_percentile(sorted_samples, 0.95),
            "p99": get_percentile(sorted_samples, 0.99),
        }

    def get_performance_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive performance statistics.

        Returns:
            Dictionary containing performance metrics
        """
        total_api_calls = self.metrics["api_calls_total"]
        cache_hit_rate = 0
        if total_api_calls > 0:
            cache_hit_rate = (
                self.metrics["cache_hits"]
                / (self.metrics["cache_hits"] + self.metrics["cache_misses"])
            ) * 100

        latency_stats = self.get_latency_percentiles()

        is_cold_start = time.monotonic() < self._cold_start_until

        return {
            "commands_executed": self.metrics["commands_executed"],
            "api_calls_total": total_api_calls,
            "db_queries_count": self.metrics["db_queries_count"],
            "cache_hit_rate": round(cache_hit_rate, 2),
            "cache_size": len(self._member_cache) + len(self._channel_cache),
            "uptime_hours": (
                time.monotonic()
                - getattr(self.bot, "_start_time_monotonic", time.monotonic())
            )
            / 3600,
            "rate_limit_denials": self.metrics["rate_limit_denials"],
            "latency_p50": round(latency_stats["p50"], 1),
            "latency_p95": round(latency_stats["p95"], 1),
            "latency_p99": round(latency_stats["p99"], 1),
            "latency_histogram": dict(self.latency_buckets),
            "cold_start": is_cold_start,
            "slo_availability": self._calculate_slo_availability(),
            "slo_performance": self._calculate_slo_performance(),
        }

    def cleanup_cache(self):
        """
        Clean expired cache entries based on TTL.
        """
        current_time = time.monotonic()
        expired_keys = []

        for key, timestamp in self._cache_times.items():
            if current_time - timestamp > self._cache_ttl:
                expired_keys.append(key)

        for key in expired_keys:
            self._member_cache.pop(key, None)
            self._channel_cache.pop(key, None)
            del self._cache_times[key]

        if expired_keys:
            _optimizer_logger.debug("cache_cleanup_completed", expired_count=len(expired_keys))

    def _calculate_slo_availability(self) -> float:
        """Calculate availability SLO based on successful vs failed operations."""
        total_ops = (
            self.metrics["commands_executed"] + self.metrics["rate_limit_denials"]
        )
        if total_ops == 0:
            return 100.0
        successful = total_ops - self.metrics["rate_limit_denials"]
        return round((successful / total_ops) * 100, 2)

    def _calculate_slo_performance(self) -> float:
        """Calculate performance SLO (P95 under threshold)."""
        if not self.latency_samples:
            return 100.0
        p95_target = getattr(config, "SLO_P95_TARGET_MS", 2000)
        latency_stats = self.get_latency_percentiles()
        return 100.0 if latency_stats["p95"] <= p95_target else 0.0

    def check_health_alerts(self):
        """Check for health issues and emit alerts with cooldown."""
        now = time.monotonic()

        if len(self._member_cache) == 0 and self.metrics["commands_executed"] > 10:
            alert_key = "cache_not_loaded"
            alert_info = self._health_alerts[alert_key]
            if now - alert_info["last_alert"] > alert_info["cooldown"]:
                _optimizer_logger.warning("cache_not_loaded_alert",
                    message="Cache appears not loaded despite command activity"
                )
                alert_info["last_alert"] = int(now)

        if hasattr(self.bot, "_reconnection_count"):
            reconnections = getattr(self.bot, "_reconnection_count", 0)
            if reconnections > getattr(config, "ALERT_RECONNECTION_THRESHOLD", 5):
                alert_key = "high_reconnections"
                alert_info = self._health_alerts[alert_key]
                if now - alert_info["last_alert"] > alert_info["cooldown"]:
                    _optimizer_logger.warning("high_reconnection_alert", reconnection_count=reconnections)
                    alert_info["last_alert"] = int(now)

        if hasattr(self.bot, "_watchdog_alert_triggered"):
            if self.bot._watchdog_alert_triggered:
                alert_key = "watchdog_triggered"
                alert_info = self._health_alerts[alert_key]
                if now - alert_info["last_alert"] > alert_info["cooldown"]:
                    _optimizer_logger.warning("watchdog_alert", message="Watchdog detected slow/stuck tasks")
                    alert_info["last_alert"] = int(now)
                    self.bot._watchdog_alert_triggered = False

    def track_correlation_id(self, correlation_id: str):
        """Track correlation ID for collision detection."""
        if correlation_id in self._correlation_ids_seen:
            self._correlation_collision_count += 1
            if self._correlation_collision_count % 10 == 0:
                _optimizer_logger.warning("correlation_id_collisions",
                    total_collisions=self._correlation_collision_count
                )
        else:
            self._correlation_ids_seen.add(correlation_id)
            if len(self._correlation_ids_seen) > 10000:
                recent_ids = list(self._correlation_ids_seen)[-5000:]
                self._correlation_ids_seen = set(recent_ids)

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
        if not hasattr(self.bot, "optimizer"):
            return await func(self, ctx, *args, **kwargs)

        start_time = time.monotonic()
        command_name = func.__name__

        try:
            result = await func(self, ctx, *args, **kwargs)
            execution_time = (time.monotonic() - start_time) * 1000
            self.bot.optimizer.track_command_execution(command_name, execution_time)
            return result

        except Exception as e:
            execution_time = (time.monotonic() - start_time) * 1000
            self.bot.optimizer.track_command_execution(
                f"{command_name}_ERROR", execution_time
            )
            raise

    return wrapper


async def optimized_run_db_query(
    original_func, bot, query: str, params: tuple = (), **kwargs
):
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
    if hasattr(bot, "optimizer"):
        bot.optimizer.track_db_query()

    start_time = time.monotonic()

    try:
        result = await original_func(query, params, **kwargs)
        execution_time = (time.monotonic() - start_time) * 1000

        if execution_time > 100:
            query_preview = query[:100] + "..." if len(query) > 100 else query
            context_info = ""
            if config.DEBUG and not config.PRODUCTION:
                ctx = current_command_context.get()
                if ctx:
                    if ctx.guild:
                        guild_info = f"guild={ctx.guild.id}"
                    else:
                        guild_info = f"guild=dm_user_{ctx.author.id if hasattr(ctx, 'author') else 'unknown'}"
                    user_info = (
                        f"user={ctx.author.id if hasattr(ctx, 'author') else 'unknown'}"
                    )
                    context_info = f" | {guild_info} | {user_info}"
            query_safe = query.replace("%s", "?").replace("%d", "?")
            query_preview = (
                query_safe[:100] + "..." if len(query_safe) > 100 else query_safe
            )
            _db_logger.warning("slow_query_detected",
                execution_time_ms=int(execution_time),
                query_preview=query_preview,
                context_info=context_info.strip() if context_info else None
            )

        return result

    except Exception as e:
        execution_time = (time.monotonic() - start_time) * 1000
        _db_logger.error("query_failed", execution_time_ms=int(execution_time), error=str(e))
        raise

# #################################################################################### #
#                            Discord Bot Startup
# #################################################################################### #
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

def handle_async_exception(loop, context):
    """
    Handle uncaught exceptions in async tasks.

    Args:
        loop: Event loop where exception occurred
        context: Exception context with details
    """
    exception = context.get("exception")
    if exception:
        _bot_logger.error("uncaught_async_exception", exception=str(exception), exc_info=exception)
    else:
        _bot_logger.error("uncaught_async_exception", message=context['message'])

loop.set_exception_handler(handle_async_exception)

# #################################################################################### #
#                            Discord Bot Initialization
# #################################################################################### #
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

def validate_config() -> None:
    """
    Validate configuration values at startup.

    Raises:
        SystemExit: If critical configuration is invalid
    """
    required_attrs = {
        "TOKEN": str,
        "LOG_FILE": str,
        "DEBUG": bool,
        "MAX_MEMORY_MB": (int, float),
        "MAX_CPU_PERCENT": (int, float),
        "MAX_RECONNECT_ATTEMPTS": int,
    }

    missing = []
    type_errors = []

    for attr, expected_type in required_attrs.items():
        if not hasattr(config, attr):
            missing.append(attr)
        else:
            value = getattr(config, attr)
            if not isinstance(value, expected_type):
                type_errors.append(
                    f"{attr} should be {expected_type.__name__ if isinstance(expected_type, type) else expected_type}, got {type(value).__name__}"
                )

    if missing:
        _bot_logger.critical("missing_config_attributes", missing_attributes=missing)
        raise SystemExit(1)

    if type_errors:
        _bot_logger.critical("config_type_errors", errors=type_errors)
        raise SystemExit(1)

    if hasattr(config, "MAX_MEMORY_MB") and config.MAX_MEMORY_MB < 100:
        _bot_logger.warning("low_memory_limit", max_memory_mb=config.MAX_MEMORY_MB, message="Very low memory limit may cause issues")

    if hasattr(config, "MAX_CPU_PERCENT") and config.MAX_CPU_PERCENT < 10:
        _bot_logger.warning("low_cpu_limit",
            max_cpu_percent=config.MAX_CPU_PERCENT,
            message="Very low CPU limit may trigger false alarms"
        )

    if hasattr(config, "CACHE_TTL_SECONDS") and config.CACHE_TTL_SECONDS < 60:
        _bot_logger.warning("low_cache_ttl",
            cache_ttl_seconds=config.CACHE_TTL_SECONDS,
            message="Very low cache TTL may reduce efficiency"
        )

    rate_limit_window = getattr(config, "RATE_LIMIT_WINDOW_SECONDS", 60)
    rate_limit_max = getattr(config, "RATE_LIMIT_COMMANDS_PER_GUILD_PER_MINUTE", 50)

    if rate_limit_window < 10:
        _bot_logger.warning("low_rate_limit_window", window_seconds=rate_limit_window)

    if rate_limit_max < 10:
        _bot_logger.warning("restrictive_rate_limit",
            commands_per_minute=rate_limit_max,
            message="Very restrictive rate limit"
        )

    _bot_logger.info("config_validation_completed")

def validate_token():
    """
    Validate Discord bot token format and return masked version for logging.

    Returns:
        Validated Discord token

    Raises:
        SystemExit: If token is invalid or missing
    """
    token = config.TOKEN
    if not token:
        _bot_logger.critical("missing_discord_token")
        raise SystemExit(1)

    if not isinstance(token, str) or len(token) < 50:
        _bot_logger.critical("invalid_token_format", reason="too_short", length=len(token))
        raise SystemExit(1)

    if token.strip() != token:
        _bot_logger.critical("invalid_token_format", reason="contains_whitespace")
        raise SystemExit(1)

    if token.count(".") < 2:
        _bot_logger.critical("invalid_token_format", reason="missing_structure", dots_count=token.count("."))
        raise SystemExit(1)

    if token.lower() in ["your_token_here", "bot_token", "discord_token"]:
        _bot_logger.critical("placeholder_token_detected", token_value=token.lower())
        raise SystemExit(1)

    if config.DEBUG and not config.PRODUCTION:
        masked_token = f"{token[:10]}...{token[-4:]}"
        _bot_logger.debug("token_validated", masked_token=masked_token)
    return token

current_command_context: ContextVar[Any] = ContextVar(
    "current_command_context", default=None
)
correlation_id_context: ContextVar[Optional[str]] = ContextVar(
    "correlation_id", default=None
)

bot = discord.Bot(intents=intents)
bot.translations = translations

bot.optimizer = BotOptimizer(bot)
bot.profiler = get_profiler()
bot.reliability_system = setup_reliability_system(bot)
bot._start_time_monotonic = time.monotonic()

original_run_db_query = run_db_query
bot.run_db_query = lambda *args, **kwargs: optimized_run_db_query(
    original_run_db_query, bot, *args, **kwargs
)

bot.get_member_optimized = bot.optimizer.get_member_optimized
bot.get_channel_optimized = bot.optimizer.get_channel_optimized

def register_background_task(task: asyncio.Task, task_name: str = "unknown") -> None:
    """
    Central API to register background tasks for proper cleanup.

    Args:
        task: AsyncIO task to register
        task_name: Human-readable task name for logging
    """
    if not hasattr(bot, "_background_tasks"):
        bot._background_tasks = []

    task._task_name = task_name
    task._last_yield = time.monotonic()

    bot._background_tasks.append(task)
    _bot_logger.debug("background_task_registered", task_name=task_name)

def heartbeat(task_name: Optional[str] = None):
    """Signal task is alive to watchdog. Call regularly in long-running tasks."""
    if hasattr(bot, "_background_tasks"):
        current_task = asyncio.current_task()
        if current_task:
            current_task._last_yield = time.monotonic()
            if task_name and not hasattr(current_task, "_task_name"):
                current_task._task_name = task_name

bot.heartbeat = heartbeat

async def task_watchdog():
    """
    Monitor background tasks for deadlocks and slow execution.
    Logs warnings if tasks don't yield control for too long.
    """
    watchdog_interval = getattr(config, "TASK_WATCHDOG_INTERVAL_SECONDS", 300)
    watchdog_threshold = getattr(config, "TASK_WATCHDOG_THRESHOLD_SECONDS", 600)

    try:
        while True:
            await asyncio.sleep(watchdog_interval)

            if hasattr(bot, "_background_tasks"):
                now = time.monotonic()
                for task in bot._background_tasks:
                    if task.done():
                        continue

                    task_name = getattr(task, "_task_name", "unknown")
                    last_yield = getattr(task, "_last_yield", now)
                    time_since_yield = now - last_yield

                    if time_since_yield > watchdog_threshold:
                        _bot_logger.warning("watchdog_deadlock_detected",
                            task_name=task_name,
                            time_since_yield_seconds=round(time_since_yield, 1)
                        )

                        if not hasattr(bot, "_watchdog_alert_triggered"):
                            bot._watchdog_alert_triggered = False
                        bot._watchdog_alert_triggered = True

                        task._last_yield = now
    except asyncio.CancelledError:
        _bot_logger.debug("watchdog_cancelled")
        raise

bot.register_background_task = register_background_task

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
    _bot_logger.info("creating_slash_command_groups")

    GROUPS_DATA = translations.get("slash_command_groups", {})

    bot.admin_group = discord.SlashCommandGroup(
        name=GROUPS_DATA.get("admin_bot", {}).get("name", {}).get("en-US", "admin_bot"),
        description=GROUPS_DATA.get("admin_bot", {})
        .get("description", {})
        .get("en-US", "Bot administration commands"),
        name_localizations=GROUPS_DATA.get("admin_bot", {}).get("name", {}),
        description_localizations=GROUPS_DATA.get("admin_bot", {}).get(
            "description", {}
        ),
        default_member_permissions=discord.Permissions(administrator=True),
    )

    bot.absence_group = discord.SlashCommandGroup(
        name=GROUPS_DATA.get("absence", {}).get("name", {}).get("en-US", "absence"),
        description=GROUPS_DATA.get("absence", {})
        .get("description", {})
        .get("en-US", "Manage member absence status"),
        name_localizations=GROUPS_DATA.get("absence", {}).get("name", {}),
        description_localizations=GROUPS_DATA.get("absence", {}).get("description", {}),
        default_member_permissions=discord.Permissions(manage_guild=True),
    )

    bot.member_group = discord.SlashCommandGroup(
        name=GROUPS_DATA.get("member", {}).get("name", {}).get("en-US", "member"),
        description=GROUPS_DATA.get("member", {})
        .get("description", {})
        .get("en-US", "Member profile and stats management"),
        name_localizations=GROUPS_DATA.get("member", {}).get("name", {}),
        description_localizations=GROUPS_DATA.get("member", {}).get("description", {}),
        default_member_permissions=discord.Permissions(send_messages=True),
    )

    bot.loot_group = discord.SlashCommandGroup(
        name=GROUPS_DATA.get("loot", {}).get("name", {}).get("en-US", "loot"),
        description=GROUPS_DATA.get("loot", {})
        .get("description", {})
        .get("en-US", "Epic T2 loot wishlist management"),
        name_localizations=GROUPS_DATA.get("loot", {}).get("name", {}),
        description_localizations=GROUPS_DATA.get("loot", {}).get("description", {}),
        default_member_permissions=discord.Permissions(send_messages=True),
    )

    bot.staff_group = discord.SlashCommandGroup(
        name=GROUPS_DATA.get("staff", {}).get("name", {}).get("en-US", "staff"),
        description=GROUPS_DATA.get("staff", {})
        .get("description", {})
        .get("en-US", "Staff management commands"),
        name_localizations=GROUPS_DATA.get("staff", {}).get("name", {}),
        description_localizations=GROUPS_DATA.get("staff", {}).get("description", {}),
        default_member_permissions=discord.Permissions(manage_roles=True),
    )

    bot.events_group = discord.SlashCommandGroup(
        name=GROUPS_DATA.get("events", {}).get("name", {}).get("en-US", "events"),
        description=GROUPS_DATA.get("events", {})
        .get("description", {})
        .get("en-US", "Guild event management"),
        name_localizations=GROUPS_DATA.get("events", {}).get("name", {}),
        description_localizations=GROUPS_DATA.get("events", {}).get("description", {}),
        default_member_permissions=discord.Permissions(manage_events=True),
    )

    bot.statics_group = discord.SlashCommandGroup(
        name=GROUPS_DATA.get("statics", {}).get("name", {}).get("en-US", "statics"),
        description=GROUPS_DATA.get("statics", {})
        .get("description", {})
        .get("en-US", "Static group management"),
        name_localizations=GROUPS_DATA.get("statics", {}).get("name", {}),
        description_localizations=GROUPS_DATA.get("statics", {}).get("description", {}),
        default_member_permissions=discord.Permissions(manage_roles=True),
    )

    groups = [
        ("admin_bot", bot.admin_group),
        ("absence", bot.absence_group),
        ("member", bot.member_group),
        ("loot", bot.loot_group),
        ("staff", bot.staff_group),
        ("events", bot.events_group),
        ("statics", bot.statics_group),
    ]

    for group_name, group in groups:
        try:
            bot.add_application_command(group)
            _bot_logger.debug("command_group_registered", group_name=group_name)
        except Exception as e:
            _bot_logger.error("command_group_registration_failed",
                group_name=group_name,
                error=str(e),
                exc_info=True
            )

    _bot_logger.info("command_groups_registered", total_groups=len(groups))

def setup_global_group_error_handlers(bot: discord.Bot) -> None:
    from .core.functions import get_user_message

    groups = [
        ("admin_bot", bot.admin_group),
        ("absence", bot.absence_group),
        ("member", bot.member_group),
        ("loot", bot.loot_group),
        ("staff", bot.staff_group),
        ("events", bot.events_group),
        ("statics", bot.statics_group),
    ]

    async def global_group_error_handler(
        ctx: discord.ApplicationContext, error: Exception
    ):
        """
        Centralized error handler for all slash command groups.

        Args:
            ctx: Discord application context
            error: Exception that occurred during command execution
        """

        command_info = (
            ctx.command.name if hasattr(ctx, "command") and ctx.command else "None"
        )
        guild_info = ctx.guild.id if ctx.guild else "None"
        _bot_logger.error("global_error_handler",
            error_type=type(error).__name__,
            error_message=str(error),
            guild_id=guild_info,
            command=command_info
        )

        group_name = "unknown"
        command_name = "unknown"

        if hasattr(ctx.command, "parent") and ctx.command.parent:
            group_name = ctx.command.parent.name
            command_name = ctx.command.name
        elif hasattr(ctx.command, "name"):
            command_name = ctx.command.name

        if config.DEBUG and not config.PRODUCTION:
            _bot_logger.error("command_error_debug",
                group_name=group_name,
                command_name=command_name,
                guild_id=ctx.guild.id if ctx.guild else "DM",
                error=str(error),
                exc_info=True
            )
        else:
            _bot_logger.error("command_error",
                group_name=group_name,
                command_name=command_name,
                error=str(error)
            )

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

        error_message = await get_user_message(
            ctx, bot.translations, error_key, **error_params
        )

        if not error_message:
            fallback_messages = {
                "global_errors.forbidden": "❌ Missing permissions to execute this command",
                "global_errors.not_found": "❌ Required resource not found (channel, role, or message)",
                "global_errors.http_exception": "❌ Discord API error occurred. Please try again",
                "global_errors.missing_permissions": "❌ You don't have the necessary permissions",
                "global_errors.bot_missing_permissions": "❌ The bot doesn't have the necessary permissions",
                "global_errors.unknown": f"❌ Unexpected error in {group_name}/{command_name}",
            }
            error_message = fallback_messages.get(
                error_key, "❌ An unexpected error occurred"
            )

        try:
            if ctx.response.is_done():
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.respond(error_message, ephemeral=True)
        except Exception as send_error:
            _bot_logger.error("error_message_send_failed", error=str(send_error))

    for group_name, group in groups:
        try:
            group.error(global_group_error_handler)
            _bot_logger.debug("error_handler_added", group_name=group_name)
        except Exception as e:
            _bot_logger.error("error_handler_add_failed", group_name=group_name, error=str(e))

    _bot_logger.info("error_handlers_setup_completed")

create_command_groups(bot)
setup_global_group_error_handlers(bot)

EXTENSIONS: Final[tuple[str, ...]] = (
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
    "cogs.autorole",
)

def load_extensions():
    """
    Load all Discord bot extensions (cogs) with error handling.

    Raises:
        SystemExit: If too many extensions fail to load
    """
    if hasattr(bot, "_extensions_loaded") and bot._extensions_loaded:
        _bot_logger.debug("extensions_already_loaded")
        return

    failed_extensions = []
    for ext in EXTENSIONS:
        try:
            bot.load_extension(ext)
            _bot_logger.debug("extension_loaded", extension=ext)
        except Exception as e:
            failed_extensions.append(ext)
            _bot_logger.error("extension_load_failed", extension=ext, exc_info=True)

    if failed_extensions:
        _bot_logger.warning("some_extensions_failed",
            failed_count=len(failed_extensions),
            failed_extensions=failed_extensions
        )

    if len(failed_extensions) >= len(EXTENSIONS) // 2:
        _bot_logger.critical("too_many_extensions_failed", failed_count=len(failed_extensions), total_count=len(EXTENSIONS))
        raise SystemExit(1)

    bot._extensions_loaded = True

# #################################################################################### #
#                            Extra Event Hooks
# #################################################################################### #
@bot.event
async def on_disconnect() -> None:
    """
    Handle Discord gateway disconnection event.
    """
    _bot_logger.warning("gateway_disconnected")


@bot.event
async def on_resumed() -> None:
    """
    Handle Discord gateway resume event.
    """
    _bot_logger.info("gateway_resumed")


@bot.before_invoke
async def global_rate_limit(ctx):
    """
    Global rate limiting before command execution.

    Args:
        ctx: Discord command context

    Raises:
        RateLimitExceeded: If rate limit is exceeded
    """
    correlation_id = str(uuid.uuid4())[:8]
    correlation_id_context.set(correlation_id)
    current_command_context.set(ctx)

    if hasattr(bot, "optimizer"):
        bot.optimizer.track_correlation_id(correlation_id)

    _bot_logger.info("command_started", command=ctx.command.name if ctx.command else 'unknown', correlation_id=correlation_id)

    guild_id = ctx.guild.id if ctx.guild else "dm_context"
    user_id = ctx.author.id
    command_name = (
        f"{ctx.command.parent.name}/{ctx.command.name}"
        if ctx.command.parent
        else ctx.command.name
    )
    _bot_logger.debug("command_executing", command=command_name, guild_id=guild_id, user_id=user_id)

    if guild_id == "dm_context":
        guild_key = f"dm_user_{user_id}"
    else:
        guild_key = f"guild_{guild_id}"
    now = time.monotonic()

    if not hasattr(bot, "guild_command_cooldowns"):
        bot.guild_command_cooldowns = defaultdict(lambda: deque())
        bot.guild_last_activity = defaultdict(float)

    window_seconds = getattr(config, "RATE_LIMIT_WINDOW_SECONDS", 60)
    cutoff = now - window_seconds

    if not hasattr(bot.guild_command_cooldowns[guild_key], "popleft"):
        old_timestamps = sorted(bot.guild_command_cooldowns[guild_key])
        bot.guild_command_cooldowns[guild_key] = deque(
            t for t in old_timestamps if t >= cutoff
        )
    else:
        while (
            bot.guild_command_cooldowns[guild_key]
            and bot.guild_command_cooldowns[guild_key][0] < cutoff
        ):
            bot.guild_command_cooldowns[guild_key].popleft()

    if not hasattr(bot, "_rate_limit_counter"):
        bot._rate_limit_counter = 0
    bot._rate_limit_counter += 1

    if bot._rate_limit_counter % 5000 == 0:
        inactive_threshold = now - getattr(
            config, "RATE_LIMIT_PURGE_INACTIVE_SECONDS", 3600
        )
        inactive_guilds = []
        for g_key in list(bot.guild_command_cooldowns.keys()):
            last_activity = bot.guild_last_activity.get(g_key, 0)
            if last_activity < inactive_threshold:
                inactive_guilds.append(g_key)
        for g_key in inactive_guilds:
            bot.guild_command_cooldowns.pop(g_key, None)
            bot.guild_last_activity.pop(g_key, None)
        if inactive_guilds:
            _bot_logger.debug("rate_limiter_purged_inactive", purged_count=len(inactive_guilds))

        if hasattr(bot, "optimizer"):
            bot.optimizer.check_health_alerts()

    max_commands_per_guild = getattr(
        config, "RATE_LIMIT_COMMANDS_PER_GUILD_PER_MINUTE", 50
    )
    if len(bot.guild_command_cooldowns[guild_key]) >= max_commands_per_guild:
        _bot_logger.warning("guild_rate_limit_exceeded",
            guild_id=guild_id,
            commands_per_minute=len(bot.guild_command_cooldowns[guild_key])
        )
        if hasattr(bot, "optimizer"):
            bot.optimizer.metrics["rate_limit_denials"] += 1
        raise RateLimitExceeded("Rate limit exceeded")

    bot.guild_command_cooldowns[guild_key].append(now)
    bot.guild_last_activity[guild_key] = now

@bot.after_invoke
async def clear_context(ctx):
    """Clear stored context after command execution."""
    _bot_logger.info("command_completed", command=ctx.command.name if ctx.command else 'unknown')
    current_command_context.set(None)
    correlation_id_context.set(None)

class RateLimitExceeded(discord.ApplicationCommandError):
    pass

@bot.event
async def on_application_command_error(
    ctx: discord.ApplicationContext, error: discord.DiscordException
):
    """Handle application command errors including rate limiting."""
    current_command_context.set(None)
    correlation_id_context.set(None)

    if isinstance(error, RateLimitExceeded):
        try:
            await ctx.respond(
                "⏰ Too many commands! Please wait a minute before trying again.",
                ephemeral=True,
            )
        except Exception:
            pass
        return

@bot.event
async def on_command_error(ctx, error):
    """Handle traditional command errors."""
    current_command_context.set(None)
    correlation_id_context.set(None)

@bot.event
async def on_ready() -> None:
    """
    Handle bot ready event and initialize background tasks.
    """
    _bot_logger.info("bot_connected", username=str(bot.user), user_id=bot.user.id)

    if not hasattr(bot, "_db_pool_initialized"):
        bot._db_pool_initialized = True
        try:
            db_initialized = await initialize_db_pool()
            if not db_initialized:
                _bot_logger.critical("database_pool_init_failed", message="Failed to initialize database pool - shutting down")
                await bot.close()
                raise SystemExit(1)
            _bot_logger.info("database_pool_initialized")
        except Exception as e:
            _bot_logger.critical("database_init_error", error=str(e))
            await bot.close()
            raise SystemExit(1)

    if not hasattr(bot, "_background_tasks"):
        bot._background_tasks = []

    if not hasattr(bot, "http_session"):
        timeout_total = getattr(config, "HTTP_TIMEOUT_TOTAL", 30)
        timeout_connect = getattr(config, "HTTP_TIMEOUT_CONNECT", 10)
        limit_total = getattr(config, "HTTP_LIMIT_TOTAL", 100)
        limit_per_host = getattr(config, "HTTP_LIMIT_PER_HOST", 10)

        timeout = aiohttp.ClientTimeout(total=timeout_total, connect=timeout_connect)

        connector_kwargs = {
            "limit": limit_total,
            "limit_per_host": limit_per_host,
            "ttl_dns_cache": getattr(config, "HTTP_DNS_CACHE_TTL", 300),
            "use_dns_cache": True,
        }

        if getattr(config, "HTTP_FORCE_IPV4", False):
            connector_kwargs["family"] = socket.AF_INET

        connector = aiohttp.TCPConnector(**connector_kwargs)

        bot.http_session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        _bot_logger.debug("http_session_created",
            timeout_total=timeout_total,
            connections_limit=limit_total,
            ipv4_only=getattr(config, 'HTTP_FORCE_IPV4', False)
        )

    if not hasattr(bot, "_cache_load_attempted"):
        bot._cache_load_attempted = True

        max_retries = 3
        retry_count = 0
        cache_loaded = False

        while retry_count < max_retries and not cache_loaded:
            try:
                retry_count += 1
                _bot_logger.info("cache_load_attempt", attempt=retry_count, max_retries=max_retries)

                await bot.cache_loader.load_all_shared_data()
                cache_loaded = True
                bot.cache._initial_load_complete = True
                _bot_logger.info("cache_load_completed", message="Initial cache load completed successfully - all categories loaded ONCE")

            except Exception as e:
                _bot_logger.error("cache_load_failed", attempt=retry_count, error=str(e), exc_info=True)

                if retry_count < max_retries:
                    wait_time = min(60, 5 * (2 ** (retry_count - 1)))
                    _bot_logger.warning("cache_load_retry", wait_time_seconds=wait_time)
                    await asyncio.sleep(wait_time)
                else:
                    _bot_logger.critical("cache_load_max_attempts_failed", attempts=3)
                    _bot_logger.critical("cache_load_critical_failure", message="The bot cannot function properly without cache")
                    _bot_logger.critical("shutdown_initiated", reason="cache_load_failure")

                    try:
                        await bot.close()
                    except:
                        pass

                    _bot_logger.critical("shutdown_complete", exit_code=1, message="Please check database connection and restart manually")
                    raise SystemExit(1)

        if not cache_loaded:
            bot.cache._initial_load_failed = True
            _bot_logger.error("cache_load_failed_all_retries", message="Bot will run with limited functionality")

    if PSUTIL_AVAILABLE and not hasattr(bot, "_monitor_task"):
        bot._monitor_task = asyncio.create_task(
            monitor_resources(), name="resource_monitoring"
        )
        bot.register_background_task(bot._monitor_task, "resource_monitoring")

    if not hasattr(bot, "_optimization_setup_done"):
        bot._optimization_setup_done = True

        async def cache_cleanup_task():
            try:
                while True:
                    await asyncio.sleep(600)
                    bot.optimizer.cleanup_cache()
            except asyncio.CancelledError:
                _bot_logger.debug("cache_cleanup_task_cancelled")
                raise

        cleanup_task = asyncio.create_task(cache_cleanup_task(), name="cache_cleanup")
        bot.register_background_task(cleanup_task, "cache_cleanup")

        await start_cache_maintenance_task(bot)
        await start_cleanup_task(bot)

        async def periodic_rate_limit_cleanup():
            try:
                while True:
                    await asyncio.sleep(
                        getattr(config, "RATE_LIMIT_CLEANUP_INTERVAL_SECONDS", 1800)
                    )
                    if hasattr(bot, "guild_command_cooldowns"):
                        now = time.monotonic()
                        inactive_threshold = now - getattr(
                            config, "RATE_LIMIT_PURGE_INACTIVE_SECONDS", 3600
                        )
                        inactive_guilds = []
                        for g_key in list(bot.guild_command_cooldowns.keys()):
                            last_activity = bot.guild_last_activity.get(g_key, 0)
                            if last_activity < inactive_threshold:
                                inactive_guilds.append(g_key)
                        for g_key in inactive_guilds:
                            bot.guild_command_cooldowns.pop(g_key, None)
                            bot.guild_last_activity.pop(g_key, None)
                        if inactive_guilds:
                            _bot_logger.debug("periodic_cleanup_purged", purged_count=len(inactive_guilds))
            except asyncio.CancelledError:
                _bot_logger.debug("periodic_cleanup_cancelled")
                raise

        periodic_cleanup = asyncio.create_task(
            periodic_rate_limit_cleanup(), name="periodic_rate_limit_cleanup"
        )
        bot.register_background_task(periodic_cleanup, "periodic_rate_limit_cleanup")

        if getattr(config, "TASK_WATCHDOG_ENABLED", True):
            watchdog_task = asyncio.create_task(task_watchdog(), name="task_watchdog")
            bot.register_background_task(watchdog_task, "task_watchdog")
            _bot_logger.debug("task_watchdog_started")

        _bot_logger.info("optimization_setup_completed", message="Intelligent cache system with smart features started")

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
    smart_cache_stats = (
        bot.cache.get_smart_stats() if hasattr(bot.cache, "get_smart_stats") else {}
    )

    embed = discord.Embed(title="📊 Bot Performance", color=discord.Color.blue())

    embed.add_field(
        name="🎯 Commands", value=f"{stats['commands_executed']} executed", inline=True
    )

    embed.add_field(
        name="🌐 Discord API", value=f"{stats['api_calls_total']} calls", inline=True
    )

    if smart_cache_stats:
        embed.add_field(
            name="🧠 Smart Cache",
            value=f"Size: {smart_cache_stats.get('cache_size', 0)}\nHit Rate: {smart_cache_stats.get('hit_rate', 0):.1f}%\nHot Keys: {smart_cache_stats.get('hot_keys', 0)}",
            inline=True,
        )
        embed.add_field(
            name="🔮 Predictions",
            value=f"Accuracy: {smart_cache_stats.get('prediction_accuracy', 0):.1f}%\nPreload Efficiency: {smart_cache_stats.get('preload_efficiency', 0):.1f}%\nActive Tasks: {smart_cache_stats.get('active_preload_tasks', 0)}",
            inline=True,
        )

    embed.add_field(
        name="💾 Cache",
        value=f"{stats['cache_hit_rate']}% hit rate\n{stats['cache_size']} entries",
        inline=True,
    )

    embed.add_field(
        name="🗄️ Database", value=f"{stats['db_queries_count']} queries", inline=True
    )

    embed.add_field(
        name="⏱️ Uptime", value=f"{stats['uptime_hours']:.1f} hours", inline=True
    )

    embed.add_field(
        name="📊 Latency (ms)",
        value=f"p50: {stats['latency_p50']}\np95: {stats['latency_p95']}\np99: {stats['latency_p99']}",
        inline=True,
    )

    embed.add_field(
        name="🚫 Rate Limits",
        value=f"{stats['rate_limit_denials']} denials",
        inline=True,
    )

    histogram = stats["latency_histogram"]
    fast_pct = round(
        100
        * (histogram["<=50ms"] + histogram["<=100ms"])
        / max(1, stats["commands_executed"]),
        1,
    )
    slow_pct = round(
        100
        * (
            histogram["<=2s"]
            + histogram["<=5s"]
            + histogram["<=10s"]
            + histogram[">10s"]
        )
        / max(1, stats["commands_executed"]),
        1,
    )

    embed.add_field(
        name="⚡ Response Speed",
        value=f"Fast (<100ms): {fast_pct}%\nSlow (>1s): {slow_pct}%",
        inline=True,
    )

    performance_score = (
        "Excellent"
        if stats["cache_hit_rate"] > 70
        else "Good" if stats["cache_hit_rate"] > 50 else "Needs improvement"
    )
    embed.add_field(name="🏆 Overall Score", value=performance_score, inline=True)

    await ctx.followup.send(embed=embed, ephemeral=True)

@bot.slash_command(name="health", description="Bot health check")
@discord.default_permissions(administrator=True)
async def health_check(ctx):
    """Simple health check for monitoring systems."""
    await ctx.defer(ephemeral=True)

    status = {
        "status": "ok",
        "uptime": f"{(time.monotonic() - getattr(bot, '_start_time_monotonic', time.monotonic())) / 3600:.1f}h",
        "guilds": len(bot.guilds),
        "cache_loaded": getattr(bot.cache, "_initial_load_complete", False),
    }

    await ctx.followup.send(f"🟢 Bot healthy: {status}", ephemeral=True)

# #################################################################################### #
#                            Resource Monitoring
# #################################################################################### #
async def monitor_resources():
    """
    Monitor system resources (CPU, memory) and log warnings for high usage.
    """
    try:
        process = None
        if PSUTIL_AVAILABLE and psutil:
            process = psutil.Process()
            process.cpu_percent()
            await asyncio.sleep(1)

        while True:
            try:
                if PSUTIL_AVAILABLE and psutil and process:
                    memory_mb = process.memory_info().rss / 1024 / 1024
                    cpu_percent = process.cpu_percent()

                    if memory_mb > config.MAX_MEMORY_MB:
                        _bot_logger.warning("high_memory_usage",
                            memory_mb=round(memory_mb, 1),
                            limit_mb=config.MAX_MEMORY_MB
                        )
                    if cpu_percent > config.MAX_CPU_PERCENT:
                        _bot_logger.warning("high_cpu_usage",
                            cpu_percent=round(cpu_percent, 1),
                            limit_percent=config.MAX_CPU_PERCENT
                        )

                    current_time = int(time.time())
                    current_hour = current_time // 3600

                    if not hasattr(monitor_resources, "_last_log_hour"):
                        monitor_resources._last_log_hour = current_hour - 1

                    if current_hour > monitor_resources._last_log_hour:
                        monitor_resources._last_log_hour = current_hour
                        _bot_logger.info("resource_usage", memory_mb=round(memory_mb, 1), cpu_percent=round(cpu_percent, 1))

                await asyncio.sleep(300)
            except Exception as e:
                _bot_logger.error("resource_monitoring_error", error=str(e))
                await asyncio.sleep(300)
    except asyncio.CancelledError:
        _bot_logger.debug("resource_monitoring_cancelled")
        raise

# #################################################################################### #
#                            Resilient runner
# #################################################################################### #
def setup_tracemalloc():
    """Setup tracemalloc for memory debugging if enabled."""
    if config.DEBUG and getattr(config, "TRACEMALLOC_ENABLED", False):
        tracemalloc.start(25)
        _bot_logger.info("tracemalloc_started")

        def dump_memory_snapshot(signum, frame):
            try:
                snapshot = tracemalloc.take_snapshot()
                top_stats = snapshot.statistics("lineno")[:10]

                _bot_logger.info("memory_snapshot_top_allocations")
                for index, stat in enumerate(top_stats, 1):
                    _bot_logger.info("memory_allocation", index=index, stats=str(stat))

                current, peak = tracemalloc.get_traced_memory()
                _bot_logger.info("memory_usage_summary",
                    current_mb=round(current / 1024 / 1024, 1),
                    peak_mb=round(peak / 1024 / 1024, 1)
                )

            except Exception as e:
                _bot_logger.error("memory_snapshot_error", error=str(e))

        if hasattr(signal, "SIGUSR1"):
            signal.signal(signal.SIGUSR1, dump_memory_snapshot)
            _bot_logger.info("signal_handler_setup", signal="SIGUSR1", platform="Unix")
        elif hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, dump_memory_snapshot)
            _bot_logger.info("signal_handler_setup", signal="SIGBREAK", platform="Windows")
        else:
            _bot_logger.warning("no_signal_handler_available", message="No suitable signal available for memory snapshots")

async def run_bot():
    """
    Main bot runner with retry logic for resilient startup.
    """
    setup_tracemalloc()
    validate_config()

    if not hasattr(bot, "_extensions_loaded"):
        load_extensions()
        bot._extensions_loaded = True
    max_retries = config.MAX_RECONNECT_ATTEMPTS
    retry_count = 0

    try:
        while retry_count < max_retries:
            try:
                await bot.start(validate_token())
            except asyncio.CancelledError:
                _bot_logger.info("bot_startup_cancelled")
                break
            except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as e:
                retry_count += 1
                base_wait_time = min(300, 15 * (2 ** (retry_count - 1)))
                jitter = random.uniform(0.1, 0.5) * base_wait_time
                wait_time = base_wait_time + jitter
                _bot_logger.error("network_error_retry",
                    attempt=retry_count,
                    max_retries=max_retries,
                    wait_time_seconds=round(wait_time, 1),
                    exc_info=True
                )
                if retry_count >= max_retries:
                    _bot_logger.critical("max_retries_reached")
                    break
                await bot.close()
                await asyncio.sleep(wait_time)
            except Exception as e:
                _bot_logger.critical("startup_critical_error", error=str(e), exc_info=True)
                break
            else:
                break
    finally:
        _bot_logger.info("shutdown_cleanup_started")
        await cleanup_background_tasks()

async def cleanup_background_tasks():
    """
    Cancel all background tasks properly during shutdown with timeout bounds.
    """
    shutdown_timeout = getattr(config, "SHUTDOWN_TIMEOUT_SECONDS", 10)

    if hasattr(bot, "_scheduler_loop") and bot._scheduler_loop:
        if bot._scheduler_loop.is_running():
            _bot_logger.debug("scheduler_loop_stopping")
            bot._scheduler_loop.cancel()
        bot._scheduler_loop = None

    if hasattr(bot, "_background_tasks"):
        _bot_logger.debug("background_tasks_cancelling", task_count=len(bot._background_tasks))
        for task in bot._background_tasks:
            if not task.done():
                task.cancel()

        if bot._background_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*bot._background_tasks, return_exceptions=True),
                    timeout=shutdown_timeout,
                )
                _bot_logger.debug("background_tasks_cleanup_completed")
            except asyncio.TimeoutError:
                _bot_logger.warning("background_tasks_cleanup_timeout",
                    timeout_seconds=shutdown_timeout,
                    message="Forcing shutdown"
                )
                for task in bot._background_tasks:
                    if not task.done():
                        task.cancel()
        bot._background_tasks.clear()

    if hasattr(bot, "http_session") and bot.http_session:
        try:
            if not bot.http_session.closed:
                await asyncio.wait_for(bot.http_session.close(), timeout=5)

            connector = getattr(bot.http_session, "_connector", None)
            if connector and not connector.closed:
                await asyncio.wait_for(connector.close(), timeout=2)

            _bot_logger.debug("http_session_closed")
        except asyncio.TimeoutError:
            _bot_logger.warning("http_session_close_timeout", message="Continuing shutdown")
        except Exception as e:
            _bot_logger.warning("http_session_close_error", error=str(e))
        finally:
            bot.http_session = None

    if hasattr(bot, "_db_pool_initialized") and bot._db_pool_initialized:
        try:
            await close_db_pool()
            _bot_logger.debug("database_pool_closed")
        except Exception as e:
            _bot_logger.warning("database_pool_close_error", error=str(e))

def _graceful_exit(sig_name):
    """
    Handle graceful shutdown on system signals.

    Args:
        sig_name: Signal name that triggered shutdown
    """
    _bot_logger.warning("signal_received", signal=sig_name, action="initiating_graceful_shutdown")

    async def shutdown():
        try:
            await cleanup_background_tasks()
            if not bot.is_closed():
                await bot.close()
            _bot_logger.info("graceful_shutdown_completed")
        except Exception as e:
            _bot_logger.error("shutdown_error", error=str(e), exc_info=True)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(shutdown())
    except RuntimeError:
        try:
            asyncio.run(shutdown())
        except Exception as e:
            _bot_logger.critical("graceful_shutdown_failed", error=str(e))
            os._exit(1)

if __name__ == "__main__":
    signals_to_handle = []
    if hasattr(signal, "SIGTERM"):
        signals_to_handle.append(signal.SIGTERM)
    if hasattr(signal, "SIGINT"):
        signals_to_handle.append(signal.SIGINT)

    for sig in signals_to_handle:
        try:
            loop.add_signal_handler(sig, _graceful_exit, sig.name)
            _bot_logger.debug("signal_handler_registered", signal=sig.name, method="loop")
        except (NotImplementedError, AttributeError):
            signal.signal(
                sig, lambda signum, frame: _graceful_exit(signal.Signals(signum).name)
            )
            _bot_logger.debug("signal_handler_registered", signal=sig.name, method="signal_module")

    try:
        loop.run_until_complete(run_bot())
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
