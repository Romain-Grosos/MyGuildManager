"""
Reliability and Resilience System - Comprehensive failure handling and recovery mechanisms.
"""

import asyncio
import logging
import time
import json
import os
from typing import Dict, Any, Optional, Callable, List, Union
from collections import defaultdict, deque
from datetime import datetime, timedelta
from functools import wraps
import discord
from discord.ext import commands

class ServiceCircuitBreaker:
    """Circuit breaker for external services (Discord API, webhooks, etc.)."""
    
    def __init__(self, service_name: str, failure_threshold: int = 5, timeout: int = 60, half_open_max_calls: int = 3):
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.half_open_max_calls = half_open_max_calls
        
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0
        self.state = "CLOSED"
        self.half_open_calls = 0
        
    def is_open(self) -> bool:
        """Check if circuit breaker is open."""
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.timeout:
                self.state = "HALF_OPEN"
                self.half_open_calls = 0
                logging.info(f"[CircuitBreaker] {self.service_name} entering HALF_OPEN state")
                return False
            return True
        return False
    
    def can_execute(self) -> bool:
        """Check if operation can be executed."""
        if self.state == "OPEN":
            return not self.is_open()
        elif self.state == "HALF_OPEN":
            return self.half_open_calls < self.half_open_max_calls
        return True
    
    def record_success(self):
        """Record successful operation."""
        if self.state == "HALF_OPEN":
            self.success_count += 1
            if self.success_count >= self.half_open_max_calls:
                self.state = "CLOSED"
                self.failure_count = 0
                self.success_count = 0
                logging.info(f"[CircuitBreaker] {self.service_name} CLOSED - service recovered")
        else:
            self.failure_count = max(0, self.failure_count - 1)
    
    def record_failure(self):
        """Record failed operation."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.state == "HALF_OPEN":
            self.state = "OPEN"
            logging.warning(f"[CircuitBreaker] {self.service_name} OPEN - half-open test failed")
        elif self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logging.warning(f"[CircuitBreaker] {self.service_name} OPEN - failure threshold reached ({self.failure_count})")
        
        if self.state == "HALF_OPEN":
            self.half_open_calls += 1
    
    def get_status(self) -> Dict[str, Any]:
        """Get circuit breaker status."""
        return {
            'service': self.service_name,
            'state': self.state,
            'failure_count': self.failure_count,
            'last_failure': datetime.fromtimestamp(self.last_failure_time) if self.last_failure_time else None,
            'next_retry': datetime.fromtimestamp(self.last_failure_time + self.timeout) if self.state == "OPEN" else None
        }

class RetryManager:
    """Advanced retry mechanism with exponential backoff and jitter."""
    
    @staticmethod
    async def retry_with_backoff(
        func: Callable,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retry_on: tuple = (Exception,),
        exclude_on: tuple = (),
        on_retry: Optional[Callable] = None
    ):
        """Execute function with exponential backoff retry."""
        import random
        
        last_exception = None
        
        for attempt in range(max_attempts):
            try:
                result = await func() if asyncio.iscoroutinefunction(func) else func()
                return result
                
            except exclude_on:
                raise
            except retry_on as e:
                last_exception = e
                
                if attempt == max_attempts - 1:
                    raise
                
                delay = min(base_delay * (exponential_base ** attempt), max_delay)
                if jitter:
                    delay *= (0.5 + random.random() * 0.5)
                
                if on_retry:
                    await on_retry(attempt + 1, e, delay)
                
                logging.debug(f"[RetryManager] Attempt {attempt + 1} failed, retrying in {delay:.2f}s: {e}")
                await asyncio.sleep(delay)
        
        raise last_exception

class GracefulDegradation:
    """System for graceful service degradation during failures."""
    
    def __init__(self):
        self.degraded_services: Dict[str, Dict[str, Any]] = {}
        self.fallback_handlers: Dict[str, Callable] = {}
        
    def register_fallback(self, service_name: str, fallback_handler: Callable):
        """Register fallback handler for a service."""
        self.fallback_handlers[service_name] = fallback_handler
        
    def degrade_service(self, service_name: str, reason: str, duration: int = 300):
        """Mark service as degraded."""
        self.degraded_services[service_name] = {
            'reason': reason,
            'degraded_at': time.time(),
            'duration': duration,
            'expires_at': time.time() + duration
        }
        logging.warning(f"[GracefulDegradation] Service {service_name} degraded: {reason}")
    
    def restore_service(self, service_name: str):
        """Restore service from degraded state."""
        if service_name in self.degraded_services:
            del self.degraded_services[service_name]
            logging.info(f"[GracefulDegradation] Service {service_name} restored")
    
    def is_degraded(self, service_name: str) -> bool:
        """Check if service is currently degraded."""
        if service_name not in self.degraded_services:
            return False
        
        degraded_info = self.degraded_services[service_name]
        if time.time() > degraded_info['expires_at']:
            self.restore_service(service_name)
            return False
        
        return True
    
    async def execute_with_fallback(self, service_name: str, primary_func: Callable, *args, **kwargs):
        """Execute function with fallback if service is degraded."""
        if self.is_degraded(service_name) and service_name in self.fallback_handlers:
            logging.info(f"[GracefulDegradation] Using fallback for {service_name}")
            return await self.fallback_handlers[service_name](*args, **kwargs)
        
        try:
            if asyncio.iscoroutinefunction(primary_func):
                result = await primary_func(*args, **kwargs)
            else:
                result = primary_func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
            return result
        except Exception as e:
            if service_name in self.fallback_handlers:
                logging.warning(f"[GracefulDegradation] Primary function failed, using fallback for {service_name}: {e}")
                self.degrade_service(service_name, str(e))
                return await self.fallback_handlers[service_name](*args, **kwargs)
            raise

class DataBackupManager:
    """Automated backup and recovery system for critical data."""
    
    def __init__(self, backup_dir: str = "backups"):
        self.backup_dir = backup_dir
        self.ensure_backup_dir()
        
    def ensure_backup_dir(self):
        """Ensure backup directory exists."""
        os.makedirs(self.backup_dir, exist_ok=True)
        
    async def backup_guild_data(self, bot, guild_id: int) -> str:
        """Create backup of all guild data."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(self.backup_dir, f"guild_{guild_id}_{timestamp}.json")
        
        try:
            guild_data = {}
            
            settings_query = "SELECT * FROM guild_settings WHERE guild_id = %s"
            settings = await bot.run_db_query(settings_query, (guild_id,), fetch_one=True)
            if settings:
                guild_data['settings'] = dict(zip([
                    'guild_id', 'guild_name', 'guild_lang', 'guild_game', 
                    'guild_server', 'initialized', 'premium'
                ], settings))
            
            members_query = "SELECT * FROM guild_members WHERE guild_id = %s"
            members = await bot.run_db_query(members_query, (guild_id,), fetch_all=True)
            guild_data['members'] = [dict(zip([
                'guild_id', 'member_id', 'username', 'language', 'GS', 'build',
                'weapons', 'DKP', 'nb_events', 'registrations', 'attendances', 'class'
            ], member)) for member in (members or [])]
            
            roles_query = "SELECT * FROM guild_roles WHERE guild_id = %s"
            roles = await bot.run_db_query(roles_query, (guild_id,), fetch_all=True)
            guild_data['roles'] = [dict(zip([
                'guild_id', 'role_name', 'role_id', 'role_type'
            ], role)) for role in (roles or [])]
            
            channels_query = "SELECT * FROM guild_channels WHERE guild_id = %s"
            channels = await bot.run_db_query(channels_query, (guild_id,), fetch_all=True)
            guild_data['channels'] = [dict(zip([
                'guild_id', 'channel_name', 'channel_id', 'channel_type', 'category_id'
            ], channel)) for channel in (channels or [])]
            
            events_query = "SELECT * FROM events_data WHERE guild_id = %s"
            events = await bot.run_db_query(events_query, (guild_id,), fetch_all=True)
            guild_data['events'] = [dict(zip([
                'guild_id', 'event_id', 'event_name', 'event_date', 'status',
                'event_type', 'members_role_id', 'registrations', 'attendances', 'groups_data'
            ], event)) for event in (events or [])]
            
            guild_data['backup_timestamp'] = timestamp
            guild_data['backup_version'] = '1.0'
            
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(guild_data, f, indent=2, ensure_ascii=False, default=str)
            
            logging.info(f"[DataBackup] Guild {guild_id} data backed up to {backup_file}")
            return backup_file
            
        except Exception as e:
            logging.error(f"[DataBackup] Failed to backup guild {guild_id}: {e}")
            raise
    
    async def restore_guild_data(self, bot, guild_id: int, backup_file: str) -> bool:
        """Restore guild data from backup."""
        try:
            if not os.path.exists(backup_file):
                logging.error(f"[DataBackup] Backup file not found: {backup_file}")
                return False
            
            with open(backup_file, 'r', encoding='utf-8') as f:
                guild_data = json.load(f)
            
            transaction_queries = []
            
            if 'settings' in guild_data:
                settings = guild_data['settings']
                transaction_queries.append((
                    "INSERT INTO guild_settings (guild_id, guild_name, guild_lang, guild_game, guild_server, initialized, premium) VALUES (%s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE guild_name=VALUES(guild_name), guild_lang=VALUES(guild_lang), guild_game=VALUES(guild_game), guild_server=VALUES(guild_server), premium=VALUES(premium)",
                    (settings['guild_id'], settings['guild_name'], settings['guild_lang'], settings['guild_game'], settings['guild_server'], settings['initialized'], settings['premium'])
                ))
            
            for member in guild_data.get('members', []):
                transaction_queries.append((
                    "INSERT INTO guild_members (guild_id, member_id, username, language, GS, build, weapons, DKP, nb_events, registrations, attendances, class) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE username=VALUES(username), language=VALUES(language), GS=VALUES(GS), build=VALUES(build), weapons=VALUES(weapons), DKP=VALUES(DKP), nb_events=VALUES(nb_events), registrations=VALUES(registrations), attendances=VALUES(attendances), class=VALUES(class)",
                    (member['guild_id'], member['member_id'], member['username'], member['language'], member['GS'], member['build'], member['weapons'], member['DKP'], member['nb_events'], member['registrations'], member['attendances'], member['class'])
                ))
            
            success = await bot.run_db_transaction(transaction_queries)
            
            if success:
                logging.info(f"[DataBackup] Guild {guild_id} data restored from {backup_file}")
                return True
            else:
                logging.error(f"[DataBackup] Failed to restore guild {guild_id} - transaction failed")
                return False
                
        except Exception as e:
            logging.error(f"[DataBackup] Failed to restore guild {guild_id}: {e}")
            return False
    
    def list_backups(self, guild_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """List available backups."""
        backups = []
        pattern = f"guild_{guild_id}_" if guild_id else "guild_"
        
        for filename in os.listdir(self.backup_dir):
            if filename.startswith(pattern) and filename.endswith('.json'):
                filepath = os.path.join(self.backup_dir, filename)
                stat = os.stat(filepath)
                
                parts = filename.replace('.json', '').split('_')
                if len(parts) >= 3:
                    backups.append({
                        'filename': filename,
                        'filepath': filepath,
                        'guild_id': int(parts[1]),
                        'timestamp': parts[2],
                        'size': stat.st_size,
                        'created': datetime.fromtimestamp(stat.st_ctime)
                    })
        
        return sorted(backups, key=lambda x: x['created'], reverse=True)

class ReliabilitySystem:
    """Main reliability and resilience system coordinator."""
    
    def __init__(self, bot):
        self.bot = bot
        self.circuit_breakers: Dict[str, ServiceCircuitBreaker] = {}
        self.retry_manager = RetryManager()
        self.graceful_degradation = GracefulDegradation()
        self.backup_manager = DataBackupManager()
        self.health_checks: Dict[str, Callable] = {}
        self.failure_counts: Dict[str, int] = defaultdict(int)
        
        self._setup_circuit_breakers()
        self._setup_fallback_handlers()
    
    def _setup_circuit_breakers(self):
        """Setup circuit breakers for various services."""
        self.circuit_breakers['discord_api'] = ServiceCircuitBreaker('discord_api', failure_threshold=5, timeout=120)
        self.circuit_breakers['database'] = ServiceCircuitBreaker('database', failure_threshold=3, timeout=60)
        self.circuit_breakers['scheduler'] = ServiceCircuitBreaker('scheduler', failure_threshold=3, timeout=180)
        self.circuit_breakers['cache'] = ServiceCircuitBreaker('cache', failure_threshold=10, timeout=30)
    
    def _setup_fallback_handlers(self):
        """Setup fallback handlers for graceful degradation."""
        self.graceful_degradation.register_fallback('member_fetch', self._fallback_member_fetch)
        self.graceful_degradation.register_fallback('role_assignment', self._fallback_role_assignment)
        self.graceful_degradation.register_fallback('channel_creation', self._fallback_channel_creation)
    
    async def _fallback_member_fetch(self, guild_id: int, member_id: int):
        """Fallback for member fetching when Discord API is degraded."""
        if hasattr(self.bot, 'cache'):
            cached_data = await self.bot.cache.get('roster_data', f'bulk_guild_members_{guild_id}')
            if cached_data and member_id in cached_data:
                return cached_data[member_id]
        return None
    
    async def _fallback_role_assignment(self, guild_id: int, member_id: int, role_id: int):
        """Fallback for role assignment - queue for later processing."""
        logging.info(f"[ReliabilitySystem] Queuing role assignment for later: guild={guild_id}, member={member_id}, role={role_id}")
        return False
    
    async def _fallback_channel_creation(self, guild_id: int, channel_name: str, channel_type: str):
        """Fallback for channel creation - return None and log for manual intervention."""
        logging.warning(f"[ReliabilitySystem] Channel creation failed, manual intervention required: guild={guild_id}, name={channel_name}")
        return None
    
    def get_circuit_breaker(self, service_name: str) -> Optional[ServiceCircuitBreaker]:
        """Get circuit breaker for service."""
        return self.circuit_breakers.get(service_name)
    
    async def execute_with_reliability(self, service_name: str, func: Callable, *args, **kwargs):
        """Execute function with full reliability features."""
        circuit_breaker = self.get_circuit_breaker(service_name)
        
        if circuit_breaker and not circuit_breaker.can_execute():
            raise Exception(f"Service {service_name} circuit breaker is open")
        
        async def monitored_execution():
            try:
                result = await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)
                if circuit_breaker:
                    circuit_breaker.record_success()
                self.failure_counts[service_name] = 0
                return result
            except Exception as e:
                if circuit_breaker:
                    circuit_breaker.record_failure()
                self.failure_counts[service_name] += 1
                raise
        
        return await self.graceful_degradation.execute_with_fallback(
            service_name, 
            lambda: self.retry_manager.retry_with_backoff(monitored_execution, max_attempts=3),
            *args, **kwargs
        )
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get overall system reliability status."""
        return {
            'circuit_breakers': {name: cb.get_status() for name, cb in self.circuit_breakers.items()},
            'degraded_services': list(self.graceful_degradation.degraded_services.keys()),
            'failure_counts': dict(self.failure_counts),
            'backup_count': len(self.backup_manager.list_backups()),
            'timestamp': datetime.now().isoformat()
        }

def discord_resilient(service_name: str = 'discord_api', max_retries: int = 3):
    """Decorator for Discord API operations with full resilience."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            bot = None
            for arg in args:
                if hasattr(arg, 'bot'):
                    bot = arg.bot
                    break
                elif hasattr(arg, '_bot'):
                    bot = arg._bot
                    break
            
            if not bot or not hasattr(bot, 'reliability_system'):
                return await func(*args, **kwargs)
            
            reliability_system = bot.reliability_system
            
            async def execute():
                try:
                    return await func(*args, **kwargs)
                except discord.Forbidden as e:
                    logging.warning(f"[DiscordResilience] Permission denied in {func.__name__}: {e}")
                    raise
                except discord.NotFound as e:
                    logging.warning(f"[DiscordResilience] Resource not found in {func.__name__}: {e}")
                    raise
                except discord.HTTPException as e:
                    if e.status == 429:
                        logging.warning(f"[DiscordResilience] Rate limited in {func.__name__}, retrying...")
                        await asyncio.sleep(e.retry_after if hasattr(e, 'retry_after') else 5)
                    raise
            
            return await reliability_system.execute_with_reliability(service_name, execute)
        
        return wrapper
    return decorator

def setup_reliability_system(bot):
    """Setup reliability system for the bot."""
    if not hasattr(bot, 'reliability_system'):
        bot.reliability_system = ReliabilitySystem(bot)
    return bot.reliability_system