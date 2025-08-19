#!/usr/bin/env python3
"""
MyGuildManager Discord Bot - Main Entry Point
"""

import sys
import os
import asyncio
import signal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.bot import run_bot, _graceful_exit

if __name__ == "__main__":
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda: _graceful_exit(sig.name))
        except NotImplementedError:
            signal.signal(sig, lambda signum, frame: _graceful_exit(sig.name))

    try:
        loop.run_until_complete(run_bot())
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
