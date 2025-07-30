import logging
import time
import asyncio
from typing import Dict, Any, Optional, Set, List, Callable
from collections import defaultdict, deque, Counter
from functools import wraps
from datetime import datetime

# #################################################################################### #
#                            Global Cache System Configuration
# #################################################################################### #
DEFAULT_TTL = 3600  # 1 hour
CACHE_CATEGORIES = {
    'guild_data': 86400,    # 24 hours - Guild settings, roles, channels (event-driven + fail-safe)
    'user_data': 3600,      # 1 hour - User profiles, setup data (event-driven + fail-safe)
    'events_data': 3600,    # 1 hour - Events, registrations (event-driven + fail-safe)
    'roster_data': 3600,    # 1 hour - Guild members, roster info (event-driven + fail-safe)
    'static_data': 3600,    # 1 hour - Weapons, combinations, static configs (event-driven + fail-safe)
    'discord_entities': 3600, # 1 hour - Discord members, channels, guilds (event-driven + fail-safe)
    'temporary': 300        # 5 minutes - Short-term cache
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
        # Smart cache features
        self.access_times = deque(maxlen=20)  # Derniers 20 accès
        self.access_times.append(time.time())
        self.predicted_next_access = None
        self.is_hot = False
    
    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        return time.time() - self.created_at > self.ttl
    
    def access(self) -> Any:
        """Access entry and update metrics with smart tracking."""
        self.access_count += 1
        current_time = time.time()
        self.last_accessed = current_time
        self.access_times.append(current_time)
        
        # Update prediction if we have enough data
        if len(self.access_times) >= 3:
            self._update_prediction(current_time)
        
        # Mark as hot if accessed frequently
        if self.access_count > 5:
            self.is_hot = True
            
        return self.value
    
    def _update_prediction(self, current_time: float):
        """Update prediction of next access time."""
        if len(self.access_times) < 3:
            return
            
        # Calculate average interval between accesses
        intervals = []
        for i in range(1, len(self.access_times)):
            intervals.append(self.access_times[i] - self.access_times[i-1])
        
        if intervals:
            avg_interval = sum(intervals) / len(intervals)
            self.predicted_next_access = current_time + avg_interval
    
    def get_age(self) -> float:
        """Get entry age in seconds."""
        return time.time() - self.created_at
    
    def should_preload(self) -> bool:
        """Determine if this entry should be preloaded."""
        if not self.predicted_next_access or not self.is_hot:
            return False
        
        current_time = time.time()
        time_until_prediction = self.predicted_next_access - current_time
        
        # Preload if prediction is within 20% of expiration and entry is hot
        return 0 < time_until_prediction < (self.ttl * 0.2)

# #################################################################################### #
#                            Global Cache System Core
# #################################################################################### #
class GlobalCacheSystem:
    """Centralized cache system for all bot components."""
    
    def __init__(self, bot=None):
        self._cache: Dict[str, CacheEntry] = {}
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
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
        
        # Smart cache features
        self.bot = bot
        self._hot_keys: Set[str] = set()
        self._preload_tasks: Dict[str, asyncio.Task] = {}
        self._maintenance_task: Optional[asyncio.Task] = None
        
        logging.info("[Cache] Global cache system initialized with smart features")
    
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
    
    # ==================================================================================== #
    #                          PERFORMANCE OPTIMIZATION METHODS                           #
    # ==================================================================================== #
    
    async def get_bulk_guild_members(self, guild_id: int, force_refresh: bool = False) -> Dict[int, Dict]:
        """Récupère tous les membres d'une guilde avec cache optimisé et prédiction."""
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
               us.locale, us.build_url
        FROM guild_members gm
        LEFT JOIN user_setup us ON gm.guild_id = us.guild_id AND gm.member_id = us.member_id
        WHERE gm.guild_id = %s
        ORDER BY gm.class, gm.GS DESC
        """
        
        start_time = time.time()
        rows = await self.bot.run_db_query(query, (guild_id,), fetch_all=True)
        query_time = time.time() - start_time
        
        members_data = {}
        if rows:
            for row in rows:
                member_id, username, language, gs, build, weapons, dkp, nb_events, registrations, attendances, class_type, locale, build_url = row
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
                    'locale': locale,
                    'build_url': build_url
                }
        
        await self.set('roster_data', cache_key, members_data, ttl=600)
        
        if query_time > 0.1:  # Log slow queries
            logging.warning(f"[Cache] Slow bulk guild members query: {query_time:.3f}s, {len(members_data)} members")
        
        return members_data
    
    async def get_cached_guild_roles(self, guild_id: int, force_refresh: bool = False) -> Dict[int, Any]:
        """Récupère les rôles d'une guilde avec cache."""
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
        await self.set('discord_entities', cache_key, roles_dict, ttl=300)
        
        return roles_dict
    
    async def get_role_members_optimized(self, guild_id: int, role_id: int) -> Set[int]:
        """Récupère les membres d'un rôle de manière optimisée."""
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
        await self.set('discord_entities', cache_key, member_ids, ttl=120)  # 2 minutes
        
        return member_ids
    
    async def _smart_maintenance(self):
        """Maintenance intelligente du cache avec prédictions et préchargement."""
        try:
            # Identify entries that should be preloaded
            for key, entry in list(self._cache.items()):
                if entry.should_preload() and key not in self._preload_tasks:
                    await self._schedule_preload(key, entry)
            
            # Update hot keys
            await self._update_hot_keys()
            
            # Optimize for active guilds if bot is available
            if self.bot:
                await self._optimize_active_guilds()
                
        except Exception as e:
            logging.error(f"[Cache] Smart maintenance error: {e}")
    
    async def _schedule_preload(self, key: str, entry: CacheEntry):
        """Planifie le préchargement d'une entrée."""
        async def preload_task():
            try:
                # Wait until close to expiration
                if entry.predicted_next_access:
                    delay = entry.predicted_next_access - time.time() - (entry.ttl * 0.1)
                    if delay > 0:
                        await asyncio.sleep(delay)
                
                # Attempt to preload
                if await self._preload_entry(key, entry):
                    self._metrics['preloads_successful'] += 1
                else:
                    self._metrics['preloads_wasted'] += 1
                    
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logging.error(f"[Cache] Preload error for {key}: {e}")
            finally:
                if key in self._preload_tasks:
                    del self._preload_tasks[key]
        
        self._preload_tasks[key] = asyncio.create_task(preload_task())
    
    async def _preload_entry(self, key: str, entry: CacheEntry) -> bool:
        """Précharge une entrée spécifique."""
        try:
            category = entry.category
            
            if key.startswith('bulk_guild_members_'):
                guild_id = int(key.split('_')[-1])
                data = await self.get_bulk_guild_members(guild_id, force_refresh=True)
                return data is not None
            
            elif key.startswith('guild_roles_'):
                guild_id = int(key.split('_')[-1])
                data = await self.get_cached_guild_roles(guild_id, force_refresh=True)
                return data is not None
                
            return False
            
        except Exception as e:
            logging.debug(f"[Cache] Failed to preload {key}: {e}")
            return False
    
    async def _update_hot_keys(self):
        """Met à jour la liste des clés chaudes."""
        # Get keys with high access counts
        hot_candidates = []
        for key, entry in self._cache.items():
            if entry.access_count > 3:  # Minimum threshold
                hot_candidates.append((key, entry.access_count, entry.get_age()))
        
        # Sort by access frequency and recency
        hot_candidates.sort(key=lambda x: (x[1] / max(x[2], 1)), reverse=True)
        
        # Keep top hot keys
        self._hot_keys = {key for key, _, _ in hot_candidates[:50]}
    
    async def _optimize_active_guilds(self):
        """Optimise le cache pour les guildes les plus actives."""
        if not self.bot:
            return
        
        # Analyze guild activity from cache access patterns
        guild_activity = Counter()
        current_time = time.time()
        
        for key, entry in self._cache.items():
            if '_' in key and entry.last_accessed > current_time - 3600:  # Last hour
                parts = key.split('_')
                if len(parts) >= 2 and parts[-1].isdigit():
                    guild_id = int(parts[-1])
                    guild_activity[guild_id] += entry.access_count
        
        # Preload data for top 3 most active guilds
        for guild_id, activity in guild_activity.most_common(3):
            await self._preload_guild_data(guild_id)
    
    async def _preload_guild_data(self, guild_id: int):
        """Précharge les données couramment utilisées d'une guilde."""
        preload_tasks = []
        
        # Common data patterns to preload
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
        """Retourne les statistiques du cache intelligent."""
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
            **self._metrics
        }

# #################################################################################### #
#                            Global Cache Instance and Utilities
# #################################################################################### #
_global_cache = None

def get_global_cache(bot=None) -> GlobalCacheSystem:
    """Get the global cache instance."""
    global _global_cache
    if _global_cache is None:
        _global_cache = GlobalCacheSystem(bot)
        setup_invalidation_rules(_global_cache)
    elif bot and not _global_cache.bot:
        _global_cache.bot = bot  # Set bot reference if not already set
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
                await asyncio.sleep(300)
                await cache.cleanup_expired()
                await cache._smart_maintenance()
            except Exception as e:
                logging.error(f"[Cache] Maintenance task error: {e}")
    
    asyncio.create_task(maintenance_loop())
    logging.info("[Cache] Cache maintenance task started")