"""
Rate Limiting System - Enterprise-grade protection with O(1) performance optimization.

This module provides comprehensive rate limiting for Discord bot commands with:

RATE LIMITING:
- Per-user, per-guild, and global scope protection
- O(1) deque-based sliding window for optimal performance
- Adaptive purge system with /5000 operation trigger
- Thread-safe async operations with comprehensive locking

OBSERVABILITY:
- JSON structured logging with correlation ID support
- PII masking for production compliance (PRODUCTION=true)
- Performance metrics and cleanup statistics
- Rate limit hit tracking and analysis

PERFORMANCE:
- Monotonic time for calculation accuracy
- Memory-efficient sliding window implementation
- Background cleanup with configurable intervals
- Optimized data structures for high-load scenarios

SECURITY:
- DM-specific key handling (dm_user_ID format)
- Qualified command name resolution for slash groups
- Graceful degradation for edge cases
- Production-hardened error handling

Architecture: Enterprise-grade with comprehensive monitoring, automatic cleanup,
and performance optimization for high-traffic Discord bot environments.
"""

import asyncio
import time
from collections import deque

from .logger import ComponentLogger
from functools import wraps
from typing import Dict, Tuple, Callable, Deque, Union
from contextvars import ContextVar

import discord
from discord.ext import commands

correlation_id_context: ContextVar[str | None] = ContextVar(
    "correlation_id", default=None
)

_logger = ComponentLogger("rate_limiter")

class RateLimiter:
    """Enterprise-grade rate limiter with O(1) deque-based sliding windows."""

    def __init__(self):
        """
        Initialize rate limiter with optimized data structures and observability.
        """
        self.user_limits: Dict[str, Dict[int, float]] = {}
        self.guild_limits: Dict[str, Dict[Union[int, str], float]] = {}
        self.global_limits: Dict[str, float] = {}
        self.guild_deque: Deque[Tuple[float, str, str]] = deque(maxlen=10000)
        self.command_deques: Dict[str, Deque[Tuple[float, str]]] = {}
        self._lock = asyncio.Lock()
        self._operation_count = 0
        self._purge_threshold = 5000
        self._high_cooldown_threshold = 300

    async def is_rate_limited(
        self,
        command_name: str,
        user_id: int | None = None,
        guild_key: Union[int, str, None] = None,
        cooldown_seconds: int = 60,
        scope: str = "user",
    ) -> Tuple[bool, float]:
        """
        Check if a command is rate limited and update tracking.

        Args:
            command_name: Name of the command to check
            user_id: Discord user ID (required for user scope)
            guild_key: Discord guild ID (int) or DM key (str) for guild scope
            cooldown_seconds: Cooldown period in seconds
            scope: Rate limit scope (user, guild, or global)

        Returns:
            Tuple containing (is_limited: bool, remaining_time: float)
        """
        async with self._lock:
            now = time.monotonic()
            self._operation_count += 1

            if self._operation_count % self._purge_threshold == 0:
                await self._adaptive_purge(now)

            if (
                scope == "guild"
                and guild_key is not None
                and cooldown_seconds > self._high_cooldown_threshold
            ):
                await self._manage_command_specific_deque(
                    command_name, guild_key, now, cooldown_seconds
                )

            if scope == "user" and user_id:
                if command_name not in self.user_limits:
                    self.user_limits[command_name] = {}

                last_used = self.user_limits[command_name].get(user_id, 0)
                remaining = cooldown_seconds - (now - last_used)

                if remaining > 0:
                    return True, remaining

                self.user_limits[command_name][user_id] = now

            elif scope == "guild" and guild_key is not None:
                if command_name not in self.guild_limits:
                    self.guild_limits[command_name] = {}

                dict_last_used = self.guild_limits[command_name].get(guild_key, 0)
                dict_remaining = cooldown_seconds - (now - dict_last_used)

                if dict_remaining > 0:
                    return True, dict_remaining

                self.guild_limits[command_name][guild_key] = now

                deque_key = f"{command_name}:{guild_key}"

                while (
                    self.guild_deque and now - self.guild_deque[0][0] > cooldown_seconds
                ):
                    expired_timestamp, expired_cmd, expired_key = (
                        self.guild_deque.popleft()
                    )
                    if expired_cmd in self.guild_limits:
                        for gk, timestamp in list(
                            self.guild_limits[expired_cmd].items()
                        ):
                            if abs(timestamp - expired_timestamp) < 0.1:
                                if now - timestamp > cooldown_seconds:
                                    del self.guild_limits[expired_cmd][gk]
                                break

                self.guild_deque.append((now, command_name, deque_key))

            elif scope == "global":
                last_used = self.global_limits.get(command_name, 0)
                remaining = cooldown_seconds - (now - last_used)

                if remaining > 0:
                    return True, remaining

                self.global_limits[command_name] = now

            return False, 0.0

    async def _adaptive_purge(self, now: float) -> None:
        """Perform adaptive purge of old entries across all rate limit stores."""
        try:
            purge_start = time.monotonic()

            user_purged = 0
            for command_name in list(self.user_limits.keys()):
                users_to_remove = [
                    user_id
                    for user_id, last_used in self.user_limits[command_name].items()
                    if now - last_used > 86400
                ]
                for user_id in users_to_remove:
                    del self.user_limits[command_name][user_id]
                    user_purged += 1

                if not self.user_limits[command_name]:
                    del self.user_limits[command_name]

            guild_purged = 0
            for command_name in list(self.guild_limits.keys()):
                guilds_to_remove = [
                    guild_id
                    for guild_id, last_used in self.guild_limits[command_name].items()
                    if now - last_used > 86400
                ]
                for guild_id in guilds_to_remove:
                    del self.guild_limits[command_name][guild_id]
                    guild_purged += 1

                if not self.guild_limits[command_name]:
                    del self.guild_limits[command_name]

            global_purged = 0
            commands_to_remove = [
                command
                for command, last_used in self.global_limits.items()
                if now - last_used > 86400
            ]
            for command in commands_to_remove:
                del self.global_limits[command]
                global_purged += 1

            purge_duration = time.monotonic() - purge_start

            _logger.info("adaptive_purge_completed",
                user_entries_purged=user_purged,
                guild_entries_purged=guild_purged,
                global_entries_purged=global_purged,
                purge_duration_ms=round(purge_duration * 1000, 2),
                operation_count=self._operation_count,
            )

        except Exception as e:
            _logger.error("adaptive_purge_error",
                error=str(e),
                operation_count=self._operation_count,
            )

    async def _manage_command_specific_deque(
        self,
        command_name: str,
        guild_key: Union[int, str],
        now: float,
        cooldown_seconds: int,
    ) -> None:
        """Manage per-command deques for high-cooldown commands to optimize performance."""
        if command_name not in self.command_deques:
            self.command_deques[command_name] = deque(maxlen=1000)

        cmd_deque = self.command_deques[command_name]

        while cmd_deque and now - cmd_deque[0][0] > cooldown_seconds:
            cmd_deque.popleft()

        cmd_deque.append((now, str(guild_key)))

        if self._operation_count % (self._purge_threshold * 2) == 0:
            _logger.debug("deque_health_metrics",
                command_name=command_name,
                deque_size=len(cmd_deque),
                global_deque_size=len(self.guild_deque),
                total_command_deques=len(self.command_deques),
            )

    async def cleanup_old_entries(self, max_age_hours: int = 24):
        """
        Clean up old rate limit entries to prevent memory leaks.

        Args:
            max_age_hours: Maximum age in hours for entries to keep
        """
        async with self._lock:
            cleanup_start = time.monotonic()
            cutoff_time = time.monotonic() - (max_age_hours * 3600)

            total_user_removed = 0
            for command_name in list(self.user_limits.keys()):
                users_to_remove = [
                    user_id
                    for user_id, last_used in self.user_limits[command_name].items()
                    if last_used < cutoff_time
                ]
                for user_id in users_to_remove:
                    del self.user_limits[command_name][user_id]
                    total_user_removed += 1

                if not self.user_limits[command_name]:
                    del self.user_limits[command_name]

            total_guild_removed = 0
            for command_name in list(self.guild_limits.keys()):
                guilds_to_remove = [
                    guild_key
                    for guild_key, last_used in self.guild_limits[command_name].items()
                    if last_used < cutoff_time
                ]
                for guild_key in guilds_to_remove:
                    del self.guild_limits[command_name][guild_key]
                    total_guild_removed += 1

                if not self.guild_limits[command_name]:
                    del self.guild_limits[command_name]

            commands_to_remove = [
                command
                for command, last_used in self.global_limits.items()
                if last_used < cutoff_time
            ]
            for command in commands_to_remove:
                del self.global_limits[command]

            total_deque_cleaned = 0
            current_time = time.monotonic()
            for cmd_name, cmd_deque in list(self.command_deques.items()):
                initial_size = len(cmd_deque)
                max_age_seconds = max_age_hours * 3600
                while cmd_deque and current_time - cmd_deque[0][0] > max_age_seconds:
                    cmd_deque.popleft()
                    total_deque_cleaned += 1

                if not cmd_deque:
                    del self.command_deques[cmd_name]

            cleanup_duration = time.monotonic() - cleanup_start
            deque_size = len(self.guild_deque)

            _logger.info("cleanup_done",
                user_entries_removed=total_user_removed,
                guild_entries_removed=total_guild_removed,
                global_entries_removed=len(commands_to_remove),
                deque_entries_cleaned=total_deque_cleaned,
                global_deque_size=deque_size,
                command_deques_count=len(self.command_deques),
                cleanup_duration_ms=round(cleanup_duration * 1000, 2),
                max_age_hours=max_age_hours,
            )

rate_limiter = RateLimiter()

def rate_limit(
    cooldown_seconds: int = 60, scope: str = "user", error_message: str | None = None
):
    """
    Decorator to add rate limiting to Discord commands.

    Args:
        cooldown_seconds: Cooldown period in seconds
        scope: Rate limit scope ("user", "guild", or "global")
        error_message: Custom error message with {remaining_time} placeholder

    Returns:
        Decorated function with rate limiting applied
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            ctx = None
            for arg in args:
                if isinstance(arg, (discord.ApplicationContext, commands.Context)):
                    ctx = arg
                    break

            if not ctx:
                _logger.warning("no_context_found", function_name=func.__name__
                )
                return await func(*args, **kwargs)

            user_id = ctx.author.id if hasattr(ctx, "author") and ctx.author else None

            if hasattr(ctx, "guild") and ctx.guild:
                guild_key = ctx.guild.id
            else:
                guild_key = f"dm_user_{user_id}" if user_id else "dm_unknown"

            if (
                hasattr(ctx, "command")
                and ctx.command
                and hasattr(ctx.command, "qualified_name")
            ):
                command_name = ctx.command.qualified_name
            else:
                command_name = func.__name__

            is_limited, remaining_time = await rate_limiter.is_rate_limited(
                command_name, user_id, guild_key, cooldown_seconds, scope
            )

            if is_limited:
                _logger.warning("rate_limit_hit",
                    user_id=user_id or "unknown",
                    guild_key=guild_key,
                    command_name=command_name,
                    remaining_time=round(remaining_time, 1),
                    scope=scope,
                )

                if error_message:
                    message = error_message.format(
                        remaining_time=int(remaining_time) + 1
                    )
                else:
                    message = f"⏱️ This command is on cooldown. Please wait {int(remaining_time) + 1} more seconds."

                if hasattr(ctx, "respond"):
                    await ctx.respond(message, ephemeral=True)
                elif hasattr(ctx, "send"):
                    await ctx.send(message)

                return

            return await func(*args, **kwargs)

        return wrapper

    return decorator

def admin_rate_limit(cooldown_seconds: int = 300):
    """
    Specialized rate limiter for admin commands with longer cooldowns.

    Args:
        cooldown_seconds: Cooldown period in seconds (default: 5 minutes)

    Returns:
        Rate limit decorator configured for administrative commands
    """
    return rate_limit(
        cooldown_seconds=cooldown_seconds,
        scope="user",
        error_message="🛡️ Administrative command cooldown: Please wait {remaining_time} more seconds.",
    )

def guild_rate_limit(cooldown_seconds: int = 120):
    """
    Specialized rate limiter for guild-wide commands.

    Args:
        cooldown_seconds: Cooldown period in seconds (default: 2 minutes)

    Returns:
        Rate limit decorator configured for guild-scoped commands
    """
    return rate_limit(
        cooldown_seconds=cooldown_seconds,
        scope="guild",
        error_message="🏰 Guild command cooldown: Please wait {remaining_time} more seconds.",
    )

def global_rate_limit(cooldown_seconds: int = 60):
    """
    Specialized rate limiter for global commands affecting all guilds.

    Args:
        cooldown_seconds: Cooldown period in seconds (default: 1 minute)

    Returns:
        Rate limit decorator configured for globally-scoped commands
    """
    return rate_limit(
        cooldown_seconds=cooldown_seconds,
        scope="global",
        error_message="🌍 Global command cooldown: Please wait {remaining_time} more seconds.",
    )

async def start_cleanup_task(bot=None):
    """
    Start the background cleanup task for rate limiter maintenance.

    Args:
        bot: Discord bot instance (optional, for task tracking)
    """
    async def cleanup_loop():
        task_id = id(asyncio.current_task())
        _logger.info("task_started", task_id=task_id, task_type="cleanup"
        )

        try:
            while True:
                try:
                    await asyncio.sleep(3600)
                    await rate_limiter.cleanup_old_entries()
                except Exception as e:
                    _logger.error("cleanup_error", error=str(e), task_id=task_id
                    )
        except asyncio.CancelledError:
            _logger.info("task_cancelled", task_id=task_id, task_type="cleanup"
            )
            raise

    task = asyncio.create_task(cleanup_loop())
    task_id = id(task)

    if bot and hasattr(bot, "_background_tasks"):
        bot._background_tasks.append(task)
        _logger.info(
            "task_registered",
            task_id=task_id,
            background_tasks_count=len(bot._background_tasks),
        )

    _logger.info("cleanup_task_started", task_id=task_id)
