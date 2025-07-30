import logging
import time
import asyncio
from typing import Dict, Any, Optional, Set, List, Callable
from collections import defaultdict
from functools import wraps

# #################################################################################### #
#                            Global Cache System Configuration
# #################################################################################### #

DEFAULT_TTL = 300  # 5 minutes
CACHE_CATEGORIES = {
    'guild_data': 600,      # 10 minutes - Guild settings, roles, channels
    'user_data': 300,       # 5 minutes - User profiles, setup data
    'events_data': 180,     # 3 minutes - Events, registrations
    'roster_data': 180,     # 3 minutes - Guild members, roster info
    'static_data': 3600,    # 1 hour - Weapons, combinations, static configs
    'discord_entities': 300, # 5 minutes - Discord members, channels, guilds
    'temporary': 60         # 1 minute - Short-term cache
}

# #################################################################################### #
#                            Cache Entry Management
# #################################################################################### #

class CacheEntry:
    """Individual cache entry with TTL and metadata."""
    
    def __init__(self, value: Any, ttl: int, category: str):
        self.value = value
        self.created_at = time.time()
        self.ttl = ttl
        self.category = category
        self.access_count = 1
        self.last_accessed = time.time()
    
    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        return time.time() - self.created_at > self.ttl
    
    def access(self) -> Any:
        """Access entry and update metrics."""
        self.access_count += 1
        self.last_accessed = time.time()
        return self.value
    
    def get_age(self) -> float:
        """Get entry age in seconds."""
        return time.time() - self.created_at

# #################################################################################### #
#                            Global Cache System Core
# #################################################################################### #

class GlobalCacheSystem:
    """Centralized cache system for all bot components."""
    
    def __init__(self):
        self._cache: Dict[str, CacheEntry] = {}
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._metrics = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'evictions': 0,
            'cleanups': 0
        }
        self._category_metrics: Dict[str, Dict[str, int]] = {
            category: {'hits': 0, 'misses': 0, 'sets': 0, 'size': 0}
            for category in CACHE_CATEGORIES.keys()
        }
        self._invalidation_rules: Dict[str, Set[str]] = {}
        
        logging.info("[Cache] Global cache system initialized")
    
    def _generate_key(self, category: str, *args) -> str:
        """Generate cache key from category and arguments."""
        key_parts = [str(arg) for arg in args if arg is not None]
        return f"{category}:{':'.join(key_parts)}"
    
    def _get_ttl_for_category(self, category: str) -> int:
        """Get TTL for specific category."""
        return CACHE_CATEGORIES.get(category, DEFAULT_TTL)
    
    async def get(self, category: str, *args) -> Optional[Any]:
        """Get value from cache."""
        key = self._generate_key(category, *args)
        
        async with self._locks[key]:
            entry = self._cache.get(key)
            
            if entry is None:
                self._metrics['misses'] += 1
                self._category_metrics[category]['misses'] += 1
                return None
            
            if entry.is_expired():
                del self._cache[key]
                self._metrics['misses'] += 1
                self._metrics['evictions'] += 1
                self._category_metrics[category]['misses'] += 1
                self._category_metrics[category]['size'] -= 1
                return None
            
            self._metrics['hits'] += 1
            self._category_metrics[category]['hits'] += 1
            return entry.access()
    
    async def set(self, category: str, value: Any, *args, ttl: Optional[int] = None) -> None:
        """Set value in cache."""
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
        """Delete specific cache entry."""
        key = self._generate_key(category, *args)
        
        async with self._locks[key]:
            if key in self._cache:
                entry = self._cache[key]
                del self._cache[key]
                self._category_metrics[entry.category]['size'] -= 1
                return True
            return False
    
    async def invalidate_category(self, category: str) -> int:
        """Invalidate all entries in a category."""
        keys_to_remove = []
        
        for key, entry in self._cache.items():
            if entry.category == category:
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            async with self._locks[key]:
                if key in self._cache:
                    del self._cache[key]
        
        self._category_metrics[category]['size'] = 0
        logging.info(f"[Cache] Invalidated {len(keys_to_remove)} entries in category {category}")
        return len(keys_to_remove)

# #################################################################################### #
#                            Cache Invalidation Rules
# #################################################################################### #

    def add_invalidation_rule(self, trigger_category: str, affected_categories: List[str]):
        """Add rule to invalidate categories when trigger category changes."""
        if trigger_category not in self._invalidation_rules:
            self._invalidation_rules[trigger_category] = set()
        self._invalidation_rules[trigger_category].update(affected_categories)
    
    async def invalidate_related(self, category: str) -> int:
        """Invalidate categories related to the changed category."""
        total_invalidated = 0
        
        if category in self._invalidation_rules:
            for affected_category in self._invalidation_rules[category]:
                invalidated = await self.invalidate_category(affected_category)
                total_invalidated += invalidated
        
        return total_invalidated

# #################################################################################### #
#                            Specialized Cache Methods
# #################################################################################### #

    async def get_guild_data(self, guild_id: int, data_type: str) -> Optional[Any]:
        """Get guild-specific data."""
        return await self.get('guild_data', guild_id, data_type)
    
    async def set_guild_data(self, guild_id: int, data_type: str, value: Any) -> None:
        """Set guild-specific data."""
        await self.set('guild_data', value, guild_id, data_type)
    
    async def get_user_data(self, guild_id: int, user_id: int, data_type: str) -> Optional[Any]:
        """Get user-specific data."""
        return await self.get('user_data', guild_id, user_id, data_type)
    
    async def set_user_data(self, guild_id: int, user_id: int, data_type: str, value: Any) -> None:
        """Set user-specific data."""
        await self.set('user_data', value, guild_id, user_id, data_type)
    
    async def get_guild_members(self, guild_id: int) -> Optional[Dict]:
        """Get cached guild members."""
        return await self.get('roster_data', guild_id, 'members')
    
    async def set_guild_members(self, guild_id: int, members_data: Dict) -> None:
        """Cache guild members data."""
        await self.set('roster_data', members_data, guild_id, 'members')
        await self.invalidate_related('roster_data')
    
    async def get_event_data(self, guild_id: int, event_type: str = 'all') -> Optional[Any]:
        """Get cached event data."""
        return await self.get('events_data', guild_id, event_type)
    
    async def set_event_data(self, guild_id: int, event_type: str, data: Any) -> None:
        """Cache event data."""
        await self.set('events_data', data, guild_id, event_type)
    
    async def get_static_data(self, data_type: str, game_id: Optional[int] = None) -> Optional[Any]:
        """Get static configuration data."""
        return await self.get('static_data', data_type, game_id)
    
    async def set_static_data(self, data_type: str, value: Any, game_id: Optional[int] = None) -> None:
        """Cache static configuration data."""
        await self.set('static_data', value, data_type, game_id)

# #################################################################################### #
#                            Cache Maintenance and Monitoring
# #################################################################################### #

    async def cleanup_expired(self) -> int:
        """Remove all expired entries."""
        expired_keys = []
        current_time = time.time()
        
        for key, entry in self._cache.items():
            if entry.is_expired():
                expired_keys.append((key, entry.category))
        
        for key, category in expired_keys:
            async with self._locks[key]:
                if key in self._cache:
                    del self._cache[key]
                    self._category_metrics[category]['size'] -= 1
        
        if expired_keys:
            self._metrics['cleanups'] += 1
            logging.debug(f"[Cache] Cleaned up {len(expired_keys)} expired entries")
        
        return len(expired_keys)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get cache performance metrics."""
        total_requests = self._metrics['hits'] + self._metrics['misses']
        hit_rate = (self._metrics['hits'] / total_requests * 100) if total_requests > 0 else 0
        
        return {
            'global': {
                **self._metrics,
                'hit_rate': round(hit_rate, 2),
                'total_entries': len(self._cache),
                'total_requests': total_requests
            },
            'by_category': dict(self._category_metrics)
        }
    
    def get_cache_info(self) -> Dict[str, Any]:
        """Get detailed cache information."""
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
                    'total_accesses': 0
                }
            
            info['categories'][category]['count'] += 1
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
                category_info['avg_accesses'] = category_info['total_accesses'] / category_info['count']
        
        return info

# #################################################################################### #
#                            Global Cache Instance and Utilities
# #################################################################################### #

_global_cache = None

def get_global_cache() -> GlobalCacheSystem:
    """Get the global cache instance."""
    global _global_cache
    if _global_cache is None:
        _global_cache = GlobalCacheSystem()
        setup_invalidation_rules(_global_cache)
    return _global_cache

def setup_invalidation_rules(cache: GlobalCacheSystem):
    """Setup cache invalidation rules."""
    cache.add_invalidation_rule('roster_data', ['events_data'])
    cache.add_invalidation_rule('guild_data', ['roster_data', 'events_data'])
    cache.add_invalidation_rule('user_data', ['roster_data'])

def cache_method(category: str, key_generator: Optional[Callable] = None, ttl: Optional[int] = None):
    """Decorator to automatically cache method results."""
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

async def start_cache_maintenance_task():
    """Start background cache maintenance task."""
    cache = get_global_cache()
    
    async def maintenance_loop():
        while True:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                await cache.cleanup_expired()
            except Exception as e:
                logging.error(f"[Cache] Maintenance task error: {e}")
    
    asyncio.create_task(maintenance_loop())
    logging.info("[Cache] Cache maintenance task started")