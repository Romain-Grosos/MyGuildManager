"""
Guild Members Cog - Enterprise-grade guild member profile management and roster operations.

This cog provides comprehensive member management with:

CORE FEATURES:
- Member profile management (GS, weapons, builds, usernames)
- Automated roster updates with bulk operations
- Class detection and validation based on weapon combinations
- Multi-language support with fallback mechanisms
- Build URL validation and sanitization

ROSTER MANAGEMENT:
- Real-time roster synchronization with database persistence
- Bulk member operations with transaction safety
- Ideal staff calculation and distribution optimization
- Recruitment message automation with dynamic updates
- Member notification system for incomplete profiles

PERFORMANCE OPTIMIZATIONS:
- Memory-efficient caching with TTL and invalidation
- Batch database operations with executemany patterns
- Async processing for concurrent guild operations
- Rate limiting and abuse prevention mechanisms
- Smart data validation with defensive programming

SECURITY FEATURES:
- Input validation and sanitization for all user data
- Build URL domain whitelist enforcement
- Permission checks before sensitive operations
- SQL injection prevention through parameterized queries
- Comprehensive error handling with structured logging

DATABASE OPERATIONS:
- Transaction-safe bulk updates with rollback capability
- Optimized queries with proper indexing strategies
- Cache invalidation patterns for data consistency
- Connection pooling and circuit breaker integration

RECOMMENDED DATABASE INDEXES:
-- Core performance indexes for guild member operations
CREATE INDEX idx_guild_members_guild_id ON guild_members(guild_id);
CREATE INDEX idx_user_setup_guild_user ON user_setup(guild_id, user_id);
CREATE UNIQUE INDEX idx_guild_ideal_staff_unique ON guild_ideal_staff(guild_id, class_name);
-- Primary/Unique keys:
-- guild_members: (guild_id, member_id) as PK/UK for fast lookups
-- These indexes support bulk scans, member lookups, and staff configuration queries
"""

import asyncio
import re
import time
import unicodedata
from datetime import datetime
from typing import Dict, List, Tuple, Any, Optional, Union, TypedDict, cast, Protocol
from urllib.parse import urlparse

try:
    from wcwidth import wcswidth
    HAS_WCWIDTH = True
except ImportError:
    HAS_WCWIDTH = False

import discord
from discord.ext import commands

from app.core.functions import get_user_message
from app.core.logger import ComponentLogger
from app.core.performance_profiler import profile_performance
from app.core.rate_limiter import admin_rate_limit
from app.core.reliability import discord_resilient
from app.core.translation import translations as global_translations
from app.db import run_db_transaction

ABSENCE_TRANSLATIONS = global_translations.get("absence_system", {}).get("messages", {})
GUILD_MEMBERS = global_translations.get("member_management", {})

_logger = ComponentLogger("guild_members")

_DANGEROUS_CHARS = re.compile(r'[<>";\\\x00-\x1f\x7f]')
DEFAULT_MAX_USERNAME_LENGTH = 32
DEFAULT_MAX_GS_VALUE = 9999
DEFAULT_MIN_GS_VALUE = 500
DEFAULT_ALLOWED_BUILD_DOMAINS = ["questlog.gg", "maxroll.gg"]
DEFAULT_CACHE_TTL_SECONDS = 300
DEFAULT_BULK_OPERATION_CHUNK_SIZE = 100

def _pad_cell(s: str, width: int) -> str:
    """Pad cell text accounting for Unicode display width."""
    s = s or ""
    if HAS_WCWIDTH:
        vis = wcswidth(s)
        if vis is None or vis < 0:
            s = "".join(ch for ch in s if wcswidth(ch, 0) > 0)
            vis = wcswidth(s) or 0
        pad = max(0, width - vis)
        return s + (" " * pad)
    else:
        return s.ljust(width)

def _center_cell(s: str, width: int) -> str:
    """Center cell text accounting for Unicode display width."""
    s = s or ""
    if HAS_WCWIDTH:
        vis = wcswidth(s)
        if vis is None or vis < 0:
            s = "".join(ch for ch in s if wcswidth(ch, 0) > 0)
            vis = wcswidth(s) or 0
        pad = max(0, width - vis)
        left_pad = pad // 2
        right_pad = pad - left_pad
        return (" " * left_pad) + s + (" " * right_pad)
    else:
        return s.center(width)

def _mono_sanitize(s: str) -> str:
    """Sanitize string for monospace display in Discord code blocks."""
    s = s.replace("`", "´")
    s = s.replace("|", "¦")
    return s

class CacheProto(Protocol):
    """Protocol for bot cache interface."""
    async def get(self, category: str, key: str) -> Any: ...
    async def set(self, category: str, value: Any, key: str) -> None: ...
    async def get_guild_data(self, gid: int, key: str) -> Any: ...
    async def set_guild_data(self, gid: int, key: str, value: Any) -> None: ...
    async def invalidate_category(self, category: str) -> None: ...

class BotProto(Protocol):
    """Protocol for bot interface."""
    cache: CacheProto
    cache_loader: Any
    async def run_db_query(self, q: str, params=(), fetch_all=False, commit=False) -> Any: ...

class MemberData(TypedDict):
    """Type definition for guild member data structure."""
    member_id: int
    username: str
    language: str
    GS: int
    build: Optional[str]
    weapons: Optional[str]
    DKP: int
    nb_events: int
    registrations: int
    attendances: int
    class_member: Optional[str]

class WeaponCombination(TypedDict):
    """Type definition for weapon combination data."""
    weapon1: str
    weapon2: str
    class_name: str

class RosterChange(TypedDict):
    """Type definition for roster update change."""
    member_id: int
    field: str
    old_value: Any
    new_value: Any
    change_type: str

class UserSetupData(TypedDict):
    """Type definition for user setup data from database."""
    username: str
    locale: str
    gs: int
    weapons: str

class MemberFieldUpdate(TypedDict, total=False):
    """Type definition for member field updates in UPSERT operations."""
    GS: int
    weapons: str
    class_member: Optional[str]
    build: str
    username: str

class GuildMemberConfig(TypedDict):
    """Type definition for guild-specific member configuration."""
    max_username_length: int
    max_gs_value: int
    min_gs_value: int
    allowed_build_domains: List[str]
    cache_ttl_seconds: int
    bulk_operation_chunk_size: int

class GuildStats(TypedDict):
    """Type definition for guild statistics."""
    total_members: int
    complete_profiles: int
    incomplete_profiles: int
    average_gs: float
    class_distribution: Dict[str, int]


class GuildMembers(commands.Cog):
    """Cog for managing guild member profiles, roster updates, and member data."""

    @staticmethod
    def _normalize_domains(domains: List[str]) -> List[str]:
        """
        Normalize domain list to ensure consistent security validation.
        
        Args:
            domains: List of domain names to normalize
            
        Returns:
            List of normalized domain names (lowercase, no www. prefix)
        """
        normalized = []
        for domain in domains:
            if not domain or not isinstance(domain, str):
                continue
            raw = domain.strip().lower()
            try:
                parsed = urlparse(raw if "://" in raw else f"https://{raw}")
                candidate = (parsed.hostname or raw).strip(".")
            except Exception:
                candidate = raw.strip(".")
            if candidate.startswith("www."):
                candidate = candidate[4:]
            try:
                candidate = candidate.encode("idna").decode("ascii")
            except Exception:
                pass
            if candidate:
                normalized.append(candidate)
        normalized = list(dict.fromkeys(normalized))
        return normalized

    @staticmethod
    def t(dic: dict, path: str, locale: str, default: str = "") -> str:
        """
        Safe translation helper with fallback chain.
        
        Navigates nested dict paths safely and provides locale fallback:
        locale → en-US → default value
        
        Args:
            dic: Translation dictionary to navigate
            path: Dot-separated path (e.g., "post_recruitment.name")
            locale: Target locale (e.g., "fr-FR")
            default: Default value if all lookups fail
            
        Returns:
            Translated string with fallback safety
        """
        node = dic
        for key in path.split("."):
            if not isinstance(node, dict):
                return default
            node = node.get(key, {})
            
        if isinstance(node, dict):
            return node.get(locale) or node.get("en-US") or default

        return node if isinstance(node, str) else default

    @staticmethod
    def safe_percentage(numerator: Union[int, float], denominator: Union[int, float], precision: int = 0, clamp: bool = True) -> Union[int, float]:
        """
        Calculate percentage with guardrails to prevent overflow and invalid values.
        
        Handles edge cases:
        - Division by zero → 0%
        - Negative values → 0% 
        - Overflow (numerator > denominator) → clamped to 100% if clamp=True
        - Invalid inputs → 0%
        
        Args:
            numerator: The numerator value
            denominator: The denominator value  
            precision: Decimal places for rounding (0 for int, >0 for float)
            clamp: If True (default), clamp to [0, 100] range. If False, allow >100% for anomaly detection
            
        Returns:
            Safe percentage, optionally clamped to [0, 100] range
        """
        try:
            if not isinstance(numerator, (int, float)) or not isinstance(denominator, (int, float)):
                return 0 if precision == 0 else 0.0
                
            if denominator <= 0 or numerator < 0:
                return 0 if precision == 0 else 0.0

            percentage = (numerator / denominator) * 100

            if clamp:
                percentage = max(0, min(100, percentage))
            else:
                percentage = max(0, percentage)

            if precision == 0:
                return round(percentage)
            else:
                return round(percentage, precision)
                
        except (ZeroDivisionError, OverflowError, ValueError):
            return 0 if precision == 0 else 0.0

    def __init__(self, bot: BotProto) -> None:
        """
        Initialize the GuildMembers cog with enterprise-grade configuration.

        Args:
            bot: The Discord bot instance
        """
        self.bot = bot

        self._default_config: GuildMemberConfig = {
            "max_username_length": DEFAULT_MAX_USERNAME_LENGTH,
            "max_gs_value": DEFAULT_MAX_GS_VALUE,
            "min_gs_value": DEFAULT_MIN_GS_VALUE,
            "allowed_build_domains": DEFAULT_ALLOWED_BUILD_DOMAINS.copy(),
            "cache_ttl_seconds": DEFAULT_CACHE_TTL_SECONDS,
            "bulk_operation_chunk_size": DEFAULT_BULK_OPERATION_CHUNK_SIZE,
        }

        self.allowed_build_domains = self._normalize_domains(self._default_config["allowed_build_domains"])
        self.max_username_length = self._default_config["max_username_length"]
        self.max_gs_value = self._default_config["max_gs_value"]
        self.min_gs_value = self._default_config["min_gs_value"]

        self._member_cache: Dict[str, Tuple[Any, float]] = {}
        self._cache_ttl = self._default_config["cache_ttl_seconds"]
        self._last_cache_cleanup = time.time()

        self._register_member_commands()
        self._register_staff_commands()

        _logger.info("guild_members_cog_initialized")

    def _register_member_commands(self):
        """Register member commands with the centralized member group."""
        if hasattr(self.bot, "member_group"):

            self.bot.member_group.command(
                name=GUILD_MEMBERS.get("gs", {}).get("name", {}).get("en-US", "gs"),
                description=GUILD_MEMBERS.get("gs", {})
                .get("description", {})
                .get("en-US", "Update your gear score (GS)"),
                name_localizations=GUILD_MEMBERS.get("gs", {}).get("name", {}),
                description_localizations=GUILD_MEMBERS.get("gs", {}).get(
                    "description", {}
                ),
            )(self.gs)

            self.bot.member_group.command(
                name=GUILD_MEMBERS.get("weapons", {})
                .get("name", {})
                .get("en-US", "weapons"),
                description=GUILD_MEMBERS.get("weapons", {})
                .get("description", {})
                .get("en-US", "Update your weapon combination"),
                name_localizations=GUILD_MEMBERS.get("weapons", {}).get("name", {}),
                description_localizations=GUILD_MEMBERS.get("weapons", {}).get(
                    "description", {}
                ),
            )(self.weapons)

            self.bot.member_group.command(
                name=GUILD_MEMBERS.get("build", {})
                .get("name", {})
                .get("en-US", "build"),
                description=GUILD_MEMBERS.get("build", {})
                .get("description", {})
                .get("en-US", "Update your build URL"),
                name_localizations=GUILD_MEMBERS.get("build", {}).get("name", {}),
                description_localizations=GUILD_MEMBERS.get("build", {}).get(
                    "description", {}
                ),
            )(self.build)

            self.bot.member_group.command(
                name=GUILD_MEMBERS.get("username", {})
                .get("name", {})
                .get("en-US", "username"),
                description=GUILD_MEMBERS.get("username", {})
                .get("description", {})
                .get("en-US", "Update your username"),
                name_localizations=GUILD_MEMBERS.get("username", {}).get("name", {}),
                description_localizations=GUILD_MEMBERS.get("username", {}).get(
                    "description", {}
                ),
            )(self.username)

            self.bot.member_group.command(
                name=GUILD_MEMBERS.get("show_build", {})
                .get("name", {})
                .get("en-US", "show_build"),
                description=GUILD_MEMBERS.get("show_build", {})
                .get("description", {})
                .get("en-US", "Show another member's build"),
                name_localizations=GUILD_MEMBERS.get("show_build", {}).get("name", {}),
                description_localizations=GUILD_MEMBERS.get("show_build", {}).get(
                    "description", {}
                ),
            )(self.show_build)

            self.bot.member_group.command(
                name=GUILD_MEMBERS.get("change_language", {})
                .get("name", {})
                .get("en-US", "change_language"),
                description=GUILD_MEMBERS.get("change_language", {})
                .get("description", {})
                .get("en-US", "Change your preferred language"),
                name_localizations=GUILD_MEMBERS.get("change_language", {}).get(
                    "name", {}
                ),
                description_localizations=GUILD_MEMBERS.get("change_language", {}).get(
                    "description", {}
                ),
            )(self.change_language)

            self.bot.member_group.command(
                name=ABSENCE_TRANSLATIONS.get("return", {})
                .get("name", {})
                .get("en-US", "return"),
                description=ABSENCE_TRANSLATIONS.get("return", {})
                .get("description", {})
                .get("en-US", "Signal your return from absence"),
                name_localizations=ABSENCE_TRANSLATIONS.get("return", {}).get(
                    "name", {}
                ),
                description_localizations=ABSENCE_TRANSLATIONS.get("return", {}).get(
                    "description", {}
                ),
            )(self.member_return)

    def _register_staff_commands(self):
        """Register staff commands with the centralized staff group."""
        if hasattr(self.bot, "staff_group"):

            self.bot.staff_group.command(
                name=GUILD_MEMBERS.get("maj_roster", {})
                .get("name", {})
                .get("en-US", "maj_roster"),
                description=GUILD_MEMBERS.get("maj_roster", {})
                .get("description", {})
                .get("en-US", "Update guild roster"),
                name_localizations=GUILD_MEMBERS.get("maj_roster", {}).get("name", {}),
                description_localizations=GUILD_MEMBERS.get("maj_roster", {}).get(
                    "description", {}
                ),
                default_member_permissions=discord.Permissions(manage_guild=True)
            )(self.maj_roster)

            self.bot.staff_group.command(
                name=GUILD_MEMBERS.get("notify_profile", {})
                .get("name", {})
                .get("en-US", "notify_profile"),
                description=GUILD_MEMBERS.get("notify_profile", {})
                .get("description", {})
                .get("en-US", "Notify members with incomplete profiles"),
                name_localizations=GUILD_MEMBERS.get("notify_profile", {}).get(
                    "name", {}
                ),
                description_localizations=GUILD_MEMBERS.get("notify_profile", {}).get(
                    "description", {}
                ),
                default_member_permissions=discord.Permissions(manage_guild=True)
            )(self.notify_incomplete_profiles)

            self.bot.staff_group.command(
                name=GUILD_MEMBERS.get("config_roster", {})
                .get("name", {})
                .get("en-US", "config_roster"),
                description=GUILD_MEMBERS.get("config_roster", {})
                .get("description", {})
                .get("en-US", "Configure ideal roster sizes"),
                name_localizations=GUILD_MEMBERS.get("config_roster", {}).get(
                    "name", {}
                ),
                description_localizations=GUILD_MEMBERS.get("config_roster", {}).get(
                    "description", {}
                ),
                default_member_permissions=discord.Permissions(manage_guild=True)
            )(self.config_roster)

    def _get_cached_data(self, cache_key: str) -> Optional[Any]:
        """
        Get data from TTL cache if not expired.
        
        Args:
            cache_key: Unique cache key
            
        Returns:
            Cached data if not expired, None otherwise
        """
        if cache_key in self._member_cache:
            data, timestamp = self._member_cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                _logger.debug("cache_hit", cache_key=cache_key)
                return data
            else:
                del self._member_cache[cache_key]
                _logger.debug("cache_expired", cache_key=cache_key)
        return None

    def _set_cached_data(self, cache_key: str, data: Any) -> None:
        """
        Store data in TTL cache with current timestamp.
        
        Args:
            cache_key: Unique cache key
            data: Data to cache
        """
        self._member_cache[cache_key] = (data, time.time())
        _logger.debug("cache_set", cache_key=cache_key)

        MAX_KEYS = 1000
        if len(self._member_cache) > MAX_KEYS:
            victims = sorted(self._member_cache.items(), key=lambda kv: kv[1][1])[:max(1, MAX_KEYS//20)]
            for k, _ in victims:
                self._member_cache.pop(k, None)

        current_time = time.time()
        if current_time - self._last_cache_cleanup > 600:
            self._cleanup_expired_cache()
            self._last_cache_cleanup = current_time

    def _cleanup_expired_cache(self) -> None:
        """
        Clean up expired cache entries to prevent memory leaks.
        """
        current_time = time.time()
        expired_keys = [
            key for key, (_, timestamp) in self._member_cache.items()
            if current_time - timestamp >= self._cache_ttl
        ]
        
        for key in expired_keys:
            del self._member_cache[key]
            
        if expired_keys:
            _logger.debug("cleaned_expired_cache_entries", count=len(expired_keys))

    def _invalidate_cache(self, pattern: Optional[str] = None) -> None:
        """
        Invalidate cache entries matching pattern or all if no pattern.
        
        Args:
            pattern: Pattern to match cache keys, None to clear all
        """
        if pattern is None:
            self._member_cache.clear()
            _logger.debug("cache_cleared_all")
        else:
            keys_to_remove = [
                key for key in self._member_cache.keys() 
                if pattern in key
            ]
            for key in keys_to_remove:
                del self._member_cache[key]
            _logger.debug("cache_invalidated", pattern=pattern, count=len(keys_to_remove))

    def _invalidate_cache_prefix(self, prefix: str) -> None:
        """
        Invalidate cache entries by exact prefix match.
        
        Args:
            prefix: Prefix to match cache keys (avoids substring surprises)
        """
        keys_to_remove = [k for k in self._member_cache.keys() if k.startswith(prefix)]
        for k in keys_to_remove:
            self._member_cache.pop(k, None)
        _logger.debug("cache_prefix_invalidated", prefix=prefix, count=len(keys_to_remove))

    def _validate_guild_id(self, guild_id: Any) -> int:
        """
        Validate guild ID parameter defensively.
        
        Args:
            guild_id: Guild ID to validate
            
        Returns:
            Validated guild ID as integer
            
        Raises:
            ValueError: If guild_id is invalid
        """
        if guild_id is None:
            raise ValueError("guild_id cannot be None")
        
        try:
            guild_id = int(guild_id)
        except (ValueError, TypeError):
            raise ValueError(f"guild_id must be a valid integer, got: {guild_id}")
        
        if guild_id <= 0:
            raise ValueError(f"guild_id must be positive, got: {guild_id}")
            
        return guild_id

    def _validate_member_id(self, member_id: Any) -> int:
        """
        Validate member ID parameter defensively.
        
        Args:
            member_id: Member ID to validate
            
        Returns:
            Validated member ID as integer
            
        Raises:
            ValueError: If member_id is invalid
        """
        if member_id is None:
            raise ValueError("member_id cannot be None")
        
        try:
            member_id = int(member_id)
        except (ValueError, TypeError):
            raise ValueError(f"member_id must be a valid integer, got: {member_id}")
        
        if member_id <= 0:
            raise ValueError(f"member_id must be positive, got: {member_id}")
            
        return member_id

    def _sanitize_string(self, text: str, max_length: int = 100) -> str:
        """
        Sanitize string input by removing dangerous characters.

        Args:
            text: The input string to sanitize
            max_length: Maximum length of the sanitized string (default: 100)

        Returns:
            Sanitized string with dangerous characters removed and length limited
        """
        if not isinstance(text, str):
            return ""
        sanitized = _DANGEROUS_CHARS.sub("", text.strip())
        return sanitized[:max_length]

    def _is_allowed_domain(self, host: str, allowed_domains: Optional[List[str]] = None) -> bool:
        """
        Check if host matches allowed domains with strict suffix matching.
        
        Args:
            host: The hostname to check
            allowed_domains: Optional list of allowed domains (defaults to instance domains)
            
        Returns:
            bool: True if host exactly matches or is a subdomain of allowed domain
        """
        if not host:
            return False
        host = host.lower().rstrip(".")
        if host.startswith("www."):
            host = host[4:]
        
        domains = self.allowed_build_domains if allowed_domains is None else self._normalize_domains(allowed_domains)
        for allowed in domains:
            if host == allowed or host.endswith("." + allowed):
                return True
        return False

    def _validate_url(self, url: str, allowed_domains: Optional[List[str]] = None) -> bool:
        """
        Validate build URL against allowed domains with strict domain matching.

        Args:
            url: The URL string to validate
            allowed_domains: Optional list of allowed domains (defaults to instance domains)

        Returns:
            True if URL is valid and from allowed domain, False otherwise
        """
        if not isinstance(url, str) or not url.strip():
            return False
        try:
            parsed = urlparse(url.strip())
            if parsed.scheme.lower() != "https":
                return False
            if parsed.port not in (None, 443):
                return False
            if parsed.username is not None or parsed.password is not None:
                return False
            hostname = parsed.hostname
            if hostname is None:
                return False
            try:
                hostname = hostname.encode("idna").decode("ascii")
            except Exception:
                return False
            return self._is_allowed_domain(hostname, allowed_domains)
        except Exception:
            return False

    def _clean_url(self, url: str) -> str:
        """
        Clean URL by removing query parameters and fragments to reduce PII leakage.
        
        Args:
            url: The URL to clean
            
        Returns:
            Cleaned URL with only scheme, host, and path
        """
        try:
            parsed = urlparse(url.strip())
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            return clean_url.rstrip('/')
        except Exception:
            return url.strip()

    def _validate_integer(
        self, value: Any, min_val: Optional[int] = None, max_val: Optional[int] = None
    ) -> Optional[int]:
        """
        Validate and convert value to integer within bounds.

        Args:
            value: The value to convert to integer
            min_val: Minimum allowed value (optional)
            max_val: Maximum allowed value (optional)

        Returns:
            Validated integer value or None if validation fails
        """
        try:
            int_val = int(value)
            if min_val is not None and int_val < min_val:
                return None
            if max_val is not None and int_val > max_val:
                return None
            return int_val
        except (ValueError, TypeError):
            return None

    def _validate_weapon_code(self, weapon: str) -> Optional[str]:
        """
        Validate and normalize weapon code.

        Args:
            weapon: The weapon code string to validate

        Returns:
            Normalized weapon code string or None if validation fails
        """
        if not isinstance(weapon, str):
            return None

        sanitized = self._sanitize_string(weapon.strip().upper(), 10)
        if not re.match(r"^[A-Z0-9_]{1,10}$", sanitized):
            return None
        return sanitized

    def _validate_language_code(self, language: str) -> bool:
        """
        Validate language code against supported locales.
        
        Args:
            language: Language code to validate
            
        Returns:
            True if language is supported, False otherwise
        """
        if not isinstance(language, str):
            return False
            
        supported_locales = global_translations.get("global", {}).get("supported_locales", ["en-US"])
        return language in supported_locales
    
    def _normalize_username(self, username: str, max_length: Optional[int] = None) -> str:
        """
        Normalize username using Unicode NFKC normalization.
        
        Args:
            username: Raw username input
            max_length: Maximum length override (defaults to instance max_username_length)
            
        Returns:
            Normalized username string
        """
        if not isinstance(username, str):
            return ""

        normalized = unicodedata.normalize('NFKC', username.strip())
        normalized = normalized.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
        
        max_len = max_length if max_length is not None else self.max_username_length
        return self._sanitize_string(normalized, max_len)

    @staticmethod
    def _truncate_embed_description(description: str, max_length: int = 4096) -> str:
        """
        Safely truncate embed description to Discord's 4096 character limit.
        
        Args:
            description: The description text to truncate
            max_length: Maximum allowed length (default: 4096 for Discord embeds)
            
        Returns:
            Truncated description with ellipsis if needed
        """
        if len(description) <= max_length:
            return description

        truncate_suffix = "...\n\n*(truncated due to length)*"
        available_length = max_length - len(truncate_suffix)
        
        if available_length <= 0:
            return "*(description too long to display)*"

        truncated = description[:available_length]
        last_newline = truncated.rfind('\n')
        
        if last_newline > available_length * 0.8:
            truncated = truncated[:last_newline]
            
        return truncated + truncate_suffix

    async def _get_guild_config(self, guild_id: int) -> GuildMemberConfig:
        """
        Load guild-specific configuration with fallback to defaults.
        
        Args:
            guild_id: Guild ID to load config for
            
        Returns:
            Guild-specific configuration with defaults as fallback
        """
        try:
            guild_settings = await self.bot.cache.get_guild_data(guild_id, "member_config")
            
            if not guild_settings:
                return self._default_config.copy()

            config: GuildMemberConfig = self._default_config.copy()

            if "max_username_length" in guild_settings:
                max_len = self._validate_integer(guild_settings["max_username_length"], 5, 100)
                if max_len:
                    config["max_username_length"] = max_len
                    
            if "max_gs_value" in guild_settings:
                max_gs = self._validate_integer(guild_settings["max_gs_value"], 1000, 20000)
                if max_gs:
                    config["max_gs_value"] = max_gs
                    
            if "min_gs_value" in guild_settings:
                min_gs = self._validate_integer(guild_settings["min_gs_value"], 100, 5000)
                if min_gs:
                    config["min_gs_value"] = min_gs
                    
            if "allowed_build_domains" in guild_settings and isinstance(guild_settings["allowed_build_domains"], list):
                domains = [d for d in guild_settings["allowed_build_domains"] if isinstance(d, str) and d.strip()]
                if domains:
                    config["allowed_build_domains"] = self._normalize_domains(domains)
                    
            if "cache_ttl_seconds" in guild_settings:
                ttl = self._validate_integer(guild_settings["cache_ttl_seconds"], 60, 3600)
                if ttl:
                    config["cache_ttl_seconds"] = ttl
                    
            if "bulk_operation_chunk_size" in guild_settings:
                chunk_size = self._validate_integer(guild_settings["bulk_operation_chunk_size"], 10, 1000)
                if chunk_size:
                    config["bulk_operation_chunk_size"] = chunk_size
            
            return config
            
        except Exception as e:
            _logger.warning(f"Failed to load guild config for {guild_id}, using defaults: {e}")
            return self._default_config.copy()

    async def _get_guild_max_members(self, guild_id: int) -> Optional[int]:
        """
        Get max members for guild's game with caching.
        
        Args:
            guild_id: Guild ID to get max members for
            
        Returns:
            Max members limit or None if not configured
        """
        cache_key = f"guild_max_members_{guild_id}"
        cached = self._get_cached_data(cache_key)
        if cached is not None:
            return cached
            
        try:
            game_id = await self.bot.cache.get_guild_data(guild_id, "guild_game")
            if not game_id:
                self._set_cached_data(cache_key, None)
                return None
                
            await self.bot.cache_loader.ensure_games_list_loaded()
            games_data = await self.bot.cache.get("static_data", "games_list")
            entry = games_data.get(game_id) or games_data.get(str(game_id)) if games_data else None
            
            max_members = entry.get("max_members") if entry else None
            max_members = self._validate_integer(max_members, 1, 10000)
            self._set_cached_data(cache_key, max_members)
            return max_members
            
        except Exception as e:
            _logger.warning(f"Failed to get max_members for guild {guild_id}: {e}")
            return None

    @discord_resilient()
    async def _load_weapons_data(self) -> None:
        """
        Load weapons and combinations data using centralized cache loaders.
        
        Enterprise-grade data loading with error handling and structured logging.
        """
        try:
            _logger.debug("loading_weapons_data_via_cache_loaders")

            await self.bot.cache_loader.ensure_weapons_loaded()
            await self.bot.cache_loader.ensure_weapons_combinations_loaded()

            _logger.info("weapons_data_loaded_successfully")
        except Exception as e:
            _logger.error("failed_to_load_weapons_data", error=str(e), exc_info=True)
            raise

    @discord_resilient()
    async def _load_user_setup_members(self) -> None:
        """
        Load user setup members with specific motif filter.
        
        Enterprise-grade data loading with defensive validation and structured logging.
        
        Raises:
            Exception: When database query fails after retries
        """
        cache_key = "user_setup_members_load"
        cached_data = self._get_cached_data(cache_key)
        if cached_data is not None:
            _logger.debug("using_cached_user_setup_data")
            return

        user_setup_query = """
            SELECT guild_id, user_id, username, locale, gs, weapons
            FROM user_setup
            WHERE motif IN ('member', 'application')
        """
        
        try:
            _logger.debug("loading_user_setup_members_from_database")
            rows = await self.bot.run_db_query(user_setup_query, fetch_all=True)
            user_setup_members = {}
            
            for row in rows:
                try:
                    guild_id, user_id, username, locale, gs, weapons = row
                    guild_id = self._validate_guild_id(guild_id)
                    user_id = self._validate_member_id(user_id)
                    
                    key = (guild_id, user_id)
                    user_setup_data: UserSetupData = {
                        "username": self._normalize_username(username or ""),
                        "locale": locale or "en-US",
                        "gs": self._validate_integer(gs, self.min_gs_value, self.max_gs_value) or 0,
                        "weapons": self._sanitize_string(weapons or "", 20),
                    }
                    user_setup_members[key] = user_setup_data
                except (ValueError, TypeError) as ve:
                    _logger.warning("invalid_user_setup_row_skipped", 
                                  row_data=str(row), error=str(ve))
                    continue
                    
            await self.bot.cache.set("user_data", user_setup_members, "user_setup_members")
            self._set_cached_data(cache_key, True)
            
            _logger.info("user_setup_members_loaded_successfully", 
                        entry_count=len(user_setup_members))
                        
        except Exception as e:
            _logger.error("failed_to_load_user_setup_members", error=str(e), exc_info=True)
            raise

    @discord_resilient()
    async def _load_members_data(self) -> None:
        """
        Load member-specific data into cache with enterprise-grade error handling.
        
        Coordinates loading of all member-related data through centralized cache loaders
        with proper sequencing and error recovery.
        """
        try:
            _logger.debug("loading_complete_members_data_set")

            await self._load_user_setup_members()
            await self.bot.cache_loader.ensure_guild_members_loaded()
            await self.bot.cache_loader.ensure_guild_ideal_staff_loaded()
            
            _logger.info("complete_members_data_loaded_successfully")
            
        except Exception as e:
            _logger.error("failed_to_load_complete_members_data", error=str(e), exc_info=True)
            raise

    async def get_weapons_combinations(self, game_id: int) -> List[WeaponCombination]:
        """
        Get weapon combinations for a specific game from cache.

        Args:
            game_id: The ID of the game to get weapon combinations for

        Returns:
            List of weapon combination TypedDict objects for the specified game
            
        Raises:
            ValueError: If game_id is invalid
        """
        try:
            if not isinstance(game_id, int) or game_id <= 0:
                raise ValueError(f"game_id must be a positive integer, got: {game_id}")

            cache_key = f"weapon_combinations_{game_id}"
            cached_data = self._get_cached_data(cache_key)
            if cached_data is not None:
                return cached_data
                
            _logger.debug("fetching_weapon_combinations_from_cache", game_id=game_id)
            combinations = await self.bot.cache.get("static_data", "weapons_combinations")
            
            if not combinations:
                _logger.warning("weapon_combinations_cache_empty", game_id=game_id)
                return []

            game_combinations = (
                combinations.get(game_id)
                or combinations.get(str(game_id))
                or []
            )

            validated_combinations = []
            for combo in game_combinations:
                if isinstance(combo, dict):
                    w1 = str(combo.get("weapon1", ""))
                    w2 = str(combo.get("weapon2", ""))
                    clazz = combo.get("class") or combo.get("class_name") or combo.get("role")
                    if w1 and w2 and clazz:
                        validated_combinations.append(cast(WeaponCombination, {
                            "weapon1": w1, "weapon2": w2, "class_name": str(clazz)
                        }))
            
            self._set_cached_data(cache_key, validated_combinations)
            _logger.debug("weapon_combinations_retrieved", 
                         game_id=game_id, combination_count=len(validated_combinations))

            if not validated_combinations:
                _logger.warning(
                    "empty_weapon_combinations_detected",
                    game_id=game_id,
                    message="No valid weapon combinations found - class detection will fail"
                )
            
            return validated_combinations
            
        except Exception as e:
            _logger.error("failed_to_get_weapon_combinations", 
                         game_id=game_id, error=str(e), exc_info=True)
            return []

    @discord_resilient()
    async def get_guild_members(self) -> Dict[Tuple[int, int], MemberData]:
        """
        Get all guild members from cache with enterprise-grade error handling and validation.

        Returns:
            Dictionary mapping (guild_id, member_id) tuples to MemberData TypedDict objects
            
        Raises:
            Exception: If critical cache operations fail after retries
        """
        try:
            cache_key = "guild_members_get"
            cached_data = self._get_cached_data(cache_key)
            if cached_data is not None:
                return cached_data
                
            _logger.debug("fetching_guild_members_from_cache")
            guild_members = await self.bot.cache.get("roster_data", "guild_members")
            
            if not guild_members:
                _logger.warning("guild_members_cache_empty_forcing_reload")
                try:
                    if hasattr(self.bot.cache_loader, '_loaded_categories') and "guild_members" in self.bot.cache_loader._loaded_categories:
                        self.bot.cache_loader._loaded_categories.discard("guild_members")
                    
                    await self.bot.cache_loader.ensure_guild_members_loaded()
                    guild_members = await self.bot.cache.get("roster_data", "guild_members")
                    
                    _logger.info("guild_members_cache_reloaded_successfully",
                               cache_type=type(guild_members).__name__)
                               
                except Exception as reload_error:
                    _logger.error("failed_to_reload_guild_members_cache", 
                                error=str(reload_error), exc_info=True)
                    raise
            
            validated_members = {}
            if guild_members:
                for key, member_data in guild_members.items():
                    try:
                        if isinstance(key, tuple) and len(key) == 2:
                            guild_id, member_id = key
                            validated_key = (self._validate_guild_id(guild_id), 
                                           self._validate_member_id(member_id))

                            if isinstance(member_data, dict):
                                def _clean_opt_str(v: Any) -> Optional[str]:
                                    if v is None:
                                        return None
                                    s = str(v).strip()
                                    return None if not s or s.lower() in ("none", "null") else s

                                build_clean = _clean_opt_str(member_data.get("build"))
                                weapons_clean = _clean_opt_str(member_data.get("weapons"))
                                class_clean = _clean_opt_str(member_data.get("class_member"))

                                validated_members[validated_key] = cast(MemberData, {
                                    "member_id": validated_key[1],
                                    "username": str(member_data.get("username", "")),
                                    "language": str(member_data.get("language") or "en-US"),
                                    "GS": int(member_data.get("GS") or 0),
                                    "build": build_clean,
                                    "weapons": weapons_clean,
                                    "DKP": int(member_data.get("DKP") or 0),
                                    "nb_events": int(member_data.get("nb_events") or 0),
                                    "registrations": int(member_data.get("registrations") or 0),
                                    "attendances": int(member_data.get("attendances") or 0),
                                    "class_member": class_clean
                                })
                    except (ValueError, TypeError) as ve:
                        _logger.warning("invalid_guild_member_data_skipped",
                                      key=str(key), error=str(ve))
                        continue
            
            self._set_cached_data(cache_key, validated_members)
            _logger.debug("guild_members_retrieved_successfully", 
                         member_count=len(validated_members))
            
            return validated_members
            
        except Exception as e:
            _logger.error("failed_to_get_guild_members", error=str(e), exc_info=True)
            raise

    async def get_user_setup_members(self) -> Dict[Tuple[int, int], UserSetupData]:
        """
        Get user setup members from cache.

        Args:
            None

        Returns:
            Dictionary mapping (guild_id, user_id) tuples to user setup data dictionaries
        """
        user_setup = await self.bot.cache.get("user_data", "user_setup_members")
        return user_setup or {}

    async def get_ideal_staff(self, guild_id: int) -> Dict[str, int]:
        """
        Get ideal staff configuration for a guild from cache.

        Args:
            guild_id: The ID of the guild to get ideal staff configuration for

        Returns:
            Dictionary mapping class names to ideal count numbers
        """
        ideal_staff_all = await self.bot.cache.get("guild_data", "ideal_staff") or {}
        return ideal_staff_all.get(guild_id) or ideal_staff_all.get(str(guild_id)) or {}

    async def update_guild_member_cache(
        self, guild_id: int, member_id: int, field: str, value: Any
    ) -> None:
        """
        Update a specific field for a guild member in cache.

        Args:
            guild_id: The ID of the guild
            member_id: The ID of the member
            field: The field name to update
            value: The new value for the field

        Returns:
            None
        """
        key = (guild_id, member_id)
        current_cache = await self.bot.cache.get("roster_data", "guild_members") or {}
        record = current_cache.get(key, {})
        record[field] = value
        current_cache[key] = record
        try:
            await self.bot.cache.set("roster_data", current_cache, "guild_members")
        except Exception as e:
            _logger.error("Failed to write shared cache", exc_info=True)
        finally:
            self._invalidate_cache("guild_members_get")

    async def _ensure_member_entry(self, guild_id: int, member: discord.Member) -> Optional[MemberData]:
        """
        Ensure member has an entry in guild_members cache, creating from user_setup if needed.
        
        Factored from hot path commands to avoid repeated cache warm-ups.
        
        Args:
            guild_id: The ID of the guild
            member: Discord member object
            
        Returns:
            MemberData if member found/created, None if not found anywhere
        """
        key = (guild_id, member.id)
        guild_members = await self.get_guild_members()
        
        if key in guild_members:
            return guild_members[key]
            
        _logger.debug(f"[GuildMembers] Member {key} not in cache, trying user_setup fallback")
        
        try:
            await self._load_user_setup_members()
            user_setup_members = await self.get_user_setup_members()
            
            setup_data = user_setup_members.get(key)
            if not setup_data:
                _logger.debug(f"[GuildMembers] Member {key} not found in user_setup either")
                return None
                
            _logger.debug(f"[GuildMembers] Creating guild_members entry from user_setup for {key}")

            member_record: MemberData = {
                "member_id": member.id,
                "username": setup_data.get("username", member.display_name),
                "language": setup_data.get("locale", "en-US"),
                "GS": setup_data.get("gs", 0),
                "build": None, 
                "weapons": setup_data.get("weapons") or None,
                "DKP": 0,
                "nb_events": 0,
                "registrations": 0,
                "attendances": 0,
                "class_member": None,
            }

            current_cache = await self.bot.cache.get("roster_data", "guild_members") or {}
            current_cache[key] = member_record
            await self.bot.cache.set("roster_data", current_cache, "guild_members")

            guild_members[key] = member_record
            
            _logger.debug(f"[GuildMembers] Successfully created cache entry for member {key}")
            return member_record
            
        except Exception as e:
            _logger.error(f"[GuildMembers] Failed to ensure member entry for {key}: {e}", exc_info=True)
            return None

    async def _class_lookup(self, game_id: int) -> Dict[str, Optional[str]]:
        """
        Build optimized O(1) lookup table for weapon combinations to classes.
        
        Args:
            game_id: The ID of the game for weapon combinations
            
        Returns:
            Dictionary mapping sorted weapon pairs to class names
        """
        cache_key = f"class_lookup_{game_id}"
        cached = self._get_cached_data(cache_key)
        if cached is not None:
            return cached
            
        combos = await self.get_weapons_combinations(game_id)
        lookup_dict = {
            "/".join(sorted([c["weapon1"].upper(), c["weapon2"].upper()])): c.get("class_name") or None
            for c in combos
        }
        self._set_cached_data(cache_key, lookup_dict)
        return lookup_dict

    async def determine_class(self, weapons_list: list, guild_id: int) -> Optional[str]:
        """
        Determine class based on weapon combination with O(1) lookup.

        Args:
            weapons_list: List of weapon codes
            guild_id: The ID of the guild to check weapon combinations for

        Returns:
            The determined class name or None if no match found
        """
        if not isinstance(weapons_list, list) or not weapons_list:
            return None

        game = await self.bot.cache.get_guild_data(guild_id, "guild_game")
        game_id = self._validate_integer(game)
        if game_id is None or game_id <= 0:
            return None

        key = "/".join(sorted([w.upper() for w in weapons_list]))
        class_lookup = await self._class_lookup(game_id)
        result_class = class_lookup.get(key)

        if not result_class:
            _logger.info(f"class_lookup_failed",
                         weapons_key=key,
                         game_id=game_id,
                         available_combinations=list(class_lookup.keys())[:10],
                         total_combinations=len(class_lookup),
                         message="No class found for weapon combination")
        else:
            _logger.debug(f"class_lookup_success",
                         weapons_key=key,
                         determined_class=result_class,
                         game_id=game_id)
        
        return result_class

    async def _get_valid_weapons_by_game(self, game_id: int) -> set:
        """
        Get cached set of valid weapons for a specific game ID.
        
        Precompute and caches valid weapon sets to avoid repeated combination scans.
        
        Args:
            game_id: The ID of the game
            
        Returns:
            Cached set of valid weapon codes for the game
        """
        if not isinstance(game_id, int) or game_id <= 0:
            return set()
            
        cache_key = f"valid_weapons_{game_id}"
        cached = self._get_cached_data(cache_key)
        if cached is not None:
            return cached

        valid_weapons = set()
        combinations = await self.get_weapons_combinations(game_id)
        for combo in combinations:
            valid_weapons.add(str(combo["weapon1"]).upper())
            valid_weapons.add(str(combo["weapon2"]).upper())
            
        self._set_cached_data(cache_key, valid_weapons)
        return valid_weapons

    async def get_valid_weapons(self, guild_id: int) -> set:
        """
        Get valid weapons for a guild based on its game configuration.
        
        Optimized with per-game caching to avoid repeated combination walks.

        Args:
            guild_id: The ID of the guild

        Returns:
            Set of valid weapon codes for the guild's game
        """
        if not isinstance(guild_id, int):
            return set()

        game = await self.bot.cache.get_guild_data(guild_id, "guild_game")
        if not game:
            return set()

        game_id = self._validate_integer(game)
        if game_id is None or game_id <= 0:
            return set()

        return await self._get_valid_weapons_by_game(game_id)

    async def _upsert_member_field(
        self, 
        guild_id: int, 
        member_id: int, 
        username: str,
        field_updates: MemberFieldUpdate,
        language: str = "en-US"
    ) -> None:
        """
        Helper method to upsert member data with specific field updates.
        
        Args:
            guild_id: Guild ID
            member_id: Member ID
            username: Display name for the member
            field_updates: Dictionary of field->value pairs to update
            language: Member language preference
            
        Raises:
            Exception: If database operation fails
        """
        try:
            ALLOWED_UPDATE_FIELDS = {"GS", "build", "weapons", "class_member", "username"}
            invalid_fields = set(field_updates.keys()) - ALLOWED_UPDATE_FIELDS
            if invalid_fields:
                raise ValueError(f"Invalid field names for update: {invalid_fields}")
            
            guild_members = await self.get_guild_members()
            key = (guild_id, member_id)
            current_member = guild_members.get(key, {})

            defaults = {
                "GS": current_member.get("GS", 0),
                "build": current_member.get("build") or None,
                "weapons": current_member.get("weapons") or None,
                "class_member": current_member.get("class_member") or None,
            }

            defaults.update(field_updates)

            update_clauses = [f"{f} = VALUES({f})" for f in field_updates]
            if "username" not in field_updates:
                update_clauses.append("username = VALUES(username)")
            if "language" not in field_updates:
                update_clauses.append("language = VALUES(language)")
            update_fields = ", ".join(update_clauses)
                
            upsert_query = f"""
            INSERT INTO guild_members 
            (guild_id, member_id, username, language, GS, build, weapons, DKP, nb_events, registrations, attendances, `class_member`)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0, 0, 0, %s)
            ON DUPLICATE KEY UPDATE {update_fields}
            """
            
            await self.bot.run_db_query(upsert_query, (
                guild_id, member_id, username, language,
                defaults["GS"], defaults["build"], defaults["weapons"], defaults["class_member"]
            ), commit=True)
            
            _logger.debug("upserted_member_field", 
                         guild_id=guild_id, member_id=member_id, 
                         updated_fields=list(field_updates.keys()))
            
        except Exception as e:
            _logger.error("failed_to_upsert_member_field", 
                         guild_id=guild_id, member_id=member_id, 
                         field_updates=field_updates, error=str(e), exc_info=True)
            raise

    @commands.cooldown(1, 5, commands.BucketType.user)
    @discord_resilient()
    async def gs(
        self,
        ctx: discord.ApplicationContext,
        value: int = discord.Option(int,
            description=GUILD_MEMBERS.get("gs", {}).get("value_comment", {}).get("en-US", "Update your gear score (GS)"),
            description_localizations=GUILD_MEMBERS.get("gs", {}).get("value_comment", {}),
        ),
    ):
        """
        Update member's gear score (GS) value.

        Args:
            ctx: Discord application context
            value: New GS value to set

        Returns:
            None
        """
        await ctx.defer(ephemeral=True)

        if not ctx.guild or not ctx.author:
            _logger.error(
                "[GuildMembers - GS] Invalid context: missing guild or author"
            )
            await ctx.followup.send("❌ Invalid request context", ephemeral=True)
            return

        guild_id = ctx.guild.id
        member_id = ctx.author.id
        key = (guild_id, member_id)

        cfg = await self._get_guild_config(guild_id)
        validated_value = self._validate_integer(
            value, cfg["min_gs_value"], cfg["max_gs_value"]
        )
        if validated_value is None:
            _logger.debug(
                f"[GuildMembers - GS] Invalid GS value provided by {ctx.author}: {value}"
            )
            msg = await get_user_message(ctx, GUILD_MEMBERS["gs"], "not_positive") or "Invalid GS value."
            try:
                await ctx.followup.send(msg, ephemeral=True)
            except Exception as ex:
                _logger.exception(
                    f"[GuildMembers - GS] Error sending followup message for invalid value: {ex}"
                )
            return

        member_data = await self._ensure_member_entry(guild_id, ctx.author)
        if not member_data:
            msg = await get_user_message(ctx, GUILD_MEMBERS["gs"], "not_registered") or "User not registered."
            await ctx.followup.send(msg, ephemeral=True)
            return

        try:
            language = member_data.get("language", "en-US")
            await self._upsert_member_field(
                guild_id, member_id, ctx.author.display_name,
                {"GS": validated_value}, language
            )
            await self.update_guild_member_cache(
                guild_id, member_id, "GS", validated_value
            )
            _logger.debug(
                f"[GuildMembers - GS] Successfully updated GS for {ctx.author} (ID: {member_id}) to {validated_value}"
            )
            msg = await get_user_message(
                ctx,
                GUILD_MEMBERS["gs"],
                "updated",
                username=ctx.author.display_name,
                value=validated_value,
            )
            await ctx.followup.send(msg, ephemeral=True)
        except Exception as e:
            _logger.exception(
                f"[GuildMembers - GS] Error updating GS for {ctx.author} (ID: {member_id}): {e}"
            )
            await ctx.followup.send("❌ Database error occurred", ephemeral=True)

    @commands.cooldown(1, 5, commands.BucketType.user)
    @discord_resilient()
    async def weapons(
        self,
        ctx: discord.ApplicationContext,
        weapon1: str = discord.Option(str,
            description=GUILD_MEMBERS.get("weapons", {}).get("value_comment", {}).get("en-US", "First weapon code"),
            description_localizations=GUILD_MEMBERS.get("weapons", {}).get("value_comment", {}),
        ),
        weapon2: str = discord.Option(str,
            description=GUILD_MEMBERS.get("weapons", {}).get("value_comment", {}).get("en-US", "Second weapon code"),
            description_localizations=GUILD_MEMBERS.get("weapons", {}).get("value_comment", {}),
        ),
    ):
        """
        Update member's weapon combination and determine class.

        Args:
            ctx: Discord application context
            weapon1: First weapon code
            weapon2: Second weapon code

        Returns:
            None
        """
        await ctx.defer(ephemeral=True)

        if not ctx.guild or not ctx.author:
            _logger.error(
                "[GuildMembers - Weapons] Invalid context: missing guild or author"
            )
            await ctx.followup.send("❌ Invalid request context", ephemeral=True)
            return

        guild_id = ctx.guild.id
        member_id = ctx.author.id
        key = (guild_id, member_id)

        member_data = await self._ensure_member_entry(guild_id, ctx.author)
        if not member_data:
            msg = await get_user_message(ctx, GUILD_MEMBERS["weapons"], "not_registered") or "User not registered."
            await ctx.followup.send(msg, ephemeral=True)
            return

        weapon1_code = self._validate_weapon_code(weapon1)
        weapon2_code = self._validate_weapon_code(weapon2)

        if not weapon1_code or not weapon2_code:
            msg = await get_user_message(ctx, GUILD_MEMBERS["weapons"], "not_valid") or "Invalid weapon combination."
            await ctx.followup.send(msg, ephemeral=True)
            return

        if weapon1_code == weapon2_code:
            msg = await get_user_message(
                ctx, GUILD_MEMBERS["weapons"], "not_valid_same"
            )
            await ctx.followup.send(msg, ephemeral=True)
            return

        valid_weapons = await self.get_valid_weapons(guild_id)
        if weapon1_code not in valid_weapons or weapon2_code not in valid_weapons:
            msg = await get_user_message(ctx, GUILD_MEMBERS["weapons"], "not_valid") or "Invalid weapon combination."
            await ctx.followup.send(msg, ephemeral=True)
            return

        try:
            weapons_normalized = sorted([weapon1_code, weapon2_code])
            player_class = await self.determine_class(weapons_normalized, guild_id)
            weapons_str = "/".join(weapons_normalized)

            language = member_data.get("language", "en-US")
            await self._upsert_member_field(
                guild_id, member_id, ctx.author.display_name,
                {"weapons": weapons_str, "class_member": player_class}, language
            )

            await self.update_guild_member_cache(
                guild_id, member_id, "weapons", weapons_str
            )
            await self.update_guild_member_cache(
                guild_id, member_id, "class_member", player_class
            )

            msg = await get_user_message(
                ctx,
                GUILD_MEMBERS["weapons"],
                "updated",
                username=ctx.author.display_name,
                weapons_str=weapons_str,
            )
            await ctx.followup.send(msg, ephemeral=True)
        except Exception as e:
            _logger.exception(
                f"[GuildMembers - Weapons] Error updating weapons for {ctx.author} (ID: {member_id}): {e}"
            )
            await ctx.followup.send("❌ Database error occurred", ephemeral=True)

    @commands.cooldown(1, 5, commands.BucketType.user)
    @discord_resilient()
    async def build(
        self,
        ctx: discord.ApplicationContext,
        url: str = discord.Option(str,
            description=GUILD_MEMBERS.get("build", {}).get("value_comment", {}).get("en-US", "Your build URL"),
            description_localizations=GUILD_MEMBERS.get("build", {}).get("value_comment", {}),
        ),
    ):
        """
        Update member's build URL.

        Args:
            ctx: Discord application context
            url: Build URL to set

        Returns:
            None
        """
        await ctx.defer(ephemeral=True)

        if not ctx.guild or not ctx.author:
            _logger.error(
                "[GuildMembers - Build] Invalid context: missing guild or author"
            )
            await ctx.followup.send("❌ Invalid request context", ephemeral=True)
            return

        guild_id = ctx.guild.id

        cfg = await self._get_guild_config(guild_id)
        if not self._validate_url(url, cfg["allowed_build_domains"]):
            msg = await get_user_message(ctx, GUILD_MEMBERS["build"], "not_correct")
            await ctx.followup.send(msg, ephemeral=True)
            return
        member_id = ctx.author.id
        key = (guild_id, member_id)

        member_data = await self._ensure_member_entry(guild_id, ctx.author)
        if not member_data:
            msg = await get_user_message(ctx, GUILD_MEMBERS["build"], "not_registered")
            await ctx.followup.send(msg, ephemeral=True)
            return

        try:
            sanitized_url = self._clean_url(url)
            language = member_data.get("language", "en-US")
            await self._upsert_member_field(
                guild_id, member_id, ctx.author.display_name,
                {"build": sanitized_url}, language
            )
            await self.update_guild_member_cache(
                guild_id, member_id, "build", sanitized_url
            )
            msg = await get_user_message(
                ctx, GUILD_MEMBERS["build"], "updated", username=ctx.author.display_name
            )
            await ctx.followup.send(msg, ephemeral=True)
        except Exception as e:
            _logger.exception(
                f"[GuildMembers - Build] Error updating build for {ctx.author} (ID: {member_id}): {e}"
            )
            await ctx.followup.send("❌ Database error occurred", ephemeral=True)

    @commands.cooldown(1, 5, commands.BucketType.user)
    @discord_resilient()
    async def username(
        self,
        ctx: discord.ApplicationContext,
        new_name: str = discord.Option(str,
            description=GUILD_MEMBERS.get("username", {}).get("value_comment", {}).get("en-US", "Your new username"),
            description_localizations=GUILD_MEMBERS.get("username", {}).get("value_comment", {}),
        ),
    ):
        """
        Update member's username and Discord nickname.

        Args:
            ctx: Discord application context
            new_name: New username to set

        Returns:
            None
        """
        await ctx.defer(ephemeral=True)

        if not ctx.guild or not ctx.author:
            _logger.error(
                "[GuildMembers - Username] Invalid context: missing guild or author"
            )
            await ctx.followup.send("❌ Invalid request context", ephemeral=True)
            return

        guild_id = ctx.guild.id
        member_id = ctx.author.id
        key = (guild_id, member_id)

        member_data = await self._ensure_member_entry(guild_id, ctx.author)
        if not member_data:
            msg = await get_user_message(ctx, GUILD_MEMBERS["username"], "not_registered")
            await ctx.followup.send(msg, ephemeral=True)
            return

        cfg = await self._get_guild_config(guild_id)
        new_username = self._normalize_username(new_name, cfg["max_username_length"])
        if not new_username or len(new_username.strip()) == 0:
            await ctx.followup.send("❌ Invalid username name", ephemeral=True)
            return

        try:
            language = member_data.get("language", "en-US")
            await self._upsert_member_field(
                guild_id, member_id, new_username,
                {"username": new_username}, language
            )
            await self.update_guild_member_cache(
                guild_id, member_id, "username", new_username
            )

            try:
                await ctx.author.edit(nick=new_username)
            except discord.Forbidden:
                _logger.warning(
                    f"[GuildMembers - Username] Unable to update nickname for {ctx.author.display_name}"
                )
            except Exception as e:
                _logger.warning(
                    f"[GuildMembers - Username] Error updating nickname for {ctx.author.display_name}: {e}"
                )

            msg = await get_user_message(
                ctx, GUILD_MEMBERS["username"], "updated", username=new_username
            )
            await ctx.followup.send(msg, ephemeral=True)
        except Exception as e:
            _logger.exception(
                f"[GuildMembers - Username] Error updating username for {ctx.author} (ID: {member_id}): {e}"
            )
            await ctx.followup.send("❌ Database error occurred", ephemeral=True)

    @admin_rate_limit(cooldown_seconds=30)
    @discord_resilient()
    async def maj_roster(self, ctx: discord.ApplicationContext):
        """
        Optimized roster update command - reduces DB queries by 90%.

        Args:
            ctx: Discord application context

        Returns:
            None
        """
        if not getattr(ctx.user, "guild_permissions", None) or not ctx.user.guild_permissions.manage_guild:
            return await ctx.respond("❌ You need Manage Server permission.", ephemeral=True)
            
        _logger.info(
            f"[GuildMembers] Starting maj_roster command for guild {ctx.guild.id}"
        )
        start_time = time.time()

        await ctx.defer(ephemeral=True)
        guild_id = ctx.guild.id

        await self.bot.cache_loader.reload_category("guild_channels")

        roles_config = await self.bot.cache.get_guild_data(guild_id, "roles")
        locale = await self.bot.cache.get_guild_data(guild_id, "guild_lang") or "en-US"

        if not roles_config:
            msg = await get_user_message(
                ctx, GUILD_MEMBERS["maj_roster"], "messages.not_config"
            )
            await ctx.followup.send(msg, ephemeral=True)
            return

        members_role_id = roles_config.get("members")
        absent_role_id = roles_config.get("absent_members")
        if not members_role_id:
            msg = await get_user_message(
                ctx, GUILD_MEMBERS["maj_roster"], "messages.roles_ko"
            )
            await ctx.followup.send(msg, ephemeral=True)
            return

        actual_members = {
            m.id: m
            for m in ctx.guild.members
            if not m.bot
            and (
                members_role_id in [role.id for role in m.roles]
                or (absent_role_id and absent_role_id in [role.id for role in m.roles])
            )
        }

        try:
            guild_members_db = await self._get_guild_members_bulk(guild_id)
            user_setup_db = await self._get_user_setup_bulk(guild_id)

            await self.bot.cache_loader.ensure_guild_members_loaded()
            current_guild_members = await self.get_guild_members()
            old_members = {
                member_id: data for (g_id, member_id), data in current_guild_members.items() 
                if g_id == guild_id
            }
        except Exception as e:
            _logger.error(
                f"[GuildMembers] Error loading member data for guild {guild_id}: {e}",
                exc_info=True,
            )
            msg = await get_user_message(
                ctx, GUILD_MEMBERS["maj_roster"], "messages.database_error"
            )
            if not msg:
                msg = "Database error occurred. Please try again later."
            await ctx.followup.send(msg, ephemeral=True)
            return

        to_delete, to_update, to_insert = await self._calculate_roster_changes(
            guild_id, actual_members, guild_members_db, user_setup_db, locale, old_members
        )

        deleted, updated, inserted = await self._apply_roster_changes_bulk(
            guild_id, to_delete, to_update, to_insert
        )

        await self.bot.cache.invalidate_category("roster_data")
        await self._load_user_setup_members()
        await self.bot.cache_loader.reload_category("guild_members")

        self._invalidate_cache("guild_members_get")
        self._invalidate_cache_prefix("class_lookup_")
        self._invalidate_cache_prefix("valid_weapons_")
        self._invalidate_cache_prefix("weapon_combinations_")
        self._invalidate_cache_prefix("guild_max_members_")

        if hasattr(self.bot.cache, 'invalidate_guild_members_bulk'):
            await self.bot.cache.invalidate_guild_members_bulk(guild_id)
        _logger.debug("local_caches_cleared_after_roster_changes")

        _logger.debug("forcing_fresh_guild_members_cache_load")
        fresh_guild_members = await self.get_guild_members()
        _logger.info(f"[GuildMembers] Fresh cache loaded with {len(fresh_guild_members)} total members after roster update")

        _logger.info(
            "[GuildMembers] Starting parallel message updates (recruitment + members)"
        )
        try:
            results = await asyncio.gather(
                self.update_recruitment_message(ctx),
                self.update_members_message(ctx),
                return_exceptions=True,
            )
            _logger.info(f"Message update results: {results}")
        except Exception as e:
            _logger.warning(f"Message update failed: {e}")

        execution_time = (time.time() - start_time) * 1000

        msg = await get_user_message(
            ctx,
            GUILD_MEMBERS["maj_roster"],
            "messages.success",
            execution_time=f"{execution_time:.0f}",
            deleted=deleted,
            updated=updated,
            inserted=inserted,
        )

        await ctx.followup.send(msg, ephemeral=True)

        _logger.info(
            f"[GuildMembers] Optimized maj_roster completed in {execution_time:.0f}ms: -{deleted} +{inserted} ~{updated}"
        )

    @profile_performance(threshold_ms=50.0)
    async def _get_guild_members_bulk(self, guild_id: int, force_db_read: bool = False) -> dict:
        """
        Retrieves all guild members with performance optimization.

        Args:
            guild_id: The ID of the guild to retrieve members for
            force_db_read: If True, bypass cache and read directly from database

        Returns:
            Dictionary mapping member IDs to member data dictionaries
        """
        if not force_db_read and hasattr(self.bot, "cache") and hasattr(
            self.bot.cache, "get_bulk_guild_members"
        ):
            return await self.bot.cache.get_bulk_guild_members(guild_id)

        query = """
        SELECT member_id, username, language, GS, build, weapons, DKP, 
               nb_events, registrations, attendances, `class_member`
        FROM guild_members 
        WHERE guild_id = %s
        """

        rows = await self.bot.run_db_query(query, (guild_id,), fetch_all=True)
        members_db = {}

        if rows:
            for row in rows:
                (
                    member_id,
                    username,
                    language,
                    gs,
                    build,
                    weapons,
                    dkp,
                    nb_events,
                    registrations,
                    attendances,
                    class_type,
                ) = row
                members_db[member_id] = {
                    "username": username,
                    "language": language,
                    "GS": gs,
                    "build": build,
                    "weapons": weapons,
                    "DKP": dkp,
                    "nb_events": nb_events,
                    "registrations": registrations,
                    "attendances": attendances,
                    "class_member": class_type,
                }

        return members_db

    async def _get_user_setup_bulk(self, guild_id: int) -> dict:
        """
        Retrieves consolidated member data from guild_members, with fallback to user_setup for missing members.

        Args:
            guild_id: The ID of the guild to retrieve setup data for

        Returns:
            Dictionary mapping member IDs to consolidated setup data dictionaries
        """
        query = """
        SELECT COALESCE(gm.member_id, us.user_id) as member_id,
               COALESCE(us.locale, gm.language) as locale,
               COALESCE(gm.GS, us.gs) as gs,
               COALESCE(gm.weapons, us.weapons) as weapons,
               gm.build,
               gm.class_member as class_member
        FROM user_setup us
        LEFT JOIN guild_members gm ON us.guild_id = gm.guild_id AND us.user_id = gm.member_id
        WHERE us.guild_id = %s
        
        UNION ALL
        
        SELECT gm.member_id,
               gm.language as locale,
               gm.GS as gs,
               gm.weapons,
               gm.build,
               gm.class_member as class_member
        FROM guild_members gm
        WHERE gm.guild_id = %s 
        AND gm.member_id NOT IN (SELECT user_id FROM user_setup WHERE guild_id = %s)
        """

        rows = await self.bot.run_db_query(
            query, (guild_id, guild_id, guild_id), fetch_all=True
        )
        setup_db = {}

        if rows:
            for row in rows:
                member_id, locale, gs, weapons, build, class_member = row
                setup_db[member_id] = {
                    "locale": locale,
                    "gs": gs,
                    "weapons": weapons,
                    "build": build,
                    "class_member": class_member,
                }

        return setup_db

    async def _calculate_roster_changes(
        self,
        guild_id: int,
        actual_members: dict,
        guild_members_db: dict,
        user_setup_db: dict,
        locale: str,
        old_members = None,
    ):
        """
        Calculates all necessary changes without DB queries.

        Args:
            guild_id: The ID of the guild
            actual_members: Dictionary of current Discord members
            guild_members_db: Dictionary of members from database
            user_setup_db: Dictionary of user setup data from database
            locale: Guild's locale for language defaults

        Returns:
            Tuple of (to_delete, to_update, to_insert) lists
        """
        to_delete = []
        to_update = []
        to_insert = []

        for member_id in guild_members_db.keys():
            if member_id not in actual_members:
                to_delete.append(member_id)

        for member_id, discord_member in actual_members.items():
            if member_id in guild_members_db:
                db_member = guild_members_db[member_id]
                user_setup = user_setup_db.get(member_id, {})

                weapons_normalized, computed_class = (
                    await self._process_weapons_optimized(
                        user_setup.get("weapons"), guild_id
                    )
                )

                user_setup_locale = user_setup.get("locale")
                if user_setup_locale and user_setup_locale != "en-US":
                    language = user_setup_locale
                else:
                    language = db_member.get("language") or locale

                gs_value = user_setup.get("gs") or 0
                if gs_value in (None, ""):
                    gs_value = 0

                changes = []
                if db_member.get("username") != discord_member.display_name:
                    changes.append(("username", discord_member.display_name))
                if db_member.get("language") != language:
                    changes.append(("language", language))
                if int(db_member.get("GS", 0) or 0) != int(gs_value):
                    changes.append(("GS", gs_value))
                if (db_member.get("build") or "").strip() != (
                    user_setup.get("build", "") or ""
                ).strip():
                    changes.append(("build", user_setup.get("build", "")))
                if (db_member.get("weapons") or "").strip() != (
                    weapons_normalized or ""
                ).strip():
                    changes.append(("weapons", weapons_normalized))

                if old_members and member_id in old_members:
                    old_class = (old_members[member_id].get("class_member") or "").strip()
                else:
                    old_class = (db_member.get("class_member") or "").strip()
                    
                new_class = (computed_class or "").strip()
                if old_class != new_class:

                    if not old_class and not new_class:
                        pass
                    else:
                        _logger.debug(f"[GuildMembers] Class change detected for member {member_id}: '{old_class}' -> '{new_class}'")
                        changes.append(("class_member", computed_class))

                if changes:
                    _logger.info(
                        f"[GuildMembers] Detected changes for member {member_id}: {changes}"
                    )
                    to_update.append((member_id, changes))

            else:
                user_setup = user_setup_db.get(member_id, {})

                weapons_normalized, computed_class = (
                    await self._process_weapons_optimized(
                        user_setup.get("weapons"), guild_id
                    )
                )

                user_setup_locale = user_setup.get("locale")
                if user_setup_locale and user_setup_locale != "en-US":
                    language = user_setup_locale
                else:
                    language = locale

                gs_value = user_setup.get("gs") or 0
                if gs_value in (None, ""):
                    gs_value = 0

                member_data = {
                    "member_id": member_id,
                    "username": discord_member.display_name,
                    "language": language,
                    "GS": gs_value,
                    "build": user_setup.get("build", ""),
                    "weapons": weapons_normalized,
                    "DKP": 0,
                    "nb_events": 0,
                    "registrations": 0,
                    "attendances": 0,
                    "class_member": computed_class,
                }
                to_insert.append(member_data)

        return to_delete, to_update, to_insert

    async def _process_weapons_optimized(self, weapons_raw: str, guild_id: int):
        """
        Optimized weapon processing with validation.

        Args:
            weapons_raw: Raw weapon string from database
            guild_id: The ID of the guild for weapon validation

        Returns:
            Tuple of (normalized_weapons_string, computed_class) or (None, None) if invalid
        """
        if not weapons_raw or not isinstance(weapons_raw, str):
            return None, None

        weapons_raw = weapons_raw.strip()
        if not weapons_raw:
            return None, None

        if "/" not in weapons_raw:
            if "," in weapons_raw:
                weapons_raw = weapons_raw.replace(",", "/")
            else:
                return None, None

        weapons_list = [w.strip().upper() for w in weapons_raw.split("/") if w.strip()]

        if len(weapons_list) != 2 or weapons_list[0] == weapons_list[1]:
            return None, None

        valid_weapons = await self.get_valid_weapons(guild_id)
        if weapons_list[0] not in valid_weapons or weapons_list[1] not in valid_weapons:
            return None, None

        weapons_normalized = "/".join(sorted(weapons_list))
        computed_class = await self.determine_class(sorted(weapons_list), guild_id)

        if weapons_normalized and not computed_class:
            _logger.info(f"class_detection_failed", 
                         weapons=weapons_normalized, 
                         guild_id=guild_id,
                         message="Class not determined despite valid weapons")
        elif weapons_normalized and computed_class:
            _logger.debug(f"class_detection_success",
                         weapons=weapons_normalized,
                         computed_class=computed_class,
                         guild_id=guild_id)

        return weapons_normalized, computed_class

    @staticmethod
    def _chunks(seq, n):
        """Split sequence into chunks of size n."""
        for i in range(0, len(seq), n):
            yield seq[i:i+n]

    @profile_performance(threshold_ms=100.0)
    async def _apply_roster_changes_bulk(
        self, guild_id: int, to_delete: list, to_update: list, to_insert: list
    ):
        """
        Applies all changes using a secure transaction with automatic rollback.

        Args:
            guild_id: The ID of the guild
            to_delete: List of member IDs to delete
            to_update: List of update tuples (member_id, changes) where changes is [(field, value), ...]
            to_insert: List of member data dictionaries to insert

        Returns:
            Tuple of (deleted_count, updated_count, inserted_count)

        Raises:
            ValueError: When invalid data is provided
            Exception: When database transaction fails
        """
        deleted_count = 0
        updated_count = 0
        inserted_count = 0

        to_delete = sorted(set(to_delete))
        to_update = sorted(to_update, key=lambda t: (guild_id, t[0]))
        to_insert = sorted(to_insert, key=lambda m: (guild_id, m["member_id"]))

        transaction_queries = []

        try:
            guild_config = await self._get_guild_config(guild_id)
            chunk_size = guild_config["bulk_operation_chunk_size"]
            
            total_operations = len(to_delete) + len(to_update) + len(to_insert)
            if total_operations > chunk_size * 10:
                _logger.warning(
                    f"[GuildMembers] Large batch operation detected: {total_operations} operations for guild {guild_id} (will be chunked into {chunk_size}-sized batches)"
                )

            if to_delete:
                if not all(isinstance(mid, int) and mid > 0 for mid in to_delete):
                    raise ValueError("Invalid member ID format in deletion list")

                for chunk in self._chunks(to_delete, chunk_size):
                    placeholders = ",".join(["%s"] * len(chunk))
                    delete_query = f"DELETE FROM guild_members WHERE guild_id = %s AND member_id IN ({placeholders})"
                    transaction_queries.append((delete_query, tuple([guild_id] + chunk)))
                deleted_count = len(to_delete)

            if to_update:
                allowed_fields = {
                    "username",
                    "language",
                    "GS",
                    "build",
                    "weapons",
                    "DKP",
                    "nb_events",
                    "registrations",
                    "attendances",
                    "class_member",
                }
                for member_id, changes in to_update:
                    if not isinstance(member_id, int) or member_id <= 0:
                        raise ValueError(
                            f"Invalid member ID format in update: {member_id}"
                        )

                    set_clauses = []
                    params = []
                    for field, value in changes:
                        if field not in allowed_fields:
                            raise ValueError(f"Invalid field name for update: {field}")
                        set_clauses.append(f"{field} = %s")
                        params.append(value)

                    if set_clauses:
                        update_query = f"UPDATE guild_members SET {', '.join(set_clauses)} WHERE guild_id = %s AND member_id = %s"
                        update_params = params + [guild_id, member_id]
                        transaction_queries.append((update_query, tuple(update_params)))

                updated_count = len(to_update)

            if to_insert:
                required_fields = [
                    "member_id", "username", "language", "GS", "build", "weapons", 
                    "DKP", "nb_events", "registrations", "attendances", "class_member"
                ]

                for member_data in to_insert:
                    if not all(field in member_data for field in required_fields):
                        raise ValueError("Missing required fields in member data")
                    if not isinstance(member_data["member_id"], int) or member_data["member_id"] <= 0:
                        raise ValueError(f"Invalid member ID format in insert: {member_data['member_id']}")

                insert_upsert_base = """
                    INSERT INTO guild_members 
                    (guild_id, member_id, username, language, GS, build, weapons, DKP, nb_events, registrations, attendances, `class_member`)
                    VALUES """
                insert_upsert_suffix = """
                    ON DUPLICATE KEY UPDATE
                    username = VALUES(username),
                    language = VALUES(language),
                    GS = VALUES(GS),
                    build = VALUES(build),
                    weapons = VALUES(weapons),
                    DKP = VALUES(DKP),
                    nb_events = VALUES(nb_events),
                    registrations = VALUES(registrations),
                    attendances = VALUES(attendances),
                    `class_member` = VALUES(`class_member`)
                """

                for chunk in self._chunks(to_insert, chunk_size):
                    values_placeholders = ",".join(["(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"] * len(chunk))
                    full_query = insert_upsert_base + values_placeholders + insert_upsert_suffix
                    
                    params = []
                    for member_data in chunk:
                        params.extend([
                            guild_id, member_data["member_id"], member_data["username"], 
                            member_data["language"], member_data["GS"], member_data["build"], 
                            member_data["weapons"], member_data["DKP"], member_data["nb_events"],
                            member_data["registrations"], member_data["attendances"], member_data["class_member"]
                        ])
                    transaction_queries.append((full_query, tuple(params)))
                inserted_count = len(to_insert)

            if transaction_queries:
                _logger.info(f"[GuildMembers] DEBUG - About to execute {len(transaction_queries)} transaction queries for guild {guild_id}")
                for i, (query, params) in enumerate(transaction_queries[:3]):
                    _logger.info(f"[GuildMembers] DEBUG - Query {i+1}: {query[:200]}... with {len(params)} params")
                    if any("class_member" in str(p) for p in params):
                        _logger.info(f"[GuildMembers] DEBUG - Query {i+1} contains class_member values: {[p for p in params if p and 'class_member' not in str(p)]}")
                
                success = await run_db_transaction(transaction_queries)
                if not success:
                    _logger.error(f"[GuildMembers] ERROR - Database transaction FAILED for guild {guild_id}")
                    raise Exception("Database transaction failed")

                _logger.info(
                    f"[GuildMembers] Roster transaction completed successfully for guild {guild_id}: {deleted_count} deleted, {updated_count} updated, {inserted_count} inserted"
                )

                _logger.info(f"[GuildMembers] DEBUG - Verifying database state after transaction for guild {guild_id}")
                post_transaction_check = await self._get_guild_members_bulk(guild_id, force_db_read=True)
                _logger.info(f"[GuildMembers] DEBUG - Post-transaction database contains {len(post_transaction_check)} members")
                for i, (member_id, data) in enumerate(list(post_transaction_check.items())[:3]):
                    _logger.info(f"[GuildMembers] DEBUG - Member {i+1} post-transaction: id={member_id}, username='{data.get('username')}', class_member='{data.get('class_member')}', weapons='{data.get('weapons')}'")
                    
            else:
                _logger.debug(
                    f"[GuildMembers] No roster changes needed for guild {guild_id}"
                )

        except Exception as e:
            _logger.error(
                f"[GuildMembers] Roster transaction failed for guild {guild_id}: {e}",
                exc_info=True,
            )
            return 0, 0, 0

        return deleted_count, updated_count, inserted_count

    @discord_resilient()
    async def update_recruitment_message(self, ctx):
        """
        Update recruitment message with current roster statistics.

        Args:
            ctx: Discord context (can be ApplicationContext or Guild object)

        Returns:
            None
        """
        total_members = 0
        members_in_roster = []
        
        try:
            _logger.debug(
                "[GuildMembers] update_recruitment_message - Starting function"
            )
            
            if hasattr(ctx, "guild"):
                guild_obj = ctx.guild
            else:
                guild_obj = ctx
            guild_id = guild_obj.id
            _logger.debug(
                f"[GuildMembers] update_recruitment_message - Guild ID: {guild_id}"
            )

            locale = (
                await self.bot.cache.get_guild_data(guild_id, "guild_lang") or "en-US"
            )
            channel_id = await self.bot.cache.get_guild_data(
                guild_id, "external_recruitment_channel"
            )
            message_id = await self.bot.cache.get_guild_data(
                guild_id, "external_recruitment_message"
            )

            try:
                if channel_id is not None:
                    channel_id = int(channel_id)
                if message_id is not None:
                    message_id = int(message_id)
            except (ValueError, TypeError) as e:
                _logger.error(f"Invalid ID format in guild {guild_id} recruitment config: {e}")
                return
            
            _logger.debug(
                f"[GuildMembers] update_recruitment_message - Channel ID: {channel_id}, Message ID: {message_id}"
            )

            if not channel_id:
                _logger.error(
                    f"[GuildMembers] No recruitment channel configured for guild {guild_id}"
                )
                return
            channel = self.bot.get_channel(channel_id)
            if not channel:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                    _logger.debug(f"Retrieved recruitment channel {channel_id} via fetch fallback")
                except Exception as fetch_error:
                    _logger.error(f"Unable to retrieve recruitment channel {channel_id}: {fetch_error}")
                    return
        except Exception as e:
            _logger.exception(
                f"[GuildMembers] Error in update_recruitment_message initialization: {e}"
            )
            return

        try:
            _logger.debug(
                "[GuildMembers] update_recruitment_message - Getting guild members"
            )
            await self.bot.cache.invalidate_category("roster_data")
            guild_members = await self.get_guild_members()
            members_in_roster = [
                v for (g, _), v in guild_members.items() if g == guild_id
            ]
            total_members = len(members_in_roster)
            _logger.info(
                f"[GuildMembers] Recruitment message - Guild members cache contains {len(guild_members)} total entries, {len(members_in_roster)} for guild {guild_id}"
            )

            if not members_in_roster:
                _logger.warning(
                    f"[GuildMembers] No members found in roster for recruitment message in guild {guild_id}, checking database directly..."
                )
                try:
                    guild_members_db = await self._get_guild_members_bulk(guild_id)
                    _logger.info(
                        f"[GuildMembers] Database query for recruitment returned {len(guild_members_db)} members for guild {guild_id}"
                    )
                    if guild_members_db:
                        current_cache = (
                            await self.bot.cache.get("roster_data", "guild_members")
                            or {}
                        )
                        for member_id, data in guild_members_db.items():
                            key = (guild_id, member_id)
                            current_cache[key] = data
                        await self.bot.cache.set(
                            "roster_data", current_cache, "guild_members"
                        )
                        members_in_roster = list(guild_members_db.values())
                        total_members = len(members_in_roster)
                        _logger.info(
                            f"[GuildMembers] Updated global cache for recruitment and found {total_members} members"
                        )
                except Exception as e:
                    _logger.error(
                        f"[GuildMembers] Error loading members for recruitment message: {e}",
                        exc_info=True,
                    )
                    members_in_roster = []
                    total_members = 0

            _logger.debug(
                "[GuildMembers] update_recruitment_message - Getting game data"
            )
            roster_size_max = await self._get_guild_max_members(guild_id)

            _logger.debug(
                "[GuildMembers] update_recruitment_message - Getting ideal staff"
            )
            ideal_staff = await self.get_ideal_staff(guild_id)
            if not ideal_staff:
                ideal_staff = {
                    "Tank": 20,
                    "Healer": 20,
                    "Flanker": 10,
                    "Ranged DPS": 10,
                    "Melee DPS": 10,
                }

            _logger.debug(
                "[GuildMembers] update_recruitment_message - Calculating class counts"
            )
            class_counts = {key: 0 for key in ideal_staff.keys()}
            for m in members_in_roster:
                cls = m.get("class_member") or None
                if cls in ideal_staff:
                    class_counts[cls] += 1

            remaining_slots = max(0, (roster_size_max or 0) - total_members)

            _logger.debug("update_recruitment_message - Building embed")
            title = self.t(GUILD_MEMBERS, "post_recruitment.name", locale, "Recruitment")
            roster_size_template = self.t(GUILD_MEMBERS, "post_recruitment.roster_size", locale, "Roster size: {roster_size}/{max_roster}")
            roster_size_line = roster_size_template.format(
                total_members=total_members, roster_size_max=roster_size_max or "∞"
            )
            places_template = self.t(GUILD_MEMBERS, "post_recruitment.places", locale, "Available places: {remaining_slots}")
            places_line = places_template.format(remaining_slots=remaining_slots)
            post_availability_template = self.t(GUILD_MEMBERS, "post_recruitment.post_availability", locale, "")
            updated_template = self.t(GUILD_MEMBERS, "post_recruitment.updated", locale, "Last updated: {timestamp}")

            class_order = list(ideal_staff.keys()) if ideal_staff else []

            positions_details = ""
            for cls_key in class_order:
                ideal_number = ideal_staff[cls_key]
                class_name = self.t(GUILD_MEMBERS, f"class.{cls_key}", locale, cls_key.capitalize())
                current_count = class_counts.get(cls_key, 0)
                available = max(0, ideal_number - current_count)
                positions_details += f"- **{class_name}** : {available}\n"

            description_parts = [
                roster_size_line,
                places_line,
                post_availability_template,
                "",
                positions_details.rstrip()
            ]
            description = "\n".join(part for part in description_parts if part)

            safe_description = self._truncate_embed_description(description)

            embed = discord.Embed(
                title=title, description=safe_description, color=discord.Color.blue()
            )
            from discord.utils import utcnow
            now = utcnow().strftime("%d/%m/%Y %H:%M UTC")
            embed.set_footer(text=updated_template.format(now=now))
        except Exception as e:
            _logger.exception(
                f"[GuildMembers] Error in update_recruitment_message processing: {e}"
            )
            return

        _logger.debug(
            "[GuildMembers] update_recruitment_message - About to update embed"
        )
        try:
            if message_id:
                _logger.debug(
                    f"[GuildMembers] update_recruitment_message - Fetching existing message {message_id}"
                )
                try:
                    message = await channel.fetch_message(message_id)
                    _logger.debug(
                        f"[GuildMembers] update_recruitment_message - Editing message"
                    )
                    await message.edit(embed=embed)
                except discord.NotFound:
                    _logger.warning(f"Recruitment message {message_id} not found, creating new message")
                    message = await channel.send(embed=embed)
                    await self.bot.cache.set_guild_data(guild_id, "external_recruitment_message", message.id)
                except discord.HTTPException as e:
                    _logger.error(f"Failed to fetch/edit recruitment message {message_id}: {e}")
                    return
                _logger.info(
                    "[GuildMembers] update_recruitment_message - Successfully updated recruitment embed"
                )
            else:
                _logger.debug(
                    f"[GuildMembers] update_recruitment_message - Creating new message"
                )
                new_message = await channel.send(embed=embed)
                await self.bot.cache.set_guild_data(
                    guild_id, "external_recruitment_message", new_message.id
                )
                query = "UPDATE guild_settings SET external_recruitment_message = %s WHERE guild_id = %s"
                await self.bot.run_db_query(
                    query, (new_message.id, guild_id), commit=True
                )
                _logger.info(
                    f"[GuildMembers] update_recruitment_message - Created new recruitment message {new_message.id}"
                )
        except discord.NotFound:
            _logger.warning(
                f"[GuildMembers] update_recruitment_message - Message {message_id} not found, creating new one"
            )
            new_message = await channel.send(embed=embed)
            await self.bot.cache.set_guild_data(
                guild_id, "external_recruitment_message", new_message.id
            )
            query = "UPDATE guild_settings SET external_recruitment_message = %s WHERE guild_id = %s"
            await self.bot.run_db_query(query, (new_message.id, guild_id), commit=True)
            _logger.info(
                f"[GuildMembers] update_recruitment_message - Created replacement message {new_message.id}"
            )
        except Exception as e:
            _logger.exception(f"Error updating recruitment message: {e}")
            return

    @discord_resilient()
    async def update_members_message(self, ctx):
        """
        Update members message with detailed roster table.

        Args:
            ctx: Discord context (can be ApplicationContext or Guild object)

        Returns:
            None
        """
        _logger.info("Starting update_members_message function")

        if hasattr(ctx, "guild"):
            guild_obj = ctx.guild
        else:
            guild_obj = ctx
        guild_id = guild_obj.id

        _logger.info(
            f"[GuildMembers] Processing update_members_message for guild {guild_id}"
        )

        locale = await self.bot.cache.get_guild_data(guild_id, "guild_lang") or "en-US"
        _logger.info(f"Guild locale: {locale}")

        channel_id = await self.bot.cache.get_guild_data(guild_id, "members_channel")
        if not channel_id:
            _logger.error(f"No members_channel configured for guild {guild_id}")
            return

        try:
            channel_id = int(channel_id)
        except (ValueError, TypeError) as e:
            _logger.error(f"Invalid channel_id format in guild {guild_id}: {e}")
            return
            
        _logger.info(f"Retrieved members_channel ID: {channel_id}")

        message_ids = []
        for i in range(1, 6):
            msg_id = await self.bot.cache.get_guild_data(guild_id, f"members_m{i}")

            if msg_id is not None:
                try:
                    msg_id = int(msg_id)
                except (ValueError, TypeError):
                    _logger.warning(f"Invalid message_id format for members_m{i} in guild {guild_id}, skipping")
                    msg_id = None
            message_ids.append(msg_id)
            _logger.debug(f"Message {i}: {msg_id}")

        _logger.info(
            f"[GuildMembers] Channel ID: {channel_id}, Message IDs: {message_ids}"
        )

        channel = self.bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(channel_id)
                _logger.debug(f"Retrieved roster channel {channel_id} via fetch fallback")
            except Exception as fetch_error:
                _logger.error(
                    f"[GuildMembers] Unable to retrieve roster channel with ID {channel_id}: {fetch_error}"
                )
                return

        _logger.info(f"Successfully retrieved channel: {channel.name}")

        guild_members = await self.get_guild_members()
        members_in_roster = [v for (g, _), v in guild_members.items() if g == guild_id]
        _logger.info(
            f"[GuildMembers] Guild members cache contains {len(guild_members)} total entries, {len(members_in_roster)} for guild {guild_id}"
        )

        _logger.info("[GuildMembers] DEBUG - First 5 members class_member values:")
        for i, member in enumerate(members_in_roster[:5]):
            _logger.info(f"  Member {i+1}: username='{member.get('username')}', class_member='{member.get('class_member')}', weapons='{member.get('weapons')}'")
        

        if not members_in_roster:
            _logger.warning(
                f"[GuildMembers] No members found in roster for guild {guild_id}, checking database directly..."
            )
            try:
                guild_members_db = await self._get_guild_members_bulk(guild_id)
                _logger.info(
                    f"[GuildMembers] Database query returned {len(guild_members_db)} members for guild {guild_id}"
                )
                if guild_members_db:
                    current_cache = (
                        await self.bot.cache.get("roster_data", "guild_members") or {}
                    )
                    for member_id, data in guild_members_db.items():
                        key = (guild_id, member_id)
                        current_cache[key] = data
                    await self.bot.cache.set(
                        "roster_data", current_cache, "guild_members"
                    )
                    members_in_roster = list(guild_members_db.values())
                    _logger.info(
                        f"[GuildMembers] Updated global cache and found {len(members_in_roster)} members"
                    )
            except Exception as e:
                _logger.error(
                    f"[GuildMembers] Error loading members from database: {e}",
                    exc_info=True,
                )

        if not members_in_roster:
            _logger.warning("No members found in roster")
            return

        sorted_members = sorted(
            members_in_roster, key=lambda x: x.get("username", "").lower()
        )

        tank_count = sum(
            1 for m in sorted_members if (m.get("class_member") or "").lower() == "tank"
        )
        dps_melee_count = sum(
            1 for m in sorted_members if (m.get("class_member") or "").lower() == "melee dps"
        )
        dps_distant_count = sum(
            1 for m in sorted_members if (m.get("class_member") or "").lower() == "ranged dps"
        )
        heal_count = sum(
            1 for m in sorted_members if (m.get("class_member") or "").lower() == "healer"
        )
        flank_count = sum(
            1 for m in sorted_members if (m.get("class_member") or "").lower() == "flanker"
        )

        username_width = 20
        language_width = 8
        gs_width = 8
        build_width = 7
        weapons_width = 9
        class_width = 14
        dkp_width = 10
        reg_width = 8
        att_width = 8

        header_array = GUILD_MEMBERS.get("table", {}).get("header", {}).get(locale) or \
                      GUILD_MEMBERS.get("table", {}).get("header", {}).get("en-US") or \
                      ["Username", "Lang", "GS", "Build", "Weapons", "Class", "DKP", "Reg", "Att"]
        
        header_labels = header_array[:9]

        header = (
            f"{header_labels[0].ljust(username_width)}│"
            f"{header_labels[1].center(language_width)}│"
            f"{header_labels[2].center(gs_width)}│"
            f"{header_labels[3].center(build_width)}│"
            f"{header_labels[4].center(weapons_width)}│"
            f"{header_labels[5].center(class_width)}│"
            f"{header_labels[6].center(dkp_width)}│"
            f"{header_labels[7].center(reg_width)}│"
            f"{header_labels[8].center(att_width)}"
        )
        separator = "─" * len(header)

        rows = []
        for m in sorted_members:
            raw_username = m.get("username", "")[:username_width]
            username = _pad_cell(_mono_sanitize(raw_username), username_width)
            language_text = str(m.get("language", "en-US"))[:language_width].center(
                language_width
            )
            gs = str(m.get("GS") or "").center(gs_width)
            build_value = m.get("build")
            build_flag = (
                "Y"
                if build_value and build_value not in (None, "", "None")
                else " "
            )
            build_flag = build_flag.center(build_width)
            weapons = m.get("weapons") or None
            if weapons:
                weapons_str = weapons.center(weapons_width)
            else:
                weapons_str = " ".center(weapons_width)
            member_class = m.get("class_member") or None
            if member_class:
                class_str = _center_cell(_mono_sanitize(member_class), class_width)
            else:
                class_str = _center_cell(" ", class_width)
            dkp = str(m.get("DKP", 0)).center(dkp_width)
            nb_events = m.get("nb_events", 0)
            registrations = m.get("registrations", 0)
            attendances = m.get("attendances", 0)

            reg_pct = self.safe_percentage(registrations, nb_events)
            att_pct = self.safe_percentage(attendances, nb_events)
            registrations = f"{reg_pct}%".center(reg_width)
            attendances = f"{att_pct}%".center(att_width)
            rows.append(
                f"{username}│{language_text}│{gs}│{build_flag}│{weapons_str}│{class_str}│{dkp}│{registrations}│{attendances}"
            )

        if not rows:
            _logger.warning("No members found in roster")
            return

        from discord.utils import utcnow
        now_str = utcnow().strftime("%d/%m/%Y %H:%M UTC")
        role_labels = [
            self.t(GUILD_MEMBERS, "table.role_stats.tank", locale, "Tank"),
            self.t(GUILD_MEMBERS, "table.role_stats.melee_dps", locale, "Melee DPS"),
            self.t(GUILD_MEMBERS, "table.role_stats.ranged_dps", locale, "Ranged DPS"),
            self.t(GUILD_MEMBERS, "table.role_stats.healer", locale, "Healer"),
            self.t(GUILD_MEMBERS, "table.role_stats.flanker", locale, "Flanker")
        ]

        role_stats = (
            f"{role_labels[0]}: {tank_count}\n"
            f"{role_labels[1]}: {dps_melee_count}\n"
            f"{role_labels[2]}: {dps_distant_count}\n"
            f"{role_labels[3]}: {heal_count}\n"
            f"{role_labels[4]}: {flank_count}"
        )
        footer_template = (
            GUILD_MEMBERS.get("table", {})
            .get("footer", {})
            .get(locale, "Number of members: {count}\\n{stats}\\nUpdated {date}")
        )
        update_footer = "\n" + footer_template.format(
            count=len(rows), stats=role_stats, date=now_str
        ).replace("\\n", "\n")
        max_length = 2000
        message_contents = []
        current_block = f"```\n{header}\n{separator}\n"
        for row in rows:
            if len(current_block) + len(row) + len(update_footer) + 10 > max_length:
                current_block += "```"
                message_contents.append(current_block)
                current_block = f"```\n{header}\n{separator}\n{row}\n"
            else:
                current_block += f"{row}\n"
        if current_block:
            current_block += "```" + update_footer
            message_contents.append(current_block)

        try:
            _logger.info(
                f"[GuildMembers] Starting message updates for {len(message_contents)} message contents"
            )
            _logger.info(
                f"[GuildMembers] Will update {len(message_ids)} messages in channel {channel.name}"
            )

            for i in range(5):
                try:
                    message_id = message_ids[i]
                    if not message_id:
                        _logger.warning(
                            f"[GuildMembers] Message ID {i+1}/5 is None, skipping"
                        )
                        continue

                    _logger.info(
                        f"[GuildMembers] Fetching message {i+1}/5 with ID {message_id}"
                    )
                    message = await channel.fetch_message(message_id)
                    new_content = (
                        message_contents[i] if i < len(message_contents) else "."
                    )

                    if len(new_content) > 2000:
                        _logger.warning(f"Message {i+1}/5 content too long ({len(new_content)} chars), truncating")
                        new_content = new_content[:1997] + "..."

                    _logger.info(
                        f"[GuildMembers] Message {i+1}/5 content length: old={len(message.content)}, new={len(new_content)}"
                    )
                    if message.content != new_content:
                        _logger.info(
                            f"[GuildMembers] Updating message {i+1}/5 (content changed)"
                        )
                        await message.edit(content=new_content)
                        _logger.info(
                            f"[GuildMembers] Message {i+1}/5 updated successfully"
                        )
                        if i < 4:
                            await asyncio.sleep(0.25)
                    else:
                        _logger.info(
                            f"[GuildMembers] Message {i+1}/5 content unchanged, skipping update"
                        )
                except discord.NotFound:
                    _logger.warning(
                        f"[GuildMembers] Roster message {i+1}/5 not found (ID: {message_ids[i]})"
                    )
                except Exception as e:
                    _logger.error(
                        f"[GuildMembers] Error updating roster message {i+1}/5: {e}",
                        exc_info=True,
                    )
        except Exception as e:
            _logger.exception(f"Error updating member messages: {e}")
        _logger.info("Member message update completed")

    async def show_build(
        self,
        ctx: discord.ApplicationContext,
        username: str = discord.Option(str,
            description=GUILD_MEMBERS.get("show_build", {}).get("value_comment", {}).get("en-US", "Username to show build for"),
            description_localizations=GUILD_MEMBERS.get("show_build", {}).get("value_comment", {}),
        ),
    ):
        """
        Show another member's build URL in private message.

        Args:
            ctx: Discord application context
            username: Username to search for

        Returns:
            None
        """
        await ctx.defer(ephemeral=True)

        if not ctx.guild or not ctx.author:
            _logger.error(
                "[GuildMembers - ShowBuild] Invalid context: missing guild or author"
            )
            await ctx.followup.send("❌ Invalid request context", ephemeral=True)
            return

        guild_id = ctx.guild.id

        cfg = await self._get_guild_config(guild_id)
        sanitized_username = self._normalize_username(username, cfg["max_username_length"])
        if not sanitized_username:
            await ctx.followup.send("❌ Invalid username format", ephemeral=True)
            return

        guild_members = await self.get_guild_members()

        exact_matches = [
            m
            for (g, _), m in guild_members.items()
            if g == guild_id
            and m.get("username", "").lower() == sanitized_username.lower()
        ]
        
        if exact_matches:
            member_data = exact_matches[0]
        else:
            prefix_matches = [
                m
                for (g, _), m in guild_members.items()
                if g == guild_id
                and m.get("username", "").lower().startswith(sanitized_username.lower())
            ]
            
            if not prefix_matches:
                msg = await get_user_message(
                    ctx, GUILD_MEMBERS["show_build"], "messages.not_found", username=username
                )
                await ctx.followup.send(msg, ephemeral=True)
                return
                
            member_data = prefix_matches[0]
        build_url = member_data.get("build")
        if not build_url or build_url in (None, "", "None"):
            msg = await get_user_message(
                ctx, GUILD_MEMBERS["show_build"], "messages.no_build", username=username
            )
            await ctx.followup.send(msg, ephemeral=True)
            return

        try:
            msg = await get_user_message(
                ctx,
                GUILD_MEMBERS["show_build"],
                "messages.build_sent",
                member=member_data.get("username"),
                build_url=build_url,
            )
            _logger.info(f"[DEBUG] get_user_message returned: '{msg}' (type: {type(msg)}, bool: {bool(msg)})")
            msg = msg or f"🔗 **{member_data.get('username')}'s build:** {build_url}"
            
            await ctx.author.send(msg)
            
            success_msg = await get_user_message(ctx, GUILD_MEMBERS["show_build"], "messages.sent")
            _logger.info(f"[DEBUG] success get_user_message returned: '{success_msg}' (type: {type(success_msg)}, bool: {bool(success_msg)})")
            success_msg = success_msg or "✅ Build sent to your DMs"
            await ctx.followup.send(success_msg, ephemeral=True)
        except discord.Forbidden:
            msg = await get_user_message(
                ctx, GUILD_MEMBERS["show_build"], "messages.cannot_send"
            )
            await ctx.followup.send(msg, ephemeral=True)

    async def _safe_dm(self, member: discord.Member, message: str, semaphore: asyncio.Semaphore) -> bool:
        """
        Send DM with semaphore-controlled concurrency to respect Discord rate limits.
        
        Args:
            member: Discord member to send DM to
            message: Message content to send
            semaphore: Semaphore to control concurrency
            
        Returns:
            True if DM sent successfully, False otherwise
        """
        async with semaphore:
            try:
                await member.send(message)
                return True
            except Exception as e:
                _logger.error(f"[GuildMembers] Failed to DM member ({member.id}): {e}")
                return False

    @discord_resilient()
    async def notify_incomplete_profiles(self, ctx: discord.ApplicationContext):
        """
        Send notifications to members with incomplete profiles.

        Args:
            ctx: Discord application context

        Returns:
            None
        """
        if not getattr(ctx.user, "guild_permissions", None) or not ctx.user.guild_permissions.manage_guild:
            return await ctx.respond("❌ You need Manage Server permission.", ephemeral=True)
            
        await ctx.defer(ephemeral=True)
        guild = ctx.guild
        guild_id = guild.id

        await self.bot.cache_loader.ensure_guild_members_loaded()

        incomplete_members = []
        guild_members = await self.get_guild_members()
        _logger.debug(
            f"[GuildMembers] notify_incomplete_profiles: Found {len(guild_members)} total members in cache"
        )

        guild_member_count = 0
        for (g, member_id), data in guild_members.items():
            if g == guild_id:
                guild_member_count += 1
                gs = data.get("GS", 0)
                weapons = data.get("weapons") or None
                _logger.debug(
                    f"[GuildMembers] Member {member_id}: GS={gs}, weapons={weapons}"
                )
                if gs in (0, "0", 0.0, None) or not weapons:
                    incomplete_members.append(member_id)
                    _logger.debug(
                        f"[GuildMembers] Member {member_id} has incomplete profile"
                    )

        _logger.debug(
            f"[GuildMembers] notify_incomplete_profiles: Found {guild_member_count} members for guild {guild_id}"
        )
        _logger.debug(
            f"[GuildMembers] notify_incomplete_profiles: Found {len(incomplete_members)} incomplete members"
        )

        if not incomplete_members:
            msg = await get_user_message(
                ctx, GUILD_MEMBERS["notify_profile"], "no_inc_profiles"
            )
            await ctx.followup.send(msg, ephemeral=True)
            return

        dm_message = await get_user_message(
            ctx, GUILD_MEMBERS["notify_profile"], "mp_sent"
        )

        dm_semaphore = asyncio.Semaphore(5)

        dm_tasks = []
        not_in_guild = 0
        for member_id in incomplete_members:
            member = guild.get_member(member_id)
            if member:
                dm_tasks.append(self._safe_dm(member, dm_message, dm_semaphore))
            else:
                not_in_guild += 1

        if dm_tasks:
            _logger.info(f"[GuildMembers] Sending {len(dm_tasks)} DMs (count={len(dm_tasks)}, concurrency=5)")
            results = await asyncio.gather(*dm_tasks, return_exceptions=True)

            successes = sum(1 for result in results if result is True)
            failures = len(results) - successes

            stats_msg = await get_user_message(
                ctx,
                GUILD_MEMBERS["notify_profile"],
                "dm_stats",
                sent=successes,
                failed=failures,
                not_in_guild=not_in_guild,
            ) or f"📊 Résultats MP : {successes} envoyés, {failures} échoués, {not_in_guild} pas dans la guilde"
        else:
            successes = 0
            failures = not_in_guild
            stats_msg = await get_user_message(
                ctx,
                GUILD_MEMBERS["notify_profile"],
                "dm_stats_simple",
                not_in_guild=not_in_guild,
            ) or f"📊 Résultats MP : 0 envoyé, {not_in_guild} pas dans la guilde"

        msg = await get_user_message(
            ctx,
            GUILD_MEMBERS["notify_profile"],
            "success",
            successes=successes,
            failures=failures,
        )
        enhanced_msg = f"{msg}\n\n{stats_msg}"
        await ctx.followup.send(enhanced_msg, ephemeral=True)

    @admin_rate_limit(cooldown_seconds=300)
    async def config_roster(
        self,
        ctx: discord.ApplicationContext,
        tank: int = discord.Option(
            int,
            description=GUILD_MEMBERS.get("config_roster", {})
            .get("options", {})
            .get("tank", {})
            .get("description", {})
            .get("en-US", "Ideal number of Tanks"),
            description_localizations=GUILD_MEMBERS.get("config_roster", {})
            .get("options", {})
            .get("tank", {})
            .get("description", {}),
            min_value=0,
            max_value=100,
            default=20,
        ),
        healer: int = discord.Option(
            int,
            description=GUILD_MEMBERS.get("config_roster", {})
            .get("options", {})
            .get("healer", {})
            .get("description", {})
            .get("en-US", "Ideal number of Healers"),
            description_localizations=GUILD_MEMBERS.get("config_roster", {})
            .get("options", {})
            .get("healer", {})
            .get("description", {}),
            min_value=0,
            max_value=100,
            default=20,
        ),
        flanker: int = discord.Option(
            int,
            description=GUILD_MEMBERS.get("config_roster", {})
            .get("options", {})
            .get("flanker", {})
            .get("description", {})
            .get("en-US", "Ideal number of Flankers"),
            description_localizations=GUILD_MEMBERS.get("config_roster", {})
            .get("options", {})
            .get("flanker", {})
            .get("description", {}),
            min_value=0,
            max_value=100,
            default=10,
        ),
        ranged_dps: int = discord.Option(
            int,
            description=GUILD_MEMBERS.get("config_roster", {})
            .get("options", {})
            .get("ranged_dps", {})
            .get("description", {})
            .get("en-US", "Ideal number of Ranged DPS"),
            description_localizations=GUILD_MEMBERS.get("config_roster", {})
            .get("options", {})
            .get("ranged_dps", {})
            .get("description", {}),
            min_value=0,
            max_value=100,
            default=10,
        ),
        melee_dps: int = discord.Option(
            int,
            description=GUILD_MEMBERS.get("config_roster", {})
            .get("options", {})
            .get("melee_dps", {})
            .get("description", {})
            .get("en-US", "Ideal number of Melee DPS"),
            description_localizations=GUILD_MEMBERS.get("config_roster", {})
            .get("options", {})
            .get("melee_dps", {})
            .get("description", {}),
            min_value=0,
            max_value=100,
            default=10,
        ),
    ):
        """
        Configure ideal roster sizes by class for the guild.

        Args:
            ctx: Discord application context
            tank: Ideal number of Tank class members
            healer: Ideal number of Healer class members
            flanker: Ideal number of Flanker class members
            ranged_dps: Ideal number of Ranged DPS class members
            melee_dps: Ideal number of Melee DPS class members

        Returns:
            None
        """
        if not getattr(ctx.user, "guild_permissions", None) or not ctx.user.guild_permissions.manage_guild:
            return await ctx.respond("❌ You need Manage Server permission.", ephemeral=True)
            
        await ctx.defer(ephemeral=True)

        if not ctx.guild or not ctx.author:
            _logger.error(
                "[GuildMembers - ConfigRoster] Invalid context: missing guild or author"
            )
            invalid_context_msg = await get_user_message(
                ctx, GUILD_MEMBERS["config_roster"], "messages.invalid_context"
            )
            await ctx.followup.send(invalid_context_msg, ephemeral=True)
            return

        guild_id = ctx.guild.id

        class_config = {
            "Tank": tank,
            "Healer": healer,
            "Flanker": flanker,
            "Ranged DPS": ranged_dps,
            "Melee DPS": melee_dps,
        }

        try:
            for class_name, count in class_config.items():
                query = """
                    INSERT INTO guild_ideal_staff (guild_id, class_name, ideal_count) 
                    VALUES (%s, %s, %s) 
                    ON DUPLICATE KEY UPDATE ideal_count = VALUES(ideal_count)
                """
                await self.bot.run_db_query(
                    query, (guild_id, class_name, count), commit=True
                )

            await self.bot.cache_loader.reload_category("guild_ideal_staff")

            await self.update_recruitment_message(ctx)

            config_summary = "\n".join(
                [
                    f"- **{class_name}** : {count}"
                    for class_name, count in class_config.items()
                ]
            )
            success_msg = await get_user_message(
                ctx,
                GUILD_MEMBERS["config_roster"],
                "messages.success",
                config_summary=config_summary,
            )

            await ctx.followup.send(success_msg, ephemeral=True)
            _logger.debug(
                f"[GuildMembers - ConfigRoster] Ideal staff configuration updated for guild {guild_id}: {class_config}"
            )

        except Exception as e:
            _logger.exception(
                f"[GuildMembers - ConfigRoster] Error updating ideal staff config for guild {guild_id}: {e}"
            )
            error_msg = await get_user_message(
                ctx, GUILD_MEMBERS["config_roster"], "messages.update_error"
            )
            await ctx.followup.send(error_msg, ephemeral=True)

    async def change_language(
        self,
        ctx: discord.ApplicationContext,
        language: str = discord.Option(
            str,
            description=GUILD_MEMBERS.get("change_language", {}).get("options", {}).get("language", {}).get("description", {}).get("en-US", "Select your preferred language"),
            description_localizations=GUILD_MEMBERS.get("change_language", {}).get("options", {}).get("language", {}).get("description", {}),
            choices=[
                discord.OptionChoice(
                    name=global_translations.get("global", {}).get("language_names", {}).get(locale, locale),
                    value=locale,
                )
                for locale in global_translations.get("global", {}).get("supported_locales", ["en-US"])
            ],
        ),
    ):
        """
        Change member's preferred language.

        Args:
            ctx: Discord application context
            language: New language code to set

        Returns:
            None
        """
        await ctx.defer(ephemeral=True)

        if not ctx.guild or not ctx.author:
            _logger.error(
                "[GuildMembers - ChangeLanguage] Invalid context: missing guild or author"
            )
            return

        guild_id = ctx.guild.id
        member_id = ctx.author.id

        if not self._validate_language_code(language):
            _logger.warning(
                f"[GuildMembers - ChangeLanguage] Invalid language code attempted: {language}"
            )
            error_msg = await get_user_message(
                ctx, GUILD_MEMBERS["change_language"], "messages.error", 
                error="Invalid language code"
            )
            await ctx.followup.send(error_msg, ephemeral=True)
            return

        member_data = await self._ensure_member_entry(guild_id, ctx.author)
        if not member_data:
            not_registered_msg = await get_user_message(
                ctx, GUILD_MEMBERS["change_language"], "messages.not_registered"
            )
            await ctx.followup.send(not_registered_msg, ephemeral=True)
            return

        try:
            upsert_query = """
                INSERT INTO guild_members (guild_id, member_id, language)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE language = VALUES(language)
            """
            await self.bot.run_db_query(
                upsert_query, (guild_id, member_id, language), commit=True
            )

            await self.update_guild_member_cache(
                guild_id, member_id, "language", language
            )

            language_name = (
                global_translations["global"]
                .get("language_names", {})
                .get(language, language)
            )

            success_msg = await get_user_message(
                ctx,
                GUILD_MEMBERS["change_language"],
                "messages.success",
                language_name=language_name,
            )
            await ctx.followup.send(success_msg, ephemeral=True)

            _logger.debug(
                f"[GuildMembers - ChangeLanguage] Language updated for user {member_id} in guild {guild_id}: {language}"
            )

        except Exception as e:
            _logger.exception(
                f"[GuildMembers - ChangeLanguage] Error updating language for user {member_id} in guild {guild_id}: {e}"
            )
            error_msg = await get_user_message(
                ctx, GUILD_MEMBERS["change_language"], "messages.error", error=str(e)
            )
            await ctx.followup.send(error_msg, ephemeral=True)

    @discord_resilient()
    async def run_maj_roster(self, guild_id: int) -> None:
        """
        Run roster update for a specific guild.

        Args:
            guild_id: The ID of the guild to update roster for

        Returns:
            None
        """
        guild_ptb_config = await self.bot.cache.get_guild_data(guild_id, "ptb_settings")
        if guild_ptb_config and guild_ptb_config.get("is_ptb_guild", False):
            _logger.debug(
                f"[GuildMembers] Skipping roster update for PTB guild {guild_id}"
            )
            return

        guild_settings = await self.bot.cache.get_guild_data(guild_id, "settings")
        if not guild_settings or not guild_settings.get("initialized", False):
            _logger.debug(
                f"[GuildMembers] Skipping roster update for unconfigured guild {guild_id}"
            )
            return

        roles_config = await self.bot.cache.get_guild_data(guild_id, "roles")
        if not roles_config:
            _logger.debug(f"No roles configured for guild {guild_id}")
            return

        members_role_id = roles_config.get("members")
        absent_role_id = roles_config.get("absent_members")
        if not members_role_id:
            _logger.error(
                f"[GuildMembers] Members role not configured for guild {guild_id}"
            )
            return

        guild = self.bot.get_guild(guild_id)
        if not guild:
            _logger.error(f"Guild {guild_id} not found on Discord")
            return

        actual_members = {
            m.id: m
            for m in guild.members
            if not m.bot
            and (
                members_role_id in [r.id for r in m.roles]
                or absent_role_id in [r.id for r in m.roles]
            )
        }

        guild_members = await self.get_guild_members()
        to_delete = []
        for (g, user_id), data in guild_members.items():
            if g == guild_id and user_id not in actual_members:
                delete_query = (
                    "DELETE FROM guild_members WHERE guild_id = %s AND member_id = %s"
                )
                await self.bot.run_db_query(
                    delete_query, (guild_id, user_id), commit=True
                )
                to_delete.append(user_id)

        user_setup_members = await self.get_user_setup_members()
        for member in actual_members.values():
            key = (guild_id, member.id)
            if key in guild_members:
                record = guild_members[key]
                if record.get("username") != member.display_name:
                    upsert_query = """
                        INSERT INTO guild_members (guild_id, member_id, username)
                        VALUES (%s, %s, %s)
                        ON DUPLICATE KEY UPDATE username = VALUES(username)
                    """
                    await self.bot.run_db_query(
                        upsert_query,
                        (guild_id, member.id, member.display_name),
                        commit=True,
                    )
                    _logger.debug(
                        f"[GuildMembers] Username updated for {member.display_name} (ID: {member.id})"
                    )
            else:
                key_setup = (guild_id, member.id)
                user_setup = user_setup_members.get(key_setup, {})
                if user_setup:
                    language = user_setup.get("locale") or "en-US"
                    gs_value = user_setup.get("gs")
                    _logger.debug(
                        f"[GuildMembers] User setup values for {member.display_name}: language={language}, gs={gs_value}"
                    )
                else:
                    language = "en-US"
                    gs_value = 0
                    _logger.debug(
                        f"[GuildMembers] No user_setup info for {member.display_name}. Default values: language={language}, gs={gs_value}"
                    )
                if gs_value in (None, ""):
                    gs_value = 0
                new_record = {
                    "username": member.display_name,
                    "language": language,
                    "GS": gs_value,
                    "build": None,
                    "weapons": None,
                    "DKP": 0,
                    "nb_events": 0,
                    "registrations": 0,
                    "attendances": 0,
                    "class_member": None,
                }
                insert_query = """
                    INSERT INTO guild_members 
                    (guild_id, member_id, username, language, GS, build, weapons, DKP, nb_events, registrations, attendances, `class_member`)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                    username = VALUES(username),
                    language = VALUES(language),
                    GS = VALUES(GS),
                    build = VALUES(build),
                    weapons = VALUES(weapons),
                    DKP = VALUES(DKP),
                    nb_events = VALUES(nb_events),
                    registrations = VALUES(registrations),
                    attendances = VALUES(attendances),
                    `class_member` = VALUES(`class_member`)
                """
                await self.bot.run_db_query(
                    insert_query,
                    (
                        guild_id,
                        member.id,
                        new_record["username"],
                        new_record["language"],
                        new_record["GS"],
                        new_record["build"],
                        new_record["weapons"],
                        new_record["DKP"],
                        new_record["nb_events"],
                        new_record["registrations"],
                        new_record["attendances"],
                        new_record["class_member"],
                    ),
                    commit=True,
                )
                _logger.debug(
                    f"[GuildMembers] New member added: {member.display_name} (ID: {member.id})"
                )

        try:
            await self._load_members_data()
            await self.update_recruitment_message(guild)
            await self.update_members_message(guild)
            _logger.info(
                f"[GuildMembers] Roster synchronization completed for guild {guild_id}"
            )
        except Exception as e:
            _logger.exception(
                f"[GuildMembers] Error during roster synchronization for guild {guild_id}: {e}"
            )

    @commands.Cog.listener()
    @discord_resilient()
    async def on_ready(self):
        """
        Initialize guild members data on bot ready with enterprise-grade initialization.
        
        Coordinates initial data loading with proper error handling and graceful degradation.
        """
        try:
            _logger.info("guild_members_cog_initializing_on_ready")

            cache_task = asyncio.create_task(
                self.bot.cache_loader.wait_for_initial_load(),
                name="guild_members_initial_cache_load"
            )

            def cache_load_done(task):
                if task.exception():
                    _logger.error("initial_cache_load_failed", 
                                error=str(task.exception()))
                else:
                    _logger.info("initial_cache_load_completed_successfully")
            
            cache_task.add_done_callback(cache_load_done)
            
            _logger.info("guild_members_cog_ready_initialization_complete")
            
        except Exception as e:
            _logger.error("guild_members_on_ready_initialization_failed", 
                         error=str(e), exc_info=True)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """
        Sync member nickname changes to PTB guild.

        Args:
            before: Member state before the update
            after: Member state after the update

        Returns:
            None
        """
        try:
            if before.display_name == after.display_name:
                return

            guild_ptb_cog = self.bot.get_cog("GuildPTB")
            if not guild_ptb_cog:
                return

            main_guild_id = after.guild.id

            ptb_settings = await guild_ptb_cog.get_guild_ptb_settings(main_guild_id)
            if not ptb_settings:
                return

            ptb_guild_id = ptb_settings.get("ptb_guild_id")
            if not ptb_guild_id:
                return

            ptb_guild = self.bot.get_guild(ptb_guild_id)
            if not ptb_guild:
                return

            ptb_member = ptb_guild.get_member(after.id)
            if not ptb_member:
                return

            try:
                await ptb_member.edit(
                    nick=after.display_name, reason="Auto sync from main Discord server"
                )
                _logger.debug(
                    f"[GuildMembers] Synchronized PTB nickname for {after.id}: '{before.display_name}' -> '{after.display_name}'"
                )
            except discord.Forbidden:
                _logger.warning(
                    f"[GuildMembers] Cannot change PTB nickname for member - insufficient permissions"
                )
            except Exception as e:
                _logger.error(
                    f"[GuildMembers] Error changing PTB nickname for {after.id}: {e}"
                )

        except Exception as e:
            _logger.error(
                f"[GuildMembers] Error in on_member_update: {e}", exc_info=True
            )

    async def member_return(self, ctx: discord.ApplicationContext):
        """
        Allow members to signal their return from absence.

        This command removes the absent role from the member and restores
        their normal member role, then sends a notification.

        Args:
            ctx: Discord application context
        """
        await ctx.defer(ephemeral=True)

        guild = ctx.guild
        member = ctx.author

        try:
            roles_data = await self.bot.cache.get_guild_data(guild.id, "roles")
            if not roles_data:
                from app.core.translation import translations as global_translations

                error_msg = await get_user_message(
                    ctx,
                    global_translations.get("absence_system", {}),
                    "error.roles_not_configured",
                )
                await ctx.followup.send(error_msg, ephemeral=True)
                return

            role_member_id = roles_data.get("members")
            role_absent_id = roles_data.get("absent_members")

            if not role_member_id or not role_absent_id:
                from app.core.translation import translations as global_translations

                error_msg = await get_user_message(
                    ctx,
                    global_translations.get("absence_system", {}),
                    "error.roles_not_configured",
                )
                await ctx.followup.send(error_msg, ephemeral=True)
                return

            role_member = guild.get_role(role_member_id)
            role_absent = guild.get_role(role_absent_id)

            if not role_member or not role_absent:
                from app.core.translation import translations as global_translations

                error_msg = await get_user_message(
                    ctx,
                    global_translations.get("absence_system", {}),
                    "error.roles_not_configured",
                )
                await ctx.followup.send(error_msg, ephemeral=True)
                return

            if role_absent not in member.roles:
                from app.core.translation import translations as global_translations

                error_msg = await get_user_message(
                    ctx,
                    global_translations.get("absence_system", {}),
                    "error.not_absent",
                )
                await ctx.followup.send(error_msg, ephemeral=True)
                return

            try:
                await member.remove_roles(role_absent)
                _logger.debug("Removed absent role from member")

                if role_member not in member.roles:
                    await member.add_roles(role_member)
                    _logger.debug("Added member role to member")

                try:
                    select_query = "SELECT message_id FROM absence_messages WHERE guild_id = %s AND member_id = %s"
                    message_ids = await self.bot.run_db_query(
                        select_query, (guild.id, member.id), fetch_all=True
                    )

                    if message_ids:
                        channels_data = await self.bot.cache.get_guild_data(
                            guild.id, "absence_channels"
                        )
                        if channels_data and channels_data.get("abs_channel"):
                            abs_channel = self.bot.get_channel(
                                channels_data["abs_channel"]
                            )
                            if abs_channel:
                                for row in message_ids:
                                    message_id = row[0]
                                    try:
                                        message = await abs_channel.fetch_message(
                                            message_id
                                        )
                                        await message.delete()
                                        _logger.debug(
                                            f"[GuildMembers] Deleted absence message {message_id}"
                                        )
                                    except discord.NotFound:
                                        _logger.debug(
                                            f"[GuildMembers] Absence message {message_id} already deleted"
                                        )
                                    except Exception as msg_error:
                                        _logger.error(
                                            f"[GuildMembers] Error deleting message {message_id}: {msg_error}"
                                        )

                    delete_query = "DELETE FROM absence_messages WHERE guild_id = %s AND member_id = %s"
                    await self.bot.run_db_query(
                        delete_query, (guild.id, member.id), commit=True
                    )
                    _logger.debug(
                        f"[GuildMembers] Removed absence record for {member.name}"
                    )
                except Exception as db_error:
                    _logger.error(
                        f"[GuildMembers] Error removing absence record: {db_error}"
                    )

                channels_data = await self.bot.cache.get_guild_data(
                    guild.id, "absence_channels"
                )
                if channels_data and channels_data.get("forum_members_channel"):
                    guild_lang = (
                        await self.bot.cache.get_guild_data(guild.id, "guild_lang")
                        or "en-US"
                    )

                    try:
                        absence_cog = self.bot.get_cog("AbsenceManager")
                        if absence_cog:
                            await absence_cog.notify_absence(
                                member,
                                "removal",
                                channels_data["forum_members_channel"],
                                guild_lang,
                            )
                    except Exception as notify_error:
                        _logger.error(
                            f"[GuildMembers] Error sending return notification: {notify_error}"
                        )

                from app.core.translation import translations as global_translations

                success_msg = await get_user_message(
                    ctx,
                    global_translations.get("absence_system", {}),
                    "success.returned",
                )
                await ctx.followup.send(success_msg, ephemeral=True)

            except discord.Forbidden:
                from app.core.translation import translations as global_translations

                error_msg = await get_user_message(
                    ctx,
                    global_translations.get("absence_system", {}),
                    "error.no_permission",
                )
                await ctx.followup.send(error_msg, ephemeral=True)
            except Exception as role_error:
                _logger.error(f"Error managing roles: {role_error}")
                from app.core.translation import translations as global_translations

                error_msg = await get_user_message(
                    ctx, global_translations.get("absence_system", {}), "error.unknown"
                )
                await ctx.followup.send(error_msg, ephemeral=True)

        except Exception as e:
            _logger.error(
                f"[GuildMembers] Error in member_return command: {e}", exc_info=True
            )
            from app.core.translation import translations as global_translations

            error_msg = await get_user_message(
                ctx, global_translations.get("absence_system", {}), "error.unknown"
            )
            await ctx.followup.send(error_msg, ephemeral=True)

def setup(bot: discord.Bot):
    """
    Setup function for the cog.

    Args:
        bot: The Discord bot instance

    Returns:
        None
    """
    bot.add_cog(GuildMembers(bot))
