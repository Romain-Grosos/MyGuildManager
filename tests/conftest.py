"""
Pytest configuration and fixtures for Discord Bot tests.
"""

import pytest
import asyncio
import sys
import os
from unittest.mock import Mock, AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def mock_bot():
    """Create mock Discord bot instance."""
    bot = Mock()
    bot.run_db_query = AsyncMock()
    bot.cache = Mock()
    bot.cache.get = AsyncMock()
    bot.cache.set = AsyncMock()
    bot.cache.delete = AsyncMock()
    bot.cache.invalidate_category = AsyncMock()
    return bot

@pytest.fixture
def mock_guild():
    """Create mock Discord guild."""
    guild = Mock()
    guild.id = 123456789
    guild.name = "Test Guild"
    return guild

@pytest.fixture
def mock_member():
    """Create mock Discord member."""
    member = Mock()
    member.id = 987654321
    member.name = "TestUser"
    member.guild = Mock()
    member.guild.id = 123456789
    return member

class AsyncContextManager:
    """Helper for mocking async context managers."""
    def __init__(self, return_value=None):
        self.return_value = return_value
    
    async def __aenter__(self):
        return self.return_value
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass