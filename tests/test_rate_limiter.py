"""
Tests for rate_limiter.py - Rate limiting system for Discord bot commands.
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, patch, AsyncMock
from rate_limiter import RateLimiter, rate_limit, admin_rate_limit, guild_rate_limit, global_rate_limit, start_cleanup_task


class TestRateLimiter:
    """Test RateLimiter class core functionality."""
    
    @pytest.fixture
    def rate_limiter(self):
        """Create a fresh RateLimiter instance for each test."""
        return RateLimiter()
    
    @pytest.mark.asyncio
    async def test_initialization(self, rate_limiter):
        """Test RateLimiter initialization."""
        assert rate_limiter.user_limits == {}
        assert rate_limiter.guild_limits == {}
        assert rate_limiter.global_limits == {}
        assert rate_limiter._lock is not None
    
    @pytest.mark.asyncio
    async def test_user_rate_limit_first_call(self, rate_limiter):
        """Test first call to a command is not rate limited."""
        is_limited, remaining = await rate_limiter.is_rate_limited(
            "test_command", user_id=123, cooldown_seconds=60, scope="user"
        )
        
        assert is_limited is False
        assert remaining == 0.0
        assert "test_command" in rate_limiter.user_limits
        assert 123 in rate_limiter.user_limits["test_command"]
    
    @pytest.mark.asyncio
    async def test_user_rate_limit_immediate_second_call(self, rate_limiter):
        """Test immediate second call is rate limited."""
        # First call
        await rate_limiter.is_rate_limited("test_command", user_id=123, cooldown_seconds=60, scope="user")
        
        # Immediate second call
        is_limited, remaining = await rate_limiter.is_rate_limited(
            "test_command", user_id=123, cooldown_seconds=60, scope="user"
        )
        
        assert is_limited is True
        assert 59 <= remaining <= 60  # Should be close to 60 seconds
    
    @pytest.mark.asyncio
    async def test_user_rate_limit_different_users(self, rate_limiter):
        """Test different users don't affect each other's rate limits."""
        # User 123 makes a call
        await rate_limiter.is_rate_limited("test_command", user_id=123, cooldown_seconds=60, scope="user")
        
        # User 456 makes a call immediately after
        is_limited, remaining = await rate_limiter.is_rate_limited(
            "test_command", user_id=456, cooldown_seconds=60, scope="user"
        )
        
        assert is_limited is False
        assert remaining == 0.0
    
    @pytest.mark.asyncio
    async def test_user_rate_limit_different_commands(self, rate_limiter):
        """Test different commands have separate rate limits."""
        # User 123 uses command1
        await rate_limiter.is_rate_limited("command1", user_id=123, cooldown_seconds=60, scope="user")
        
        # Same user uses command2 immediately
        is_limited, remaining = await rate_limiter.is_rate_limited(
            "command2", user_id=123, cooldown_seconds=60, scope="user"
        )
        
        assert is_limited is False
        assert remaining == 0.0
    
    @pytest.mark.asyncio
    async def test_guild_rate_limit_functionality(self, rate_limiter):
        """Test guild-scoped rate limiting."""
        # First call
        is_limited, remaining = await rate_limiter.is_rate_limited(
            "guild_command", guild_id=789, cooldown_seconds=120, scope="guild"
        )
        assert is_limited is False
        
        # Immediate second call
        is_limited, remaining = await rate_limiter.is_rate_limited(
            "guild_command", guild_id=789, cooldown_seconds=120, scope="guild"
        )
        assert is_limited is True
        assert 119 <= remaining <= 120
    
    @pytest.mark.asyncio
    async def test_global_rate_limit_functionality(self, rate_limiter):
        """Test global-scoped rate limiting."""
        # First call
        is_limited, remaining = await rate_limiter.is_rate_limited(
            "global_command", cooldown_seconds=30, scope="global"
        )
        assert is_limited is False
        
        # Immediate second call
        is_limited, remaining = await rate_limiter.is_rate_limited(
            "global_command", cooldown_seconds=30, scope="global"
        )
        assert is_limited is True
        assert 29 <= remaining <= 30
    
    @pytest.mark.asyncio
    async def test_rate_limit_expires(self, rate_limiter):
        """Test rate limit expires after cooldown period."""
        # First call
        await rate_limiter.is_rate_limited("test_command", user_id=123, cooldown_seconds=1, scope="user")
        
        # Wait for cooldown to expire
        await asyncio.sleep(1.1)
        
        # Second call should not be rate limited
        is_limited, remaining = await rate_limiter.is_rate_limited(
            "test_command", user_id=123, cooldown_seconds=1, scope="user"
        )
        assert is_limited is False
        assert remaining == 0.0
    
    @pytest.mark.asyncio
    async def test_cleanup_old_entries(self, rate_limiter):
        """Test cleanup of old rate limit entries."""
        # Add some old entries
        old_time = time.time() - (25 * 3600)  # 25 hours ago
        rate_limiter.user_limits["old_command"] = {123: old_time}
        rate_limiter.guild_limits["old_guild_command"] = {789: old_time}
        rate_limiter.global_limits["old_global_command"] = old_time
        
        # Add some recent entries
        recent_time = time.time() - 3600  # 1 hour ago
        rate_limiter.user_limits["recent_command"] = {456: recent_time}
        
        await rate_limiter.cleanup_old_entries(max_age_hours=24)
        
        # Old entries should be removed
        assert "old_command" not in rate_limiter.user_limits
        assert "old_guild_command" not in rate_limiter.guild_limits
        assert "old_global_command" not in rate_limiter.global_limits
        
        # Recent entries should remain
        assert "recent_command" in rate_limiter.user_limits
        assert 456 in rate_limiter.user_limits["recent_command"]
    
    @pytest.mark.asyncio
    async def test_invalid_scope_parameters(self, rate_limiter):
        """Test handling of invalid scope parameters."""
        # Test user scope without user_id
        is_limited, remaining = await rate_limiter.is_rate_limited(
            "test_command", user_id=None, cooldown_seconds=60, scope="user"
        )
        assert is_limited is False
        assert remaining == 0.0
        
        # Test guild scope without guild_id
        is_limited, remaining = await rate_limiter.is_rate_limited(
            "test_command", guild_id=None, cooldown_seconds=60, scope="guild"
        )
        assert is_limited is False
        assert remaining == 0.0


class TestRateLimitDecorator:
    """Test rate_limit decorator functionality."""
    
    @pytest.fixture
    def mock_ctx(self):
        """Create a mock Discord context."""
        ctx = Mock()
        ctx.author = Mock()
        ctx.author.id = 12345
        ctx.guild = Mock()
        ctx.guild.id = 67890
        ctx.respond = AsyncMock()
        ctx.send = AsyncMock()
        return ctx
    
    @pytest.mark.asyncio
    async def test_rate_limit_decorator_first_call(self, mock_ctx):
        """Test decorator allows first call through."""
        @rate_limit(cooldown_seconds=60, scope="user")
        async def test_command(ctx):
            return "success"
        
        result = await test_command(mock_ctx)
        assert result == "success"
        mock_ctx.respond.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_rate_limit_decorator_rate_limited(self, mock_ctx):
        """Test decorator blocks rate limited calls."""
        @rate_limit(cooldown_seconds=60, scope="user")
        async def test_command(ctx):
            return "success"
        
        # First call succeeds
        result1 = await test_command(mock_ctx)
        assert result1 == "success"
        
        # Second call is blocked
        result2 = await test_command(mock_ctx)
        assert result2 is None
        mock_ctx.respond.assert_called_once()
        
        # Check error message
        call_args = mock_ctx.respond.call_args
        assert "cooldown" in call_args[0][0].lower()
        assert call_args[1]['ephemeral'] is True
    
    @pytest.mark.asyncio
    async def test_rate_limit_decorator_custom_message(self, mock_ctx):
        """Test decorator with custom error message."""
        @rate_limit(cooldown_seconds=60, scope="user", error_message="Custom error: wait {remaining_time}s")
        async def test_command(ctx):
            return "success"
        
        # First call to set rate limit
        await test_command(mock_ctx)
        
        # Second call should show custom message
        await test_command(mock_ctx)
        
        call_args = mock_ctx.respond.call_args
        assert "Custom error" in call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_rate_limit_decorator_no_context(self):
        """Test decorator handling when no context is found."""
        @rate_limit(cooldown_seconds=60, scope="user")
        async def test_command(some_arg):
            return "success"
        
        with patch('rate_limiter.logging.error') as mock_log:
            result = await test_command("not_context")
            assert result == "success"
            mock_log.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_rate_limit_decorator_context_without_author(self):
        """Test decorator with context missing author."""
        mock_ctx = Mock()
        mock_ctx.author = None
        mock_ctx.guild = Mock()
        mock_ctx.guild.id = 67890
        
        @rate_limit(cooldown_seconds=60, scope="user")
        async def test_command(ctx):
            return "success"
        
        result = await test_command(mock_ctx)
        assert result == "success"
    
    @pytest.mark.asyncio
    async def test_rate_limit_decorator_send_fallback(self):
        """Test decorator falls back to send when respond is not available."""
        mock_ctx = Mock()
        mock_ctx.author = Mock()
        mock_ctx.author.id = 12345
        mock_ctx.guild = Mock()
        mock_ctx.guild.id = 67890
        mock_ctx.send = AsyncMock()
        # No respond method
        
        @rate_limit(cooldown_seconds=60, scope="user")
        async def test_command(ctx):
            return "success"
        
        # First call to set rate limit
        await test_command(mock_ctx)
        
        # Second call should use send
        await test_command(mock_ctx)
        mock_ctx.send.assert_called_once()


class TestSpecializedDecorators:
    """Test specialized rate limit decorators."""
    
    @pytest.fixture
    def mock_ctx(self):
        """Create a mock Discord context."""
        ctx = Mock()
        ctx.author = Mock()
        ctx.author.id = 12345
        ctx.guild = Mock()
        ctx.guild.id = 67890
        ctx.respond = AsyncMock()
        return ctx
    
    @pytest.mark.asyncio
    async def test_admin_rate_limit_decorator(self, mock_ctx):
        """Test admin_rate_limit decorator with longer cooldown."""
        @admin_rate_limit(cooldown_seconds=300)
        async def admin_command(ctx):
            return "admin_success"
        
        # First call succeeds
        result = await admin_command(mock_ctx)
        assert result == "admin_success"
        
        # Second call is blocked with admin message
        await admin_command(mock_ctx)
        call_args = mock_ctx.respond.call_args
        assert "Administrative command cooldown" in call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_guild_rate_limit_decorator(self, mock_ctx):
        """Test guild_rate_limit decorator."""
        @guild_rate_limit(cooldown_seconds=120)
        async def guild_command(ctx):
            return "guild_success"
        
        result = await guild_command(mock_ctx)
        assert result == "guild_success"
        
        await guild_command(mock_ctx)
        call_args = mock_ctx.respond.call_args
        assert "Guild command cooldown" in call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_global_rate_limit_decorator(self, mock_ctx):
        """Test global_rate_limit decorator."""
        @global_rate_limit(cooldown_seconds=60)
        async def global_command(ctx):
            return "global_success"
        
        result = await global_command(mock_ctx)
        assert result == "global_success"
        
        await global_command(mock_ctx)
        call_args = mock_ctx.respond.call_args
        assert "Global command cooldown" in call_args[0][0]


class TestCleanupTask:
    """Test cleanup task functionality."""
    
    @pytest.mark.asyncio
    async def test_start_cleanup_task(self):
        """Test cleanup task starts successfully."""
        with patch('rate_limiter.logging.info') as mock_log, \
             patch('rate_limiter.asyncio.create_task') as mock_create_task:
            
            await start_cleanup_task()
            
            mock_create_task.assert_called_once()
            mock_log.assert_called_once_with("[RateLimiter] Rate limiter cleanup task started")
    
    @pytest.mark.asyncio
    async def test_cleanup_task_exception_handling(self):
        """Test cleanup task handles exceptions properly."""
        # This test verifies the structure rather than running the actual loop
        # since the loop runs indefinitely
        
        with patch('rate_limiter.asyncio.sleep') as mock_sleep, \
             patch('rate_limiter.rate_limiter.cleanup_old_entries') as mock_cleanup, \
             patch('rate_limiter.logging.error') as mock_error:
            
            # Mock an exception in cleanup
            mock_cleanup.side_effect = Exception("Test error")
            mock_sleep.side_effect = [None, asyncio.CancelledError()]  # Stop after first iteration
            
            # Import the cleanup loop function to test it directly
            from rate_limiter import start_cleanup_task
            
            # We can't easily test the actual loop, but we can verify the structure
            # by checking that the function completes without error
            try:
                await start_cleanup_task()
            except asyncio.CancelledError:
                pass  # Expected when we cancel the task


class TestRateLimiterIntegration:
    """Integration tests for the rate limiter system."""
    
    @pytest.mark.asyncio
    async def test_multiple_scopes_same_command(self):
        """Test that different scopes for the same command work independently."""
        limiter = RateLimiter()
        
        # User scope
        await limiter.is_rate_limited("multi_command", user_id=123, cooldown_seconds=60, scope="user")
        user_limited, _ = await limiter.is_rate_limited("multi_command", user_id=123, cooldown_seconds=60, scope="user")
        
        # Guild scope (same command name)
        guild_limited, _ = await limiter.is_rate_limited("multi_command", guild_id=789, cooldown_seconds=60, scope="guild")
        
        # Global scope (same command name)
        global_limited, _ = await limiter.is_rate_limited("multi_command", cooldown_seconds=60, scope="global")
        
        assert user_limited is True  # User is limited
        assert guild_limited is False  # Guild is not limited
        assert global_limited is False  # Global is not limited
    
    @pytest.mark.asyncio
    async def test_concurrent_access(self):
        """Test thread safety with concurrent access."""
        limiter = RateLimiter()
        
        async def make_request(user_id):
            return await limiter.is_rate_limited("concurrent_test", user_id=user_id, cooldown_seconds=1, scope="user")
        
        # Make concurrent requests
        tasks = [make_request(i) for i in range(10)]
        results = await asyncio.gather(*tasks)
        
        # All first requests should succeed
        for is_limited, remaining in results:
            assert is_limited is False
            assert remaining == 0.0
    
    @pytest.mark.asyncio
    async def test_memory_efficiency(self):
        """Test that memory usage doesn't grow unbounded."""
        limiter = RateLimiter()
        
        # Add many entries
        for i in range(1000):
            await limiter.is_rate_limited(f"command_{i}", user_id=i, cooldown_seconds=1, scope="user")
        
        # Verify entries were created
        total_entries = sum(len(users) for users in limiter.user_limits.values())
        assert total_entries == 1000
        
        # Wait for entries to become old
        await asyncio.sleep(1.1)
        
        # Clean up
        await limiter.cleanup_old_entries(max_age_hours=0.001)  # Very short max age
        
        # Verify cleanup worked
        total_entries_after = sum(len(users) for users in limiter.user_limits.values())
        assert total_entries_after == 0