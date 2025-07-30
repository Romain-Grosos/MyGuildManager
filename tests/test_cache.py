"""
Cache system tests - Validates global cache functionality and performance.
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch
from cache import GlobalCacheSystem, CacheEntry, get_global_cache

class TestCacheEntry:
    """Test CacheEntry class functionality."""
    
    def test_cache_entry_creation(self):
        """Test cache entry initialization."""
        entry = CacheEntry("test_value", 300, "test_category")
        
        assert entry.value == "test_value"
        assert entry.ttl == 300
        assert entry.category == "test_category"
        assert not entry.is_expired()
        assert len(entry.access_times) == 1
        assert not entry.is_hot
    
    def test_cache_entry_expiration(self):
        """Test cache entry TTL expiration."""
        entry = CacheEntry("test_value", 1, "test_category")
        assert not entry.is_expired()
        
        time.sleep(1.1)
        assert entry.is_expired()
    
    def test_cache_entry_hot_detection(self):
        """Test hot key detection mechanism."""
        entry = CacheEntry("test_value", 300, "test_category")
        
        for _ in range(15):
            entry.access()
        
        assert entry.is_hot

class TestGlobalCache:
    """Test GlobalCacheSystem functionality."""
    
    @pytest.fixture
    def cache(self):
        """Create GlobalCacheSystem instance for testing."""
        return GlobalCacheSystem()
    
    @pytest.mark.asyncio
    async def test_basic_set_get(self, cache):
        """Test basic cache set and get operations."""
        await cache.set("guild_data", "test_value", 123, "test_key")
        result = await cache.get("guild_data", 123, "test_key")
        
        assert result == "test_value"
    
    @pytest.mark.asyncio
    async def test_cache_miss(self, cache):
        """Test cache miss returns None."""
        result = await cache.get("guild_data", 999, "nonexistent_key")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_cache_with_ttl(self, cache):
        """Test cache TTL functionality."""
        await cache.set("guild_data", "ttl_value", 123, "ttl_key", ttl=1)
        
        result = await cache.get("guild_data", 123, "ttl_key")
        assert result == "ttl_value"
        
        await asyncio.sleep(1.1)
        result = await cache.get("guild_data", 123, "ttl_key")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_cache_delete(self, cache):
        """Test cache deletion."""
        await cache.set("guild_data", "delete_value", 123, "delete_key")
        
        result = await cache.get("guild_data", 123, "delete_key")
        assert result == "delete_value"
        
        await cache.delete("guild_data", 123, "delete_key")
        result = await cache.get("guild_data", 123, "delete_key")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_invalidate_category(self, cache):
        """Test category invalidation."""
        await cache.set("guild_data", "value1", 123, "key1")
        await cache.set("guild_data", "value2", 123, "key2")  
        await cache.set("user_data", "value3", 456, "key3")
        
        await cache.invalidate_category("guild_data")
        
        assert await cache.get("guild_data", 123, "key1") is None
        assert await cache.get("guild_data", 123, "key2") is None
        assert await cache.get("user_data", 456, "key3") == "value3"
    
    @pytest.mark.asyncio
    async def test_guild_data_operations(self, cache):
        """Test guild-specific cache operations."""
        guild_id = 123456789
        
        await cache.set_guild_data(guild_id, "guild_name", "Test Guild")
        await cache.set_guild_data(guild_id, "premium", 1)
        
        name = await cache.get_guild_data(guild_id, "guild_name")
        premium = await cache.get_guild_data(guild_id, "premium")
        
        assert name == "Test Guild"
        assert premium == 1
    
    @pytest.mark.asyncio
    async def test_bulk_guild_members_cache(self, cache):
        """Test bulk guild members caching."""
        guild_id = 123456789
        
        await cache.set_guild_members(guild_id, {"user1": {"class": "Tank"}, "user2": {"class": "Healer"}})
        result = await cache.get_guild_members(guild_id)
        
        assert result is not None
        assert len(result) == 2
    
    @pytest.mark.asyncio
    async def test_cache_metrics(self, cache):
        """Test cache metrics collection."""
        await cache.set("guild_data", "metrics_value", 123, "metrics_key")
        await cache.get("guild_data", 123, "metrics_key")
        await cache.get("guild_data", 123, "nonexistent_key")
        
        metrics = cache.get_metrics()
        
        assert "global" in metrics
        assert metrics["global"]["total_requests"] >= 2
        assert metrics["global"]["hits"] >= 1
        assert metrics["global"]["misses"] >= 1
        assert metrics["global"]["hit_rate"] >= 0
    
    @pytest.mark.asyncio
    async def test_cache_cleanup(self, cache):
        """Test automatic cache cleanup of expired entries."""
        await cache.set("guild_data", "cleanup_value", 123, "cleanup_key", ttl=1)
        
        assert await cache.get("guild_data", 123, "cleanup_key") == "cleanup_value"
        
        await asyncio.sleep(1.1)
        await cache.cleanup_expired()
        
        metrics = cache.get_metrics()
        assert metrics["global"]["total_entries"] == 0
    
    @pytest.mark.asyncio
    async def test_predictive_caching(self, cache):
        """Test predictive caching mechanism."""
        await cache.set("guild_data", "predict_value", 123, "predict_key")
        
        for _ in range(10):
            await cache.get("guild_data", 123, "predict_key")
        
        key = cache._generate_key("guild_data", 123, "predict_key")
        entry = cache._cache.get(key)
        
        assert entry is not None
        assert entry.is_hot
        assert entry.predicted_next_access is not None

if __name__ == "__main__":
    """Run cache tests directly."""
    pytest.main([__file__, "-v"])