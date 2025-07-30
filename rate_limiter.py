"""
Rate Limiting System for Discord Bot Commands
Provides protection against spam and abuse of administrative commands.
"""

import time
import logging
import asyncio
from typing import Dict, Tuple, Callable, Any
from functools import wraps
from discord.ext import commands
import discord

class RateLimiter:
    """Thread-safe rate limiter with per-user and per-guild tracking."""
    
    def __init__(self):
        self.user_limits: Dict[str, Dict[int, float]] = {}  # command -> {user_id: last_used}
        self.guild_limits: Dict[str, Dict[int, float]] = {}  # command -> {guild_id: last_used}
        self.global_limits: Dict[str, float] = {}  # command -> last_used
        self._lock = asyncio.Lock()
    
    async def is_rate_limited(self, command_name: str, user_id: int = None, guild_id: int = None, 
                            cooldown_seconds: int = 60, scope: str = "user") -> Tuple[bool, float]:
        """Check if a command is rate limited.
        
        Args:
            command_name: Name of the command
            user_id: Discord user ID
            guild_id: Discord guild ID
            cooldown_seconds: Cooldown period in seconds
            scope: Rate limit scope ("user", "guild", or "global")
            
        Returns:
            Tuple[bool, float]: (is_limited, remaining_time)
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
        """Clean up old rate limit entries to prevent memory leaks."""
        async with self._lock:
            cutoff_time = time.time() - (max_age_hours * 3600)
            
            # Clean user limits
            for command_name in list(self.user_limits.keys()):
                users_to_remove = [
                    user_id for user_id, last_used in self.user_limits[command_name].items()
                    if last_used < cutoff_time
                ]
                for user_id in users_to_remove:
                    del self.user_limits[command_name][user_id]
                
                if not self.user_limits[command_name]:
                    del self.user_limits[command_name]
            
            # Clean guild limits
            for command_name in list(self.guild_limits.keys()):
                guilds_to_remove = [
                    guild_id for guild_id, last_used in self.guild_limits[command_name].items()
                    if last_used < cutoff_time
                ]
                for guild_id in guilds_to_remove:
                    del self.guild_limits[command_name][guild_id]
                
                if not self.guild_limits[command_name]:
                    del self.guild_limits[command_name]
            
            # Clean global limits
            commands_to_remove = [
                command for command, last_used in self.global_limits.items()
                if last_used < cutoff_time
            ]
            for command in commands_to_remove:
                del self.global_limits[command]
            
            logging.debug(f"[RateLimiter] Cleaned up old entries: {len(users_to_remove)} users, {len(guilds_to_remove)} guilds, {len(commands_to_remove)} global")

# Global rate limiter instance
rate_limiter = RateLimiter()

def rate_limit(cooldown_seconds: int = 60, scope: str = "user", error_message: str = None):
    """Decorator to add rate limiting to Discord commands.
    
    Args:
        cooldown_seconds: Cooldown period in seconds
        scope: Rate limit scope ("user", "guild", or "global")
        error_message: Custom error message (optional)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract context from arguments
            ctx = None
            for arg in args:
                if isinstance(arg, (discord.ApplicationContext, commands.Context)):
                    ctx = arg
                    break
            
            if not ctx:
                logging.error(f"[RateLimiter] Could not find context in {func.__name__}")
                return await func(*args, **kwargs)
            
            user_id = ctx.author.id if hasattr(ctx, 'author') and ctx.author else None
            guild_id = ctx.guild.id if hasattr(ctx, 'guild') and ctx.guild else None
            command_name = func.__name__
            
            # Check rate limit
            is_limited, remaining_time = await rate_limiter.is_rate_limited(
                command_name, user_id, guild_id, cooldown_seconds, scope
            )
            
            if is_limited:
                # Security: Log rate limit violations for monitoring
                logging.warning(f"[RateLimiter] Rate limit hit: user={user_id}, guild={guild_id}, command={command_name}, remaining={remaining_time:.1f}s")
                
                # Send rate limit message
                if error_message:
                    message = error_message.format(remaining_time=int(remaining_time) + 1)
                else:
                    message = f"⏱️ This command is on cooldown. Please wait {int(remaining_time) + 1} more seconds."
                
                if hasattr(ctx, 'respond'):
                    await ctx.respond(message, ephemeral=True)
                elif hasattr(ctx, 'send'):
                    await ctx.send(message)
                
                return
            
            # Execute the original function
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator

def admin_rate_limit(cooldown_seconds: int = 300):
    """Specialized rate limiter for admin commands with longer cooldowns."""
    return rate_limit(
        cooldown_seconds=cooldown_seconds,
        scope="user",
        error_message="🛡️ Administrative command cooldown: Please wait {remaining_time} more seconds."
    )

def guild_rate_limit(cooldown_seconds: int = 120):
    """Specialized rate limiter for guild-wide commands."""
    return rate_limit(
        cooldown_seconds=cooldown_seconds,
        scope="guild",
        error_message="🏰 Guild command cooldown: Please wait {remaining_time} more seconds."
    )

def global_rate_limit(cooldown_seconds: int = 60):
    """Specialized rate limiter for global commands affecting all guilds."""
    return rate_limit(
        cooldown_seconds=cooldown_seconds,
        scope="global",
        error_message="🌍 Global command cooldown: Please wait {remaining_time} more seconds."
    )

async def start_cleanup_task():
    """Start the cleanup task for rate limiter."""
    async def cleanup_loop():
        while True:
            try:
                await asyncio.sleep(3600)  # Clean up every hour
                await rate_limiter.cleanup_old_entries()
            except Exception as e:
                logging.error(f"[RateLimiter] Error in cleanup task: {e}")
    
    asyncio.create_task(cleanup_loop())
    logging.info("[RateLimiter] Rate limiter cleanup task started")