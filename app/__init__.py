"""
MyGuildManager - Discord Bot Application Package

This package contains the core bot application for managing guilds in Throne and Liberty.
"""

__version__ = "1.0.0"
__author__ = "MyGuildManager Team"

# Export main components for easier imports
from .bot import bot_instance, setup_bot
from .cache import get_global_cache
from .cache_loader import get_cache_loader
from .db import run_db_query, run_db_transaction

__all__ = [
    "bot_instance",
    "setup_bot", 
    "get_global_cache",
    "get_cache_loader",
    "run_db_query",
    "run_db_transaction"
]