#!/usr/bin/env python3
"""
Main entry point for the Discord bot when run as a module.
Usage: python -m app
"""

if __name__ == "__main__":
    from .bot import loop, run_bot
    
    try:
        loop.run_until_complete(run_bot())
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()