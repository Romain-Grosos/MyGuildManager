"""
Rate Limiting System for Discord Bot Commands
Provides protection against spam and abuse of administrative commands.
"""

import asyncio
import logging
import time
from functools import wraps
from typing import Dict, Tuple, Callable, Any

import discord
from discord.ext import commands

class RateLimiter:
    """Thread-safe rate limiter with per-user and per-guild tracking."""
    
    def __init__(self):
        """
        Initialize rate limiter with tracking dictionaries for different scopes.
        """
        self.user_limits: Dict[str, Dict[int, float]] = {}
        self.guild_limits: Dict[str, Dict[int, float]] = {}
        self.global_limits: Dict[str, float] = {}
        self._lock = asyncio.Lock()
    
    async def is_rate_limited(self, command_name: str, user_id: int | None = None, guild_id: int | None = None, 
                            cooldown_seconds: int = 60, scope: str = "user") -> Tuple[bool, float]:
        """
        Check if a command is rate limited and update tracking.
        
        Args:
            command_name: Name of the command to check
            user_id: Discord user ID (required for user scope)
            guild_id: Discord guild ID (required for guild scope)
            cooldown_seconds: Cooldown period in seconds
            scope: Rate limit scope ("user", "guild", or "global")
            
        Returns:
            Tuple containing (is_limited: bool, remaining_time: float)
        """
        async with self._lock:
            now = time.time()
            
            if scope == "user" and user_id:
                if command_name not in self.user_limits:
                    self.user_limits[command_name] = {}
                
                last_used = self.user_limits[command_name].get(user_id, 0)
                remaining = cooldown_seconds - (now - last_used)
                
                if remaining > 0:
                    return True, remaining
                
                self.user_limits[command_name][user_id] = now
                
            elif scope == "guild" and guild_id:
                if command_name not in self.guild_limits:
                    self.guild_limits[command_name] = {}
                
                last_used = self.guild_limits[command_name].get(guild_id, 0)
                remaining = cooldown_seconds - (now - last_used)
                
                if remaining > 0:
                    return True, remaining
                
                self.guild_limits[command_name][guild_id] = now
                
            elif scope == "global":
                last_used = self.global_limits.get(command_name, 0)
                remaining = cooldown_seconds - (now - last_used)
                
                if remaining > 0:
                    return True, remaining
                
                self.global_limits[command_name] = now
            
            return False, 0.0
    
    async def cleanup_old_entries(self, max_age_hours: int = 24):
        """
        Clean up old rate limit entries to prevent memory leaks.
        
        Args:
            max_age_hours: Maximum age in hours for entries to keep
        """
        async with self._lock:
            cutoff_time = time.time() - (max_age_hours * 3600)

            for command_name in list(self.user_limits.keys()):
                users_to_remove = [
                    user_id for user_id, last_used in self.user_limits[command_name].items()
                    if last_used < cutoff_time
                ]
                for user_id in users_to_remove:
                    del self.user_limits[command_name][user_id]
                
                if not self.user_limits[command_name]:
                    del self.user_limits[command_name]

            for command_name in list(self.guild_limits.keys()):
                guilds_to_remove = [
                    guild_id for guild_id, last_used in self.guild_limits[command_name].items()
                    if last_used < cutoff_time
                ]
                for guild_id in guilds_to_remove:
                    del self.guild_limits[command_name][guild_id]
                
                if not self.guild_limits[command_name]:
                    del self.guild_limits[command_name]

            commands_to_remove = [
                command for command, last_used in self.global_limits.items()
                if last_used < cutoff_time
            ]
            for command in commands_to_remove:
                del self.global_limits[command]
            
            logging.debug(f"[RateLimiter] Cleaned up old entries - global commands: {len(commands_to_remove)}")

rate_limiter = RateLimiter()

def rate_limit(cooldown_seconds: int = 60, scope: str = "user", error_message: str | None = None):
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
                logging.error(f"[RateLimiter] Could not find context in {func.__name__}")
                return await func(*args, **kwargs)
            
            user_id = ctx.author.id if hasattr(ctx, 'author') and ctx.author else 0
            guild_id = ctx.guild.id if hasattr(ctx, 'guild') and ctx.guild else 0
            command_name = func.__name__

            is_limited, remaining_time = await rate_limiter.is_rate_limited(
                command_name, user_id if user_id != 0 else None, guild_id if guild_id != 0 else None, cooldown_seconds, scope
            )
            
            if is_limited:
                logging.warning(f"[RateLimiter] Rate limit hit: user={user_id}, guild={guild_id}, command={command_name}, remaining={remaining_time:.1f}s")

                if error_message:
                    message = error_message.format(remaining_time=int(remaining_time) + 1)
                else:
                    message = f"⏱️ This command is on cooldown. Please wait {int(remaining_time) + 1} more seconds."
                
                if hasattr(ctx, 'respond'):
                    await ctx.respond(message, ephemeral=True)
                elif hasattr(ctx, 'send'):
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
        error_message="🛡️ Administrative command cooldown: Please wait {remaining_time} more seconds."
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
        error_message="🏰 Guild command cooldown: Please wait {remaining_time} more seconds."
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
        error_message="🌍 Global command cooldown: Please wait {remaining_time} more seconds."
    )

async def start_cleanup_task(bot=None):
    """
    Start the background cleanup task for rate limiter maintenance.
    
    Args:
        bot: Discord bot instance (optional, for task tracking)
    """
    async def cleanup_loop():
        try:
            while True:
                try:
                    await asyncio.sleep(3600)
                    await rate_limiter.cleanup_old_entries()
                except Exception as e:
                    logging.error(f"[RateLimiter] Error in cleanup task: {e}")
        except asyncio.CancelledError:
            logging.debug("[RateLimiter] Cleanup task cancelled")
            raise
    
    task = asyncio.create_task(cleanup_loop())

    if bot and hasattr(bot, '_background_tasks'):
        bot._background_tasks.append(task)
    
    logging.info("[RateLimiter] Rate limiter cleanup task started")
