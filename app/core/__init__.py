"""
Core Utilities Module - Enterprise-grade shared functionality for Discord bot.

Provides centralized access to core bot functionality including:
- Translation system with multi-language support
- Rate limiting and protection mechanisms
- Performance profiling and monitoring
- Reliability and resilience systems
- Utility functions for message handling
"""

from .functions import (
    sanitize_kwargs,
    get_nested_value,
    get_user_message,
    get_effective_locale,
    get_guild_message,
)
from .translation import translations, load_translations
from .reliability import discord_resilient, setup_reliability_system
from .rate_limiter import admin_rate_limit, start_cleanup_task
from .performance_profiler import profile_performance, get_profiler

__all__ = [
    "sanitize_kwargs",
    "get_nested_value",
    "get_user_message",
    "get_effective_locale",
    "get_guild_message",
    "translations",
    "load_translations",
    "discord_resilient",
    "setup_reliability_system",
    "admin_rate_limit",
    "start_cleanup_task",
    "profile_performance",
    "get_profiler",
]
