"""
Core Utilities Module - Enterprise-grade shared functionality for Discord bot.

Provides centralized access to core bot functionality including:
- Translation system with multi-language support
- Rate limiting and protection mechanisms
- Performance profiling and monitoring
- Reliability and resilience systems
- Utility functions for message handling
"""

from core.functions import (
    sanitize_kwargs,
    get_nested_value,
    get_user_message,
    get_effective_locale,
    get_guild_message,
)
from core.translation import translations, load_translations
from core.reliability import discord_resilient, setup_reliability_system
from core.rate_limiter import admin_rate_limit, start_cleanup_task
from core.performance_profiler import profile_performance, get_profiler

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
