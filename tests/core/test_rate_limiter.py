"""
Tests for core.rate_limiter module - Rate limiting system for Discord bot commands.
"""

import asyncio
import pytest
import time
from unittest.mock import Mock, AsyncMock, patch
from pathlib import Path

# Import test utilities
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.mark.core
@pytest.mark.asyncio
class TestRateLimiter:
    """Test the RateLimiter class and its functionality."""

    @pytest.fixture
    def rate_limiter(self):
        """Create a fresh RateLimiter instance for each test."""
        from app.core.rate_limiter import RateLimiter
        return RateLimiter()

    async def test_rate_limiter_initialization(self, rate_limiter):
        """Test RateLimiter initialization."""
        assert rate_limiter.user_limits == {}
        assert rate_limiter.guild_limits == {}
        assert rate_limiter.global_limits == {}
        assert rate_limiter._lock is not None

    async def test_user_scope_not_rate_limited_first_use(self, rate_limiter):
        """Test first use of command is not rate limited."""
        is_limited, remaining_time = await rate_limiter.is_rate_limited(
            command_name="test_command",
            user_id=123456789,
            cooldown_seconds=60,
            scope="user"
        )
        
        assert not is_limited
        assert remaining_time == 0

    async def test_user_scope_rate_limited_second_use(self, rate_limiter):
        """Test second immediate use is rate limited."""
        user_id = 123456789
        command_name = "test_command"
        cooldown = 60
        
        # First use
        await rate_limiter.is_rate_limited(command_name, user_id=user_id, cooldown_seconds=cooldown, scope="user")
        
        # Immediate second use
        is_limited, remaining_time = await rate_limiter.is_rate_limited(
            command_name, user_id=user_id, cooldown_seconds=cooldown, scope="user"
        )
        
        assert is_limited
        assert remaining_time > 0
        assert remaining_time <= cooldown

    async def test_user_scope_different_users(self, rate_limiter):
        """Test different users are tracked separately."""
        command_name = "test_command"
        
        # User 1 uses command
        await rate_limiter.is_rate_limited(command_name, user_id=111, cooldown_seconds=60, scope="user")
        
        # User 2 should not be rate limited
        is_limited, remaining_time = await rate_limiter.is_rate_limited(
            command_name, user_id=222, cooldown_seconds=60, scope="user"
        )
        
        assert not is_limited
        assert remaining_time == 0

    async def test_user_scope_different_commands(self, rate_limiter):
        """Test different commands are tracked separately for same user."""
        user_id = 123456789
        
        # Use command1
        await rate_limiter.is_rate_limited("command1", user_id=user_id, cooldown_seconds=60, scope="user")
        
        # command2 should not be rate limited for same user
        is_limited, remaining_time = await rate_limiter.is_rate_limited(
            "command2", user_id=user_id, cooldown_seconds=60, scope="user"
        )
        
        assert not is_limited
        assert remaining_time == 0

    async def test_guild_scope_rate_limiting(self, rate_limiter):
        """Test guild scope rate limiting."""
        guild_id = 987654321
        command_name = "guild_command"
        
        # First use
        is_limited1, _ = await rate_limiter.is_rate_limited(
            command_name, guild_id=guild_id, cooldown_seconds=30, scope="guild"
        )
        
        # Second use
        is_limited2, remaining_time = await rate_limiter.is_rate_limited(
            command_name, guild_id=guild_id, cooldown_seconds=30, scope="guild"
        )
        
        assert not is_limited1
        assert is_limited2
        assert remaining_time > 0

    async def test_guild_scope_different_guilds(self, rate_limiter):
        """Test different guilds are tracked separately."""
        command_name = "guild_command"
        
        # Guild 1 uses command
        await rate_limiter.is_rate_limited(command_name, guild_id=111, cooldown_seconds=30, scope="guild")
        
        # Guild 2 should not be rate limited
        is_limited, remaining_time = await rate_limiter.is_rate_limited(
            command_name, guild_id=222, cooldown_seconds=30, scope="guild"
        )
        
        assert not is_limited
        assert remaining_time == 0

    async def test_global_scope_rate_limiting(self, rate_limiter):
        """Test global scope rate limiting."""
        command_name = "global_command"
        
        # First use
        is_limited1, _ = await rate_limiter.is_rate_limited(
            command_name, cooldown_seconds=120, scope="global"
        )
        
        # Second use
        is_limited2, remaining_time = await rate_limiter.is_rate_limited(
            command_name, cooldown_seconds=120, scope="global"
        )
        
        assert not is_limited1
        assert is_limited2
        assert remaining_time > 0

    async def test_cooldown_expiry(self, rate_limiter):
        """Test that rate limits expire after cooldown period."""
        user_id = 123456789
        command_name = "test_command"
        cooldown = 1  # 1 second for quick testing
        
        # First use
        await rate_limiter.is_rate_limited(command_name, user_id=user_id, cooldown_seconds=cooldown, scope="user")
        
        # Wait for cooldown to expire
        await asyncio.sleep(1.1)
        
        # Should not be rate limited anymore
        is_limited, remaining_time = await rate_limiter.is_rate_limited(
            command_name, user_id=user_id, cooldown_seconds=cooldown, scope="user"
        )
        
        assert not is_limited
        assert remaining_time == 0

    async def test_concurrent_access(self, rate_limiter):
        """Test thread safety with concurrent access."""
        user_id = 123456789
        command_name = "concurrent_command"
        
        async def check_rate_limit():
            return await rate_limiter.is_rate_limited(
                command_name, user_id=user_id, cooldown_seconds=60, scope="user"
            )
        
        # Run multiple concurrent checks
        results = await asyncio.gather(*[check_rate_limit() for _ in range(10)])
        
        # Only one should be allowed (first one), rest should be rate limited
        allowed_count = sum(1 for is_limited, _ in results if not is_limited)
        assert allowed_count == 1

    async def test_user_scope_without_user_id(self, rate_limiter):
        """Test user scope without providing user_id."""
        is_limited, remaining_time = await rate_limiter.is_rate_limited(
            "test_command", cooldown_seconds=60, scope="user"
        )
        
        # Should not be rate limited if no user_id provided
        assert not is_limited
        assert remaining_time == 0

    async def test_guild_scope_without_guild_id(self, rate_limiter):
        """Test guild scope without providing guild_id."""
        is_limited, remaining_time = await rate_limiter.is_rate_limited(
            "test_command", cooldown_seconds=60, scope="guild"
        )
        
        # Should not be rate limited if no guild_id provided
        assert not is_limited
        assert remaining_time == 0

    async def test_cleanup_expired_entries(self, rate_limiter):
        """Test cleanup of expired entries."""
        user_id = 123456789
        command_name = "test_command"
        
        # Use command
        await rate_limiter.is_rate_limited(command_name, user_id=user_id, cooldown_seconds=1, scope="user")
        
        # Verify entry exists
        assert command_name in rate_limiter.user_limits
        assert user_id in rate_limiter.user_limits[command_name]
        
        # Run cleanup
        await rate_limiter.cleanup_expired_entries()
        
        # Entry should still exist (not expired yet)
        assert command_name in rate_limiter.user_limits
        assert user_id in rate_limiter.user_limits[command_name]
        
        # Wait for expiry and cleanup again
        await asyncio.sleep(1.1)
        await rate_limiter.cleanup_expired_entries()
        
        # Entry should be cleaned up (but command_name dict might still exist)
        if command_name in rate_limiter.user_limits:
            assert user_id not in rate_limiter.user_limits[command_name]

    async def test_get_remaining_time(self, rate_limiter):
        """Test accurate remaining time calculation."""
        user_id = 123456789
        command_name = "test_command"
        cooldown = 60
        
        # Use command
        start_time = time.time()
        await rate_limiter.is_rate_limited(command_name, user_id=user_id, cooldown_seconds=cooldown, scope="user")
        
        # Small delay
        await asyncio.sleep(0.1)
        
        # Check remaining time
        is_limited, remaining_time = await rate_limiter.is_rate_limited(
            command_name, user_id=user_id, cooldown_seconds=cooldown, scope="user"
        )
        
        assert is_limited
        assert remaining_time > 0
        assert remaining_time < cooldown  # Should be less than full cooldown
        assert remaining_time <= cooldown - 0.1  # Accounting for the sleep

    async def test_reset_user_limits(self, rate_limiter):
        """Test resetting user limits."""
        user_id = 123456789
        command_name = "test_command"
        
        # Use command to set limit
        await rate_limiter.is_rate_limited(command_name, user_id=user_id, cooldown_seconds=60, scope="user")
        
        # Reset limits
        await rate_limiter.reset_user_limits(user_id)
        
        # Should not be rate limited anymore
        is_limited, remaining_time = await rate_limiter.is_rate_limited(
            command_name, user_id=user_id, cooldown_seconds=60, scope="user"
        )
        
        assert not is_limited
        assert remaining_time == 0

    async def test_reset_guild_limits(self, rate_limiter):
        """Test resetting guild limits."""
        guild_id = 987654321
        command_name = "guild_command"
        
        # Use command to set limit
        await rate_limiter.is_rate_limited(command_name, guild_id=guild_id, cooldown_seconds=60, scope="guild")
        
        # Reset limits
        await rate_limiter.reset_guild_limits(guild_id)
        
        # Should not be rate limited anymore
        is_limited, remaining_time = await rate_limiter.is_rate_limited(
            command_name, guild_id=guild_id, cooldown_seconds=60, scope="guild"
        )
        
        assert not is_limited
        assert remaining_time == 0

    async def test_reset_all_limits(self, rate_limiter):
        """Test resetting all limits."""
        # Set various limits
        await rate_limiter.is_rate_limited("cmd1", user_id=111, cooldown_seconds=60, scope="user")
        await rate_limiter.is_rate_limited("cmd2", guild_id=222, cooldown_seconds=60, scope="guild")
        await rate_limiter.is_rate_limited("cmd3", cooldown_seconds=60, scope="global")
        
        # Reset all
        await rate_limiter.reset_all_limits()
        
        # All should be empty
        assert rate_limiter.user_limits == {}
        assert rate_limiter.guild_limits == {}
        assert rate_limiter.global_limits == {}

    async def test_get_stats(self, rate_limiter):
        """Test getting rate limiter statistics."""
        # Set some limits
        await rate_limiter.is_rate_limited("cmd1", user_id=111, cooldown_seconds=60, scope="user")
        await rate_limiter.is_rate_limited("cmd2", user_id=222, cooldown_seconds=60, scope="user")
        await rate_limiter.is_rate_limited("cmd3", guild_id=333, cooldown_seconds=60, scope="guild")
        await rate_limiter.is_rate_limited("cmd4", cooldown_seconds=60, scope="global")
        
        stats = await rate_limiter.get_stats()
        
        assert "active_user_limits" in stats
        assert "active_guild_limits" in stats
        assert "active_global_limits" in stats
        assert stats["active_user_limits"] >= 2
        assert stats["active_guild_limits"] >= 1
        assert stats["active_global_limits"] >= 1


@pytest.mark.core
@pytest.mark.asyncio 
class TestRateLimitDecorator:
    """Test the rate limit decorator functionality."""

    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot with rate limiter."""
        from app.core.rate_limiter import RateLimiter
        bot = Mock()
        bot.rate_limiter = RateLimiter()
        return bot

    @pytest.fixture
    def mock_ctx(self, mock_bot):
        """Create a mock Discord context."""
        ctx = Mock()
        ctx.bot = mock_bot
        ctx.author = Mock()
        ctx.author.id = 123456789
        ctx.guild = Mock()
        ctx.guild.id = 987654321
        ctx.send = AsyncMock()
        return ctx

    async def test_rate_limit_decorator_success(self, mock_ctx):
        """Test rate limit decorator allows first use."""
        from app.core.rate_limiter import rate_limit
        
        @rate_limit(cooldown=60, scope="user")
        async def test_command(ctx):
            return "success"
        
        result = await test_command(mock_ctx)
        assert result == "success"

    async def test_rate_limit_decorator_blocks_second_use(self, mock_ctx):
        """Test rate limit decorator blocks second immediate use."""
        from app.core.rate_limiter import rate_limit
        
        @rate_limit(cooldown=60, scope="user")
        async def test_command(ctx):
            return "success"
        
        # First use
        await test_command(mock_ctx)
        
        # Second use should be blocked
        result = await test_command(mock_ctx)
        assert result is None  # Should be blocked and return None
        
        # Check that rate limit message was sent
        mock_ctx.send.assert_called_once()

    async def test_rate_limit_decorator_custom_message(self, mock_ctx):
        """Test rate limit decorator with custom message."""
        from app.core.rate_limiter import rate_limit
        
        custom_message = "Please wait before using this command again!"
        
        @rate_limit(cooldown=60, scope="user", message=custom_message)
        async def test_command(ctx):
            return "success"
        
        # First use
        await test_command(mock_ctx)
        
        # Second use should send custom message
        await test_command(mock_ctx)
        mock_ctx.send.assert_called_with(custom_message)

    async def test_rate_limit_decorator_different_scopes(self, mock_ctx):
        """Test rate limit decorator with different scopes."""
        from app.core.rate_limiter import rate_limit
        
        @rate_limit(cooldown=60, scope="guild")
        async def guild_command(ctx):
            return "guild_success"
        
        @rate_limit(cooldown=60, scope="global") 
        async def global_command(ctx):
            return "global_success"
        
        # Both should work initially
        result1 = await guild_command(mock_ctx)
        result2 = await global_command(mock_ctx)
        
        assert result1 == "guild_success"
        assert result2 == "global_success"

    async def test_rate_limit_decorator_preserves_function_metadata(self):
        """Test that decorator preserves original function metadata."""
        from app.core.rate_limiter import rate_limit
        
        @rate_limit(cooldown=60, scope="user")
        async def documented_command(ctx):
            """This is a test command with documentation."""
            return "success"
        
        assert documented_command.__name__ == "documented_command"
        assert "test command with documentation" in documented_command.__doc__

    async def test_rate_limit_decorator_error_handling(self, mock_ctx):
        """Test rate limit decorator error handling."""
        from app.core.rate_limiter import rate_limit
        
        # Remove rate_limiter from bot to simulate error
        mock_ctx.bot.rate_limiter = None
        
        @rate_limit(cooldown=60, scope="user")
        async def test_command(ctx):
            return "success"
        
        with patch('logging.error') as mock_error:
            result = await test_command(mock_ctx)
        
        # Should still execute function despite rate limiter error
        assert result == "success"
        mock_error.assert_called_once()


@pytest.mark.core
@pytest.mark.slow
@pytest.mark.asyncio
class TestRateLimiterPerformance:
    """Test rate limiter performance under load."""

    @pytest.fixture
    def rate_limiter(self):
        """Create a RateLimiter for performance testing."""
        from app.core.rate_limiter import RateLimiter
        return RateLimiter()

    async def test_high_concurrency_performance(self, rate_limiter):
        """Test performance under high concurrency."""
        async def rapid_fire_test(user_id):
            tasks = []
            for i in range(100):
                task = rate_limiter.is_rate_limited(
                    f"cmd_{i}", user_id=user_id, cooldown_seconds=1, scope="user"
                )
                tasks.append(task)
            return await asyncio.gather(*tasks)
        
        start_time = time.time()
        
        # Run concurrent tests with different users
        results = await asyncio.gather(*[
            rapid_fire_test(user_id) for user_id in range(10)
        ])
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        # Should complete within reasonable time (adjust based on system)
        assert execution_time < 5.0  # 5 seconds max for 1000 operations
        assert len(results) == 10  # All users completed

    async def test_memory_usage_with_many_users(self, rate_limiter):
        """Test memory usage with many users and commands.""" 
        # Simulate many users using many commands
        users = range(1000)
        commands = [f"cmd_{i}" for i in range(50)]
        
        tasks = []
        for user_id in users:
            for command in commands[:5]:  # Each user uses 5 commands
                task = rate_limiter.is_rate_limited(
                    command, user_id=user_id, cooldown_seconds=60, scope="user"
                )
                tasks.append(task)
        
        await asyncio.gather(*tasks)
        
        # Verify data structures are populated but not excessively large
        assert len(rate_limiter.user_limits) <= 5  # Max 5 different commands
        
        total_user_entries = sum(
            len(users_dict) for users_dict in rate_limiter.user_limits.values()
        )
        assert total_user_entries == 5000  # 1000 users * 5 commands each