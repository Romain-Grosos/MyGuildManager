"""
Global Cache System - Enterprise-grade caching with observability and performance optimization.

Provides centralized caching for Discord bot data with features including:
- TTL-based expiration with smart predictions
- Performance metrics and alerting
- Single-flight protection against thundering herd
- Correlation ID tracking for observability
- PII masking for production compliance
- Bounded shutdown and resource cleanup
"""

import asyncio
import os
import time
from collections import defaultdict, deque, Counter
from datetime import datetime
from functools import wraps
from typing import Dict, Any, Optional, Set, List, Callable
from contextvars import ContextVar

from .core.logger import ComponentLogger

correlation_id_context: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)

# #################################################################################### #
#                            Global Cache System Configuration
# #################################################################################### #
DEFAULT_TTL = 3600
CACHE_CATEGORIES = {
    'guild_data': 604800,
    'user_data': 86400,
    'events_data': 172800,
    'roster_data': 86400,
    'static_data': 2592000,
    'discord_entities': 43200,
    'temporary': 300
}

# #################################################################################### #
#                            Cache Entry Management
# #################################################################################### #
class CacheEntry:
    """
    Represents a cached entry with TTL, access tracking, and prediction capabilities.
    
    Tracks access patterns to predict future usage and optimize cache performance.
    Includes smart preloading based on access frequency and timing patterns.
    """
    
    def __init__(self, value: Any, ttl: int, category: str):
        self.value = value
        self.created_at = time.monotonic()
        self.ttl = ttl
        self.category = category
        self.access_count = 1
        self.last_accessed = time.monotonic()
        self.access_times = deque(maxlen=20)
        self.access_times.append(time.monotonic())
        self.predicted_next_access = None
        self.is_hot = False
    
    def is_expired(self) -> bool:
        """
        Check if the cache entry has expired based on TTL.
        
        Returns:
            bool: True if entry has exceeded its TTL, False otherwise
        """
        return time.monotonic() - self.created_at > self.ttl
    
    def access(self) -> Any:
        """
        Access the cached value and update tracking metrics.
        
        Updates access count, timing, and prediction algorithms.
        Marks entry as hot if frequently accessed.
        
        Returns:
            Any: The cached value
        """
        self.access_count += 1
        current_time = time.monotonic()
        self.last_accessed = current_time
        self.access_times.append(current_time)

        if len(self.access_times) >= 3:
            self._update_prediction(current_time)

        if self.access_count > 5:
            self.is_hot = True
            
        return self.value
    
    def _update_prediction(self, current_time: float):
        """
        Update prediction for next access time based on historical patterns.
        
        Analyzes access intervals to predict when this entry will be needed next,
        enabling smart preloading to avoid cache misses.
        
        Args:
            current_time: Current monotonic time
        """
        if len(self.access_times) < 3:
            return

        intervals = []
        for i in range(1, len(self.access_times)):
            intervals.append(self.access_times[i] - self.access_times[i-1])
        
        if intervals:
            avg_interval = sum(intervals) / len(intervals)
            self.predicted_next_access = current_time + avg_interval
    
    def get_age(self) -> float:
        """
        Get the age of this cache entry in seconds.
        
        Returns:
            float: Age in seconds since entry was created
        """
        return time.monotonic() - self.created_at
    
    def should_preload(self) -> bool:
        """
        Determine if this entry should be preloaded based on predictions.
        
        Uses access patterns and predictions to determine if proactive
        reloading would be beneficial to avoid future cache misses.
        
        Returns:
            bool: True if entry should be preloaded, False otherwise
        """
        if not self.predicted_next_access or not self.is_hot:
            return False
        
        current_time = time.monotonic()
        time_until_prediction = self.predicted_next_access - current_time

        return 0 < time_until_prediction < (self.ttl * 0.2)

# #################################################################################### #
#                            Global Cache System Core
# #################################################################################### #
class GlobalCacheSystem:
    """Centralized cache system for all bot components."""
    
    def __init__(self, bot=None):
        """
        Initialize global cache system with metrics and smart features.
        
        Args:
            bot: Discord bot instance (optional)
        """
        self._cache: Dict[str, CacheEntry] = {}
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._initial_load_complete = False
        self._metrics = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'evictions': 0,
            'cleanups': 0,
            'preloads_successful': 0,
            'preloads_wasted': 0,
            'predictions_correct': 0,
            'predictions_total': 0
        }
        self._category_metrics: Dict[str, Dict[str, int]] = {
            category: {'hits': 0, 'misses': 0, 'sets': 0, 'size': 0}
            for category in CACHE_CATEGORIES.keys()
        }
        self._invalidation_rules: Dict[str, Set[str]] = {}

        self.bot = bot
        self._hot_keys: Set[str] = set()
        self._preload_tasks: Dict[str, asyncio.Task] = {}
        self._maintenance_task: Optional[asyncio.Task] = None
        
        self._inflight_reloads: Dict[str, asyncio.Event] = {}
        self._configured_guilds_cache: Optional[Set[int]] = None
        self._configured_guilds_cache_time: float = 0
        
        self._sliding_window_size = 900
        self._latency_samples = deque(maxlen=1000)
        self._request_timestamps = deque(maxlen=10000)
        
        self._fast_threshold_ms = 100
        self._slow_threshold_ms = 1000
        
        self._preload_semaphore = asyncio.Semaphore(4)
        self._preload_slots_total = 4
        self._preload_slots_used = 0
        
        self._started_at = time.monotonic()
        self._cold_start_seconds = int(os.environ.get('COLD_START_SECONDS', '300'))
        self._alert_cooldown_seconds = int(os.environ.get('ALERT_COOLDOWN_SECONDS', '300'))
        self._last_alert_times = {}
        self._logger = ComponentLogger("cache")
        
        self._logger.info("cache_initialized", component="cache", smart_features=True)

    def _generate_key(self, category: str, *args) -> str:
        """
        Generate cache key from category and arguments.
        
        Args:
            category: Cache category
            *args: Arguments to include in key
            
        Returns:
            Generated cache key string
        """
        key_parts = [str(arg) for arg in args if arg is not None]
        return f"{category}:{':'.join(key_parts)}"
    
    def _get_ttl_for_category(self, category: str) -> int:
        """
        Get TTL for specific category.
        
        Args:
            category: Cache category name
            
        Returns:
            TTL in seconds for the category
        """
        return CACHE_CATEGORIES.get(category, DEFAULT_TTL)
    
    async def get(self, category: str, *args) -> Optional[Any]:
        """
        Get value from cache with TTL validation and metrics tracking.
        
        Args:
            category: Cache category
            *args: Arguments for cache key generation
            
        Returns:
            Cached value or None if not found/expired
        """
        key = self._generate_key(category, *args)
        start_time = time.monotonic()
        
        async with self._locks[key]:
            entry = self._cache.get(key)
            
            if entry is None:
                self._metrics['misses'] += 1
                self._category_metrics[category]['misses'] += 1
                self._track_latency(start_time)
                return None
            
            if entry.is_expired():
                del self._cache[key]
                self._metrics['misses'] += 1
                self._metrics['evictions'] += 1
                self._category_metrics[category]['misses'] += 1
                self._category_metrics[category]['size'] = max(0, self._category_metrics[category]['size'] - 1)
                self._track_latency(start_time)
                return None
            
            self._metrics['hits'] += 1
            self._category_metrics[category]['hits'] += 1
            self._track_latency(start_time)
            return entry.access()
    
    def _track_latency(self, start_time: float) -> None:
        """Track request latency for performance metrics."""
        latency_ms = (time.monotonic() - start_time) * 1000
        self._latency_samples.append(latency_ms)
        self._request_timestamps.append(time.monotonic())
    
    async def set(self, category: str, value: Any, *args, ttl: Optional[int] = None) -> None:
        """
        Set value in cache with optional custom TTL.
        
        Args:
            category: Cache category
            value: Value to cache
            *args: Arguments for cache key generation
            ttl: Custom TTL in seconds (optional)
        """
        key = self._generate_key(category, *args)
        cache_ttl = ttl or self._get_ttl_for_category(category)
        
        async with self._locks[key]:
            was_new_entry = key not in self._cache
            self._cache[key] = CacheEntry(value, cache_ttl, category)
            
            self._metrics['sets'] += 1
            self._category_metrics[category]['sets'] += 1
            
            if was_new_entry:
                self._category_metrics[category]['size'] += 1
    
    async def delete(self, category: str, *args) -> bool:
        """
        Delete specific cache entry.
        
        Args:
            category: Cache category
            *args: Arguments for cache key generation
            
        Returns:
            True if entry was deleted, False if not found
        """
        key = self._generate_key(category, *args)
        
        async with self._locks[key]:
            if key in self._cache:
                entry = self._cache[key]
                del self._cache[key]
                self._category_metrics[entry.category]['size'] = max(0, self._category_metrics[entry.category]['size'] - 1)
                return True
            return False
    
    async def invalidate_category(self, category: str) -> int:
        """
        Invalidate all entries in a specific category.
        
        Args:
            category: Cache category to invalidate
            
        Returns:
            Number of entries invalidated
        """
        keys_to_remove = []
        
        for key, entry in self._cache.items():
            if entry.category == category:
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            async with self._locks[key]:
                if key in self._cache:
                    del self._cache[key]
        
        if category in self._category_metrics:
            self._category_metrics[category]['size'] = 0
        self._logger.info("category_invalidated", category=category, entry_count=len(keys_to_remove))
        return len(keys_to_remove)
    
    async def stop(self) -> None:
        """Stop cache system with bounded shutdown."""
        self._logger.info("cache_stopping")
        
        if self._maintenance_task and not self._maintenance_task.done():
            self._maintenance_task.cancel()
            try:
                await asyncio.wait_for(self._maintenance_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        
        if self._preload_tasks:
            for task in list(self._preload_tasks.values()):
                if not task.done():
                    task.cancel()
            
            if self._preload_tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*self._preload_tasks.values(), return_exceptions=True),
                        timeout=2.0
                    )
                except asyncio.TimeoutError:
                    pass
            
            self._preload_tasks.clear()
        
        self._maintenance_task = None
        self._logger.info("cache_stopped")

    # #################################################################################### #
    #                            Cache Invalidation Rules
    # #################################################################################### #
    def add_invalidation_rule(self, trigger_category: str, affected_categories: List[str]):
        """
        Add rule to invalidate categories when trigger category changes.
        
        Args:
            trigger_category: Category that triggers invalidation
            affected_categories: Categories to invalidate when trigger changes
        """
        if trigger_category not in self._invalidation_rules:
            self._invalidation_rules[trigger_category] = set()
        self._invalidation_rules[trigger_category].update(affected_categories)
    
    async def invalidate_related(self, category: str) -> int:
        """
        Invalidate categories related to the changed category.
        
        Args:
            category: Category that changed
            
        Returns:
            Total number of entries invalidated
        """
        total_invalidated = 0
        
        if category in self._invalidation_rules:
            for affected_category in self._invalidation_rules[category]:
                invalidated = await self.invalidate_category(affected_category)
                total_invalidated += invalidated
        
        return total_invalidated

    # #################################################################################### #
    #                            Specialized Cache Methods
    # #################################################################################### #
    async def get_guild_data(self, guild_id: int, data_type: str, _auto_reload: bool = True) -> Optional[Any]:
        """
        Get guild-specific data from cache with auto-reload if missing.
        
        Args:
            guild_id: Discord guild ID
            data_type: Type of data to retrieve
            _auto_reload: Internal flag to prevent infinite recursion
            
        Returns:
            Cached guild data or None
        """
        key = self._generate_key('guild_data', guild_id, data_type)

        if key in self._inflight_reloads:
            await self._inflight_reloads[key].wait()
            result = await self.get('guild_data', guild_id, data_type)
            if result is not None:
                return result
            
        result = await self.get('guild_data', guild_id, data_type)

        if result is None and _auto_reload and self._initial_load_complete and self.bot and hasattr(self.bot, 'cache_loader'):
            if not await self._is_guild_configured(guild_id):
                self._logger.debug("skipping_auto_reload", reason="unconfigured_guild")
                return None
                
            async with self._locks[key]:
                if key in self._inflight_reloads:
                    await self._inflight_reloads[key].wait()
                    return await self.get('guild_data', guild_id, data_type)
                    
                event = asyncio.Event()
                self._inflight_reloads[key] = event
            
            try:
                category_map = {
                    'roles': 'guild_roles',
                    'settings': 'guild_settings',
                    'channels': 'guild_channels',
                    'guild_lang': 'guild_settings',
                    'guild_ptb': 'guild_settings',
                    'guild_name': 'guild_settings',
                    'guild_game': 'guild_settings',
                    'guild_server': 'guild_settings',
                    'initialized': 'guild_settings',
                    'premium': 'guild_settings',
                    'members_role': 'guild_roles',
                    'absent_members_role': 'guild_roles',
                    'rules_ok_role': 'guild_roles',
                    'config_ok_role': 'guild_roles',
                    'members_channel': 'guild_channels',
                    'rules_message': 'guild_channels',
                    'absence_channels': 'guild_channels'
                }
                
                category = category_map.get(data_type)
                if category:
                    self._logger.debug("auto_reloading", category=category, reason="missing_data")
                    try:
                        await self.bot.cache_loader.reload_category(category)
                        result = await self.get_guild_data(guild_id, data_type, _auto_reload=False)
                    except Exception as e:
                        self._logger.error("auto_reload_failed", category=category, 
                                      error_type=type(e).__name__, error_msg=str(e))
            finally:
                event.set()
                self._inflight_reloads.pop(key, None)
        
        return result
    
    async def _is_guild_configured(self, guild_id: int) -> bool:
        """
        Check if a guild is configured (initialized) without triggering auto-reload.
        
        Uses a cached list of configured guild IDs to avoid repeated DB queries.
        Cache is refreshed every 30 minutes or when explicitly invalidated.
        
        Args:
            guild_id: Discord guild ID to check
            
        Returns:
            True if guild is configured, False otherwise
        """
        current_time = time.monotonic()
        if (self._configured_guilds_cache is None or 
            current_time - self._configured_guilds_cache_time > 1800):

            try:
                if not self.bot:
                    return False
                    
                query = "SELECT guild_id FROM guild_settings WHERE initialized = TRUE"
                rows = await self.bot.run_db_query(query, fetch_all=True)
                
                self._configured_guilds_cache = set()
                if rows:
                    for row in rows:
                        self._configured_guilds_cache.add(row[0])
                        
                self._configured_guilds_cache_time = current_time
                self._logger.debug("configured_guilds_refreshed", 
                              guild_count=len(self._configured_guilds_cache))
                
            except Exception as e:
                self._logger.error("configured_guilds_error", error_type=type(e).__name__, error_msg=str(e))
                return False
        
        return guild_id in self._configured_guilds_cache
    
    async def invalidate_configured_guilds_cache(self) -> None:
        """
        Invalidate the configured guilds cache.
        
        Should be called after adding/removing a configured guild to ensure
        the cache reflects the current state immediately.
        """
        self._configured_guilds_cache = None
        self._configured_guilds_cache_time = 0
        self._logger.debug("configured_guilds_invalidated")
    
    async def ensure_cache_persistence(self) -> None:
        """
        Ensure cache data persists and reload if necessary.
        
        This method checks if critical cache data exists and
        triggers a reload if the cache appears to be empty.
        """
        critical_empty = True

        for key in self._cache:
            if key.startswith('guild_data:'):
                critical_empty = False
                break
                
        if critical_empty and self._initial_load_complete:
            self._logger.warning("cache_empty_triggering_reload")
            if hasattr(self, 'bot') and hasattr(self.bot, 'cache_loader'):
                try:
                    self._initial_load_complete = False
                    await self.bot.cache_loader.load_all_shared_data()
                    self._initial_load_complete = True
                    self._logger.info("cache_reloaded_successfully")
                except Exception as e:
                    self._logger.error("cache_reload_failed", 
                                  error_type=type(e).__name__, error_msg=str(e))
                    self._initial_load_complete = True
    
    async def set_guild_data(self, guild_id: int, data_type: str, value: Any) -> None:
        """
        Set guild-specific data in cache.
        
        Args:
            guild_id: Discord guild ID
            data_type: Type of data to store
            value: Data value to cache
        """
        await self.set('guild_data', value, guild_id, data_type)
    
    async def delete_guild_data(self, guild_id: int, data_type: str) -> bool:
        """
        Delete guild-specific data from cache.
        
        Args:
            guild_id: Discord guild ID
            data_type: Type of data to delete
            
        Returns:
            True if data was deleted, False if not found
        """
        return await self.delete('guild_data', guild_id, data_type)
    
    async def get_user_data(self, guild_id: int, user_id: int, data_type: str, _auto_reload: bool = True) -> Optional[Any]:
        """
        Get user-specific data from cache with auto-reload if missing.
        
        Args:
            guild_id: Discord guild ID
            user_id: Discord user ID
            data_type: Type of data to retrieve
            _auto_reload: Internal flag to prevent infinite recursion
            
        Returns:
            Cached user data or None
        """
        key = self._generate_key('user_data', guild_id, user_id, data_type)

        if key in self._inflight_reloads:
            await self._inflight_reloads[key].wait()
            result = await self.get('user_data', guild_id, user_id, data_type)
            if result is not None:
                return result
            
        result = await self.get('user_data', guild_id, user_id, data_type)

        if result is None and _auto_reload and self._initial_load_complete and self.bot and hasattr(self.bot, 'cache_loader'):
            if not await self._is_guild_configured(guild_id):
                self._logger.debug("skipping_auto_reload_user", reason="unconfigured_guild")
                return None
                
            async with self._locks[key]:
                if key in self._inflight_reloads:
                    await self._inflight_reloads[key].wait()
                    return await self.get('user_data', guild_id, user_id, data_type)
                    
                event = asyncio.Event()
                self._inflight_reloads[key] = event
            
            try:
                category_map = {
                    'setup': 'user_setup',
                    'locale': 'user_setup',
                    'welcome_message': 'welcome_messages'
                }
                
                category = category_map.get(data_type)
                if category:
                    self._logger.debug("auto_reloading_user", category=category, reason="missing_data")
                    try:
                        await self.bot.cache_loader.reload_category(category)
                        result = await self.get_user_data(guild_id, user_id, data_type, _auto_reload=False)
                    except Exception as e:
                        self._logger.error("auto_reload_user_failed", category=category, 
                                      error_type=type(e).__name__, error_msg=str(e))
            finally:
                event.set()
                self._inflight_reloads.pop(key, None)
        
        return result
    
    async def set_user_data(self, guild_id: int, user_id: int, data_type: str, value: Any) -> None:
        """
        Set user-specific data in cache.
        
        Args:
            guild_id: Discord guild ID
            user_id: Discord user ID
            data_type: Type of data to store
            value: Data value to cache
        """
        await self.set('user_data', value, guild_id, user_id, data_type)
    
    async def get_guild_members(self, guild_id: int) -> Optional[Dict]:
        """
        Get cached guild members data.
        
        Args:
            guild_id: Discord guild ID
            
        Returns:
            Cached guild members dictionary or None
        """
        return await self.get('roster_data', guild_id, 'members')
    
    async def set_guild_members(self, guild_id: int, members_data: Dict) -> None:
        """
        Cache guild members data and invalidate related caches.
        
        Args:
            guild_id: Discord guild ID
            members_data: Members data dictionary to cache
        """
        await self.set('roster_data', members_data, guild_id, 'members')
        await self.invalidate_related('roster_data')
    
    async def get_event_data(self, guild_id: int, event_type: str = 'all') -> Optional[Any]:
        """
        Get cached event data for a guild.
        
        Args:
            guild_id: Discord guild ID
            event_type: Type of event data to retrieve (default: 'all')
            
        Returns:
            Cached event data or None
        """
        return await self.get('events_data', guild_id, event_type)
    
    async def set_event_data(self, guild_id: int, event_type: str, data: Any) -> None:
        """
        Cache event data for a guild.
        
        Args:
            guild_id: Discord guild ID
            event_type: Type of event data
            data: Event data to cache
        """
        await self.set('events_data', data, guild_id, event_type)
    
    async def get_static_data(self, data_type: str, game_id: Optional[int] = None) -> Optional[Any]:
        """
        Get static configuration data from cache.
        
        Args:
            data_type: Type of static data to retrieve
            game_id: Optional game ID for game-specific data
            
        Returns:
            Cached static data or None
        """
        return await self.get('static_data', data_type, game_id)
    
    async def set_static_data(self, data_type: str, value: Any, game_id: Optional[int] = None) -> None:
        """
        Cache static configuration data.
        
        Args:
            data_type: Type of static data
            value: Data value to cache
            game_id: Optional game ID for game-specific data
        """
        await self.set('static_data', value, data_type, game_id)

    # #################################################################################### #
    #                            Cache Maintenance and Monitoring
    # #################################################################################### #
    async def cleanup_expired(self) -> int:
        """
        Remove all expired entries from cache.
        
        Returns:
            Number of entries cleaned up
        """
        expired_keys = []
        current_time = time.monotonic()
        
        for key, entry in self._cache.items():
            if entry.is_expired():
                expired_keys.append((key, entry.category))
        
        for key, category in expired_keys:
            async with self._locks[key]:
                if key in self._cache:
                    del self._cache[key]
                    self._category_metrics[category]['size'] = max(0, self._category_metrics[category]['size'] - 1)
        
        if expired_keys:
            self._metrics['cleanups'] += 1
            self._logger.debug("cache_cleanup", expired_count=len(expired_keys))
        
        return len(expired_keys)
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get cache performance metrics with sliding windows.
        
        Returns:
            Dictionary containing global and category-specific metrics
        """
        total_requests = self._metrics['hits'] + self._metrics['misses']
        hit_rate = (self._metrics['hits'] / total_requests * 100) if total_requests > 0 else 0
        
        percentiles = {'p50': 0, 'p95': 0, 'p99': 0}
        if self._latency_samples:
            sorted_latencies = sorted(self._latency_samples)
            n = len(sorted_latencies)
            percentiles = {
                'p50': sorted_latencies[int(n * 0.50)] if n > 0 else 0,
                'p95': sorted_latencies[int(n * 0.95)] if n > 0 else 0,
                'p99': sorted_latencies[int(n * 0.99)] if n > 0 else 0
            }
        
        fast_count = sum(1 for lat in self._latency_samples if lat < self._fast_threshold_ms)
        slow_count = sum(1 for lat in self._latency_samples if lat > self._slow_threshold_ms)
        total_samples = len(self._latency_samples)
        
        fast_percent = (fast_count / total_samples * 100) if total_samples > 0 else 0
        slow_percent = (slow_count / total_samples * 100) if total_samples > 0 else 0
        
        if self._should_trigger_alert():
            self._check_performance_alerts(fast_percent, slow_percent)
        
        return {
            'global': {
                **self._metrics,
                'hit_rate': round(hit_rate, 2),
                'total_entries': len(self._cache),
                'total_requests': total_requests,
                **percentiles,
                'fast_percent': round(fast_percent, 1),
                'slow_percent': round(slow_percent, 1),
                'latency_samples_count': total_samples
            },
            'by_category': dict(self._category_metrics)
        }
    
    def get_cache_info(self) -> Dict[str, Any]:
        """
        Get detailed cache information and statistics.
        
        Returns:
            Dictionary containing detailed cache information
        """
        info = {
            'total_entries': len(self._cache),
            'categories': {},
            'oldest_entry': None,
            'newest_entry': None
        }
        
        oldest_time = float('inf')
        newest_time = 0
        
        for key, entry in self._cache.items():
            category = entry.category
            if category not in info['categories']:
                info['categories'][category] = {
                    'count': 0,
                    'avg_age': 0,
                    'total_age': 0,
                    'total_accesses': 0
                }
            
            info['categories'][category]['count'] += 1
            info['categories'][category]['total_age'] += entry.get_age()
            info['categories'][category]['total_accesses'] += entry.access_count
            
            if entry.created_at < oldest_time:
                oldest_time = entry.created_at
                info['oldest_entry'] = {
                    'key': key,
                    'age': entry.get_age(),
                    'category': category
                }
            
            if entry.created_at > newest_time:
                newest_time = entry.created_at
                info['newest_entry'] = {
                    'key': key,
                    'age': entry.get_age(),
                    'category': category
                }
        
        for category_info in info['categories'].values():
            if category_info['count'] > 0:
                category_info['avg_age'] = round(category_info['total_age'] / category_info['count'], 2)
                category_info['avg_accesses'] = category_info['total_accesses'] / category_info['count']
            category_info.pop('total_age', None)
        
        return info
    
    def _preload_slots_available(self) -> int:
        """Get number of available preload slots (robust wrapper)."""
        return max(0, self._preload_slots_total - self._preload_slots_used)
    
    def _should_trigger_alert(self) -> bool:
        """Check if we should trigger alerts (post cold-start)."""
        current_time = time.monotonic()
        return current_time - self._started_at > self._cold_start_seconds
    
    def _check_performance_alerts(self, fast_percent: float, slow_percent: float) -> None:
        """Check and trigger performance alerts with cooldown."""
        current_time = time.monotonic()
        
        fast_min_threshold = int(os.environ.get('ALERT_FAST_PERCENT_MIN', '60'))
        if fast_percent < fast_min_threshold:
            if self._can_send_alert('fast_percent_drop', current_time):
                self._logger.warning("performance_alert", 
                              alert_type="fast_percent_drop", 
                              current_fast_percent=fast_percent,
                              threshold=fast_min_threshold)
                self._last_alert_times['fast_percent_drop'] = current_time
        
  
        slow_max_threshold = int(os.environ.get('ALERT_SLOW_PERCENT_MAX', '10'))
        if slow_percent > slow_max_threshold:
            if self._can_send_alert('slow_percent_spike', current_time):
                self._logger.warning("performance_alert", 
                              alert_type="slow_percent_spike", 
                              current_slow_percent=slow_percent,
                              threshold=slow_max_threshold)
                self._last_alert_times['slow_percent_spike'] = current_time
    
    def _can_send_alert(self, alert_type: str, current_time: float) -> bool:
        """Check if alert can be sent (respecting cooldown)."""
        last_alert = self._last_alert_times.get(alert_type, 0)
        return current_time - last_alert > self._alert_cooldown_seconds
    
    # #################################################################################### #
    #                            Performance Optimization Methods
    # #################################################################################### #
    async def get_bulk_guild_members(self, guild_id: int, force_refresh: bool = False) -> Dict[int, Dict]:
        """
        Get all guild members with optimized cache and database query.
        
        Args:
            guild_id: Discord guild ID
            force_refresh: Force refresh from database (default: False)
            
        Returns:
            Dictionary mapping member IDs to member data
        """
        cache_key = f"bulk_guild_members_{guild_id}"
        
        if not force_refresh:
            cached_result = await self.get('roster_data', cache_key)
            if cached_result:
                return cached_result
        
        if not self.bot:
            return {}
        
        query = """
        SELECT gm.member_id, gm.username, gm.language, gm.GS, gm.build, gm.weapons, 
               gm.DKP, gm.nb_events, gm.registrations, gm.attendances, gm.class,
               us.locale
        FROM guild_members gm
        LEFT JOIN user_setup us ON gm.guild_id = us.guild_id AND gm.member_id = us.user_id
        WHERE gm.guild_id = %s
        ORDER BY gm.class, gm.GS DESC
        """
        
        start_time = time.monotonic()
        try:
            rows = await self.bot.run_db_query(query, (guild_id,), fetch_all=True)
        except Exception as e:
            self._logger.error("db_query_error", operation="get_bulk_guild_members", 
                          error_type=type(e).__name__, error_msg=str(e))
            return {}
        query_time = time.monotonic() - start_time
        
        members_data = {}
        if rows:
            for row in rows:
                member_id, username, language, gs, build, weapons, dkp, nb_events, registrations, attendances, class_type, locale = row
                members_data[member_id] = {
                    'username': username,
                    'language': language,
                    'GS': gs,
                    'build': build,
                    'weapons': weapons,
                    'DKP': dkp,
                    'nb_events': nb_events,
                    'registrations': registrations,
                    'attendances': attendances,
                    'class': class_type,
                    'locale': locale
                }
        
        await self.set('roster_data', members_data, cache_key, ttl=600)
        
        if query_time > 0.1:
            self._logger.warning("slow_db_query", operation="get_bulk_guild_members",
                          duration_ms=int(query_time * 1000), member_count=len(members_data))
        
        return members_data
    
    async def get_guild_member_data(self, guild_id: int, user_id: int) -> Optional[Dict]:
        """
        Get individual guild member data from cache.
        
        Args:
            guild_id: Discord guild ID
            user_id: Discord user ID
            
        Returns:
            Member data dictionary or None if not found
        """
        try:
            bulk_members = await self.get_bulk_guild_members(guild_id)
            return bulk_members.get(user_id)
        except Exception as e:
            self._logger.error("guild_member_data_error", 
                          error_type=type(e).__name__, error_msg=str(e))
            return None
    
    async def get_user_setup_data(self, guild_id: int, user_id: int) -> Optional[Dict]:
        """
        Get user setup data from cache via bulk guild members.
        
        Args:
            guild_id: Discord guild ID
            user_id: Discord user ID
            
        Returns:
            User setup data dictionary or None if not found
        """
        try:
            member_data = await self.get_guild_member_data(guild_id, user_id)
            if member_data and 'locale' in member_data:
                return {
                    'locale': member_data['locale'],
                    'gs': member_data.get('GS'),
                    'weapons': member_data.get('weapons')
                }
            return None
        except Exception as e:
            self._logger.error("user_setup_data_error", 
                          error_type=type(e).__name__, error_msg=str(e))
            return None

    async def get_cached_guild_roles(self, guild_id: int, force_refresh: bool = False) -> Dict[int, Any]:
        """
        Get guild roles with cache optimization.
        
        Args:
            guild_id: Discord guild ID
            force_refresh: Force refresh from Discord API (default: False)
            
        Returns:
            Dictionary mapping role IDs to role objects
        """
        cache_key = f"guild_roles_{guild_id}"
        
        if not force_refresh:
            cached_result = await self.get('discord_entities', cache_key)
            if cached_result:
                return cached_result
        
        if not self.bot:
            return {}
        
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return {}
        
        roles_dict = {role.id: role for role in guild.roles}
        await self.set('discord_entities', roles_dict, cache_key, ttl=300)
        
        return roles_dict
    
    async def get_role_members_optimized(self, guild_id: int, role_id: int) -> Set[int]:
        """
        Get role members in an optimized way with caching.
        
        Args:
            guild_id: Discord guild ID
            role_id: Discord role ID
            
        Returns:
            Set of member IDs with the role
        """
        cache_key = f"role_members_{guild_id}_{role_id}"
        
        cached_result = await self.get('discord_entities', cache_key)
        if cached_result:
            return cached_result
        
        if not self.bot:
            return set()
        
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return set()
        
        role = guild.get_role(role_id)
        if not role:
            return set()
        
        member_ids = {member.id for member in role.members}
        await self.set('discord_entities', member_ids, cache_key, ttl=120)
        
        return member_ids
    
    async def _smart_maintenance(self):
        """
        Smart cache maintenance with predictions and preloading.
        """
        try:
            for key, entry in list(self._cache.items()):
                if entry.should_preload() and key not in self._preload_tasks:
                    await self._schedule_preload(key, entry)

            await self._update_hot_keys()

            if self.bot:
                await self._optimize_active_guilds()
                
        except Exception as e:
            self._logger.error("smart_maintenance_error", 
                          error_type=type(e).__name__, error_msg=str(e))
    
    async def _schedule_preload(self, key: str, entry: CacheEntry):
        """
        Schedule preloading of an entry based on predictions.
        
        Args:
            key: Cache key
            entry: Cache entry to preload
        """
        async def preload_task():
            async with self._preload_semaphore:
                self._preload_slots_used += 1
                try:
                    if entry.predicted_next_access:
                        delay = entry.predicted_next_access - time.monotonic() - (entry.ttl * 0.1)
                        if delay > 0:
                            await asyncio.sleep(delay)

                    if await self._preload_entry(key, entry):
                        self._metrics['preloads_successful'] += 1
                    else:
                        self._metrics['preloads_wasted'] += 1
                    
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    self._logger.error("preload_error", 
                                error_type=type(e).__name__, error_msg=str(e))
                finally:
                    self._preload_slots_used = max(0, self._preload_slots_used - 1)
                    if key in self._preload_tasks:
                        del self._preload_tasks[key]
        
        self._preload_tasks[key] = asyncio.create_task(preload_task())
    
    async def _preload_entry(self, key: str, entry: CacheEntry) -> bool:
        """
        Preload a specific entry by refreshing its data.
        
        Args:
            key: Cache key
            entry: Cache entry to preload
            
        Returns:
            True if preload was successful, False otherwise
        """
        try:
            key_parts = key.split(':', 1)
            if len(key_parts) > 1:
                _, remainder = key_parts
                if remainder.startswith('bulk_guild_members_'):
                    guild_id = int(remainder.split('_')[-1])
                    data = await self.get_bulk_guild_members(guild_id, force_refresh=True)
                    return data is not None
                elif remainder.startswith('guild_roles_'):
                    guild_id = int(remainder.split('_')[-1])
                    data = await self.get_cached_guild_roles(guild_id, force_refresh=True)
                    return data is not None
                
            return False
            
        except Exception as e:
            self._logger.debug("preload_failed", 
                          error_type=type(e).__name__, error_msg=str(e))
            return False
    
    async def _update_hot_keys(self):
        """
        Update the list of hot keys based on access patterns.
        """
        hot_candidates = []
        for key, entry in self._cache.items():
            if entry.access_count > 3:
                hot_candidates.append((key, entry.access_count, entry.get_age()))

        hot_candidates.sort(key=lambda x: (x[1] / max(x[2], 1)), reverse=True)

        self._hot_keys = {key for key, _, _ in hot_candidates[:50]}
    
    async def _optimize_active_guilds(self):
        """
        Optimize cache for the most active guilds by preloading data.
        """
        if not self.bot:
            return

        guild_activity = Counter()
        current_time = time.monotonic()
        
        for key, entry in self._cache.items():
            if '_' in key and entry.last_accessed > current_time - 3600:
                parts = key.split('_')
                if len(parts) >= 2 and parts[-1].isdigit():
                    guild_id = int(parts[-1])
                    guild_activity[guild_id] += entry.access_count

        for guild_id, activity in guild_activity.most_common(3):
            await self._preload_guild_data(guild_id)
    
    async def _preload_guild_data(self, guild_id: int):
        """
        Preload commonly used guild data for optimization.
        
        Args:
            guild_id: Discord guild ID
        """
        preload_tasks = []
 
        common_keys = [
            f'bulk_guild_members_{guild_id}',
            f'guild_roles_{guild_id}'
        ]
        
        for key in common_keys:
            if key not in self._cache:
                if key.startswith('bulk_guild_members_'):
                    preload_tasks.append(self.get_bulk_guild_members(guild_id))
                elif key.startswith('guild_roles_'):
                    preload_tasks.append(self.get_cached_guild_roles(guild_id))
        
        if preload_tasks:
            await asyncio.gather(*preload_tasks, return_exceptions=True)
    
    def get_smart_stats(self) -> Dict[str, Any]:
        """
        Return smart cache statistics including predictions and preloading.
        
        Returns:
            Dictionary containing smart cache statistics
        """
        total_requests = self._metrics['hits'] + self._metrics['misses']
        hit_rate = (self._metrics['hits'] / total_requests * 100) if total_requests > 0 else 0
        
        preload_total = self._metrics['preloads_successful'] + self._metrics['preloads_wasted']
        preload_efficiency = (self._metrics['preloads_successful'] / preload_total * 100) if preload_total > 0 else 0
        
        prediction_accuracy = 0
        if self._metrics['predictions_total'] > 0:
            prediction_accuracy = (self._metrics['predictions_correct'] / self._metrics['predictions_total'] * 100)
        
        return {
            'cache_size': len(self._cache),
            'hot_keys': len(self._hot_keys),
            'hit_rate': hit_rate,
            'prediction_accuracy': prediction_accuracy,
            'preload_efficiency': preload_efficiency,
            'active_preload_tasks': len(self._preload_tasks),
            'preload_queue_available': self._preload_slots_available(),
            **self._metrics
        }
    
    async def handle_cache_error(self, operation: str, key: str, error: Exception) -> None:
        """
        Handle cache errors with logging and recovery attempts.
        
        Args:
            operation: Operation that failed (get, set, delete)
            key: Cache key involved
            error: Exception that occurred
        """
        self._logger.error("cache_operation_error", operation=operation, 
                      error_type=type(error).__name__, error_msg=str(error))

        if operation == "get" and "guild_data" in key:
            try:
                parts = key.split(":")
                if len(parts) >= 3:
                    await self.delete(parts[0], *parts[1:])
                    self._logger.debug("corrupted_entry_cleared")
            except Exception as recovery_error:
                self._logger.error("cache_recovery_failed", 
                              error_type=type(recovery_error).__name__, error_msg=str(recovery_error))
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform cache system health check and return status.
        
        Returns:
            Dictionary containing health status and metrics
        """
        health_status = {
            'status': 'healthy',
            'issues': [],
            'recommendations': []
        }

        cache_size = len(self._cache)
        if cache_size > 10000:
            health_status['issues'].append(f"Cache size very large: {cache_size} entries")
            health_status['recommendations'].append("Consider reducing TTL values or implementing more aggressive cleanup")

        total_requests = self._metrics['hits'] + self._metrics['misses']
        if total_requests > 100:
            hit_rate = (self._metrics['hits'] / total_requests * 100)
            if hit_rate < 70:
                health_status['issues'].append(f"Low cache hit rate: {hit_rate:.1f}%")
                health_status['recommendations'].append("Review caching strategy and TTL configuration")

        if self._metrics['evictions'] > self._metrics['sets'] * 0.5:
            health_status['issues'].append("High eviction rate indicates TTL values may be too low")
            health_status['recommendations'].append("Consider increasing TTL for frequently accessed data")

        if len(health_status['issues']) > 0:
            health_status['status'] = 'warning' if len(health_status['issues']) <= 2 else 'critical'
        
        return {
            **health_status,
            'metrics': self.get_metrics(),
            'timestamp': datetime.utcnow().isoformat() + "Z"
        }

# #################################################################################### #
#                            Global Cache Instance and Utilities
# #################################################################################### #
_global_cache = None

def get_global_cache(bot=None) -> GlobalCacheSystem:
    """
    Get the global cache instance (singleton pattern).
    
    Args:
        bot: Discord bot instance (optional)
        
    Returns:
        Global cache system instance
    """
    global _global_cache
    if _global_cache is None:
        _global_cache = GlobalCacheSystem(bot)
        setup_invalidation_rules(_global_cache)
    elif bot and not _global_cache.bot:
        _global_cache.bot = bot
    return _global_cache

def setup_invalidation_rules(cache: GlobalCacheSystem):
    """
    Setup cache invalidation rules for automatic cache management.
    
    Args:
        cache: Cache system instance
    """
    cache.add_invalidation_rule('roster_data', ['events_data'])
    cache.add_invalidation_rule('guild_data', ['roster_data', 'events_data'])
    cache.add_invalidation_rule('user_data', ['roster_data'])

def cache_method(category: str, key_generator: Optional[Callable] = None, ttl: Optional[int] = None):
    """
    Decorator to automatically cache method results.
    
    Args:
        category: Cache category for the results
        key_generator: Optional function to generate cache keys
        ttl: Optional custom TTL for cached results
        
    Returns:
        Decorated function with caching
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            cache = get_global_cache()
            
            if key_generator:
                cache_key_args = key_generator(*args, **kwargs)
            else:
                cache_key_args = args
            
            cached_result = await cache.get(category, *cache_key_args)
            if cached_result is not None:
                return cached_result
            
            result = await func(self, *args, **kwargs)
            
            if result is not None:
                await cache.set(category, result, *cache_key_args, ttl=ttl)
            
            return result
        return wrapper
    return decorator

async def start_cache_maintenance_task(bot=None):
    """
    Start background cache maintenance task for cleanup and optimization.
    
    Args:
        bot: Discord bot instance (optional)
    """
    cache = get_global_cache(bot)
    
    async def maintenance_loop():
        try:
            while True:
                try:
                    await asyncio.sleep(300)
                    await cache.cleanup_expired()
                    await cache._smart_maintenance()
                except Exception as e:
                    cache._logger.error("maintenance_task_error", 
                                  error_type=type(e).__name__, error_msg=str(e))
        except asyncio.CancelledError:
            cache._logger.debug("maintenance_task_cancelled")
            raise
    
    task = asyncio.create_task(maintenance_loop())
    
    cache._maintenance_task = task

    if bot and hasattr(bot, '_background_tasks'):
        bot._background_tasks.append(task)
    
    if hasattr(cache, '_logger'):
        cache._logger.info("maintenance_task_started")
    else:
        cache._logger.info("maintenance_task_started_fallback")
