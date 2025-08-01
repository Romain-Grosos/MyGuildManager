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
    
    @pytest.mark.asyncio
    async def test_invalidation_rules(self, cache):
        """Test cache invalidation rules system."""
        # Set up invalidation rule
        cache.add_invalidation_rule("roster_data", ["user_data", "guild_data"])
        
        # Add data to categories
        await cache.set("roster_data", "roster_value", 123, "roster_key")
        await cache.set("user_data", "user_value", 123, 456, "user_key")
        await cache.set("guild_data", "guild_value", 123, "guild_key")
        
        # Trigger invalidation
        invalidated = await cache.invalidate_related("roster_data")
        
        # Check that related data was invalidated
        assert invalidated > 0
        assert await cache.get("user_data", 123, 456, "user_key") is None
        assert await cache.get("guild_data", 123, "guild_key") is None
        assert await cache.get("roster_data", 123, "roster_key") == "roster_value"  # Original not affected
    
    @pytest.mark.asyncio
    async def test_cache_key_generation(self, cache):
        """Test cache key generation with various arguments."""
        key1 = cache._generate_key("guild_data", 123, "test")
        key2 = cache._generate_key("guild_data", 123, "test", None)
        key3 = cache._generate_key("guild_data", 123)
        
        assert key1 == "guild_data:123:test"
        assert key2 == "guild_data:123:test"
        assert key3 == "guild_data:123"
    
    @pytest.mark.asyncio
    async def test_ttl_for_category(self, cache):
        """Test TTL assignment for different categories."""
        # Test default TTL
        ttl_unknown = cache._get_ttl_for_category("unknown_category")
        assert ttl_unknown == 3600  # DEFAULT_TTL
        
        # Test specific category TTL
        ttl_guild = cache._get_ttl_for_category("guild_data")
        assert ttl_guild == 86400  # 24 hours
        
        ttl_temp = cache._get_ttl_for_category("temporary")
        assert ttl_temp == 300  # 5 minutes
    
    @pytest.mark.asyncio
    async def test_cache_get_info(self, cache):
        """Test detailed cache information retrieval."""
        # Add various entries
        await cache.set("guild_data", "value1", 123, "key1")
        await cache.set("user_data", "value2", 456, "key2")
        await cache.set("guild_data", "value3", 789, "key3")
        
        info = cache.get_cache_info()
        
        assert info['total_entries'] == 3
        assert 'guild_data' in info['categories']
        assert 'user_data' in info['categories']
        assert info['categories']['guild_data']['count'] == 2
        assert info['categories']['user_data']['count'] == 1
        assert info['oldest_entry'] is not None
        assert info['newest_entry'] is not None
    
    @pytest.mark.asyncio
    async def test_specialized_guild_methods(self, cache):
        """Test specialized guild data methods."""
        guild_id = 123456
        
        # Test guild data operations
        await cache.set_guild_data(guild_id, "name", "Test Guild")
        await cache.set_guild_data(guild_id, "premium", True)
        
        name = await cache.get_guild_data(guild_id, "name")
        premium = await cache.get_guild_data(guild_id, "premium")
        
        assert name == "Test Guild"
        assert premium is True
    
    @pytest.mark.asyncio
    async def test_specialized_user_methods(self, cache):
        """Test specialized user data methods."""
        guild_id = 123456
        user_id = 789012
        
        # Test user data operations
        await cache.set_user_data(guild_id, user_id, "class", "Warrior")
        await cache.set_user_data(guild_id, user_id, "level", 60)
        
        user_class = await cache.get_user_data(guild_id, user_id, "class")
        user_level = await cache.get_user_data(guild_id, user_id, "level")
        
        assert user_class == "Warrior"
        assert user_level == 60
    
    @pytest.mark.asyncio
    async def test_specialized_event_methods(self, cache):
        """Test specialized event data methods."""
        guild_id = 123456
        event_data = {"name": "Raid Night", "participants": 20}
        
        await cache.set_event_data(guild_id, "raid", event_data)
        result = await cache.get_event_data(guild_id, "raid")
        
        assert result == event_data
        assert result["name"] == "Raid Night"
    
    @pytest.mark.asyncio
    async def test_specialized_static_methods(self, cache):
        """Test specialized static data methods."""
        weapon_data = {"name": "Sword", "damage": 100}
        
        await cache.set_static_data("weapons", weapon_data, 1)
        result = await cache.get_static_data("weapons", 1)
        
        assert result == weapon_data
        assert result["name"] == "Sword"
    
    @pytest.mark.asyncio
    async def test_cache_entry_prediction_logic(self, cache):
        """Test cache entry prediction update logic."""
        await cache.set("guild_data", "test_prediction", 123, "predict_key")
        
        # Access multiple times to build prediction data
        for i in range(5):
            await cache.get("guild_data", 123, "predict_key")
            await asyncio.sleep(0.1)  # Small delay between accesses
        
        key = cache._generate_key("guild_data", 123, "predict_key")
        entry = cache._cache.get(key)
        
        assert entry is not None
        assert len(entry.access_times) >= 3
        assert entry.predicted_next_access is not None
    
    @pytest.mark.asyncio
    async def test_cache_entry_preload_detection(self, cache):
        """Test cache entry preload detection logic."""
        # Create entry with short TTL for testing
        await cache.set("temporary", "preload_test", 123, "preload_key", ttl=10)
        
        key = cache._generate_key("temporary", 123, "preload_key")
        entry = cache._cache.get(key)
        
        # Make it hot and set prediction
        for _ in range(10):
            entry.access()
        
        # Set prediction within preload window
        entry.predicted_next_access = time.time() + 1  # Within 20% of TTL (2 seconds)
        
        assert entry.should_preload()
    
    @pytest.mark.asyncio
    async def test_cache_metrics_accuracy(self, cache):
        """Test cache metrics collection accuracy."""
        # Perform various operations
        await cache.set("guild_data", "metrics_test1", 123, "key1")
        await cache.set("user_data", "metrics_test2", 456, "key2")
        
        # Generate hits
        await cache.get("guild_data", 123, "key1")
        await cache.get("guild_data", 123, "key1")
        
        # Generate misses
        await cache.get("guild_data", 999, "nonexistent")
        await cache.get("user_data", 999, "nonexistent2")
        
        metrics = cache.get_metrics()
        
        assert metrics['global']['sets'] == 2
        assert metrics['global']['hits'] == 2
        assert metrics['global']['misses'] == 2
        assert metrics['global']['hit_rate'] == 50.0
        assert metrics['by_category']['guild_data']['hits'] == 2
        assert metrics['by_category']['user_data']['misses'] == 1
    
    @pytest.mark.asyncio
    async def test_concurrent_cache_operations(self, cache):
        """Test thread safety with concurrent operations."""
        async def set_get_operation(key_suffix):
            await cache.set("guild_data", f"value_{key_suffix}", 123, f"key_{key_suffix}")
            result = await cache.get("guild_data", 123, f"key_{key_suffix}")
            return result
        
        # Run multiple concurrent operations
        tasks = [set_get_operation(i) for i in range(10)]
        results = await asyncio.gather(*tasks)
        
        # Verify all operations completed successfully
        for i, result in enumerate(results):
            assert result == f"value_{i}"
        
        # Verify all entries are in cache
        assert len(cache._cache) == 10


class TestCacheEntryAdvanced:
    """Advanced tests for CacheEntry functionality."""
    
    def test_cache_entry_age_calculation(self):
        """Test cache entry age calculation."""
        entry = CacheEntry("test_value", 300, "test_category")
        initial_age = entry.get_age()
        
        time.sleep(0.1)
        later_age = entry.get_age()
        
        assert later_age > initial_age
        assert later_age >= 0.1
    
    def test_cache_entry_prediction_insufficient_data(self):
        """Test prediction with insufficient access data."""
        entry = CacheEntry("test_value", 300, "test_category")
        
        # Access once (insufficient for prediction)
        entry.access()
        
        assert entry.predicted_next_access is None
        assert not entry.should_preload()
    
    def test_cache_entry_prediction_calculation(self):
        """Test prediction calculation with sufficient data."""
        entry = CacheEntry("test_value", 300, "test_category")
        
        # Access multiple times with intervals
        base_time = time.time()
        entry.access_times.clear()
        entry.access_times.extend([base_time, base_time + 1, base_time + 2, base_time + 3])
        
        entry._update_prediction(base_time + 3)
        
        # Should predict next access at base_time + 4 (interval of 1 second)
        expected_next = base_time + 4
        assert abs(entry.predicted_next_access - expected_next) < 0.1
    
    def test_cache_entry_hot_key_detection(self):
        """Test hot key detection thresholds."""
        entry = CacheEntry("test_value", 300, "test_category")
        
        # Initial access count is 1
        assert entry.access_count == 1
        assert not entry.is_hot
        
        # Access 4 times (total 5, should not be hot yet)
        for _ in range(4):
            entry.access()
        assert entry.access_count == 5
        assert not entry.is_hot
        
        # Access one more time (total 6, should become hot)
        entry.access()
        assert entry.access_count == 6
        assert entry.is_hot
    
    def test_cache_entry_preload_conditions(self):
        """Test various preload conditions."""
        entry = CacheEntry("test_value", 100, "test_category")  # 100s TTL
        
        # Not hot, should not preload
        entry.predicted_next_access = time.time() + 10
        assert not entry.should_preload()
        
        # Make it hot
        entry.is_hot = True
        
        # Prediction too far in future
        entry.predicted_next_access = time.time() + 50
        assert not entry.should_preload()
        
        # Prediction in past
        entry.predicted_next_access = time.time() - 10
        assert not entry.should_preload()
        
        # Prediction in preload window (within 20% of TTL = 20s)
        entry.predicted_next_access = time.time() + 15
        assert entry.should_preload()


class TestGlobalCacheSystemAdvanced:
    """Advanced tests for GlobalCacheSystem functionality."""
    
    @pytest.fixture
    def cache(self):
        """Create GlobalCacheSystem instance for testing."""
        return GlobalCacheSystem()
    
    @pytest.mark.asyncio
    async def test_cache_bulk_operations_without_bot(self, cache):
        """Test bulk operations when bot is not available."""
        result = await cache.get_bulk_guild_members(123456)
        assert result == {}
    
    @pytest.mark.asyncio
    async def test_cache_category_size_tracking(self, cache):
        """Test category size tracking accuracy."""
        # Add entries to different categories
        await cache.set("guild_data", "value1", 123, "key1")
        await cache.set("guild_data", "value2", 123, "key2")
        await cache.set("user_data", "value3", 456, "key3")
        
        metrics = cache.get_metrics()
        assert metrics['by_category']['guild_data']['size'] == 2
        assert metrics['by_category']['user_data']['size'] == 1
        
        # Delete one entry
        await cache.delete("guild_data", 123, "key1")
        
        updated_metrics = cache.get_metrics()
        assert updated_metrics['by_category']['guild_data']['size'] == 1
    
    @pytest.mark.asyncio
    async def test_cache_cleanup_with_locks(self, cache):
        """Test cleanup respects async locks."""
        # Add entries that will expire
        await cache.set("temporary", "expire1", 123, "key1", ttl=1)
        await cache.set("temporary", "expire2", 123, "key2", ttl=1)
        
        # Wait for expiration
        await asyncio.sleep(1.1)
        
        # Cleanup should remove expired entries
        cleaned_count = await cache.cleanup_expired()
        assert cleaned_count == 2
        assert len(cache._cache) == 0
    
    @pytest.mark.asyncio
    async def test_cache_invalidation_empty_category(self, cache):
        """Test invalidation of empty categories."""
        # Try to invalidate non-existent category
        invalidated = await cache.invalidate_category("nonexistent")
        assert invalidated == 0
        
        # Add and remove entry, then try invalidation
        await cache.set("guild_data", "temp_value", 123, "temp_key")
        await cache.delete("guild_data", 123, "temp_key")
        
        invalidated = await cache.invalidate_category("guild_data")
        assert invalidated == 0


if __name__ == "__main__":
    """Run cache tests directly."""
    pytest.main([__file__, "-v"])