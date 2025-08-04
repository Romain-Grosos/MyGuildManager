#!/usr/bin/env python3
"""
MyGuildManager Discord Bot - Main Entry Point
"""

import sys
import os
import asyncio
import signal
import logging

# Add the current directory to Python path to allow imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import bot components
from app.bot import run_bot, bot_instance, _graceful_exit

if __name__ == "__main__":
    # Get or create event loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    # Setup signal handlers
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda: _graceful_exit(sig.name))
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            signal.signal(sig, lambda signum, frame: _graceful_exit(sig.name))
    
    # Run the bot
    try:
        loop.run_until_complete(run_bot())
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        logging.shutdown()
        loop.close()