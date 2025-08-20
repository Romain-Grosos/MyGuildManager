"""
Guild Events Cog - Manages event creation, scheduling, and registration system.

Event Status Management:
- Uses normalized lowercase status values: 'planned', 'confirmed', 'canceled', 'closed'
- EventStatus class provides validation and normalization for consistent handling
- US spelling used for consistency: 'canceled' (not 'cancelled')

Database Schema Recommendations for events_data table:
- PRIMARY KEY: (guild_id, event_id) - for unique identification
- UNIQUE KEY uniq_gdt (guild_id, name, event_date, event_time) - CRITICAL anti-duplication
- INDEX: (guild_id, event_date) - for date-based queries and cron jobs
- INDEX: (guild_id, status) - for status-based filtering
- INDEX: (event_date, status) - for reminder and close cron operations
- CONSTRAINT status CHECK (status IN ('planned', 'confirmed', 'canceled', 'closed'))
  OR ENUM status ('planned', 'confirmed', 'canceled', 'closed')
  to prevent invalid status values from external writes

CRON Safety:
- All CRON functions (_delete, _reminder, _close) use locking mechanism to prevent double execution
- Locks are stored in cache with timeout for automatic cleanup
- WARNING: CRON locks are NOT distributed across multiple bot instances (multi-process deployment)
- For multi-instance deployment, consider implementing Redis/DB-based distributed locks
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import statistics
import time

from datetime import datetime, timedelta, date, time as dt_time
from typing import Optional, Any, TypedDict, cast, List

import discord
import pytz
from pytz import AmbiguousTimeError, NonExistentTimeError
from discord import NotFound, HTTPException
from discord.ext import commands

from ..core.logger import ComponentLogger

class EventRegistrations(TypedDict):
    """Event registrations structure - stores member IDs only."""
    presence: list[int]
    tentative: list[int]
    absence: list[int]

class GroupMember(TypedDict, total=False):
    """Group member data structure for display/processing."""
    user_id: int
    pseudo: str
    member_class: str
    GS: str | int
    weapons: str
    tentative: bool

class EventRowDB(TypedDict):
    """Event data structure as stored in database (JSON fields as strings)."""
    guild_id: int
    event_id: int
    game_id: int
    name: str
    event_date: str
    event_time: str
    duration: int
    dkp_value: int
    dkp_ins: int
    status: str
    initial_members: str
    registrations: str
    actual_presence: str

class EventData(TypedDict):
    """Event data structure for runtime use (JSON fields as Python objects)."""
    guild_id: int
    event_id: int
    game_id: int
    name: str
    event_date: str
    event_time: str
    duration: int
    dkp_value: int
    dkp_ins: int
    status: str
    initial_members: list[int]
    registrations: EventRegistrations
    actual_presence: list[int]

class GroupStats(TypedDict):
    """Group composition statistics."""
    size: int
    composition: str
    avg_gs: float
    tanks: int
    healers: int
    dps: int
    classes: dict[str, int]

from ..core.performance_profiler import profile_performance
from ..core.reliability import discord_resilient
from ..core.translation import translations as global_translations
from ..core.functions import get_user_message, get_guild_message, get_effective_locale

EVENT_MANAGEMENT = global_translations.get("event_management", {})
STATIC_GROUPS = global_translations.get("static_groups", {})

_logger = ComponentLogger("guild_events")

def ensure_dict_from_json(data: str | dict | None, default: dict | None = None) -> dict:
    """
    Ensure data is a dictionary, parsing from JSON string if necessary.
    
    Args:
        data: Input data (string, dict, or None)
        default: Default dictionary if parsing fails
        
    Returns:
        Dictionary representation of the data
    """
    if default is None:
        default = {}
        
    if isinstance(data, dict):
        return data
    elif isinstance(data, str):
        try:
            parsed = json.loads(data)
            return parsed if isinstance(parsed, dict) else default
        except (json.JSONDecodeError, TypeError):
            return default
    else:
        return default

def ensure_list_from_json(data: str | list | None, default: list | None = None) -> list:
    """
    Ensure data is a list, parsing from JSON string if necessary.
    
    Args:
        data: Input data (string, list, or None)
        default: Default list if parsing fails
        
    Returns:
        List representation of the data
    """
    if default is None:
        default = []
        
    if isinstance(data, list):
        return data
    elif isinstance(data, str):
        try:
            parsed = json.loads(data)
            return parsed if isinstance(parsed, list) else default
        except (json.JSONDecodeError, TypeError):
            return default
    else:
        return default

def ensure_json_string(data: dict | list | str | None, default: str = "{}") -> str:
    """
    Ensure data is a JSON string, serializing if necessary.
    
    Args:
        data: Input data (dict, list, string, or None)
        default: Default JSON string if serialization fails
        
    Returns:
        JSON string representation of the data
    """
    if isinstance(data, str):
        try:
            json.loads(data)
            return data
        except (json.JSONDecodeError, TypeError):
            return default
    elif isinstance(data, (dict, list)):
        try:
            return json.dumps(data, ensure_ascii=False, separators=(',', ':'))
        except (TypeError, ValueError):
            return default
    else:
        return default

def from_db_row(db_row: EventRowDB) -> EventData:
    """
    Convert database row format to runtime format.
    
    Args:
        db_row: Event data from database with JSON strings
        
    Returns:
        Event data with parsed Python objects for runtime use
    """
    return {
        "guild_id": db_row["guild_id"],
        "event_id": db_row["event_id"],
        "game_id": db_row["game_id"],
        "name": db_row["name"],
        "event_date": db_row["event_date"],
        "event_time": db_row["event_time"],
        "duration": db_row["duration"],
        "dkp_value": db_row["dkp_value"],
        "dkp_ins": db_row["dkp_ins"],
        "status": db_row["status"],
        "initial_members": ensure_list_from_json(db_row["initial_members"], []),
        "registrations": cast(EventRegistrations, ensure_dict_from_json(
            db_row["registrations"], 
            {"presence": [], "tentative": [], "absence": []}
        )),
        "actual_presence": ensure_list_from_json(db_row["actual_presence"], [])
    }

def validate_event_data(event_data: EventData) -> EventData:
    """
    Validate EventData structure and fix common issues.
    
    Args:
        event_data: Event data to validate
        
    Returns:
        Validated and corrected event data
        
    Raises:
        ValueError: If critical validation fails
    """
    if not isinstance(event_data, dict):
        raise ValueError("Event data must be a dictionary")

    required_fields = ["guild_id", "event_id", "name"]
    for field in required_fields:
        if field not in event_data or event_data[field] is None:
            raise ValueError(f"Missing required field: {field}")

    if "registrations" not in event_data:
        event_data["registrations"] = {"presence": [], "tentative": [], "absence": []}
    elif not isinstance(event_data["registrations"], dict):
        event_data["registrations"] = {"presence": [], "tentative": [], "absence": []}
    else:
        for key in ["presence", "tentative", "absence"]:
            if key not in event_data["registrations"]:
                event_data["registrations"][key] = []
            elif not isinstance(event_data["registrations"][key], list):
                event_data["registrations"][key] = []

    for list_field in ["initial_members", "actual_presence"]:
        if list_field not in event_data:
            event_data[list_field] = []
        elif not isinstance(event_data[list_field], list):
            event_data[list_field] = []

    event_data["status"] = EventStatus.validate(event_data.get("status", EventStatus.PLANNED))
            
    return event_data

def to_db_row(event_data: EventData) -> EventRowDB:
    """
    Convert runtime format to database row format.
    
    Args:
        event_data: Event data with Python objects
        
    Returns:
        Event data with JSON strings for database storage
    """
    return {
        "guild_id": event_data["guild_id"],
        "event_id": event_data["event_id"],
        "game_id": event_data["game_id"],
        "name": event_data["name"],
        "event_date": event_data["event_date"],
        "event_time": event_data["event_time"],
        "duration": event_data["duration"],
        "dkp_value": event_data["dkp_value"],
        "dkp_ins": event_data["dkp_ins"],
        "status": event_data["status"],
        "initial_members": ensure_json_string(event_data["initial_members"], "[]"),
        "registrations": ensure_json_string(dict(event_data["registrations"])),
        "actual_presence": ensure_json_string(event_data["actual_presence"], "[]")
    }

class EventStatus:
    """Event status constants and normalization utilities."""
    
    PLANNED = "planned"
    CONFIRMED = "confirmed" 
    CANCELED = "canceled"
    CLOSED = "closed"
    
    ALL_STATUSES = [PLANNED, CONFIRMED, CANCELED, CLOSED]
    
    @classmethod
    def normalize(cls, status: str) -> str:
        """
        Normalize status string to canonical form.
        
        Args:
            status: Status string to normalize
            
        Returns:
            Canonical status string
        """
        if not status:
            return cls.PLANNED
            
        status_map = {
            "planned": cls.PLANNED,
            "confirmed": cls.CONFIRMED,
            "canceled": cls.CANCELED,
            "cancelled": cls.CANCELED,
            "closed": cls.CLOSED
        }
        
        normalized = status_map.get(status.lower())
        if normalized:
            return normalized
            
        _logger.warning(
            "unknown_event_status_normalization",
            input_status=status,
            fallback=cls.PLANNED
        )
        return cls.PLANNED
    
    @classmethod
    def is_valid(cls, status: str) -> bool:
        """Check if status is valid."""
        return cls.normalize(status) in cls.ALL_STATUSES

    @classmethod
    def validate(cls, status: str) -> str:
        """
        Validate and normalize status before DB operations.
        
        Args:
            status: Status string to validate
            
        Returns:
            Validated normalized status
            
        Raises:
            ValueError: If status is not valid
        """
        normalized = cls.normalize(status)
        if normalized not in cls.ALL_STATUSES:
            raise ValueError(f"Invalid event status: {status}. Must be one of: {cls.ALL_STATUSES}")
        return normalized

def get_guild_timezone(settings: dict) -> pytz.BaseTzInfo:
    """
    Get timezone for guild from settings with fallback to Europe/Paris.
    
    Args:
        settings: Guild settings dictionary
        
    Returns:
        pytz timezone object
    """
    tz_name = settings.get("timezone", "Europe/Paris") if settings else "Europe/Paris"
    try:
        return pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        _logger.warning(
            "unknown_timezone_fallback",
            requested_timezone=tz_name,
            fallback_timezone="Europe/Paris"
        )
        return pytz.timezone("Europe/Paris")

def normalize_event_datetime(
    event_date_value: Any, 
    event_time_value: Any, 
    tz: pytz.BaseTzInfo
) -> datetime:
    """
    Normalize various date/time formats to timezone-aware datetime.
    
    Args:
        event_date_value: Date value (str, date, datetime)
        event_time_value: Time value (str, time, timedelta, datetime)
        tz: Timezone for the event
        
    Returns:
        Normalized timezone-aware datetime
    """

    if isinstance(event_date_value, datetime):
        event_date = event_date_value.date()
    elif isinstance(event_date_value, date):
        event_date = event_date_value
    elif isinstance(event_date_value, str):
        event_date = datetime.strptime(event_date_value, "%Y-%m-%d").date()
    else:
        raise ValueError(f"Invalid date type: {type(event_date_value)}")
    

    if isinstance(event_time_value, dt_time):
        event_time = event_time_value
    elif isinstance(event_time_value, timedelta):
        hours = int(event_time_value.total_seconds() // 3600)
        minutes = int((event_time_value.total_seconds() % 3600) // 60)
        event_time = dt_time(hours, minutes)
    elif isinstance(event_time_value, str):

        if len(event_time_value.split(":")) == 2:
            event_time = datetime.strptime(event_time_value, "%H:%M").time()
        else:
            event_time = datetime.strptime(event_time_value, "%H:%M:%S").time()
    elif isinstance(event_time_value, datetime):
        event_time = event_time_value.time()
    else:
        raise ValueError(f"Invalid time type: {type(event_time_value)}")
    

    naive_dt = datetime.combine(event_date, event_time)
    try:
            return tz.localize(naive_dt)
    except AmbiguousTimeError:
        _logger.warning(
        "dst_ambiguous_time_resolved",
        timezone=str(tz),
        naive_datetime=naive_dt.isoformat(),
            resolution="winter_time_selected",
            is_dst_used=False
        )
        return tz.localize(naive_dt, is_dst=False)
    except NonExistentTimeError:
        _logger.warning(
        "dst_nonexistent_time_resolved", 
        timezone=str(tz),
        naive_datetime=naive_dt.isoformat(),
            resolution="summer_time_selected",
            is_dst_used=True
        )
        return tz.localize(naive_dt, is_dst=True)

def datetime_to_db_format(dt: datetime) -> tuple[str, str]:
    """
    Convert datetime to DB format (date, time strings).
    
    Args:
        dt: Datetime object (can be timezone-aware or naive)
        
    Returns:
        Tuple of (date_str, time_str) for DB storage
    """
    return (dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S"))

def normalize_date_only(date_value: Any) -> date:
    """
    Normalize various date formats to date object.
    
    Args:
        date_value: Date value (str, date, datetime)
        
    Returns:
        Normalized date object
    """
    if isinstance(date_value, datetime):
        return date_value.date()
    elif isinstance(date_value, date):
        return date_value
    elif isinstance(date_value, str):
        date_str = date_value.strip()
        if not date_str:
            raise ValueError("Empty date string")

        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            for fmt in ["%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"]:
                try:
                    return datetime.strptime(date_str, fmt).date()
                except ValueError:
                    continue
        raise ValueError(f"Invalid date format: {date_str}")
    else:
        raise ValueError(f"Invalid date type: {type(date_value)}")

def is_same_date(event_date_value, target_date: date) -> bool:
    """
    Robust date comparison that handles various date formats.
    
    Args:
        event_date_value: Event date (can be string, datetime, date, or None)
        target_date: Target date to compare against (date object)
    
    Returns:
        bool: True if dates match, False otherwise
    """
    if not event_date_value:
        return False
        
    try:
        normalized_date = normalize_date_only(event_date_value)
        return normalized_date == target_date
    except (ValueError, TypeError):
        return False

GROUP_MIN_SIZE = 4
GROUP_MAX_SIZE = 6

def _parse_gs(val) -> int:
    """
    Parse GS value from various formats (int, float, string with comma/dot).
    
    Args:
        val: GS value in any format
        
    Returns:
        int: Parsed GS value, 0 if parsing fails
    """
    try:
        return int(float(str(val).replace(",", ".").strip()))
    except (ValueError, TypeError, AttributeError):
        return 0

def _fit_mentions(tokens: list[str], limit: int = 1024) -> str:
    """
    Fit mentions list within Discord embed field limits with precise counting.
    
    Args:
        tokens: List of mention strings to fit
        limit: Maximum character limit (default: 1024 for embed fields)
        
    Returns:
        str: Formatted mentions string with exact hidden count if needed
    """
    out, cur_len, shown = [], 0, 0
    for i, tok in enumerate(tokens):
        add = (", " if shown else "") + tok
        if cur_len + len(add) > limit:
            hidden = len(tokens) - shown
            return (", ".join(out)) + (f"\n… (+{hidden} de plus)" if hidden > 0 else "")
        out.append(tok)
        shown += 1
        cur_len += len(add)
    return ", ".join(out) if out else ""

WEAPON_EMOJIS = {
    "B": "<:TL_B:1362340360470270075>",
    "CB": "<:TL_CB:1362340413142335619>",
    "DG": "<:TL_DG:1362340445148938251>",
    "GS": "<:TL_GS:1362340479819059211>",
    "S": "<:TL_S:1362340495447167048>",
    "SNS": "<:TL_SNS:1362340514002763946>",
    "SP": "<:TL_SP:1362340530062888980>",
    "W": "<:TL_W:1362340545376030760>",
}

CLASS_EMOJIS = {
    "Tank": "<:tank:1374760483164524684>",
    "Healer": "<:healer:1374760495613218816>",
    "Melee DPS": "<:DPS:1374760287491850312>",
    "Ranged DPS": "<:DPS:1374760287491850312>",
    "Flanker": "<:flank:1374762529036959854>",
}

class GuildEvents(commands.Cog):
    """
    Discord cog for managing guild events and group systems.

    This cog provides comprehensive event management functionality including:
    - Automated event creation based on calendar schedules
    - Manual event creation with custom parameters
    - Event registration system with reaction-based interaction
    - Automatic group formation for balanced team composition
    - Static group management for recurring events
    - Event confirmation, cancellation, and cleanup processes
    - Integration with DKP (Dragon Kill Points) systems
    - Multi-language support for international guilds

    The cog handles both premium and standard guild features, with enhanced
    functionality available for premium subscribers.
    """
    
    EMOJI_YES = discord.PartialEmoji.from_str("<:_yes_:1340109996666388570>")
    EMOJI_MAYBE = discord.PartialEmoji.from_str("<:_attempt_:1340110058692018248>")
    EMOJI_NO = discord.PartialEmoji.from_str("<:_no_:1340110124521357313>")

    def __init__(self, bot: discord.Bot) -> None:
        """
        Initialize the GuildEvents cog.

        Args:
            bot: Discord bot instance to register the cog with

        Returns:
            None
        """
        self.bot = bot

        self._register_events_commands()
        self._register_statics_commands()
        self.json_lock = asyncio.Lock()
        self.ignore_removals = {}
        self.scheduled_tasks = set()
        
        self.VALID_EMOJIS = {
            str(self.EMOJI_YES): self.EMOJI_YES,
            str(self.EMOJI_MAYBE): self.EMOJI_MAYBE,
            str(self.EMOJI_NO): self.EMOJI_NO
        }

    async def _t(self, guild_id: int, *keys: str) -> dict[str, str]:
        """
        Batch fetch translations to avoid multiple awaits.
        
        Args:
            guild_id: Discord guild ID
            *keys: Translation keys to fetch
            
        Returns:
            Dictionary mapping keys to translated values
        """
        vals = await asyncio.gather(*[
            get_guild_message(self.bot, guild_id, EVENT_MANAGEMENT, k) for k in keys
        ])
        result = {}
        for k, v in zip(keys, vals):
            if v:
                result[k] = v
            else:
                fallback = k.split('.')[-1].replace('_', ' ').title()
                result[k] = fallback
                _logger.warning(
                    "translation_missing_using_fallback",
                    guild_id=guild_id,
                    translation_key=k,
                    fallback=fallback
                )
        return result

    async def _invalidate_all_event_caches(self, guild_id: int, event_id: Optional[int] = None):
        """
        Comprehensive cache invalidation for event-related data.
        
        Args:
            guild_id: Discord guild ID
            event_id: Optional specific event ID to invalidate
        """
        await self.bot.cache.delete_guild_data(guild_id, "events_data")
        _logger.debug("events_data_cache_invalidated", guild_id=guild_id)

        if event_id:
            await self.bot.cache.delete_guild_data(guild_id, f"event_{event_id}")
            _logger.debug("individual_event_cache_invalidated", guild_id=guild_id, event_id=event_id)
            
    async def _invalidate_events_list_cache(self, guild_id: int):
        """
        Invalidate events_data cache for a guild to ensure fresh data.
        
        Args:
            guild_id: Discord guild ID
        """
        await self.bot.cache.delete_guild_data(guild_id, "events_data")
        _logger.debug("events_data_cache_invalidated", guild_id=guild_id)

    def _localize_safe(self, tz, naive_dt: datetime) -> datetime:
        """
        Safely localize a naive datetime, handling DST transitions.
        
        DST Policy (consistent with normalize_event_datetime):
        - Ambiguous times (fall back): Use winter time (is_dst=False)
        - Non-existent times (spring forward): Use summer time (is_dst=True)
        
        Args:
            tz: Timezone object
            naive_dt: Naive datetime to localize
            
        Returns:
            Localized datetime
        """
        try:
            return tz.localize(naive_dt)
        except AmbiguousTimeError:
            _logger.warning(
                "dst_ambiguous_time_resolved_safe_localize",
                timezone=str(tz),
                naive_datetime=naive_dt.isoformat(),
                resolution="winter_time_selected",
                is_dst_used=False
            )
            return tz.localize(naive_dt, is_dst=False)
        except NonExistentTimeError:
            _logger.warning(
                "dst_nonexistent_time_resolved_safe_localize",
                timezone=str(tz), 
                naive_datetime=naive_dt.isoformat(),
                resolution="summer_time_selected",
                is_dst_used=True
            )
            return tz.localize(naive_dt, is_dst=True)

    async def _create_event_embed(
        self, 
        event_name: str, 
        description: str, 
        start_dt: datetime, 
        duration: int,
        status: str, 
        dkp_value: int, 
        dkp_ins: int,
        translations: dict,
        embed_color: discord.Color = discord.Color.blue()
    ) -> discord.Embed:
        """
        Create standardized event embed with common fields.
        
        Args:
            event_name: Name of the event
            description: Event description  
            start_dt: Event start datetime
            duration: Event duration in minutes
            status: Event status (localized)
            dkp_value: DKP value for event
            dkp_ins: DKP instance value
            translations: Localized field labels
            embed_color: Embed color (default blue)
            
        Returns:
            Configured Discord embed for the event
        """
        embed = discord.Embed(
            title=event_name, description=description, color=embed_color
        )
        embed.add_field(
            name=translations["date"],
            value=start_dt.strftime("%d-%m-%Y"),
            inline=True,
        )
        embed.add_field(
            name=translations["hour"], 
            value=start_dt.strftime("%H:%M"),
            inline=True,
        )
        embed.add_field(
            name=translations["duration"],
            value=str(duration),
            inline=True,
        )
        embed.add_field(
            name=translations["status"],
            value=status,
            inline=True,
        )
        embed.add_field(
            name=translations["dkp_v"],
            value=str(dkp_value),
            inline=True,
        )
        embed.add_field(
            name=translations["dkp_i"],
            value=str(dkp_ins),
            inline=True,
        )
        embed.add_field(
            name=f"{translations['present']} {self.EMOJI_YES} (0)",
            value=translations["none"],
            inline=False,
        )
        embed.add_field(
            name=f"{translations['attempt']} {self.EMOJI_MAYBE} (0)", 
            value=translations["none"],
            inline=False,
        )
        embed.add_field(
            name=f"{translations['absence']} {self.EMOJI_NO} (0)",
            value=translations["none"],
            inline=False,
        )
        return embed

    def _register_events_commands(self):
        """Register event commands with the centralized events group."""
        if hasattr(self.bot, "events_group"):

            self.bot.events_group.command(
                name=EVENT_MANAGEMENT.get("event_create", {})
                .get("name", {})
                .get("en-US", "create"),
                description=EVENT_MANAGEMENT.get("event_create", {})
                .get("description", {})
                .get("en-US", "Create a guild event"),
                name_localizations=EVENT_MANAGEMENT.get("event_create", {}).get(
                    "name", {}
                ),
                description_localizations=EVENT_MANAGEMENT.get("event_create", {}).get(
                    "description", {}
                ),
            )(self.event_create)

            self.bot.events_group.command(
                name=EVENT_MANAGEMENT.get("event_confirm", {})
                .get("name", {})
                .get("en-US", "confirm"),
                description=EVENT_MANAGEMENT.get("event_confirm", {})
                .get("description", {})
                .get("en-US", "Confirm an event"),
                name_localizations=EVENT_MANAGEMENT.get("event_confirm", {}).get(
                    "name", {}
                ),
                description_localizations=EVENT_MANAGEMENT.get("event_confirm", {}).get(
                    "description", {}
                ),
            )(self.event_confirm)

            self.bot.events_group.command(
                name=EVENT_MANAGEMENT.get("event_cancel", {})
                .get("name", {})
                .get("en-US", "cancel"),
                description=EVENT_MANAGEMENT.get("event_cancel", {})
                .get("description", {})
                .get("en-US", "Cancel an event"),
                name_localizations=EVENT_MANAGEMENT.get("event_cancel", {}).get(
                    "name", {}
                ),
                description_localizations=EVENT_MANAGEMENT.get("event_cancel", {}).get(
                    "description", {}
                ),
            )(self.event_cancel)

            self.bot.events_group.command(
                name=EVENT_MANAGEMENT.get("preview_groups", {})
                .get("name", {})
                .get("en-US", "preview_groups"),
                description=EVENT_MANAGEMENT.get("preview_groups", {})
                .get("description", {})
                .get("en-US", "Preview groups before creation"),
                name_localizations=EVENT_MANAGEMENT.get("preview_groups", {}).get(
                    "name", {}
                ),
                description_localizations=EVENT_MANAGEMENT.get(
                    "preview_groups", {}
                ).get("description", {}),
            )(self.preview_groups)

    def _register_statics_commands(self):
        """Register static group commands with the centralized statics group."""
        if hasattr(self.bot, "statics_group"):

            self.bot.statics_group.command(
                name=STATIC_GROUPS.get("static_create", {})
                .get("name", {})
                .get("en-US", "group_create"),
                description=STATIC_GROUPS.get("static_create", {})
                .get("description", {})
                .get("en-US", "Create a static group"),
                name_localizations=STATIC_GROUPS.get("static_create", {}).get(
                    "name", {}
                ),
                description_localizations=STATIC_GROUPS.get("static_create", {}).get(
                    "description", {}
                ),
            )(self.static_create)

            self.bot.statics_group.command(
                name=STATIC_GROUPS.get("static_add", {})
                .get("name", {})
                .get("en-US", "player_add"),
                description=STATIC_GROUPS.get("static_add", {})
                .get("description", {})
                .get("en-US", "Add player to static group"),
                name_localizations=STATIC_GROUPS.get("static_add", {}).get(
                    "name", {}
                ),
                description_localizations=STATIC_GROUPS.get("static_add", {}).get(
                    "description", {}
                ),
            )(self.static_add)

            self.bot.statics_group.command(
                name=STATIC_GROUPS.get("static_remove", {})
                .get("name", {})
                .get("en-US", "player_remove"),
                description=STATIC_GROUPS.get("static_remove", {})
                .get("description", {})
                .get("en-US", "Remove player from static group"),
                name_localizations=STATIC_GROUPS.get("static_remove", {}).get(
                    "name", {}
                ),
                description_localizations=STATIC_GROUPS.get("static_remove", {}).get(
                    "description", {}
                ),
            )(self.static_remove)

            self.bot.statics_group.command(
                name=STATIC_GROUPS.get("static_delete", {})
                .get("name", {})
                .get("en-US", "group_delete"),
                description=STATIC_GROUPS.get("static_delete", {})
                .get("description", {})
                .get("en-US", "Delete a static group"),
                name_localizations=STATIC_GROUPS.get("static_delete", {}).get(
                    "name", {}
                ),
                description_localizations=STATIC_GROUPS.get("static_delete", {}).get(
                    "description", {}
                ),
            )(self.static_delete)

            self.bot.statics_group.command(
                name=STATIC_GROUPS.get("static_update", {})
                .get("name", {})
                .get("en-US", "update"),
                description=STATIC_GROUPS.get("static_update", {})
                .get("description", {})
                .get("en-US", "Update static groups message"),
                name_localizations=STATIC_GROUPS.get("static_update", {}).get(
                    "name", {}
                ),
                description_localizations=STATIC_GROUPS.get("static_update", {}).get(
                    "description", {}
                ),
            )(self.static_update)

    @commands.Cog.listener()
    async def on_ready(self):
        """
        Initialize events data when bot is ready.

        Args:
            None

        Returns:
            None
        """
        self._ready_once = getattr(self, "_ready_once", False)
        if self._ready_once:
            return
        self._ready_once = True
        
        asyncio.create_task(self.bot.cache_loader.wait_for_initial_load())
        _logger.debug("waiting_cache_load")

    async def get_event_from_cache(
        self, guild_id: int, event_id: int
    ) -> Optional[EventData]:
        """
        Get event data with fallback strategy: individual cache -> events_data cache -> database.

        Args:
            guild_id: Discord guild ID
            event_id: Unique event identifier

        Returns:
            Dictionary containing event data if found, None otherwise
        """
        if not isinstance(guild_id, int) or not isinstance(event_id, int):
            _logger.error(
                "cache_get_invalid_params",
                guild_id=guild_id,
                event_id=event_id,
                guild_id_type=type(guild_id),
                event_id_type=type(event_id)
            )
            return None
            
        if event_id <= 0 or guild_id <= 0:
            _logger.error(
                "cache_get_invalid_values",
                guild_id=guild_id,
                event_id=event_id
            )
            return None
            
        try:
            event_data = await self.bot.cache.get_guild_data(
                guild_id, f"event_{event_id}"
            )
            
            if event_data:
                db_row_with_guild = event_data.copy()
                db_row_with_guild["guild_id"] = guild_id
                event_data = from_db_row(db_row_with_guild)
                _logger.debug(
                    "event_found_in_individual_cache",
                    event_id=event_id,
                    guild_id=guild_id
                )
            else:
                _logger.debug(
                    "event_not_in_individual_cache_trying_events_data",
                    event_id=event_id,
                    guild_id=guild_id
                )
                
                events_cache = await self.bot.cache.get_guild_data(guild_id, "events_data")
                if events_cache:
                    for cached_event in events_cache:
                        if cached_event.get("event_id") == event_id:
                            event_data = cached_event.copy()
                            event_data["guild_id"] = guild_id
                            _logger.debug(
                                "event_found_in_events_data_cache",
                                event_id=event_id,
                                guild_id=guild_id
                            )
                            break
                
                if not event_data:
                    _logger.info(
                        "event_not_in_cache_fallback_db",
                        event_id=event_id,
                        guild_id=guild_id
                    )
                    
                    query = """
                        SELECT event_id, game_id, name, event_date, event_time, duration, 
                               dkp_value, dkp_ins, status, registrations, actual_presence, initial_members
                        FROM events_data WHERE guild_id = %s AND event_id = %s
                    """
                    
                    row = await self.bot.run_db_query(query, (guild_id, event_id), fetch_one=True)
                    if row:
                        (
                            db_event_id, game_id, name, event_date, event_time, duration,
                            dkp_value, dkp_ins, status, registrations, actual_presence, initial_members
                        ) = row

                        db_row: EventRowDB = {
                            "guild_id": guild_id,
                            "event_id": db_event_id,
                            "game_id": game_id,
                            "name": name,
                            "event_date": event_date,
                            "event_time": event_time,
                            "duration": duration,
                            "dkp_value": dkp_value,
                            "dkp_ins": dkp_ins,
                            "status": status,
                            "registrations": registrations or '{"presence":[],"tentative":[],"absence":[]}',
                            "actual_presence": actual_presence or "[]",
                            "initial_members": initial_members or "[]",
                        }
                        event_data = from_db_row(db_row)
                        
                        _logger.info(
                            "event_found_in_db_hydrating_cache",
                            event_id=event_id,
                            guild_id=guild_id
                        )

                        await self.set_event_in_cache(guild_id, event_id, event_data)
                    else:
                        _logger.warning(
                            "event_not_found_anywhere",
                            event_id=event_id,
                            guild_id=guild_id
                        )
                        return None
            
                
            return event_data
            
        except Exception as e:
            _logger.error(
                "error_retrieving_event_with_fallback",
                event_id=event_id,
                guild_id=guild_id,
                error=str(e),
                exc_info=True
            )
            return None

    async def set_event_in_cache(
        self, guild_id: int, event_id: int, event_data: EventData
    ) -> None:
        """
        Set event data in global cache.

        Args:
            guild_id: Discord guild ID
            event_id: Unique event identifier
            event_data: Dictionary containing event information to store

        Returns:
            None
        """
        if not isinstance(guild_id, int) or not isinstance(event_id, int):
            _logger.error(
                "cache_set_invalid_params",
                guild_id=guild_id,
                event_id=event_id,
                guild_id_type=type(guild_id),
                event_id_type=type(event_id)
            )
            return
            
        if event_id <= 0 or guild_id <= 0:
            _logger.error(
                "cache_set_invalid_values", 
                guild_id=guild_id,
                event_id=event_id
            )
            return
            
        try:
            cache_data = to_db_row(event_data)
            cache_data.pop("guild_id", None)
                
            await self.bot.cache.set_guild_data(
                guild_id, f"event_{event_id}", cache_data
            )
        except (KeyError, AttributeError, TypeError) as e:
            _logger.error(
                "error_storing_event_cache",
                event_id=event_id,
                guild_id=guild_id,
                error=str(e),
                exc_info=True
            )

    async def delete_event_from_cache(self, guild_id: int, event_id: int) -> None:
        """
        Delete event data from global cache.

        Args:
            guild_id: Discord guild ID
            event_id: Unique event identifier

        Returns:
            None
        """
        try:
            await self.bot.cache.delete_guild_data(guild_id, f"event_{event_id}")
        except (KeyError, AttributeError) as e:
            _logger.error(
                "error_deleting_event_cache",
                event_id=event_id,
                guild_id=guild_id,
                error=str(e),
                exc_info=True,
            )


    async def get_all_guild_events(self, guild_id: int) -> list[EventData]:
        """
        Get all events for a specific guild from global cache.

        Args:
            guild_id: Discord guild ID

        Returns:
            List of dictionaries containing event data for the guild
        """
        try:
            events_cache = await self.bot.cache.get_guild_data(guild_id, "events_data")
            if events_cache:
                _logger.debug("events_retrieved_from_cache", guild_id=guild_id, count=len(events_cache))
                return events_cache

            _logger.warning("events_cache_miss_fallback_db", guild_id=guild_id)
            query = """
                SELECT event_id, game_id, name, event_date, event_time, duration, 
                       dkp_value, dkp_ins, status, registrations, actual_presence, initial_members
                FROM events_data WHERE guild_id = %s
            """
            rows = await self.bot.run_db_query(query, (guild_id,), fetch_all=True)
            events = []
            if rows:
                for row in rows:
                    (
                        event_id,
                        game_id,
                        name,
                        event_date,
                        event_time,
                        duration,
                        dkp_value,
                        dkp_ins,
                        status,
                        registrations,
                        actual_presence,
                        initial_members,
                    ) = row
                    db_row: EventRowDB = {
                        "guild_id": guild_id,
                        "event_id": event_id,
                        "game_id": game_id,
                        "name": name,
                        "event_date": event_date,
                        "event_time": event_time,
                        "duration": duration,
                        "dkp_value": dkp_value,
                        "dkp_ins": dkp_ins,
                        "status": status,
                        "registrations": registrations or '{"presence":[],"tentative":[],"absence":[]}',
                        "actual_presence": actual_presence or "[]",
                        "initial_members": initial_members or "[]",
                    }
                    event_data = from_db_row(db_row)
                    events.append(event_data)

                if events:
                    await self.bot.cache.set_guild_data(guild_id, "events_data", events)
                    _logger.info("events_cache_populated", guild_id=guild_id, count=len(events))
            return events
        except Exception as e:
            _logger.error(
                "error_retrieving_all_events",
                guild_id=guild_id,
                error=str(e),
                exc_info=True
            )
            return []

    async def get_static_group_data(
        self, guild_id: int, group_name: str
    ) -> Optional[dict]:
        """
        Get static group data from centralized cache.

        Args:
            guild_id: Discord guild ID
            group_name: Name of the static group to retrieve

        Returns:
            Dictionary containing static group data if found, None otherwise
        """
        static_groups = await self.bot.cache.get_guild_data(guild_id, "static_groups")
        if not static_groups:
            return None
        return static_groups.get(group_name)

    async def get_guild_settings(self, guild_id: int) -> dict:
        """
        Get guild settings from centralized cache.

        Args:
            guild_id: Discord guild ID

        Returns:
            Dictionary containing guild configuration settings including language, channels, roles, and premium status
        """
        guild_lang = (
            await self.bot.cache.get_guild_data(guild_id, "guild_lang") or "en-US"
        )
        guild_game = await self.bot.cache.get_guild_data(guild_id, "guild_game")
        events_channel = await self.bot.cache.get_guild_data(guild_id, "events_channel")
        notifications_channel = await self.bot.cache.get_guild_data(
            guild_id, "notifications_channel"
        )
        groups_channel = await self.bot.cache.get_guild_data(guild_id, "groups_channel")
        members_role = await self.bot.cache.get_guild_data(guild_id, "members_role")
        premium = await self.bot.cache.get_guild_data(guild_id, "premium")
        war_channel = await self.bot.cache.get_guild_data(guild_id, "voice_war_channel")

        return {
            "guild_lang": guild_lang,
            "guild_game": guild_game,
            "events_channel": events_channel,
            "notifications_channel": notifications_channel,
            "groups_channel": groups_channel,
            "members_role": members_role,
            "premium": premium,
            "war_channel": war_channel,
        }

    async def get_events_calendar_data(self, game_id: int) -> dict:
        """
        Get events calendar data from centralized cache.

        Args:
            game_id: Unique game identifier

        Returns:
            Dictionary containing events calendar data for the specified game
        """
        calendar_data = await self.bot.cache.get(
            "static_data", f"events_calendar_{game_id}"
        )

        if calendar_data is None:
            _logger.debug("events_calendar_loading", game_id=game_id)
            await self.bot.cache_loader.ensure_events_calendar_loaded()
            calendar_data = await self.bot.cache.get(
                "static_data", f"events_calendar_{game_id}"
            )

        return calendar_data or {}

    async def get_event_data(self, guild_id: int, event_id: int) -> EventData:
        """
        Get event data from centralized cache in normalized runtime format.

        Args:
            guild_id: Discord guild ID
            event_id: Unique event identifier

        Returns:
            EventData in runtime format (parsed JSON), empty dict if not found
        """
        event_data_raw = await self.bot.cache.get_guild_data(guild_id, f"event_{event_id}")
        if not event_data_raw:
            return cast(EventData, {})
        
        try:
            if "guild_id" not in event_data_raw:
                event_data_raw["guild_id"] = guild_id
            event_data = from_db_row(cast(EventRowDB, event_data_raw))
            return event_data
        except Exception as e:
            _logger.warning(
                "error_normalizing_event_data",
                guild_id=guild_id,
                event_id=event_id,
                error=str(e)
            )
            return cast(EventData, event_data_raw)

    async def get_guild_member_data(self, guild_id: int, member_id: int) -> dict:
        """
        Get guild member data from centralized cache.

        Args:
            guild_id: Discord guild ID
            member_id: Discord member ID

        Returns:
            Dictionary containing member data, empty dict if not found
        """
        member_data = await self.bot.cache.get_guild_data(
            guild_id, f"member_{member_id}"
        )
        return member_data or {}

    async def get_static_groups_data(self, guild_id: int) -> dict:
        """
        Get static groups data from centralized cache.

        Args:
            guild_id: Discord guild ID

        Returns:
            Dictionary containing all static groups data for the guild, empty dict if not found
        """
        static_groups = await self.bot.cache.get_guild_data(guild_id, "static_groups")
        return static_groups or {}

    async def get_ideal_staff_data(self, guild_id: int) -> dict:
        """
        Get ideal staff data from centralized cache.

        Args:
            guild_id: Discord guild ID

        Returns:
            Dictionary containing ideal staff composition data for the guild, empty dict if not found
        """
        staff_data = await self.bot.cache.get("guild_data", "ideal_staff")
        return staff_data.get(guild_id, {}) if staff_data else {}

    def get_next_date_for_day(
        self, day_name: str, event_time_value, tz, tomorrow_only: bool = False, guild_id: Optional[int] = None
    ) -> Optional[datetime]:
        """
        Get next occurrence date for specified day of week.

        Args:
            day_name: Name of the day (e.g., 'monday', 'tuesday')
            event_time_value: Time value as timedelta, string, or other format
            tz: Timezone object for localization
            tomorrow_only: If True, only return tomorrow's date if it matches the day

        Returns:
            Localized datetime object for the next occurrence of the specified day, None if invalid day or no match
        """

        now = datetime.now(tz)
        
        try:
            today = now.date()
            normalized_dt = normalize_event_datetime(today, event_time_value, tz)
            event_time = normalized_dt.time()
        except (ValueError, TypeError):
            _logger.warning(
                "fallback_time_21_00",
                guild_id=guild_id,
                raw_input=event_time_value
            )
            event_time = dt_time(21, 0)

        days = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
        }
        day_key = day_name.lower()
        if day_key not in days:
            _logger.debug("invalid_day", day_name=day_name)
            return None
        target_weekday = days[day_key]

        if tomorrow_only:
            tomorrow = now.date() + timedelta(days=1)
            if tomorrow.weekday() != target_weekday:
                _logger.debug(
                    "event_day_not_scheduled_tomorrow",
                    day_name=day_name,
                    tomorrow=str(tomorrow)
                )
                return None
            event_date = tomorrow
        else:
            current_weekday = now.weekday()
            days_ahead = target_weekday - current_weekday
            if days_ahead < 0 or (
                days_ahead == 0 and now.time() >= event_time
            ):
                days_ahead += 7
            event_date = now.date() + timedelta(days=days_ahead)

        naive_dt = datetime.combine(event_date, event_time)
        return self._localize_safe(tz, naive_dt)

    async def create_events_for_all_premium_guilds(self) -> None:
        """
        Create recurring events for all premium guilds based on calendar.

        Args:
            None

        Returns:
            None
        """
        for guild in self.bot.guilds:
            guild_id = guild.id
            settings = await self.bot.cache.get_guild_data(guild_id, "settings")
            premium_value = settings.get("premium") if settings else None
            is_premium = premium_value in (True, "true", "True", "yes", "Yes", 1, "1")
            if settings and is_premium:
                try:
                    await self.create_events_for_guild(guild)
                    _logger.info(
                        "events_created_premium_guild",
                        guild_id=guild_id
                    )
                except Exception as e:
                    _logger.error(
                        "error_creating_events_guild",
                        guild_id=guild_id,
                        error=str(e),
                        exc_info=True
                    )
            else:
                if not settings:
                    _logger.debug(
                        "guild_no_settings_skipping",
                        guild_id=guild_id
                    )
                else:
                    _logger.debug(
                        "guild_not_premium_skipping",
                        guild_id=guild_id
                    )

    @profile_performance(threshold_ms=100.0)
    @discord_resilient(service_name="discord_api", max_retries=2)
    async def create_events_for_guild(self, guild: discord.Guild) -> None:
        """
        Create recurring events for a specific guild based on its game calendar.

        Args:
            guild: Discord guild object to create events for

        Returns:
            None
        """
        guild_id = guild.id

        settings = await self.bot.cache.get_guild_data(guild_id, "settings")
        if not settings:
            _logger.error(
                "no_configuration_for_guild",
                guild_id=guild_id
            )
            return

        guild_lang = settings.get("guild_lang")

        channels_data = await self.bot.cache.get_guild_data(guild_id, "channels")
        if not channels_data:
            _logger.error(
                "no_channels_configuration",
                guild_id=guild_id
            )
            return

        events_channel = guild.get_channel(channels_data.get("events_channel"))
        conference_channel = guild.get_channel(channels_data.get("voice_war_channel"))
        if not events_channel:
            _logger.error(
                "events_channel_not_found",
                guild_id=guild_id
            )
            return
        if not conference_channel:
            _logger.error(
                "conference_channel_not_found",
                guild_id=guild_id
            )
            return

        try:
            game_id = int(settings.get("guild_game"))
        except (ValueError, TypeError) as e:
            _logger.error(
                "error_converting_guild_game",
                guild_id=guild_id,
                error=str(e)
            )
            return

        calendar_data = await self.get_events_calendar_data(game_id)
        calendar = calendar_data.get("events", [])
        if not calendar:
            _logger.info(
                "no_events_in_calendar",
                game_id=game_id
            )
            return

        tz = get_guild_timezone(settings)

        for cal_event in calendar:
            try:
                day = cal_event.get("day")
                event_time_str = cal_event.get("time", "21:00")
                start_time = self.get_next_date_for_day(
                    day, event_time_str, tz, tomorrow_only=True, guild_id=guild_id
                )

                if start_time is None:
                    _logger.debug(
                        "event_day_not_scheduled",
                        day=day
                    )
                    continue

                try:
                    duration_minutes = int(cal_event.get("duration", 60))
                except (ValueError, TypeError) as e:
                    _logger.warning(
                        "invalid_duration_using_default",
                        error=str(e)
                    )
                    duration_minutes = 60
                end_time = start_time + timedelta(minutes=duration_minutes)

                week_setting = cal_event.get("week", "all")
                if week_setting != "all":
                    week_number = start_time.isocalendar()[1]
                    if week_setting == "odd" and week_number % 2 == 0:
                        _logger.info(
                            "event_not_scheduled_even_week",
                            event_name=cal_event.get('name')
                        )
                        continue
                    elif week_setting == "even" and week_number % 2 != 0:
                        _logger.info(
                            "event_not_scheduled_odd_week",
                            event_name=cal_event.get('name')
                        )
                        continue

                event_key = cal_event.get("name")
                events_infos = EVENT_MANAGEMENT.get("events_infos", {})
                event_info = events_infos.get(event_key)
                event_name = (
                    event_info.get(guild_lang, event_info.get("en-US"))
                    if event_info
                    else event_key
                )

                translations = self._get_cached_translations(guild_lang, events_infos)

                try:
                    embed = await self._create_event_embed(
                        event_name=event_name,
                        description=translations["description"], 
                        start_dt=start_time,
                        duration=duration_minutes,
                        status=translations["status_planned"],
                        dkp_value=cal_event.get("dkp_value", 0),
                        dkp_ins=cal_event.get("dkp_ins", 0),
                        translations=translations
                    )
                    conference_link = f"https://discord.com/channels/{guild.id}/{conference_channel.id}"
                    embed.add_field(
                        name=translations["voice_channel"],
                        value=f"[🏹 WAR]({conference_link})",
                        inline=False,
                    )
                    embed.add_field(
                        name=translations["groups"],
                        value=translations["auto_grouping"],
                        inline=False,
                    )
                except Exception as e:
                    _logger.error(
                        "error_building_embed",
                        event_name=event_name,
                        error=str(e),
                        exc_info=True,
                    )
                    continue

                date_str, time_str = datetime_to_db_format(start_time)
                
                try:
                    announcement_task = self._send_announcement(events_channel, embed)

                    announcement = await announcement_task
                    message_link = f"https://discord.com/channels/{guild.id}/{announcement.channel.id}/{announcement.id}"

                    embed.set_footer(text=f"Event ID = {announcement.id}")
                    await announcement.edit(embed=embed)

                    description_scheduled = (
                        events_infos.get("description_scheduled", {})
                        .get(
                            guild_lang,
                            events_infos.get("description_scheduled", {}).get(
                                "en-US", "View event: {link}"
                            ),
                        )
                        .format(link=message_link)
                    )

                    scheduled_event = await self._create_scheduled_event(
                        guild,
                        event_name,
                        description_scheduled,
                        start_time,
                        end_time,
                        conference_channel,
                    )

                except Exception as e:
                    _logger.error(
                        "error_creating_announcement",
                        error=str(e),
                        exc_info=True,
                    )
                    continue

                try:
                    roles_data = await self.bot.cache.get_guild_data(guild_id, "roles")
                    members_role_id = roles_data.get("members") if roles_data else None
                    if members_role_id:
                        if hasattr(self.bot, "cache") and hasattr(
                            self.bot.cache, "get_role_members_optimized"
                        ):
                            initial_members = list(
                                await self.bot.cache.get_role_members_optimized(
                                    guild_id, int(members_role_id)
                                )
                            )
                        else:
                            role = guild.get_role(int(members_role_id))
                            if role:
                                initial_members = [
                                    member.id
                                    for member in guild.members
                                    if role in member.roles
                                ]
                            else:
                                initial_members = []
                    else:
                        initial_members = []
                except Exception as e:
                    _logger.error(
                        "error_determining_initial_members",
                        guild_id=guild_id,
                        error=str(e),
                        exc_info=True,
                    )
                    initial_members = []

                record = {
                    "guild_id": guild_id,
                    "event_id": announcement.id,
                    "game_id": game_id,
                    "name": event_name,
                    "event_date": datetime_to_db_format(start_time)[0],
                    "event_time": datetime_to_db_format(start_time)[1],
                    "duration": duration_minutes,
                    "dkp_value": cal_event.get("dkp_value", 0),
                    "dkp_ins": cal_event.get("dkp_ins", 0),
                    "status": EventStatus.validate(EventStatus.PLANNED),
                    "initial_members": ensure_json_string(initial_members, "[]"),
                    "registrations": ensure_json_string({"presence": [], "tentative": [], "absence": []}),
                    "actual_presence": ensure_json_string([], "[]"),
                }

                query = """
                INSERT IGNORE INTO events_data (
                    guild_id,
                    event_id,
                    game_id,
                    name,
                    event_date,
                    event_time,
                    duration,
                    dkp_value,
                    dkp_ins,
                    status,
                    initial_members,
                    registrations,
                    actual_presence
                ) VALUES (
                    %(guild_id)s,
                    %(event_id)s,
                    %(game_id)s,
                    %(name)s,
                    %(event_date)s,
                    %(event_time)s,
                    %(duration)s,
                    %(dkp_value)s,
                    %(dkp_ins)s,
                    %(status)s,
                    %(initial_members)s,
                    %(registrations)s,
                    %(actual_presence)s
                )
                """
                try:
                    result = await self.bot.run_db_query(query, record, commit=True, return_result=True)

                    if hasattr(result, 'lastrowid') and result.lastrowid == 0:
                        try:
                            await announcement.delete()
                            _logger.info(
                                "duplicate_event_announcement_deleted",
                                name=event_name,
                                guild_id=guild_id,
                                deleted_message_id=announcement.id
                            )
                        except Exception as del_err:
                            _logger.error(
                                "error_deleting_duplicate_announcement",
                                error=str(del_err),
                                message_id=announcement.id
                            )
                        continue

                    _logger.info(
                        "event_saved_in_db",
                        announcement_id=announcement.id
                    )

                    db_row_data = cast(EventRowDB, {
                        "guild_id": guild_id,
                        "event_id": record["event_id"],
                        "game_id": record["game_id"],
                        "name": record["name"],
                        "event_date": record["event_date"],
                        "event_time": record["event_time"],
                        "duration": record["duration"],
                        "dkp_value": record["dkp_value"],
                        "dkp_ins": record["dkp_ins"],
                        "status": record["status"],
                        "registrations": record["registrations"],
                        "actual_presence": record["actual_presence"],
                        "initial_members": record["initial_members"]
                    })
                    event_data = from_db_row(db_row_data)
                    await self.set_event_in_cache(guild_id, record["event_id"], event_data)
                    _logger.debug(
                        "cache_invalidated_after_event_creation"
                    )

                    await self._invalidate_events_list_cache(guild_id)

                except Exception as e:
                    error_msg = str(e).lower()
                    if "duplicate entry" in error_msg or "1062" in error_msg:
                        try:
                            await announcement.delete()
                        except:
                            pass
                        _logger.warning(
                            "duplicate_event_entry",
                            guild_id=guild_id,
                            error=str(e)
                        )
                    elif "foreign key constraint" in error_msg or "1452" in error_msg:
                        _logger.error(
                            "foreign_key_constraint_failed",
                            guild_id=guild_id,
                            error=str(e)
                        )
                    else:
                        _logger.error(
                            "error_saving_event_in_db",
                            guild_id=guild_id,
                            error=str(e)
                        )
            except Exception as outer_e:
                _logger.error(
                    "unexpected_error_create_events",
                    guild_id=guild_id,
                    error=str(outer_e),
                    exc_info=True,
                )

    def _get_cached_translations(
        self, guild_lang: str, events_infos: dict
    ) -> dict[str, str]:
        """
        Get cached translations for event fields to avoid repetitive dictionary lookups.

        Args:
            guild_lang: Guild language code
            events_infos: Events info dictionary from translations

        Returns:
            Dictionary with pre-resolved translations
        """

        def get_translation(key: str, default: str = "") -> str:
            """Helper to get translation with fallback to en-US then default."""
            field_dict = events_infos.get(key, {})
            return field_dict.get(guild_lang, field_dict.get("en-US", default))

        return {
            "date": get_translation("date", "Date"),
            "hour": get_translation("hour", "Hour"),
            "duration": get_translation("duration", "Duration"),
            "status": get_translation("status", "Status"),
            "dkp_v": get_translation("dkp_v", "DKP Value"),
            "dkp_i": get_translation("dkp_i", "DKP Ins"),
            "present": get_translation("present", "Present"),
            "attempt": get_translation("attempt", "Attempt"),
            "absence": get_translation("absence", "Absence"),
            "voice_channel": get_translation("voice_channel", "Voice Channel"),
            "groups": get_translation("groups", "Groups"),
            "auto_grouping": get_translation("auto_grouping", "Auto Grouping"),
            "status_planned": get_translation("status_planned", "Planned"),
            "description": get_translation(
                "description", "React to indicate your presence."
            ),
            "none": get_translation("none", "None"),
        }

    @profile_performance(threshold_ms=100.0)
    async def _send_announcement(
        self, events_channel: discord.TextChannel, embed: discord.Embed
    ) -> discord.Message:
        """
        Send event announcement with batched reactions.

        Args:
            events_channel: Channel to send the announcement
            embed: Event embed to send

        Returns:
            Sent message object
        """
        announcement = await events_channel.send(embed=embed)
        _logger.debug(
            "announcement_sent",
            announcement_id=announcement.id,
            channel_id=announcement.channel.id
        )

        reactions = [
            self.EMOJI_YES,
            self.EMOJI_MAYBE,
            self.EMOJI_NO,
        ]
        await asyncio.gather(
            *[announcement.add_reaction(reaction) for reaction in reactions]
        )

        return announcement

    @profile_performance(threshold_ms=100.0)
    async def _create_scheduled_event(
        self,
        guild: discord.Guild,
        event_name: str,
        description_scheduled: str,
        start_time: datetime,
        end_time: datetime,
        conference_channel: discord.VoiceChannel,
    ) -> Optional[discord.ScheduledEvent]:
        """
        Create Discord scheduled event.

        Args:
            guild: Guild to create event in
            event_name: Name of the event
            description_scheduled: Event description with link
            start_time: Event start time
            end_time: Event end time
            conference_channel: Voice channel for the event

        Returns:
            Created scheduled event or None if failed
        """
        try:
            try:
                scheduled_event = await guild.create_scheduled_event(
                    name=event_name,
                    description=description_scheduled,
                    start_time=start_time,
                    end_time=end_time,
                    channel=conference_channel,
                )
                _logger.debug("scheduled_event_signature_used", signature="channel")
            except TypeError as e:
                _logger.debug(
                    "scheduled_event_signature_fallback", 
                    signature="location", 
                    original_error=str(e)
                )
                scheduled_event = await guild.create_scheduled_event(
                    name=event_name,
                    description=description_scheduled,
                    start_time=start_time,
                    end_time=end_time,
                    location=str(conference_channel),
                )
            _logger.debug(
                "scheduled_event_created",
                event_id=scheduled_event.id if scheduled_event else None
            )
            return scheduled_event
        except discord.Forbidden:
            _logger.error(
                "insufficient_permissions_scheduled_event",
                guild_id=guild.id
            )
            return None
        except discord.HTTPException as e:
            _logger.error(
                "http_error_creating_scheduled_event",
                guild_id=guild.id,
                error=str(e)
            )
            return None

    async def event_confirm(self, ctx: discord.ApplicationContext, event_id: str):
        """
        Confirm and close an event for registration.

        Args:
            ctx: Discord application context from the command
            event_id: String identifier of the event to confirm

        Returns:
            None
        """
        await ctx.defer(ephemeral=True)

        guild = ctx.guild
        guild_id = ctx.guild.id
        settings = await self.bot.cache.get_guild_data(guild_id, "settings")
        user_locale = await get_effective_locale(self.bot, guild_id, ctx.user.id)
        guild_locale = (
            settings.get("guild_lang")
            if settings and settings.get("guild_lang")
            else "en-US"
        )

        translations = await self._t(guild_id,
            "events_infos.id_ko",
            "event_confirm_messages.no_settings", 
            "event_confirm_messages.no_events",
            "event_confirm_messages.no_events_canal",
            "event_confirm_messages.no_events_message",
            "event_confirm_messages.no_events_message_embed",
            "events_infos.status",
            "event_confirm_messages.confirmed",
            "event_confirm_messages.confirmed_notif",
            "event_confirm_messages.event_updated",
            "event_confirm_messages.event_embed_ko"
        )

        try:
            event_id_int = int(event_id)
        except ValueError:
            await ctx.followup.send(translations["events_infos.id_ko"], ephemeral=True)
            return

        if not settings:
            await ctx.followup.send(translations["event_confirm_messages.no_settings"], ephemeral=True)
            return

        try:
            async with self.json_lock:
                target_event = await self.get_event_from_cache(guild.id, event_id_int)
                if not target_event:
                    follow_message = translations["event_confirm_messages.no_events"].format(event_id=event_id)
                    await ctx.followup.send(follow_message, ephemeral=True)
                    return

                query = (
                    "UPDATE events_data SET status = %s WHERE guild_id = %s AND event_id = %s"
                )
                validated_status = EventStatus.validate(EventStatus.CONFIRMED)
                await self.bot.run_db_query(
                    query, (validated_status, guild.id, event_id_int), commit=True
                )
                target_event["status"] = EventStatus.validate(EventStatus.CONFIRMED)
                await self.set_event_in_cache(guild.id, event_id_int, target_event)
                _logger.info(
                    "event_status_confirmed",
                    event_id=event_id,
                    guild_id=guild.id
                )
        except Exception as e:
            _logger.error(
                "error_updating_event_status",
                event_id=event_id,
                guild_id=guild.id,
                error=str(e),
                exc_info=True,
            )

        channels_data = await self.bot.cache.get_guild_data(guild_id, "channels")

        events_channel = (
            guild.get_channel(channels_data.get("events_channel"))
            if channels_data
            else None
        )
        if not events_channel:
            await ctx.followup.send(translations["event_confirm_messages.no_events_canal"], ephemeral=True)
            return

        try:
            message = await events_channel.fetch_message(event_id_int)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            _logger.warning("cannot_fetch_event_message", event_id=event_id, error=str(e))
            await ctx.followup.send(translations["event_confirm_messages.no_events_message"], ephemeral=True)
            return

        if not message.embeds:
            await ctx.followup.send(translations["event_confirm_messages.no_events_message_embed"], ephemeral=True)
            return

        new_embed = message.embeds[0]
        new_embed.color = discord.Color.green()

        status_key = translations["events_infos.status"].lower()
        status_name = translations["events_infos.status"]
        status_localized = translations["event_confirm_messages.confirmed"]

        new_fields = []
        status_found = False
        for field in new_embed.fields:
            if field.name.lower() == status_key:
                new_fields.append(
                    {
                        "name": status_name,
                        "value": status_localized,
                        "inline": field.inline,
                    }
                )
                status_found = True
            else:
                new_fields.append(
                    {"name": field.name, "value": field.value, "inline": field.inline}
                )
        if not status_found:
            new_fields.append(
                {"name": status_name, "value": status_localized, "inline": False}
            )
        new_embed.clear_fields()
        for field in new_fields:
            new_embed.add_field(
                name=field["name"], value=field["value"], inline=field["inline"]
            )

        try:
            roles_data = await self.bot.cache.get_guild_data(guild_id, "roles")

            role_id = (roles_data or {}).get("members")
            role_mention = guild.get_role(int(role_id)).mention if role_id and guild.get_role(int(role_id)) else ""
            update_message = translations["event_confirm_messages.confirmed_notif"].format(role=role_mention)
            await message.edit(content=update_message, embed=new_embed)
            follow_message = translations["event_confirm_messages.event_updated"].format(event_id=event_id)
            await ctx.followup.send(follow_message, ephemeral=True)
        except (HTTPException, discord.DiscordException) as e:
            _logger.error(
                "discord_api_error_confirm_followup",
                error=str(e),
                exc_info=True
            )
            follow_message = translations["event_confirm_messages.event_embed_ko"].format(e=str(e))
            await ctx.followup.send(follow_message, ephemeral=True)
            return
        except Exception as e:
            _logger.error(
                "unexpected_error_confirm_followup",
                error=str(e),
                exc_info=True
            )
            follow_message = translations["event_confirm_messages.event_embed_ko"].format(e=str(e))
            await ctx.followup.send(follow_message, ephemeral=True)
            return
        
        await self._invalidate_events_list_cache(guild.id)

    async def event_cancel(self, ctx: discord.ApplicationContext, event_id: str):
        """
        Cancel an event and remove it from the system.

        Args:
            ctx: Discord application context from the command
            event_id: String identifier of the event to cancel

        Returns:
            None
        """
        await ctx.defer(ephemeral=True)

        guild = ctx.guild
        guild_id = ctx.guild.id
        settings = await self.bot.cache.get_guild_data(guild_id, "settings")
        user_locale = await get_effective_locale(self.bot, guild_id, ctx.user.id)
        guild_locale = (
            settings.get("guild_lang")
            if settings and settings.get("guild_lang")
            else "en-US"
        )

        translations = await self._t(guild_id,
            "events_infos.id_ko",
            "event_cancel_messages.no_settings", 
            "event_cancel_messages.no_events",
            "event_cancel_messages.no_events_canal",
            "event_cancel_messages.no_events_message",
            "event_cancel_messages.discord_api_error",
            "event_cancel_messages.unexpected_error",
            "event_cancel_messages.no_events_message_embed",
            "events_infos.status",
            "events_infos.present",
            "events_infos.attempt", 
            "events_infos.absence",
            "events_infos.dkp_v",
            "events_infos.dkp_i",
            "events_infos.groups",
            "events_infos.voice_channel",
            "event_cancel_messages.canceled",
            "event_cancel_messages.event_updated",
            "event_cancel_messages.event_embed_ko"
        )

        try:
            event_id_int = int(event_id)
        except ValueError:
            await ctx.followup.send(translations["events_infos.id_ko"], ephemeral=True)
            return

        if not settings:
            await ctx.followup.send(translations["event_cancel_messages.no_settings"], ephemeral=True)
            return

        try:
            async with self.json_lock:
                target_event = await self.get_event_from_cache(guild.id, event_id_int)
                if not target_event:
                    follow_message = translations["event_cancel_messages.no_events"].format(event_id=event_id)
                    await ctx.followup.send(follow_message, ephemeral=True)
                    return

                query = (
                    "UPDATE events_data SET status = %s WHERE guild_id = %s AND event_id = %s"
                )
                validated_status = EventStatus.validate(EventStatus.CANCELED)
                await self.bot.run_db_query(
                    query, (validated_status, guild.id, event_id_int), commit=True
                )
                target_event["status"] = EventStatus.validate(EventStatus.CANCELED)
                await self.set_event_in_cache(guild.id, event_id_int, target_event)
                _logger.info(
                    "event_status_canceled",
                    event_id=event_id_int,
                    guild_id=guild.id
                )
        except Exception as e:
            _logger.error(
                "error_updating_event_cancel_status",
                event_id=event_id,
                guild_id=guild.id,
                error=str(e),
                exc_info=True,
            )

        channels_data = await self.bot.cache.get_guild_data(guild_id, "channels")

        events_channel = (
            guild.get_channel(channels_data.get("events_channel"))
            if channels_data
            else None
        )
        if not events_channel:
            await ctx.followup.send(translations["event_cancel_messages.no_events_canal"], ephemeral=True)
            return

        try:
            message = await events_channel.fetch_message(event_id_int)
        except NotFound:
            await ctx.followup.send(translations["event_cancel_messages.no_events_message"], ephemeral=True)
            return
        except (HTTPException, discord.DiscordException) as e:
            _logger.error(
                "discord_api_error_fetch_message",
                event_id=event_id_int,
                channel_id=events_channel.id,
                error=str(e),
                exc_info=True
            )
            await ctx.followup.send(translations["event_cancel_messages.discord_api_error"], ephemeral=True)
            return
        except Exception as e:
            _logger.error(
                "unexpected_error_fetch_message",
                event_id=event_id_int,
                channel_id=events_channel.id,
                error=str(e),
                exc_info=True
            )
            await ctx.followup.send(translations["event_cancel_messages.unexpected_error"], ephemeral=True)
            return

        try:
            await message.clear_reactions()
        except (HTTPException, discord.Forbidden, discord.DiscordException) as e:
            _logger.error(
                "discord_api_error_clear_reactions",
                message_id=message.id,
                error=str(e),
                exc_info=True
            )
        except Exception as e:
            _logger.error(
                "error_clearing_reactions",
                error=str(e),
                exc_info=True,
            )

        if not message.embeds:
            await ctx.followup.send(translations["event_cancel_messages.no_events_message_embed"], ephemeral=True)
            return

        embed = message.embeds[0]
        embed.color = discord.Color.red()

        status_key = translations["events_infos.status"].lower()
        status_name = translations["events_infos.status"]
        status_localized = translations["event_cancel_messages.canceled"]
        present_key = translations["events_infos.present"].lower()
        tentative_key = translations["events_infos.attempt"].lower()
        absence_key = translations["events_infos.absence"].lower()
        dkp_v_key = translations["events_infos.dkp_v"].lower()
        dkp_i_key = translations["events_infos.dkp_i"].lower()
        groups_key = translations["events_infos.groups"].lower()
        chan_key = translations["events_infos.voice_channel"].lower()

        new_fields = []
        for field in embed.fields:
            field_name = field.name.lower()
            if (
                field_name.startswith(present_key)
                or field_name.startswith(tentative_key)
                or field_name.startswith(absence_key)
                or field_name in [dkp_v_key, dkp_i_key, groups_key, chan_key]
            ):
                continue
            elif field_name == status_key:
                new_fields.append(
                    {"name": status_name, "value": status_localized, "inline": False}
                )
            else:
                new_fields.append(
                    {"name": field.name, "value": field.value, "inline": field.inline}
                )
        embed.clear_fields()
        for field in new_fields:
            embed.add_field(
                name=field["name"], value=field["value"], inline=field["inline"]
            )

        try:
            await message.edit(content="", embed=embed)
            follow_message = translations["event_cancel_messages.event_updated"].format(event_id=event_id)
            await ctx.followup.send(follow_message, ephemeral=True)
        except (HTTPException, discord.DiscordException) as e:
            _logger.error(
                "discord_api_error_cancel_followup",
                error=str(e),
                exc_info=True
            )
            follow_message = translations["event_cancel_messages.event_embed_ko"].format(e=str(e))
            await ctx.followup.send(follow_message, ephemeral=True)
            return
        except Exception as e:
            _logger.error(
                "unexpected_error_cancel_followup",
                error=str(e),
                exc_info=True
            )
            follow_message = translations["event_cancel_messages.event_embed_ko"].format(e=str(e))
            await ctx.followup.send(follow_message, ephemeral=True)
            return
        
        await self._invalidate_events_list_cache(guild.id)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """
        Handle reaction additions for event registration.

        Args:
            payload: Discord raw reaction event payload containing reaction details

        Returns:
            None
        """
        now_mono = time.monotonic()
        self.ignore_removals = {
            k: v for k, v in self.ignore_removals.items() 
            if now_mono - v < 3.0
        }
        
        _logger.debug(
            "reaction_add_starting",
            guild_id=payload.guild_id,
            message_id=payload.message_id,
            user_id=payload.user_id,
            emoji=str(payload.emoji)
        )
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            _logger.debug("guild_not_found_reaction_add")
            return

        channels_data = await self.bot.cache.get_guild_data(guild.id, "channels")
        if not channels_data:
            _logger.debug(
                "[GuildEvents - on_raw_reaction_add] Channels data not found for this guild."
            )
            return

        events_channel_id = channels_data.get("events_channel")
        if payload.channel_id == events_channel_id:
            await self._handle_event_reaction(payload, guild, channels_data)

    async def _handle_event_reaction(
        self,
        payload: discord.RawReactionActionEvent,
        guild: discord.Guild,
        channels_data: dict,
    ) -> None:
        """
        Process event registration reactions and update participant lists.

        Args:
            payload: Discord raw reaction event payload
            guild: Discord guild object where the reaction occurred
            channels_data: Dictionary containing guild channels configuration

        Returns:
            None
        """
        emoji_str = str(payload.emoji)
        if emoji_str not in self.VALID_EMOJIS:
            _logger.debug(
                "invalid_emoji_reaction",
                emoji=emoji_str
            )
            return

        channel = guild.get_channel(payload.channel_id)
        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            _logger.error(
                "error_fetching_message",
                error=str(e)
            )
            return

        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            _logger.debug(
                "[GuildEvents - on_raw_reaction_add] Member not found or is a bot."
            )
            return

        for emoji_s, emoji_obj in self.VALID_EMOJIS.items():
            if emoji_s != emoji_str:
                try:
                    key = (message.id, member.id, emoji_s)
                    self.ignore_removals[key] = time.monotonic()
                    await message.remove_reaction(emoji_obj, member)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                    _logger.error(
                        "error_removing_reaction",
                        emoji=emoji_s,
                        member=str(member),
                        error=str(e)
                    )

        async with self.json_lock:
            target_event = await self.get_event_from_cache(guild.id, message.id)
            if not target_event:
                _logger.debug(
                    "[GuildEvents - on_raw_reaction_add] No event found for this message."
                )
                return

            original_event = target_event.copy()

            status = EventStatus.normalize(target_event.get("status", ""))
            if status in (EventStatus.CLOSED, EventStatus.CANCELED):
                if str(payload.emoji) in self.VALID_EMOJIS:
                    try:
                        await message.remove_reaction(self.VALID_EMOJIS[str(payload.emoji)], member)
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        pass
                return

            _logger.debug(
                "event_found_for_reaction",
                event_id=target_event.get('event_id'),
                guild_id=target_event.get('guild_id'),
                status=target_event.get('status')
            )

            for key in ["presence", "tentative", "absence"]:
                if payload.user_id in target_event["registrations"].get(key, []):
                    target_event["registrations"][key].remove(payload.user_id)
            
            if emoji_str == str(self.EMOJI_YES):
                target_event["registrations"]["presence"].append(payload.user_id)
            elif emoji_str == str(self.EMOJI_MAYBE):
                target_event["registrations"]["tentative"].append(payload.user_id)
            elif emoji_str == str(self.EMOJI_NO):
                target_event["registrations"]["absence"].append(payload.user_id)

            await self.set_event_in_cache(guild.id, message.id, target_event)

            target_event_copy = target_event.copy()

        try:
            update_query = "UPDATE events_data SET registrations = %s WHERE guild_id = %s AND event_id = %s"
            await self.bot.run_db_query(
                update_query,
                (ensure_json_string(dict(target_event_copy["registrations"])), target_event_copy["guild_id"], target_event_copy["event_id"]),
                commit=True,
            )
            
            _logger.debug(
                "db_update_successful_registrations"
            )

            await self.update_event_embed(message, target_event_copy)
        except Exception as e:
            _logger.error(
                "error_updating_db_registrations",
                phase="add",
                error=str(e),
                exc_info=True
            )
            if original_event:
                async with self.json_lock:
                    await self.set_event_in_cache(guild.id, message.id, original_event)
                    _logger.warning(
                        "cache_restored_after_db_failure",
                        event_id=message.id
                    )
            return

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        """
        Handle reaction removals for event registration.

        Args:
            payload: Discord raw reaction event payload containing reaction details

        Returns:
            None
        """
        key = (payload.message_id, payload.user_id, str(payload.emoji))
        if key in self.ignore_removals:
            ts = self.ignore_removals.pop(key)
            if time.monotonic() - ts < 3:
                _logger.debug(
                    "ignoring_automatic_removal",
                    key=key
                )
                return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        now_mono = time.monotonic()
        self.ignore_removals = {
            k: v for k, v in self.ignore_removals.items() 
            if now_mono - v < 3.0
        }

        channels_data = await self.bot.cache.get_guild_data(guild.id, "channels")
        if not channels_data:
            return
        events_channel_id = channels_data.get("events_channel")
        if payload.channel_id != events_channel_id:
            return

        try:
            channel = guild.get_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            _logger.error(
                "error_fetching_message_on_remove",
                error=str(e)
            )
            return

        async with self.json_lock:
            target_event = await self.get_event_from_cache(guild.id, message.id)
            if not target_event:
                return
            
            if EventStatus.normalize(target_event.get("status", "")) in (EventStatus.CLOSED, EventStatus.CANCELED):
                _logger.debug(
                    "ignoring_removal_closed_event",
                    event_id=target_event['event_id']
                )
                return

            original_event = target_event.copy()
            
            for key in ["presence", "tentative", "absence"]:
                if payload.user_id in target_event["registrations"].get(key, []):
                    target_event["registrations"][key].remove(payload.user_id)

            await self.set_event_in_cache(guild.id, message.id, target_event)

            target_event_copy = target_event.copy()

        try:
            update_query = "UPDATE events_data SET registrations = %s WHERE guild_id = %s AND event_id = %s"
            await self.bot.run_db_query(
                update_query,
                (ensure_json_string(dict(target_event_copy["registrations"])), target_event_copy["guild_id"], target_event_copy["event_id"]),
                commit=True,
            )
            
            _logger.debug(
                "db_update_successful_registrations_remove"
            )

            await self.update_event_embed(message, target_event_copy)
        except Exception as e:
            _logger.error(
                "error_updating_db_registrations",
                phase="remove",
                error=str(e),
                exc_info=True
            )
            if original_event:
                async with self.json_lock:
                    await self.set_event_in_cache(guild.id, message.id, original_event)
                    _logger.warning(
                        "cache_restored_after_db_failure",
                        event_id=message.id,
                        phase="remove"
                    )

    async def update_event_embed(self, message, event_record):
        """
        Update event embed with current registration information.

        Args:
            message: Discord message object containing the event embed
            event_record: Dictionary containing event data and registrations

        Returns:
            None
        """
        _logger.debug("starting_embed_update_for_event")
        guild = self.bot.get_guild(message.guild.id)
        guild_id = guild.id

        translations = await self._t(guild_id,
            "events_infos.present",
            "events_infos.attempt", 
            "events_infos.absence",
            "events_infos.none"
        )
        
        present_display = translations["events_infos.present"]
        attempt_display = translations["events_infos.attempt"]
        absence_display = translations["events_infos.absence"]
        none_key = translations["events_infos.none"]
        present_key = present_display.lower()
        attempt_key = attempt_display.lower() 
        absence_key = absence_display.lower()

        def build_mention_tokens(id_list):
            """
            Build mention tokens for member ID list in a single pass.

            Args:
                id_list: List of Discord member IDs

            Returns:
                List of mention tokens
            """
            tokens = []
            for uid in id_list:
                m = guild.get_member(uid)
                if m:
                    tokens.append(m.mention)
                else:
                    tokens.append(f"<@{uid}>")
            return tokens

        presence_ids = event_record["registrations"].get("presence", [])
        tentative_ids = event_record["registrations"].get("tentative", [])
        absence_ids = event_record["registrations"].get("absence", [])

        presence_tokens = build_mention_tokens(presence_ids)
        tentative_tokens = build_mention_tokens(tentative_ids)
        absence_tokens = build_mention_tokens(absence_ids)

        presence_str = _fit_mentions(presence_tokens) if presence_tokens else none_key
        tentative_str = _fit_mentions(tentative_tokens) if tentative_tokens else none_key
        absence_str = _fit_mentions(absence_tokens) if absence_tokens else none_key

        if not message.embeds:
            _logger.error("no_embed_found_in_message")
            return
        embed = message.embeds[0]

        new_fields = []
        for field in embed.fields:
            lower_name = field.name.lower()
            if lower_name.startswith(present_key) or str(self.EMOJI_YES) in field.name:
                new_name = f"{present_display} {self.EMOJI_YES} ({len(presence_ids)})"
                new_fields.append((new_name, presence_str, field.inline))
            elif lower_name.startswith(attempt_key) or str(self.EMOJI_MAYBE) in field.name:
                new_name = f"{attempt_display} {self.EMOJI_MAYBE} ({len(tentative_ids)})"
                new_fields.append((new_name, tentative_str, field.inline))
            elif lower_name.startswith(absence_key) or str(self.EMOJI_NO) in field.name:
                new_name = f"{absence_display} {self.EMOJI_NO} ({len(absence_ids)})"
                new_fields.append((new_name, absence_str, field.inline))
            else:
                new_fields.append((field.name, field.value, field.inline))

        embed.clear_fields()
        for name, value, inline in new_fields:
            embed.add_field(name=name, value=value, inline=inline)

        try:
            await message.edit(embed=embed)
            _logger.debug("embed_update_successful")
        except Exception as e:
            _logger.error("error_updating_embed", error=str(e), exc_info=True)

    async def _check_cron_lock(self, cron_name: str) -> bool:
        """
        Check if a CRON task is already running to prevent double execution.
        
        WARNING: This lock is not distributed across multiple bot instances.
        In multi-process deployment, consider using Redis/DB-based locks.
        
        Args:
            cron_name: Name of the CRON task
            
        Returns:
            True if safe to run, False if already running
        """
        lock_key = f"cron_lock_{cron_name}"
        current_time = time.time()
        
        try:
            last_run_data = await self.bot.cache.get_generic_data(lock_key)
            
            if last_run_data and isinstance(last_run_data, dict):
                last_run_time = last_run_data.get("timestamp", 0)
                is_running = last_run_data.get("running", False)
                process_id = last_run_data.get("process_id")

                if is_running and (current_time - last_run_time) < 600:
                    _logger.warning(
                        "cron_execution_blocked_already_running",
                        cron_name=cron_name,
                        last_run_ago_seconds=int(current_time - last_run_time),
                        lock_process_id=process_id,
                        current_process_id=os.getpid(),
                        is_same_process=(process_id == os.getpid())
                    )
                    return False
                elif is_running and (current_time - last_run_time) >= 600:
                    _logger.warning(
                        "cron_lock_expired_taking_over", 
                        cron_name=cron_name,
                        expired_ago_seconds=int(current_time - last_run_time),
                        previous_process_id=process_id
                    )

            await self.bot.cache.set_generic_data(
                lock_key,
                {
                    "timestamp": current_time, 
                    "running": True,
                    "process_id": os.getpid(),
                    "hostname": os.environ.get("HOSTNAME", "unknown")
                },
                ttl=1800
            )
        except Exception as e:
            _logger.warning(
                "cron_lock_check_failed_proceeding",
                cron_name=cron_name,
                error=str(e)
            )
        
        return True
        
    async def _release_cron_lock(self, cron_name: str) -> None:
        """
        Release CRON lock after task completion.
        
        Args:
            cron_name: Name of the CRON task
        """
        lock_key = f"cron_lock_{cron_name}"
        try:
            await self.bot.cache.set_generic_data(
                lock_key,
                {
                    "timestamp": time.time(), 
                    "running": False,
                    "process_id": os.getpid(),
                    "hostname": os.environ.get("HOSTNAME", "unknown")
                },
                ttl=3600
            )
        except Exception as e:
            _logger.warning(
                "cron_lock_release_failed",
                cron_name=cron_name,
                error=str(e)
            )

    async def _process_guild_delete_events(self, guild: discord.Guild) -> str:
        """
        Process event deletions for a single guild.
        
        Args:
            guild: Discord guild to process
            
        Returns:
            Result string for this guild
        """
        guild_id = guild.id
        try:
            settings = await self.bot.cache.get_guild_data(guild_id, "settings")
            if not settings:
                return f"{guild.name}: No settings configured."
                
            tz = get_guild_timezone(settings)
            now = datetime.now(tz)

            channels_data = await self.bot.cache.get_guild_data(guild_id, "channels")
            if not channels_data:
                return f"{guild.name}: No channels configured."

            events_channel = guild.get_channel(channels_data.get("events_channel"))
            if not events_channel:
                _logger.error(
                    "cron_events_channel_not_found",
                    guild_id=guild_id
                )
                return f"{guild.name}: Events channel not found."

            guild_events = await self.get_all_guild_events(guild_id)
            canceled_events_to_delete = []

            EVENT_BATCH_SIZE = 8
            for i in range(0, len(guild_events), EVENT_BATCH_SIZE):
                batch = guild_events[i:i + EVENT_BATCH_SIZE]
                
                batch_tasks = []
                for event in batch:
                    batch_tasks.append(
                        self._process_single_event_delete(
                            guild, event, events_channel, tz, now
                        )
                    )

                if batch_tasks:
                    batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
                    for event, result in zip(batch, batch_results):
                        if isinstance(result, Exception):
                            _logger.error(
                                "error_processing_event_delete",
                                guild_id=guild_id,
                                event_id=event.get('event_id'),
                                error=str(result),
                                exc_info=result
                            )
                        elif result:
                            canceled_events_to_delete.append(result)

            total_deleted = 0
            if canceled_events_to_delete:
                deleted_count = await self._batch_delete_canceled_events(guild_id, canceled_events_to_delete)
                total_deleted += deleted_count
                
            return f"{guild.name}: {total_deleted} events deleted"
            
        except Exception as e:
            _logger.error(
                "error_processing_guild_delete_events",
                guild_id=guild_id, 
                guild_name=guild.name,
                error=str(e),
                exc_info=True
            )
            return f"{guild.name}: Error - {str(e)}"

    async def _process_single_event_delete(
        self,
        guild: discord.Guild,
        ev: EventData,
        events_channel: discord.TextChannel,
        tz: pytz.BaseTzInfo,
        now: datetime
    ) -> Optional[dict]:
        """
        Process deletion for a single event.
        
        Args:
            guild: Discord guild
            ev: Event data
            events_channel: Events channel
            tz: Guild timezone
            now: Current datetime
            
        Returns:
            Event data if should be deleted, None otherwise
        """
        try:
            try:
                event_dt = normalize_event_datetime(ev["event_date"], ev["event_time"], tz)
            except (ValueError, TypeError) as e:
                _logger.warning(
                    "cleanup_datetime_normalization_failed",
                    event_id=ev.get('event_id'),
                    guild_id=guild.id,
                    raw_date=ev.get('event_date'),
                    raw_time=ev.get('event_time'),
                    error=str(e)
                )
                try:
                    safe_date = normalize_date_only(ev.get("event_date"))
                except Exception:
                    return None
                fallback_time = dt_time(21, 0)
                event_dt = self._localize_safe(tz, datetime.combine(safe_date, fallback_time))
        except Exception as e:
            _logger.error(
                "cleanup_error_parsing_event",
                event_id=ev.get('event_id'),
                error=str(e),
                exc_info=True,
            )
            return None

        time_since_event = now - event_dt
        should_delete = (
            time_since_event > timedelta(days=2) or
            ev.get("status", "").strip().lower() == "canceled"
        )

        if should_delete:
            try:
                msg = await events_channel.fetch_message(ev["event_id"])
                await msg.delete()
                
                return {
                    "guild_id": guild.id,
                    "event_id": ev["event_id"]
                }
                
            except discord.NotFound:
                return {
                    "guild_id": guild.id,
                    "event_id": ev["event_id"]
                }
            except Exception as e:
                _logger.warning(
                    "cron_error_deleting_message",
                    event_id=ev["event_id"],
                    error=str(e)
                )
                return {
                    "guild_id": guild.id,
                    "event_id": ev["event_id"]
                }
        
        return None

    async def _batch_delete_canceled_events(self, guild_id: int, events_to_delete: List[dict]) -> int:
        """
        Delete multiple events from database and cache.
        
        Args:
            guild_id: Guild ID
            events_to_delete: List of event data to delete
            
        Returns:
            Number of events successfully deleted
        """
        try:
            validated_pairs = [
                (ev["guild_id"], ev["event_id"]) 
                for ev in events_to_delete 
                if ev.get("guild_id") and ev.get("event_id")
            ]
            
            if not validated_pairs:
                return 0

            placeholders = ",".join(["(%s,%s)"] * len(validated_pairs))
            delete_query = f"DELETE FROM events_data WHERE (guild_id, event_id) IN ({placeholders})"

            params = [param for pair in validated_pairs for param in pair]
            
            await self.bot.run_db_query(delete_query, params, commit=True)

            for ev in events_to_delete:
                try:
                    await self.delete_event_from_cache(ev["guild_id"], ev["event_id"])
                except Exception as cache_err:
                    _logger.warning(
                        "error_removing_event_from_cache_during_deletion",
                        event_id=ev["event_id"],
                        error=str(cache_err)
                    )

            await self._invalidate_events_list_cache(guild_id)
            
            _logger.info(
                "batch_deleted_canceled_events",
                guild_id=guild_id,
                count=len(validated_pairs)
            )
            
            return len(validated_pairs)
            
        except Exception as e:
            _logger.error(
                "error_batch_deleting_canceled_events",
                guild_id=guild_id,
                error=str(e),
                exc_info=True
            )
            return 0

    async def event_delete_cron(self, ctx=None) -> None:
        """
        Automated task to delete finished events.

        Args:
            ctx: Optional Discord application context (default: None)

        Returns:
            None
        """
        if not await self._check_cron_lock("event_delete"):
            return
            
        try:
            GUILD_BATCH_SIZE = 10
            all_guilds = list(self.bot.guilds)
            all_results = []
            
            for i in range(0, len(all_guilds), GUILD_BATCH_SIZE):
                batch = all_guilds[i:i + GUILD_BATCH_SIZE]

                batch_results = await asyncio.gather(
                    *[self._process_guild_delete_events(guild) for guild in batch],
                    return_exceptions=True
                )

                for guild, result in zip(batch, batch_results):
                    if isinstance(result, Exception):
                        _logger.error(
                            "guild_delete_processing_failed",
                            guild_id=guild.id,
                            guild_name=guild.name,
                            error=str(result),
                            exc_info=result
                        )
                        all_results.append(f"{guild.name}: Failed - {str(result)}")
                    else:
                        all_results.append(result)

                if i + GUILD_BATCH_SIZE < len(all_guilds):
                    await asyncio.sleep(0.2)
            
            _logger.info("event_delete_cron_finished", results=len(all_results))
        finally:
            await self._release_cron_lock("event_delete")

    async def _process_guild_reminders(self, guild: discord.Guild) -> str:
        """
        Process event reminders for a single guild.
        
        Args:
            guild: Discord guild to process
            
        Returns:
            Result string for this guild
        """
        guild_id = guild.id
        try:
            settings = await self.bot.cache.get_guild_data(guild_id, "settings")
            if not settings:
                return f"{guild.name}: No settings configured."

            tz = get_guild_timezone(settings)
            today_date = datetime.now(tz).date()
            guild_locale = settings.get("guild_lang") or "en-US"

            channels_data = await self.bot.cache.get_guild_data(guild_id, "channels")
            if not channels_data:
                return f"{guild.name}: No channels configured."

            notifications_channel = guild.get_channel(
                channels_data.get("notifications_channel")
            )
            events_channel = guild.get_channel(channels_data.get("events_channel"))
            if not events_channel or not notifications_channel:
                _logger.error(
                    "channels_not_found_for_guild",
                    guild_name=guild.name,
                    guild_id=guild.id
                )
                return f"{guild.name}: Required channels not found."

            guild_events = await self.get_all_guild_events(guild_id)
            
            confirmed_events = [
                ev
                for ev in guild_events
                if is_same_date(ev.get("event_date"), today_date)
                and EventStatus.normalize(ev.get("status", "")) == EventStatus.CONFIRMED
            ]
            
            if not confirmed_events:
                return f"{guild.name}: No confirmed events today."

            guild_results = []
            for event in confirmed_events:
                result = await self._process_single_event_reminder(
                    guild, event, events_channel, notifications_channel
                )
                if result:
                    guild_results.append(result)
            
            return " | ".join(guild_results) if guild_results else f"{guild.name}: All processed."
            
        except Exception as e:
            _logger.error(
                "error_processing_guild_reminders",
                guild_id=guild_id,
                guild_name=guild.name,
                error=str(e),
                exc_info=True
            )
            return f"{guild.name}: Error - {str(e)}"

    async def _process_single_event_reminder(
        self, 
        guild: discord.Guild, 
        event: EventData,
        events_channel: discord.TextChannel,
        notifications_channel: discord.TextChannel
    ) -> Optional[str]:
        """
        Process reminder for a single event.
        
        Args:
            guild: Discord guild
            event: Event data
            events_channel: Events channel
            notifications_channel: Notifications channel
            
        Returns:
            Result string or None
        """
        guild_id = guild.id
        
        registrations_obj = event.get("registrations", {
            "presence": [],
            "tentative": [], 
            "absence": []
        })
        registrations = (
            set(registrations_obj.get("presence", []))
            | set(registrations_obj.get("tentative", []))
            | set(registrations_obj.get("absence", []))
        )
        initial_members = event.get("initial_members", [])
        if not isinstance(initial_members, list):
            initial_members = []
            
        initial = set(initial_members)

        try:
            roles_data = await self.bot.cache.get_guild_data(guild_id, "roles")
            members_role_id = roles_data.get("members") if roles_data else None
            if members_role_id:
                role = guild.get_role(int(members_role_id))
                if role:
                    if hasattr(self.bot, "cache") and hasattr(
                        self.bot.cache, "get_role_members_optimized"
                    ):
                        current_members = (
                            await self.bot.cache.get_role_members_optimized(
                                guild_id, int(members_role_id)
                            )
                        )
                    else:
                        current_members = {
                            member.id
                            for member in guild.members
                            if role in member.roles
                        }
                else:
                    current_members = set()
            else:
                current_members = set()
        except Exception as e:
            _logger.error(
                "error_retrieving_current_members",
                guild_id=guild.id,
                error=str(e),
                exc_info=True,
            )
            current_members = set()

        updated_initial = current_members
        to_remind = list(updated_initial - registrations)

        if not current_members:
            _logger.warning(
                "no_members_for_reminder_role_not_configured",
                guild_id=guild_id,
                event_name=event["name"],
                members_role_id=members_role_id,
                roles_data_exists=bool(roles_data)
            )
            return f"Event '{event['name']}': No members role configured - skipping reminder"
        
        if not to_remind:
            event_link = f"https://discord.com/channels/{guild.id}/{events_channel.id}/{event['event_id']}"
            reminder_template = await get_guild_message(
                self.bot,
                guild_id,
                EVENT_MANAGEMENT,
                "event_reminder.notification_all_OK",
            )
            if reminder_template is None:
                reminder_template = (
                    EVENT_MANAGEMENT.get("event_reminder", {})
                    .get("notification_all_OK", {})
                    .get(
                        "en-US",
                        "## :bell: Event Reminder\nFor event **{event}**\n({event_link})\n\nAll members have responded.",
                    )
                )
            try:
                reminder_msg = reminder_template.format(
                    event=event["name"], event_link=event_link
                )
                await notifications_channel.send(reminder_msg)
                return f"Event '{event['name']}': All members responded"
            except Exception as e:
                _logger.error(
                    "error_sending_all_ok_notification",
                    error=str(e),
                    exc_info=True
                )
                return None

        reminded = await self._send_dm_reminders(guild, event, to_remind, events_channel)
        
        if reminded:
            event_link = f"https://discord.com/channels/{guild.id}/{events_channel.id}/{event['event_id']}"
            reminder_template = await get_guild_message(
                self.bot,
                guild_id,
                EVENT_MANAGEMENT,
                "event_reminder.notification_reminded",
            )
            if reminder_template is None:
                reminder_template = (
                    EVENT_MANAGEMENT.get("event_reminder", {})
                    .get("notification_reminded", {})
                    .get(
                        "en-US",
                        "## :bell: Event Reminder\nFor event **{event}**\n({event_link})\n\n{len} member(s) were reminded: {members}",
                    )
                )
            try:
                reminder_msg = reminder_template.format(
                    event=event["name"],
                    event_link=event_link,
                    len=len(reminded),
                    members=", ".join(reminded),
                )
                await notifications_channel.send(reminder_msg)
                return f"Event '{event['name']}': {len(reminded)} reminded"
            except Exception as e:
                _logger.error(
                    "error_sending_reminder_notification",
                    error=str(e),
                    exc_info=True
                )
        
        return None

    async def _send_dm_reminders(
        self,
        guild: discord.Guild,
        event: EventData,
        to_remind: List[int],
        events_channel: discord.TextChannel
    ) -> List[str]:
        """
        Send DM reminders to members.
        
        Args:
            guild: Discord guild
            event: Event data
            to_remind: List of member IDs to remind
            events_channel: Events channel
            
        Returns:
            List of reminded member mentions
        """
        guild_id = guild.id
        reminded = []
        event_link = f"https://discord.com/channels/{guild.id}/{events_channel.id}/{event['event_id']}"
        
        dm_template = await get_guild_message(
            self.bot, guild_id, EVENT_MANAGEMENT, "event_reminder.dm_message"
        )
        if not dm_template:
            dm_template = "Hello {member_name}! You have an event '{event_name}' today at {time}. Please check Discord for details."
            _logger.warning(
                "dm_template_missing_using_fallback",
                guild_id=guild_id,
                guild_name=guild.name
            )
        
        BATCH_SIZE = 30
        MAX_REMINDERS = 300
        
        if len(to_remind) > MAX_REMINDERS:
            _logger.warning(
                "too_many_reminders_capped",
                guild_id=guild_id,
                total_members=len(to_remind),
                capped_at=MAX_REMINDERS
            )
            to_remind = to_remind[:MAX_REMINDERS]

        for i in range(0, len(to_remind), BATCH_SIZE):
            batch = to_remind[i:i + BATCH_SIZE]
            batch_tasks = []
            
            for member_id in batch:
                member = guild.get_member(member_id)
                if member:
                    batch_tasks.append(
                        self._send_single_dm_reminder(
                            member, event, dm_template, event_link
                        )
                    )

            if batch_tasks:
                results = await asyncio.gather(*batch_tasks, return_exceptions=True)
                for member_id, result in zip(batch, results):
                    if result is True:
                        member = guild.get_member(member_id)
                        if member:
                            reminded.append(member.mention)
            
            if i + BATCH_SIZE < len(to_remind):
                await asyncio.sleep(1.5)
        
        return reminded

    async def _send_single_dm_reminder(
        self,
        member: discord.Member,
        event: EventData,
        dm_template: str,
        event_link: str
    ) -> bool:
        """
        Send a single DM reminder to a member.
        
        Args:
            member: Discord member
            event: Event data
            dm_template: DM message template
            event_link: Link to the event
            
        Returns:
            True if sent successfully, False otherwise
        """
        try:
            try:
                dm_message = dm_template.format(
                    member_name=member.name,
                    event_name=event["name"],
                    date=event["event_date"],
                    time=event["event_time"],
                    link=event_link,
                )
            except (KeyError, ValueError) as format_error:
                _logger.error(
                    "error_formatting_reminder_template",
                    member_name=member.name,
                    template=dm_template,
                    error=str(format_error)
                )
                dm_message = f"Hello {member.name}! You have an event '{event['name']}' today at {event['event_time']}. Link: {event_link}"
            
            await member.send(dm_message)
            await asyncio.sleep(0.2)
            _logger.debug(
                "dm_sent_to_member",
                member_name=member.name,
                event_name=event['name']
            )
            return True
            
        except discord.Forbidden:
            _logger.debug(
                "dm_blocked_by_member",
                member_id=member.id,
                reason="member_disabled_dms"
            )
        except (HTTPException, discord.DiscordException) as e:
            _logger.warning(
                "discord_api_error_dm_send",
                member_id=member.id,
                error=str(e),
                exc_info=True
            )
        except Exception as e:
            _logger.error(
                "error_sending_dm",
                member_id=member.id,
                error=str(e)
            )
        
        return False

    async def event_reminder_cron(self) -> None:
        """
        Automated task to send event reminders.

        Args:
            None

        Returns:
            None
        """
        if not await self._check_cron_lock("event_reminder"):
            return
            
        try:
            _logger.info("starting_automatic_reminder", date=datetime.utcnow().date().isoformat())

            GUILD_BATCH_SIZE = 10
            all_guilds = list(self.bot.guilds)
            overall_results = []
            
            for i in range(0, len(all_guilds), GUILD_BATCH_SIZE):
                batch = all_guilds[i:i + GUILD_BATCH_SIZE]

                batch_results = await asyncio.gather(
                    *[self._process_guild_reminders(guild) for guild in batch],
                    return_exceptions=True
                )

                for guild, result in zip(batch, batch_results):
                    if isinstance(result, Exception):
                        _logger.error(
                            "guild_reminder_processing_failed",
                            guild_id=guild.id,
                            guild_name=guild.name,
                            error=str(result),
                            exc_info=result
                        )
                        overall_results.append(f"{guild.name}: Failed - {str(result)}")
                    else:
                        overall_results.append(result)

                if i + GUILD_BATCH_SIZE < len(all_guilds):
                    await asyncio.sleep(0.5)
            
            _logger.info("reminder_results", results="\n".join(overall_results))
        finally:
            await self._release_cron_lock("event_reminder")

    async def _process_guild_close_events(self, guild: discord.Guild) -> List[str]:
        """
        Process event closures for a single guild.
        
        Args:
            guild: Discord guild to process
            
        Returns:
            List of result strings for this guild
        """
        guild_id = guild.id
        guild_results = []
        
        try:
            settings = await self.bot.cache.get_guild_data(guild_id, "settings")
            if not settings:
                return [f"{guild.name}: No settings configured."]
                
            tz = get_guild_timezone(settings)
            now = datetime.now(tz)

            channels_data = await self.bot.cache.get_guild_data(guild_id, "channels")
            if not channels_data:
                return [f"{guild.name}: No channels configured."]

            events_channel = guild.get_channel(channels_data.get("events_channel"))
            if not events_channel:
                _logger.error(
                    "cron_events_channel_not_found",
                    guild_id=guild_id
                )
                return [f"{guild.name}: Events channel not found."]

            guild_lang = settings.get("guild_lang") or "en-US"
            guild_events = await self.get_all_guild_events(guild_id)
            closed_events_to_update = []

            EVENT_BATCH_SIZE = 5
            for i in range(0, len(guild_events), EVENT_BATCH_SIZE):
                batch = guild_events[i:i + EVENT_BATCH_SIZE]
                
                batch_tasks = []
                for ev in batch:
                    batch_tasks.append(
                        self._process_single_event_close(
                            guild, ev, events_channel, tz, now, guild_lang
                        )
                    )

                if batch_tasks:
                    batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
                    for ev, result in zip(batch, batch_results):
                        if isinstance(result, Exception):
                            _logger.error(
                                "error_processing_event_close",
                                guild_id=guild_id,
                                event_id=ev['event_id'],
                                error=str(result),
                                exc_info=result
                            )
                        elif result:
                            closed_events_to_update.append(result)

            if closed_events_to_update:
                await self._batch_update_closed_events(guild_id, closed_events_to_update)
                guild_results.append(f"{guild.name}: {len(closed_events_to_update)} events closed")
            else:
                guild_results.append(f"{guild.name}: No events to close")
                
        except Exception as e:
            _logger.error(
                "error_processing_guild_close_events", 
                guild_id=guild_id,
                guild_name=guild.name,
                error=str(e),
                exc_info=True
            )
            guild_results.append(f"{guild.name}: Error - {str(e)}")
            
        return guild_results

    async def _process_single_event_close(
        self,
        guild: discord.Guild,
        ev: EventData,
        events_channel: discord.TextChannel,
        tz: pytz.BaseTzInfo,
        now: datetime,
        guild_lang: str
    ) -> Optional[dict]:
        """
        Process closure for a single event.
        
        Args:
            guild: Discord guild
            ev: Event data
            events_channel: Events channel
            tz: Guild timezone
            now: Current datetime
            guild_lang: Guild language
            
        Returns:
            Event data if closed, None otherwise
        """
        try:
            try:
                start_dt = normalize_event_datetime(ev["event_date"], ev["event_time"], tz)
            except (ValueError, TypeError) as e:
                _logger.warning(
                    "cron_datetime_normalization_failed",
                    event_id=ev['event_id'],
                    guild_id=guild.id,
                    raw_date=ev.get('event_date'),
                    raw_time=ev.get('event_time'),
                    error=str(e)
                )
                try:
                    safe_date = normalize_date_only(ev.get("event_date"))
                except Exception:
                    return None
                fallback_time = dt_time(21, 0)
                start_dt = self._localize_safe(tz, datetime.combine(safe_date, fallback_time))
        except Exception as e:
            _logger.error(
                "cron_error_parsing_event",
                event_id=ev['event_id'],
                error=str(e),
                exc_info=True,
            )
            return None

        time_diff = start_dt - now
        time_condition = (
            timedelta(minutes=-60) <= time_diff <= timedelta(minutes=15)
        )
        status_condition = ev.get("status", "").strip().lower() in [
            "confirmed",
            "planned",
        ]

        _logger.debug(
            "cron_event_time_condition_check",
            event_id=ev['event_id'],
            time_diff=time_diff,
            condition_met=time_condition and status_condition
        )

        if time_condition and status_condition:
            closed_localized = await get_guild_message(self.bot, guild.id, EVENT_MANAGEMENT, "events_infos.status_closed")
            if not closed_localized:
                closed_localized = "Closed"
            closed_db = EventStatus.validate(EventStatus.CLOSED)
            
            try:
                msg = await events_channel.fetch_message(ev["event_id"])
                
                if msg.embeds:
                    embed = msg.embeds[0]
                    for i, field in enumerate(embed.fields):
                        if "status" in field.name.lower():
                            embed.set_field_at(i, name=field.name, value=closed_localized, inline=field.inline)
                            break
                    await msg.edit(embed=embed)
                    
                return {
                    "event_id": ev["event_id"],
                    "status": closed_db
                }
                    
            except Exception as e:
                _logger.error(
                    "cron_error_fetching_message",
                    event_id=ev['event_id'],
                    error=str(e),
                    exc_info=True,
                )
                return None
        
        return None

    async def _batch_update_closed_events(self, guild_id: int, closed_events: List[dict]) -> None:
        """
        Update multiple closed events in the database.
        
        Args:
            guild_id: Guild ID
            closed_events: List of closed event data
        """
        try:
            event_updates = [(ev["status"], guild_id, ev["event_id"]) for ev in closed_events]
            
            query = """
            UPDATE events_data 
            SET status = %s 
            WHERE guild_id = %s AND event_id = %s
            """
            
            for status, gid, event_id in event_updates:
                await self.bot.run_db_query(query, (status, gid, event_id), commit=True)

                cached_event = await self.get_event_from_cache(gid, event_id)
                if cached_event:
                    cached_event["status"] = status
                    await self.set_event_in_cache(gid, event_id, cached_event)
                    
            _logger.info(
                "batch_updated_closed_events",
                guild_id=guild_id,
                count=len(closed_events)
            )
            
        except Exception as e:
            _logger.error(
                "error_batch_updating_closed_events",
                guild_id=guild_id,
                error=str(e),
                exc_info=True
            )

    async def event_close_cron(self) -> None:
        """
        Automated task to close events and process registrations.

        Args:
            None

        Returns:
            None
        """
        if not await self._check_cron_lock("event_close"):
            return
            
        try:
            GUILD_BATCH_SIZE = 8
            all_guilds = list(self.bot.guilds)
            all_results = []
            
            for i in range(0, len(all_guilds), GUILD_BATCH_SIZE):
                batch = all_guilds[i:i + GUILD_BATCH_SIZE]

                batch_results = await asyncio.gather(
                    *[self._process_guild_close_events(guild) for guild in batch],
                    return_exceptions=True
                )

                for guild, result in zip(batch, batch_results):
                    if isinstance(result, Exception):
                        _logger.error(
                            "guild_close_processing_failed",
                            guild_id=guild.id,
                            guild_name=guild.name,
                            error=str(result),
                            exc_info=result
                        )
                        all_results.append(f"{guild.name}: Failed - {str(result)}")
                    elif isinstance(result, list):
                        all_results.extend(result)
                    else:
                        _logger.warning(
                            "unexpected_result_type_in_close_cron",
                            guild_id=guild.id,
                            result_type=type(result).__name__
                        )
                        all_results.append(f"{guild.name}: Unexpected result type")

                if i + GUILD_BATCH_SIZE < len(all_guilds):
                    await asyncio.sleep(0.3)
            
            _logger.info("event_close_cron_finished", results=len(all_results))
        finally:
            await self._release_cron_lock("event_close")

    @staticmethod
    def group_members_by_class(member_ids, roster_data):
        """
        Group members by their class for balanced team composition.

        Args:
            member_ids: List of member IDs to group
            roster_data: Dictionary containing member roster information

        Returns:
            Tuple of (classes_dict, missing_list) where classes_dict contains members grouped by class and missing_list contains members without class data
        """
        _logger.debug("building_class_buckets")
        classes = {
            c: [] for c in ("Tank", "Melee DPS", "Ranged DPS", "Healer", "Flanker")
        }
        missing = []

        for mid in member_ids:
            try:
                info = roster_data["members"][str(mid)]
            except KeyError:
                _logger.warning(
                    "member_id_not_found_in_roster",
                    member_id=mid,
                    operation="GroupsMembersByClass"
                )
                missing.append(mid)
                continue

            pseudo = info.get("pseudo", "Unknown")
            gs = info.get("GS", "N/A")
            weapons = info.get("weapons", "")
            member_class = info.get("class", "Unknown")

            weapon_parts = [c.strip() for c in (weapons or "").split("/") if c.strip()]
            emojis = " ".join([WEAPON_EMOJIS.get(c, c) for c in weapon_parts]) or "N/A"

            classes.setdefault(member_class, []).append(f"{pseudo} {emojis} - GS: {gs}")

        _logger.info(
            "buckets_built_complete",
            operation="GroupsMembersByClass",
            total_entries=sum(len(v) for v in classes.values()),
            missing_count=len(missing)
        )
        return classes, missing

    @staticmethod
    def _get_optimal_grouping(
        n: int, min_size: int = GROUP_MIN_SIZE, max_size: int = GROUP_MAX_SIZE
    ) -> "list[int]":
        """
        Calculate optimal group sizes for a given number of participants.

        Args:
            n: Total number of participants
            min_size: Minimum group size (default: 4)
            max_size: Maximum group size (default: 6)

        Returns:
            List of integers representing optimal group sizes
        """
        if n <= 0:
            return []
            
        _logger.debug(
            "optimal_grouping_start",
            n=n,
            min_size=min_size,
            max_size=max_size
        )
        possible = []
        try:
            for k in range(math.ceil(n / max_size), n // min_size + 1):
                base = n // k
                extra = n % k
                if base < min_size or base + 1 > max_size:
                    continue
                grouping = [base + 1] * extra + [base] * (k - extra)
                possible.append((k, grouping))

            if not possible:
                k = math.ceil(n / max_size)
                base = n // k
                extra = n % k
                result = [base + 1] * extra + [base] * (k - extra)
                _logger.debug(
                    "optimal_grouping_fallback_result",
                    result=result
                )
                return result

            possible.sort(
                key=lambda t: (sum(1 for s in t[1] if s == max_size), -t[0]),
                reverse=True,
            )
            result = possible[0][1]
            _logger.debug("optimal_grouping_best_result", result=result)
            return result
        except Exception as exc:
            _logger.error(
                "optimal_grouping_unexpected_error",
                error=str(exc),
                exc_info=True
            )
            sizes, remaining = [], n
            while remaining > 0:
                s = min(max_size, max(min_size, remaining))
                rem = remaining - s
                if 0 < rem < min_size:
                    delta = min(s - min_size, min_size - rem)
                    s -= delta
                    rem = remaining - s
                sizes.append(s)
                remaining = rem
            return sizes

    def _calculate_gs_ranges(self, members_data: list[dict]) -> list[tuple[int, int]]:
        """
        Calculate gear score ranges for balanced grouping.

        Args:
            members_data: List of dictionaries containing member information including GS

        Returns:
            List of tuples representing gear score ranges (min, max)
        """
        gs_values = []
        for member in members_data:
            gs_str = member.get("GS", "0")
            if isinstance(gs_str, str) and gs_str.lower() in [
                "n/a",
                "na",
                "",
                "unknown",
            ]:
                continue
            gs = _parse_gs(gs_str)
            if gs > 0:
                gs_values.append(gs)

        if len(gs_values) < 2:
            return [(0, 10000)]

        gs_values.sort()
        min_gs, max_gs = gs_values[0], gs_values[-1]

        total_members = len(gs_values)
        gs_spread = max_gs - min_gs

        if total_members < 10:
            tolerance = max(gs_spread * 0.4, 200)
        elif total_members < 30:
            tolerance = max(gs_spread * 0.25, 150)
        else:
            std_dev = statistics.stdev(gs_values) if len(gs_values) > 1 else 100
            tolerance = min(std_dev * 1.2, 200)
        
        tolerance = max(tolerance, 50)

        ranges = []
        current_min = min_gs

        while current_min < max_gs:
            range_max = min(current_min + tolerance, max_gs)
            ranges.append((int(current_min), int(range_max)))
            current_min = range_max - (tolerance * 0.1)

            if len(ranges) >= 5:
                break

        _logger.debug(
            "gs_ranges_calculated",
            total_members=total_members,
            ranges=ranges
        )
        return ranges

    def _get_member_gs_range(self, member_gs: Optional[int | float | str], gs_ranges: list[tuple[int, int]]) -> int:
        """
        Determine which gear score range a member belongs to.

        Args:
            member_gs: Member's gear score value
            gs_ranges: List of gear score range tuples

        Returns:
            Integer index of the appropriate gear score range
        """
        if isinstance(member_gs, str) and member_gs.lower() in ["n/a", "na", ""]:
            return 0
        gs = _parse_gs(member_gs)
        if gs == 0:
            return 0
            
        for i, (min_gs, max_gs) in enumerate(gs_ranges):
            if min_gs <= gs <= max_gs:
                return i
        for i, (min_gs, max_gs) in enumerate(gs_ranges):
            if gs < min_gs:
                return i
            if gs > max_gs and i == len(gs_ranges) - 1:
                return i
        return 0

    async def _format_static_group_members(
        self, member_ids: list[int], guild_obj, absent_text: str
    ) -> list[str]:
        """
        Format static group members for display with class icons and status.

        Args:
            member_ids: List of Discord member IDs
            guild_obj: Discord guild object
            absent_text: Text to display for absent members

        Returns:
            List of formatted member strings with class icons and names
        """
        member_info_list = []

        guild_members_cache = (
            await self.bot.cache.get("roster_data", "guild_members") or {}
        )

        for member_id in member_ids:
            member = guild_obj.get_member(member_id) if guild_obj else None

            member_data = (
                guild_members_cache.get((guild_obj.id, member_id), {})
                if guild_obj
                else {}
            )

            class_value = member_data.get("class")
            if not class_value or class_value == "NULL":
                class_value = "Unknown"

            gs_value = member_data.get("GS")
            if not gs_value or gs_value == 0 or gs_value == "0":
                gs_value = "N/A"

            weapons_value = member_data.get("weapons")
            if not weapons_value or weapons_value == "NULL":
                weapons_value = "N/A"

            member_info = {
                "member": member,
                "member_id": member_id,
                "class": class_value,
                "gs": gs_value,
                "weapons": weapons_value,
                "mention": (
                    member.mention if member else f"<@{member_id}> ({absent_text})"
                ),
                "is_present": member is not None,
            }
            member_info_list.append(member_info)

        class_priority = {
            "Tank": 1,
            "Healer": 2,
            "Melee DPS": 3,
            "Ranged DPS": 4,
            "Flanker": 5,
            "Unknown": 99,
        }

        member_info_list.sort(
            key=lambda x: (class_priority.get(x["class"], 99), not x["is_present"])
        )

        formatted_members = []
        for info in member_info_list:
            class_emoji = CLASS_EMOJIS.get(info["class"], "❓")

            weapons_emoji = ""
            if info["weapons"] and info["weapons"] != "N/A":
                weapon_list = [
                    w.strip() for w in info["weapons"].split("/") if w.strip()
                ]
                weapons_emoji = (
                    " ".join(
                        [
                            str(WEAPON_EMOJIS.get(weapon, weapon))
                            for weapon in weapon_list
                        ]
                    )
                    if weapon_list
                    else ""
                )

            gs_display = (
                f"({info['gs']})" if info["gs"] and info["gs"] != "N/A" else "(N/A)"
            )

            line = f"{class_emoji} {info['mention']} {weapons_emoji} {gs_display}"

            formatted_members.append(line)

        return formatted_members

    def _calculate_group_role_needs(self, group: list[dict]) -> dict[str, int]:
        """
        Calculate how many tanks and healers a group is missing for optimal composition.
        
        Args:
            group: List of member dictionaries in the group
            
        Returns:
            Dictionary with 'tanks_needed' and 'healers_needed' counts
        """
        current_tanks = sum(1 for m in group if m.get("member_class", m.get("class")) == "Tank")
        current_healers = sum(1 for m in group if m.get("member_class", m.get("class")) == "Healer")
        

        tanks_needed = max(0, 1 - current_tanks)
        healers_needed = max(0, 1 - current_healers)
        
        return {
            "tanks_needed": tanks_needed,
            "healers_needed": healers_needed
        }
        
    def _get_group_composition_trace(self, group: list[dict]) -> GroupStats:
        """
        Generate detailed composition trace for debugging group formation.
        
        Args:
            group: List of member dictionaries in the group
            
        Returns:
            Dictionary with composition details for logging
        """
        if not group:
            return {
                "size": 0, 
                "composition": "empty", 
                "avg_gs": 0.0, 
                "classes": {}, 
                "tanks": 0, 
                "healers": 0, 
                "dps": 0
            }
            

        class_counts = {}
        gs_values = []
        
        for member in group:
            member_class = member.get("member_class", member.get("class", "Unknown"))
            class_counts[member_class] = class_counts.get(member_class, 0) + 1
            
            gs = _parse_gs(member.get("GS", 0))
            if gs > 0:
                gs_values.append(gs)
        

        avg_gs = sum(gs_values) / len(gs_values) if gs_values else 0
        

        composition_parts = []
        for class_name, count in class_counts.items():
            composition_parts.append(f"{count}{class_name[:1]}")
        composition = "/".join(composition_parts)
        
        return {
            "size": len(group),
            "composition": composition,
            "avg_gs": round(avg_gs, 1),
            "classes": class_counts,
            "tanks": class_counts.get("Tank", 0),
            "healers": class_counts.get("Healer", 0),
            "dps": sum(class_counts.get(cls, 0) for cls in ["Melee DPS", "Ranged DPS", "Flanker"])
        }

    def _calculate_member_score(
        self,
        member: dict,
        target_class: str,
        target_gs_range: int,
        gs_ranges: list[tuple[int, int]],
        is_tentative: bool = False,
        group_context: Optional[list[dict]] = None,
    ) -> float:
        """
        Calculate a score for how well a member fits a target group position.
        Enhanced with role shortage bonus for tanks and healers.

        Args:
            member: Dictionary containing member information
            target_class: Target class for the position
            target_gs_range: Target gear score range index
            gs_ranges: List of gear score range tuples
            is_tentative: Whether the member is tentative (default: False)
            group_context: Optional group to check for role needs

        Returns:
            Float score representing member fit (higher is better)
        """
        score = 0.0
        member_class = member.get("member_class", member.get("class"))
        if member_class == target_class:
            score += 0.7
        elif target_class in ["Melee DPS", "Ranged DPS"] and member_class in [
            "Melee DPS",
            "Ranged DPS",
        ]:
            score += 0.5
        elif member_class in ["Melee DPS", "Ranged DPS", "Flanker"]:
            score += 0.3
        if group_context:
            role_needs = self._calculate_group_role_needs(group_context)
            member_class_value = member.get("member_class", member.get("class"))
            
            if member_class_value == "Tank" and role_needs["tanks_needed"] > 0:
                score += 0.5
                _logger.debug(
                    "role_shortage_bonus_applied",
                    member_id=member.get("user_id"),
                    role="Tank",
                    bonus=0.5
                )
            elif member_class_value == "Healer" and role_needs["healers_needed"] > 0:
                score += 0.4
                _logger.debug(
                    "role_shortage_bonus_applied",
                    member_id=member.get("user_id"),
                    role="Healer",
                    bonus=0.4
                )
        member_gs_range = self._get_member_gs_range(member.get("GS", 0), gs_ranges)
        if member_gs_range == target_gs_range:
            score += 0.2
        elif abs(member_gs_range - target_gs_range) == 1:
            score += 0.1
        if not is_tentative:
            score += 0.1
        else:
            score += 0.05

        return score

    async def _assign_groups_enhanced(
        self,
        guild_id: int,
        presence_ids: list[int],
        tentative_ids: list[int],
        roster_data: dict,
    ) -> list[list[GroupMember]]:
        """
        Assign members to balanced groups using enhanced algorithm with gear score and class balancing.

        Args:
            guild_id: Discord guild ID
            presence_ids: List of confirmed participant IDs
            tentative_ids: List of tentative participant IDs
            roster_data: Dictionary containing member roster information

        Returns:
            List of groups, where each group is a list of member dictionaries
        """
        _logger.info(
            "[GuildEvents - Groups Enhanced] Starting enhanced group assignment"
        )

        all_inscribed = set(presence_ids + tentative_ids)
        final_groups = []
        used_members = set()
        incomplete_static_groups = []

        def get_member_info(uid: int, tentative: bool = False):
            """
            Get formatted member information for event display.

            Args:
                uid: Discord user ID
                tentative: Whether the member is tentative (default: False)

            Returns:
                Dictionary with member information and tentative status, None if not found
            """
            info = roster_data["members"].get(str(uid))
            if not info:
                return None
            return {**info, "tentative": tentative, "user_id": uid}

        all_members_data = [
            info for uid in all_inscribed if (info := get_member_info(uid)) is not None
        ]
        gs_ranges = self._calculate_gs_ranges(all_members_data)
        _logger.info(
            "groups_enhanced_gs_ranges_calculated",
            gs_ranges=gs_ranges
        )

        _logger.info(
            "[GuildEvents - Groups Enhanced] Step 1: Processing static groups (complete or N-1)"
        )

        static_groups = await self.get_static_groups_data(guild_id)
        for group_name, group_data in static_groups.items():
            member_ids = group_data["member_ids"]
            configured_count = len(member_ids)
            signed = set(presence_ids) | set(tentative_ids)
            available_members = [
                mid
                for mid in member_ids
                if mid in signed and mid not in used_members
            ]
            present_count = len(available_members)

            _logger.debug(
                "groups_enhanced_static_group_availability",
                group_name=group_name,
                present_count=present_count,
                configured_count=configured_count
            )

            if present_count == configured_count or present_count == (
                configured_count - 1
            ):
                group_members = []
                for mid in available_members:
                    is_tentative = mid in tentative_ids
                    member_info = get_member_info(mid, is_tentative)
                    if member_info:
                        group_members.append(member_info)
                        used_members.add(mid)

                if group_members:
                    incomplete_static_groups.append(
                        {
                            "name": group_name,
                            "members": group_members,
                            "missing_slots": 6 - len(group_members),
                            "original_ids": member_ids,
                        }
                    )
                    _logger.info(
                        "groups_enhanced_static_group_created",
                        group_name=group_name,
                        member_count=len(group_members),
                        max_members=6
                    )
            else:
                _logger.debug(
                    "static_group_not_eligible",
                    operation="Groups Enhanced",
                    group_name=group_name,
                    present_count=present_count,
                    configured_count=configured_count
                )

        _logger.info("groups_enhanced_step2_completing_static")

        for static_group in incomplete_static_groups:
            if static_group["missing_slots"] > 0:
                existing_classes = [m["class"] for m in static_group["members"]]
                missing_classes = []

                if len(static_group["members"]) == (
                    len(static_group["original_ids"]) - 1
                ):
                    missing_id = [
                        mid
                        for mid in static_group["original_ids"]
                        if mid not in [m["user_id"] for m in static_group["members"]]
                    ][0]
                    missing_info = get_member_info(missing_id)
                    if missing_info:
                        missing_classes.append(missing_info["class"])

                essential_classes = ["Tank", "Healer"]
                for essential in essential_classes:
                    if essential not in existing_classes:
                        missing_classes.append(essential)

                available_members = [
                    uid
                    for uid in all_inscribed
                    if uid not in used_members
                    and uid not in static_group["original_ids"]
                ]

                for _ in range(static_group["missing_slots"]):
                    best_candidate = None
                    best_score = 0

                    for uid in available_members:
                        member_info = get_member_info(uid, uid in tentative_ids)
                        if not member_info:
                            continue

                        if missing_classes and member_info["class"] in missing_classes:
                            score = self._calculate_member_score(
                                member_info,
                                missing_classes[0],
                                0,
                                gs_ranges,
                                uid in tentative_ids,
                            )
                        else:
                            score = self._calculate_member_score(
                                member_info,
                                "Melee DPS",
                                0,
                                gs_ranges,
                                uid in tentative_ids,
                            )

                        if score > best_score:
                            best_score = score
                            best_candidate = uid

                    if best_candidate:
                        member_info = get_member_info(
                            best_candidate, best_candidate in tentative_ids
                        )
                        static_group["members"].append(member_info)
                        used_members.add(best_candidate)
                        available_members.remove(best_candidate)
                        static_group["missing_slots"] -= 1

                        if (
                            missing_classes
                            and member_info
                            and member_info.get("class") in missing_classes
                        ):
                            missing_classes.remove(member_info["class"])

                        if member_info:
                            _logger.info(
                                "added_member_to_static_group",
                                operation="Groups Enhanced",
                                member_class=member_info.get('class', 'Unknown'),
                                group_name=static_group['name']
                            )

            final_groups.append(static_group["members"])

        _logger.info(
            "[GuildEvents - Groups Enhanced] Step 3: Creating optimized groups with GS matching"
        )

        remaining_members = [uid for uid in all_inscribed if uid not in used_members]
        present_remaining = [uid for uid in remaining_members if uid in presence_ids]
        tentative_remaining = [uid for uid in remaining_members if uid in tentative_ids]

        gs_buckets = {}
        for i, gs_range in enumerate(gs_ranges):
            gs_buckets[i] = {
                "Tank": [],
                "Healer": [],
                "Melee DPS": [],
                "Ranged DPS": [],
                "Flanker": [],
            }

        for uid in present_remaining:
            member_info = get_member_info(uid, False)
            if member_info:
                gs_range_idx = self._get_member_gs_range(
                    member_info.get("GS", 0), gs_ranges
                )
                if member_info["class"] in gs_buckets[gs_range_idx]:
                    gs_buckets[gs_range_idx][member_info["class"]].append(member_info)

        for gs_idx in sorted(gs_buckets.keys(), reverse=True):
            bucket = gs_buckets[gs_idx]

            while len(bucket["Flanker"]) >= 5:
                flanker_group = (
                    bucket["Flanker"][:6]
                    if len(bucket["Flanker"]) >= 6
                    else bucket["Flanker"][:5]
                )
                final_groups.append(flanker_group)
                bucket["Flanker"] = bucket["Flanker"][len(flanker_group) :]
                for member in flanker_group:
                    used_members.add(member["user_id"])
                _logger.info(
                    "groups_enhanced_flanker_group_formed",
                    gs_range=gs_ranges[gs_idx]
                )

            while len(bucket["Tank"]) >= 1 and len(bucket["Healer"]) >= 1:
                group = []

                tanks_needed = min(2, len(bucket["Tank"]))
                healers_needed = min(2, len(bucket["Healer"]))

                for _ in range(tanks_needed):
                    if bucket["Tank"]:
                        member = bucket["Tank"].pop(0)
                        group.append(member)
                        used_members.add(member["user_id"])

                for _ in range(healers_needed):
                    if bucket["Healer"]:
                        member = bucket["Healer"].pop(0)
                        group.append(member)
                        used_members.add(member["user_id"])

                remaining_slots = 6 - len(group)
                dps_classes = ["Melee DPS", "Ranged DPS", "Flanker"]

                for dps_class in dps_classes:
                    while remaining_slots > 0 and bucket[dps_class]:
                        member = bucket[dps_class].pop(0)
                        group.append(member)
                        used_members.add(member["user_id"])
                        remaining_slots -= 1

                if len(group) >= 4:
                    final_groups.append(group)
                    composition = self._get_group_composition_trace(group)
                    _logger.info(
                        "groups_enhanced_optimized_group_formed",
                        gs_range=gs_ranges[gs_idx],
                        member_count=len(group),
                        composition=composition["composition"],
                        avg_gs=composition["avg_gs"],
                        tanks=composition["tanks"],
                        healers=composition["healers"]
                    )
                else:
                    for member in group:
                        used_members.discard(member["user_id"])
                        bucket[member["class"]].append(member)
                    break

        for uid in tentative_remaining:
            if uid not in used_members:
                member_info = get_member_info(uid, True)
                if member_info and final_groups:
                    best_group = None
                    best_score = 0

                    for group in final_groups:
                        if len(group) < GROUP_MAX_SIZE:
                            valid_gs_values = [
                                _parse_gs(m.get("GS", 0))
                                for m in group
                                if _parse_gs(m.get("GS", 0)) > 0
                            ]
                            group_gs_avg = (
                                sum(valid_gs_values) / len(valid_gs_values)
                                if valid_gs_values
                                else 0
                            )
                            gs_range_idx = self._get_member_gs_range(
                                group_gs_avg, gs_ranges
                            )
                            score = self._calculate_member_score(
                                member_info, "Melee DPS", gs_range_idx, gs_ranges, True, group
                            )

                            if score > best_score:
                                best_score = score
                                best_group = group

                    if best_group:
                        best_group.append(member_info)
                        used_members.add(uid)
                        _logger.info(
                            "added_tentative_to_optimized_group",
                            operation="Groups Enhanced",
                            member_class=member_info['class']
                        )

        _logger.info(
            "[GuildEvents - Groups Enhanced] Step 4: Creating non-optimized groups"
        )

        remaining_members = [uid for uid in all_inscribed if uid not in used_members]

        while len(remaining_members) >= 4:
            group = []

            for uid in remaining_members[:6]:
                member_info = get_member_info(uid, uid in tentative_ids)
                if member_info:
                    group.append(member_info)
                    used_members.add(uid)

            remaining_members = [
                uid for uid in remaining_members if uid not in used_members
            ]

            if len(group) >= 4:
                final_groups.append(group)
                composition = self._get_group_composition_trace(group)
                _logger.info(
                    "groups_enhanced_non_optimized_group_formed",
                    member_count=len(group),
                    composition=composition["composition"],
                    avg_gs=composition["avg_gs"],
                    tanks=composition["tanks"],
                    healers=composition["healers"]
                )

        _logger.info("groups_enhanced_step5_final_redistribution")

        final_remaining = [uid for uid in all_inscribed if uid not in used_members]

        for uid in final_remaining[:]:
            member_info = get_member_info(uid, uid in tentative_ids)
            if member_info:
                for group in final_groups:
                    if len(group) < GROUP_MAX_SIZE:
                        group.append(member_info)
                        used_members.add(uid)
                        final_remaining.remove(uid)
                        _logger.info(
                            "added_remaining_member_to_group",
                            operation="Groups Enhanced"
                        )
                        break

        if final_remaining:
            last_group = []
            for uid in final_remaining:
                member_info = get_member_info(uid, uid in tentative_ids)
                if member_info:
                    last_group.append(member_info)
                    used_members.add(uid)

            if last_group:
                final_groups.append(last_group)
                composition = self._get_group_composition_trace(last_group)
                _logger.info(
                    "groups_enhanced_final_isolation_group_formed",
                    member_count=len(last_group),
                    composition=composition["composition"],
                    avg_gs=composition["avg_gs"],
                    tanks=composition["tanks"],
                    healers=composition["healers"]
                )

        _logger.info(
            "groups_enhanced_completed",
            operation="Groups Enhanced",
            groups_count=len(final_groups)
        )
        return final_groups

    def _assign_groups_legacy(
        self, presence_ids: "list[int]", tentative_ids: "list[int]", roster_data: dict
    ) -> "list[list[dict]]":
        """
        Assign members to groups using legacy algorithm for backward compatibility.

        Args:
            presence_ids: List of confirmed participant IDs
            tentative_ids: List of tentative participant IDs
            roster_data: Dictionary containing member roster information

        Returns:
            List of groups, where each group is a list of member dictionaries
        """
        _logger.debug("starting_group_assignment")

        buckets = {
            c: [] for c in ("Tank", "Healer", "Melee DPS", "Ranged DPS", "Flanker")
        }

        def _push(uid: int, tentative: bool):
            """
            Add a member to the appropriate class bucket for group assignment.

            Args:
                uid: Discord user ID
                tentative: Whether the member is tentative

            Returns:
                None
            """
            info = roster_data["members"].get(str(uid))
            if not info:
                _logger.warning(
                    "uid_missing_from_roster",
                    operation="AssignGroups",
                    uid=uid
                )
                return
            try:
                buckets[info["class"]].append({**info, "tentative": tentative})
            except KeyError:
                _logger.error(
                    "unknown_class_for_uid",
                    operation="AssignGroups",
                    member_class=info.get('class'),
                    uid=uid
                )

        for uid in presence_ids:
            _push(uid, False)
        for uid in tentative_ids:
            _push(uid, True)

        try:
            groups = []

            titular_flankers = [m for m in buckets["Flanker"] if not m["tentative"]]
            if len(titular_flankers) >= 4:
                grp = titular_flankers[:6]
                if len(grp) < 6:
                    extra = [m for m in buckets["Flanker"] if m["tentative"]][
                        : 6 - len(grp)
                    ]
                    grp.extend(extra)
                groups.append(grp)
                used = {id(m) for m in grp}
                buckets["Flanker"] = [
                    m for m in buckets["Flanker"] if id(m) not in used
                ]

            buckets["Ranged DPS"].extend(buckets.get("Flanker", []))
            buckets.pop("Flanker", None)

            sizes = self._get_optimal_grouping(len(presence_ids), 4, 6)

            def _pop(role, titular_first=True):
                """
                Remove and return a member from the specified role bucket.

                Args:
                    role: Class role to pop from
                    titular_first: Whether to prioritize confirmed members over tentative (default: True)

                Returns:
                    Member dictionary if found, None otherwise
                """
                pool = buckets[role]
                for i, m in enumerate(pool):
                    if (titular_first and not m["tentative"]) or not titular_first:
                        return pool.pop(i)
                return None

            for size in sizes:
                grp = []
                for role in ("Tank", "Healer"):
                    member = _pop(role) or _pop(role, False)
                    if member:
                        grp.append(member)

                for role in ("Melee DPS", "Ranged DPS"):
                    while len(grp) < size and buckets[role]:
                        member = _pop(role)
                        if not member:
                            break
                        grp.append(member)

                role_cycle, idx = ("Melee DPS", "Ranged DPS"), 0
                while len(grp) < size and any(buckets[r] for r in role_cycle):
                    role = role_cycle[idx % 2]
                    member = _pop(role) or _pop(role, False)
                    if member:
                        grp.append(member)
                    idx += 1

                groups.append(grp)

            fill_order = ("Healer", "Tank", "Melee DPS", "Ranged DPS")

            def _need_role(g):
                """
                Determine which role is most needed for group balance.

                Args:
                    g: Current group list of members

                Returns:
                    String role name that is most needed, None if group is balanced
                """
                classes = [m["class"] for m in g]
                if "Healer" not in classes and buckets["Healer"]:
                    return "Healer"
                if "Tank" not in classes and buckets["Tank"]:
                    return "Tank"
                melee = sum(c == "Melee DPS" for c in classes)
                ranged = sum(c == "Ranged DPS" for c in classes)
                if melee > ranged and buckets["Melee DPS"]:
                    return "Melee DPS"
                if buckets["Ranged DPS"]:
                    return "Ranged DPS"
                return None

            for grp in groups:
                while len(grp) < 6 and any(buckets[r] for r in fill_order):
                    role = _need_role(grp) or next(r for r in fill_order if buckets[r])
                    grp.append(buckets[role].pop(0))

            remaining = [m for pool in buckets.values() for m in pool]
            if remaining:
                comp_sizes = self._get_optimal_grouping(len(remaining), 4, 6)
                start = 0
                for cs in comp_sizes:
                    groups.append(remaining[start : start + cs])
                    start += cs

            _logger.info(
                "assign_groups_finished",
                operation="AssignGroups",
                groups_count=len(groups)
            )
            return groups

        except Exception as exc:
            _logger.error(
                "assign_groups_unexpected_error",
                error=str(exc),
                exc_info=True
            )
            return []

    async def create_groups(self, guild_id: int, event_id: int) -> None:
        """
        Create balanced groups for an event based on registrations.

        Args:
            guild_id: Discord guild ID
            event_id: Unique event identifier

        Returns:
            None
        """
        _logger.info(
            "cron_creating_groups",
            guild_id=guild_id,
            event_id=event_id
        )

        guild = self.bot.get_guild(guild_id)
        if not guild:
            _logger.error(
                "cron_guild_not_found",
                guild_id=guild_id
            )
            return

        settings = await self.bot.cache.get_guild_data(guild_id, "settings")
        if not settings:
            _logger.error(
                "cron_no_configuration_found",
                guild_id=guild_id
            )
            return

        guild_lang = settings.get("guild_lang", "en-US")

        channels_data = await self.bot.cache.get_guild_data(guild_id, "channels")
        if not channels_data:
            _logger.error(
                "cron_no_channels_configuration",
                guild_id=guild_id
            )
            return

        roles_data = await self.bot.cache.get_guild_data(guild_id, "roles")

        groups_channel = (
            guild.get_channel(channels_data.get("groups_channel"))
            if channels_data.get("groups_channel")
            else None
        )
        events_channel = (
            guild.get_channel(channels_data.get("events_channel"))
            if channels_data.get("events_channel")
            else None
        )
        members_role_id = roles_data.get("members") if roles_data else None
        mention_role = f"<@&{members_role_id}>" if members_role_id else ""
        if not groups_channel or not events_channel:
            _logger.error(
                "cron_channels_not_found",
                guild_id=guild_id
            )
            return

        event = await self.get_event_from_cache(guild_id, event_id)
        if not event:
            _logger.error(
                "event_not_found_for_groups",
                guild_id=guild_id,
                event_id=event_id
            )
            return

        registrations = event["registrations"]
        presence_ids = registrations.get("presence", [])
        tentative_ids = registrations.get("tentative", [])

        presence_count = len(presence_ids)
        tentative_count = len(tentative_ids)
        event_link = (
            f"https://discord.com/channels/{guild.id}/{events_channel.id}/{event_id}"
        )
        labels = await self._t(guild_id,
            "events_infos.event_name",
            "events_infos.time_at",
            "events_infos.present_count",
            "events_infos.attempt_count",
            "events_infos.view_event",
            "events_infos.groups_below"
        )
        
        event_name_label = labels["events_infos.event_name"]
        time_at_label = labels["events_infos.time_at"]
        present_count_label = labels["events_infos.present_count"]
        attempt_count_label = labels["events_infos.attempt_count"]
        view_event_label = labels["events_infos.view_event"]
        groups_below_label = labels["events_infos.groups_below"]
        
        header = (
            f"{mention_role}\n\n"
            f"**__{event_name_label} :__ {event['name']}**\n"
            f"{event['event_date']} {time_at_label} {event['event_time']}\n"
            f"{present_count_label} : {presence_count}\n{attempt_count_label} : {tentative_count}\n\n"
            f"[{view_event_label}]({event_link})\n\n"
            f"{groups_below_label}\n"
        )

        try:
            roster_data = {"members": {}}

            if hasattr(self.bot, "cache") and hasattr(
                self.bot.cache, "get_bulk_guild_members"
            ):
                members_data = await self.bot.cache.get_bulk_guild_members(guild_id)
                for member_id, member_data in members_data.items():
                    try:
                        discord_member = guild.get_member(member_id)
                        if discord_member:
                            roster_data["members"][str(member_id)] = {
                                "pseudo": discord_member.display_name,
                                "GS": member_data.get("GS", "N/A"),
                                "weapons": member_data.get("weapons", "N/A"),
                                "class": member_data.get("class", "Unknown"),
                            }
                    except Exception:
                        continue
            else:
                for member in guild.members:
                    md = await self.get_guild_member_data(guild_id, member.id)
                    roster_data["members"][str(member.id)] = {
                        "pseudo": member.display_name,
                        "GS": md.get("GS", "N/A"),
                        "weapons": md.get("weapons", "N/A"),
                        "class": md.get("class", "Unknown"),
                    }
        except Exception as exc:
            _logger.error(
                "create_groups_failed_build_roster",
                error=str(exc),
                exc_info=True
            )
            return

        try:
            all_groups = await self._assign_groups_enhanced(
                guild_id, presence_ids, tentative_ids, roster_data
            )
        except Exception as exc:
            _logger.error(
                "[Guild_Events - CreateGroups] _assign_groups_enhanced crashed.",
                error=str(exc),
                exc_info=True
            )
            return

        try:
            embeds = []
            total = len(all_groups)
            for idx, grp in enumerate(all_groups, 1):
                e = discord.Embed(
                    title=f"Groupe {idx} / {total}", color=discord.Color.blue()
                )
                lines = []
                for m in grp:
                    cls_emoji = CLASS_EMOJIS.get(m.get("class", ""), "")
                    weapon_parts = [
                        c.strip()
                        for c in (m.get("weapons") or "").split("/")
                        if c.strip()
                    ]
                    weapons_emoji = " ".join(
                        [WEAPON_EMOJIS.get(c, c) for c in weapon_parts]
                    )
                    pseudo = m.get('pseudo', 'Unknown')
                    gs = m.get('GS', 'N/A')
                    if m.get("tentative"):
                        lines.append(
                            f"{cls_emoji} {weapons_emoji} *{pseudo}* ({gs}) 🔶"
                        )
                    else:
                        lines.append(
                            f"{cls_emoji} {weapons_emoji} {pseudo} ({gs})"
                        )
                no_member_text = EVENT_MANAGEMENT.get("no_member", {}).get(
                    guild_lang, "No member"
                )
                e.description = "\n".join(lines) or no_member_text
                embeds.append(e)

            MAX_EMBEDS = 10
            for i in range(0, len(embeds), MAX_EMBEDS):
                await groups_channel.send(
                    content=header if i == 0 else None,
                    embeds=embeds[i:i + MAX_EMBEDS]
                )
            _logger.info(
                "groups_sent_to_channel",
                channel_id=groups_channel.id,
                embed_count=len(embeds),
                message_count=math.ceil(len(embeds) / MAX_EMBEDS)
            )

            await self._notify_ptb_groups(guild_id, event_id, all_groups)
            _logger.info("groups_sent_to_ptb")

        except Exception as exc:
            _logger.error(
                "create_groups_failed_send_embeds",
                error=str(exc),
                exc_info=True
            )

    async def event_create(
        self,
        ctx: discord.ApplicationContext,
        event_name: str = discord.Option(
            str,
            description=EVENT_MANAGEMENT["event_create_options"]["event_name"]["en-US"],
            description_localizations=EVENT_MANAGEMENT["event_create_options"][
                "event_name"
            ],
        ),
        event_date: str = discord.Option(
            str,
            description=EVENT_MANAGEMENT["event_create_options"]["event_date"]["en-US"],
            description_localizations=EVENT_MANAGEMENT["event_create_options"][
                "event_date"
            ],
        ),
        event_time: str = discord.Option(
            str,
            description=EVENT_MANAGEMENT["event_create_options"]["event_hour"]["en-US"],
            description_localizations=EVENT_MANAGEMENT["event_create_options"][
                "event_hour"
            ],
        ),
        duration: int = discord.Option(
            int,
            description=EVENT_MANAGEMENT["event_create_options"]["duration"]["en-US"],
            description_localizations=EVENT_MANAGEMENT["event_create_options"]["duration"],
            min_value=1,
            max_value=1440,
        ),
        status: str = discord.Option(
            str,
            default=EventStatus.CONFIRMED,
            description=EVENT_MANAGEMENT["event_create_options"]["status"]["en-US"],
            description_localizations=EVENT_MANAGEMENT["event_create_options"][
                "status"
            ],
            choices=[
                discord.OptionChoice(
                    name=choice_data["name"].get("en-US", key),
                    value=choice_data["value"],
                    name_localizations=choice_data["name"],
                )
                for key, choice_data in EVENT_MANAGEMENT["event_create_options"][
                    "choices"
                ].items()
            ],
        ),
        dkp_value: int = discord.Option(
            int,
            default=0,
            description=EVENT_MANAGEMENT["event_create_options"]["dkp_value"]["en-US"],
            description_localizations=EVENT_MANAGEMENT["event_create_options"][
                "dkp_value"
            ],
            min_value=0,
            max_value=9999,
        ),
        dkp_ins: int = discord.Option(
            int,
            default=0,
            description=EVENT_MANAGEMENT["event_create_options"]["dkp_ins"]["en-US"],
            description_localizations=EVENT_MANAGEMENT["event_create_options"][
                "dkp_ins"
            ],
            min_value=0,
            max_value=9999,
        ),
    ):
        """
        Create a new event with specified parameters.

        Args:
            ctx: Discord application context from the command
            event_name: Name of the event to create
            event_date: Date of the event in DD-MM-YYYY format
            event_time: Start time of the event in HH:MM format
            duration: Duration of the event in minutes (1-1440)
            status: Event status (Confirmed, Cancelled, etc.)
            dkp_value: DKP points awarded for event completion (0-9999)
            dkp_ins: DKP points required for event inscription (0-9999)

        Returns:
            None
        """
        await ctx.defer(ephemeral=True)

        guild = ctx.guild
        guild_id = ctx.guild.id

        user_locale = await get_effective_locale(self.bot, guild_id, ctx.user.id)
        guild_lang = (
            await self.bot.cache.get_guild_data(guild_id, "guild_lang") or "en-US"
        )

        settings = await self.bot.cache.get_guild_data(guild_id, "settings")
        if not settings:
            follow_message = await get_user_message(
                ctx, EVENT_MANAGEMENT, "event_create_options.no_settings"
            )
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        status = EventStatus.normalize(status)
        
        _logger.debug(
            "event_create_parameters_received",
            event_name=event_name,
            event_date=event_date,
            event_time=event_time,
            duration=duration,
            status=status,
            dkp_value=dkp_value,
            dkp_ins=dkp_ins
        )

        if not event_name or not event_name.strip():
            follow_message = await get_user_message(
                ctx, EVENT_MANAGEMENT, "event_create_options.name_empty"
            )
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        event_name = event_name.strip()
        if len(event_name) > 100:
            follow_message = await get_user_message(
                ctx, EVENT_MANAGEMENT, "event_create_options.name_too_long"
            )
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        if dkp_value < 0 or dkp_value > 9999:
            follow_message = await get_user_message(
                ctx, EVENT_MANAGEMENT, "event_create_options.dkp_value_invalid"
            )
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        if dkp_ins < 0 or dkp_ins > 9999:
            follow_message = await get_user_message(
                ctx, EVENT_MANAGEMENT, "event_create_options.dkp_ins_invalid"
            )
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        if duration <= 0 or duration > 1440:
            follow_message = await get_user_message(
                ctx, EVENT_MANAGEMENT, "event_create_options.duration_invalid"
            )
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        settings = await self.bot.cache.get_guild_data(ctx.guild.id, "settings")
        tz = get_guild_timezone(settings)
        try:

            try:
                start_date = normalize_date_only(event_date)

                temp_tz = pytz.timezone("Europe/Paris")  # Will be replaced with guild tz
                temp_dt = normalize_event_datetime(start_date, event_time, temp_tz)
                start_time_obj = temp_dt.time()
                _logger.debug(
                    "dates_parsed_successfully",
                    start_date=start_date,
                    start_time=start_time_obj
                )
            except (ValueError, TypeError) as parse_error:
                raise ValueError(f"Could not parse date/time: {event_date} {event_time}") from parse_error
        except Exception as e:
            _logger.error(
                "error_parsing_date_or_time",
                error=str(e),
                exc_info=True,
            )
            follow_message = await get_user_message(
                ctx, EVENT_MANAGEMENT, "event_create_options.date_ko"
            )
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        try:
            duration = int(duration)
            start_dt = self._localize_safe(tz, datetime.combine(start_date, start_time_obj))
            end_dt = start_dt + timedelta(minutes=duration)
            _logger.debug(
                "datetime_calculated",
                start_dt=start_dt,
                end_dt=end_dt
            )
        except Exception as e:
            _logger.error(
                "[GuildEvents - event_create] Error localizing or calculating end date.",
                exc_info=True,
            )
            follow_message = await get_user_message(
                ctx, EVENT_MANAGEMENT, "event_create_options.date_ko_2"
            )
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        translations = await self._t(guild_id,
            "events_infos.description",
            "events_infos.status_confirmed",
            "events_infos.status_planned",
            "events_infos.present",
            "events_infos.attempt",
            "events_infos.absence",
            "events_infos.voice_channel",
            "events_infos.groups",
            "events_infos.auto_grouping"
        )
        
        description = translations["events_infos.description"]
        if EventStatus.normalize(status) == EventStatus.CONFIRMED:
            localized_status = translations["events_infos.status_confirmed"]
        else:
            localized_status = translations["events_infos.status_planned"]
        event_present = translations["events_infos.present"]
        event_attempt = translations["events_infos.attempt"]
        event_absence = translations["events_infos.absence"]
        event_voice_channel = translations["events_infos.voice_channel"]
        event_groups = translations["events_infos.groups"]
        event_auto_grouping = translations["events_infos.auto_grouping"]
        channels_data = await self.bot.cache.get_guild_data(guild_id, "channels")
        conference_channel = (
            guild.get_channel(channels_data.get("voice_war_channel"))
            if channels_data
            else None
        )
        events_channel = (
            guild.get_channel(channels_data.get("events_channel"))
            if channels_data
            else None
        )
        if not events_channel or not conference_channel:
            _logger.error(
                "channels_not_found",
                events_channel=events_channel,
                conference_channel=conference_channel
            )
            follow_message = await get_user_message(
                ctx, EVENT_MANAGEMENT, "event_create_options.no_events_canal"
            )
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        embed_color = (
            discord.Color.green()
            if EventStatus.normalize(status) == EventStatus.CONFIRMED
            else discord.Color.blue()
        )

        t = await self._t(guild_id, 
            "events_infos.date",
            "events_infos.hour", 
            "events_infos.duration",
            "events_infos.status",
            "events_infos.dkp_v",
            "events_infos.dkp_i",
            "events_infos.none"
        )

        embed_translations = {
            "date": t["events_infos.date"],
            "hour": t["events_infos.hour"], 
            "duration": t["events_infos.duration"],
            "status": t["events_infos.status"],
            "dkp_v": t["events_infos.dkp_v"],
            "dkp_i": t["events_infos.dkp_i"],
            "present": event_present,
            "attempt": event_attempt,
            "absence": event_absence,
            "none": t["events_infos.none"]
        }
        
        embed = await self._create_event_embed(
            event_name=event_name,
            description=description,
            start_dt=start_dt,
            duration=duration,
            status=localized_status,
            dkp_value=dkp_value,
            dkp_ins=dkp_ins,
            translations=embed_translations,
            embed_color=embed_color
        )
        conference_link = (
            f"https://discord.com/channels/{guild.id}/{conference_channel.id}"
        )
        embed.add_field(
            name=event_voice_channel, value=f"[🏹 WAR]({conference_link})", inline=False
        )
        embed.add_field(name=event_groups, value=event_auto_grouping, inline=False)

        try:
            if EventStatus.normalize(status) == EventStatus.CONFIRMED:
                roles_data = await self.bot.cache.get_guild_data(guild.id, "roles")
                members_role_id = roles_data.get("members") if roles_data else None
                role_mention = guild.get_role(int(members_role_id)).mention if members_role_id and guild.get_role(int(members_role_id)) else ""
                update_message = await get_user_message(ctx, EVENT_MANAGEMENT, "event_confirm_messages.confirmed_notif", role=role_mention)
                announcement = await events_channel.send(
                    content=update_message, embed=embed
                )
            else:
                announcement = await events_channel.send(embed=embed)
            _logger.debug(
                "announcement_message_sent",
                message_id=announcement.id,
                channel_id=announcement.channel.id
            )
            message_link = f"https://discord.com/channels/{guild.id}/{announcement.channel.id}/{announcement.id}"
            embed.set_footer(text=f"Event ID = {announcement.id}")
            await announcement.edit(embed=embed)
            await asyncio.gather(
                announcement.add_reaction(self.EMOJI_YES),
                announcement.add_reaction(self.EMOJI_MAYBE),
                announcement.add_reaction(self.EMOJI_NO),
            )
        except Exception as e:
            _logger.error(
                "error_sending_announcement",
                error=str(e),
                exc_info=True,
            )
            follow_message = await get_user_message(
                ctx, EVENT_MANAGEMENT, "event_create_options.error_event", e=str(e)
            )
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        try:
            description_scheduled = await get_guild_message(self.bot, guild_id, EVENT_MANAGEMENT, "events_infos.description_scheduled")
            if not description_scheduled:
                description_scheduled = "Event details: {link}"
            description_scheduled = description_scheduled.format(link=message_link)
            try:
                scheduled_event = await guild.create_scheduled_event(
                    name=event_name,
                    description=description_scheduled,
                    start_time=start_dt,
                    end_time=end_dt,
                    channel=conference_channel,
                )
            except TypeError:
                scheduled_event = await guild.create_scheduled_event(
                    name=event_name,
                    description=description_scheduled,
                    start_time=start_dt,
                    end_time=end_dt,
                    location=str(conference_channel),
                )
            _logger.debug(
                "scheduled_event_created",
                scheduled_event_id=scheduled_event.id if scheduled_event else None
            )
        except Exception as e:
            _logger.error(
                "error_creating_scheduled_event",
                error=str(e),
                exc_info=True,
            )

        try:
            roles_data = await self.bot.cache.get_guild_data(guild.id, "roles")
            members_role_id = roles_data.get("members") if roles_data else None
            if members_role_id:
                role = guild.get_role(int(members_role_id))
                if role:
                    initial_members = [
                        member.id for member in guild.members if role in member.roles
                    ]
                else:
                    initial_members = []
            else:
                initial_members = []
        except Exception as e:
            _logger.error(
                "error_determining_initial_members",
                error=str(e),
                exc_info=True,
            )
            initial_members = []

        record = {
            "guild_id": guild.id,
            "event_id": announcement.id,
            "game_id": int(settings.get("guild_game", 0)),
            "name": event_name,
            "event_date": datetime_to_db_format(start_dt)[0],
            "event_time": datetime_to_db_format(start_dt)[1],
            "duration": duration,
            "dkp_value": dkp_value,
            "dkp_ins": dkp_ins,
            "status": EventStatus.validate(status),
            "initial_members": ensure_json_string(initial_members, "[]"),
            "registrations": ensure_json_string({"presence": [], "tentative": [], "absence": []}),
            "actual_presence": ensure_json_string([], "[]"),
        }
        query = """
        INSERT INTO events_data (
            guild_id,
            event_id,
            game_id,
            name,
            event_date,
            event_time,
            duration,
            dkp_value,
            dkp_ins,
            status,
            initial_members,
            registrations,
            actual_presence
        ) VALUES (
            %(guild_id)s,
            %(event_id)s,
            %(game_id)s,
            %(name)s,
            %(event_date)s,
            %(event_time)s,
            %(duration)s,
            %(dkp_value)s,
            %(dkp_ins)s,
            %(status)s,
            %(initial_members)s,
            %(registrations)s,
            %(actual_presence)s
        )
        ON DUPLICATE KEY UPDATE
            game_id = VALUES(game_id),
            name = VALUES(name),
            event_date = VALUES(event_date),
            event_time = VALUES(event_time),
            duration = VALUES(duration),
            dkp_value = VALUES(dkp_value),
            dkp_ins = VALUES(dkp_ins),
            status = VALUES(status),
            initial_members = VALUES(initial_members),
            registrations = VALUES(registrations),
            actual_presence = VALUES(actual_presence)
        """
        try:
            await self.bot.run_db_query(query, record, commit=True)
            event_data = from_db_row(cast(EventRowDB, record))
            await self.set_event_in_cache(guild.id, announcement.id, event_data)
            _logger.info(
                "event_saved_in_db_successfully",
                announcement_id=announcement.id
            )
            
            await self._invalidate_events_list_cache(guild.id)

            follow_message = await get_user_message(
                ctx,
                EVENT_MANAGEMENT,
                "event_create_options.events_created",
                event_id=announcement.id,
            )
            await ctx.followup.send(follow_message, ephemeral=True)
        except Exception as e:
            error_msg = str(e).lower()
            if "duplicate entry" in error_msg or "1062" in error_msg:
                _logger.warning(
                    "duplicate_event_entry_manual_create",
                    guild_id=guild.id,
                    event_name=event_name,
                    event_date=event_date,
                    event_time=event_time,
                    error=str(e)
                )
                follow_message = await get_user_message(
                    ctx, EVENT_MANAGEMENT, "event_create_options.duplicate_event"
                )
            else:
                _logger.error(
                    "error_saving_event_in_db_create",
                    guild_id=guild.id,
                    error=str(e),
                    exc_info=True,
                )
                follow_message = await get_user_message(
                    ctx, EVENT_MANAGEMENT, "event_create_options.event_ko", e=str(e)
                )
            await ctx.followup.send(follow_message, ephemeral=True)

    async def static_create(
        self,
        ctx: discord.ApplicationContext,
        group_name: str = discord.Option(
            str,
            description=STATIC_GROUPS["static_create"]["options"]["group_name"][
                "description"
            ]["en-US"],
            description_localizations=STATIC_GROUPS["static_create"]["options"][
                "group_name"
            ]["description"],
            min_length=2,
            max_length=50,
        ),
    ):
        """
        Create a new static group for recurring events.

        Args:
            ctx: Discord application context from the command
            group_name: Name of the static group to create (max 50 characters)

        Returns:
            None
        """
        await ctx.defer(ephemeral=True)

        guild_id = ctx.guild.id
        leader_id = ctx.author.id
        guild_lang = (
            await self.bot.cache.get_guild_data(guild_id, "guild_lang") or "en-US"
        )

        existing_group = await self.get_static_group_data(guild_id, group_name)
        if existing_group:
            error_msg = (
                STATIC_GROUPS["static_create"]["messages"]["already_exists"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_create"]["messages"]["already_exists"].get(
                        "en-US"
                    ),
                )
                .format(group_name=group_name)
            )
            await ctx.followup.send(error_msg, ephemeral=True)
            return

        try:
            query = "INSERT INTO guild_static_groups (guild_id, group_name, leader_id) VALUES (%s, %s, %s)"
            await self.bot.run_db_query(
                query, (guild_id, group_name, leader_id), commit=True
            )

            await self.bot.cache_loader.reload_category("static_groups")

            success_msg = (
                STATIC_GROUPS["static_create"]["messages"]["success"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_create"]["messages"]["success"].get("en-US"),
                )
                .format(group_name=group_name)
            )
            await ctx.followup.send(success_msg, ephemeral=True)
            _logger.info(
                "static_group_created",
                group_name=group_name,
                guild_id=guild_id,
                author=str(ctx.author)
            )

        except Exception as e:
            error_msg = str(e).lower()
            if "duplicate entry" in error_msg:
                duplicate_msg = (
                    STATIC_GROUPS["static_create"]["messages"]["already_exists"]
                    .get(
                        guild_lang,
                        STATIC_GROUPS["static_create"]["messages"][
                            "already_exists"
                        ].get("en-US"),
                    )
                    .format(group_name=group_name)
                )
                await ctx.followup.send(duplicate_msg, ephemeral=True)
            else:
                general_error_msg = (
                    STATIC_GROUPS["static_create"]["messages"]["error"]
                    .get(
                        guild_lang,
                        STATIC_GROUPS["static_create"]["messages"]["error"].get(
                            "en-US"
                        ),
                    )
                    .format(error=e)
                )
                await ctx.followup.send(general_error_msg, ephemeral=True)
                _logger.error("error_creating_static_group", error=str(e))

    async def static_add(
        self,
        ctx: discord.ApplicationContext,
        group_name: str = discord.Option(
            str,
            description=STATIC_GROUPS["static_add"]["options"]["group_name"][
                "description"
            ]["en-US"],
            description_localizations=STATIC_GROUPS["static_add"]["options"][
                "group_name"
            ]["description"],
        ),
        member: discord.Member = discord.Option(
            discord.Member,
            description=STATIC_GROUPS["static_add"]["options"]["member"]["description"][
                "en-US"
            ],
            description_localizations=STATIC_GROUPS["static_add"]["options"]["member"][
                "description"
            ],
        ),
    ):
        """
        Add a member to an existing static group.

        Args:
            ctx: Discord application context from the command
            group_name: Name of the static group to add member to
            member: Discord member to add to the group

        Returns:
            None
        """
        await ctx.defer(ephemeral=True)

        guild_id = ctx.guild.id
        guild_lang = (
            await self.bot.cache.get_guild_data(guild_id, "guild_lang") or "en-US"
        )

        group_data = await self.get_static_group_data(guild_id, group_name)
        if not group_data:
            error_msg = (
                STATIC_GROUPS["static_add"]["messages"]["group_not_found"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_add"]["messages"]["group_not_found"].get(
                        "en-US"
                    ),
                )
                .format(group_name=group_name)
            )
            await ctx.followup.send(error_msg, ephemeral=True)
            return

        current_members = group_data.get("member_ids", [])
        if member.id in current_members:
            already_in_msg = (
                STATIC_GROUPS["static_add"]["messages"]["already_in_group"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_add"]["messages"]["already_in_group"].get(
                        "en-US"
                    ),
                )
                .format(member=member.mention, group_name=group_name)
            )
            await ctx.followup.send(already_in_msg, ephemeral=True)
            return

        if len(current_members) >= 6:
            full_group_msg = (
                STATIC_GROUPS["static_add"]["messages"]["group_full"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_add"]["messages"]["group_full"].get("en-US"),
                )
                .format(group_name=group_name)
            )
            await ctx.followup.send(full_group_msg, ephemeral=True)
            return

        try:
            static_groups_data = await self.bot.cache.get_guild_data(guild_id, "static_groups") or {}
            group_info = static_groups_data.get(group_name)
            result = (group_info.get("id"),) if group_info and group_info.get("is_active", False) else None

            if not result:
                not_found_msg = (
                    STATIC_GROUPS["static_add"]["messages"]["group_not_found"]
                    .get(
                        guild_lang,
                        STATIC_GROUPS["static_add"]["messages"]["group_not_found"].get(
                            "en-US"
                        ),
                    )
                    .format(group_name=group_name)
                )
                await ctx.followup.send(not_found_msg, ephemeral=True)
                return

            group_id = result[0]
            position = len(current_members) + 1

            query = "INSERT INTO guild_static_members (group_id, member_id, position_order) VALUES (%s, %s, %s)"
            await self.bot.run_db_query(
                query, (group_id, member.id, position), commit=True
            )

            await self.bot.cache_loader.reload_category("static_groups")

            member_count = len(current_members) + 1
            success_msg = (
                STATIC_GROUPS["static_add"]["messages"]["success"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_add"]["messages"]["success"].get("en-US"),
                )
                .format(
                    member=member.mention, group_name=group_name, count=member_count
                )
            )
            await ctx.followup.send(success_msg, ephemeral=True)
            _logger.info(
                "member_added_to_static_group",
                member_id=member.id,
                group_name=group_name,
                guild_id=guild_id
            )

        except Exception as e:
            error_msg = (
                STATIC_GROUPS["static_add"]["messages"]["error"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_add"]["messages"]["error"].get("en-US"),
                )
                .format(error=e)
            )
            await ctx.followup.send(error_msg, ephemeral=True)
            _logger.error("error_adding_member_static_group", error=str(e))

    async def static_remove(
        self,
        ctx: discord.ApplicationContext,
        group_name: str = discord.Option(
            str,
            description=STATIC_GROUPS["static_remove"]["options"]["group_name"][
                "description"
            ]["en-US"],
            description_localizations=STATIC_GROUPS["static_remove"]["options"][
                "group_name"
            ]["description"],
        ),
        member: discord.Member = discord.Option(
            discord.Member,
            description=STATIC_GROUPS["static_remove"]["options"]["member"][
                "description"
            ]["en-US"],
            description_localizations=STATIC_GROUPS["static_remove"]["options"][
                "member"
            ]["description"],
        ),
    ):
        """
        Remove a member from an existing static group.

        Args:
            ctx: Discord application context from the command
            group_name: Name of the static group to remove member from
            member: Discord member to remove from the group

        Returns:
            None
        """
        await ctx.defer(ephemeral=True)

        guild_id = ctx.guild.id
        guild_lang = (
            await self.bot.cache.get_guild_data(guild_id, "guild_lang") or "en-US"
        )

        group_data = await self.get_static_group_data(guild_id, group_name)
        if not group_data:
            error_msg = (
                STATIC_GROUPS["static_remove"]["messages"]["group_not_found"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_remove"]["messages"]["group_not_found"].get(
                        "en-US"
                    ),
                )
                .format(group_name=group_name)
            )
            await ctx.followup.send(error_msg, ephemeral=True)
            return

        current_members = group_data.get("member_ids", [])
        if member.id not in current_members:
            not_in_group_msg = (
                STATIC_GROUPS["static_remove"]["messages"]["not_in_group"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_remove"]["messages"]["not_in_group"].get(
                        "en-US"
                    ),
                )
                .format(member=member.mention, group_name=group_name)
            )
            await ctx.followup.send(not_in_group_msg, ephemeral=True)
            return

        try:
            static_groups_data = await self.bot.cache.get_guild_data(guild_id, "static_groups") or {}
            group_info = static_groups_data.get(group_name)
            result = (group_info.get("id"),) if group_info and group_info.get("is_active", False) else None

            if not result:
                not_found_msg = (
                    STATIC_GROUPS["static_remove"]["messages"]["group_not_found"]
                    .get(
                        guild_lang,
                        STATIC_GROUPS["static_remove"]["messages"][
                            "group_not_found"
                        ].get("en-US"),
                    )
                    .format(group_name=group_name)
                )
                await ctx.followup.send(not_found_msg, ephemeral=True)
                return

            group_id = result[0]

            query = "DELETE FROM guild_static_members WHERE group_id = %s AND member_id = %s"
            await self.bot.run_db_query(query, (group_id, member.id), commit=True)

            await self.bot.cache_loader.reload_category("static_groups")

            member_count = len(current_members) - 1
            success_msg = (
                STATIC_GROUPS["static_remove"]["messages"]["success"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_remove"]["messages"]["success"].get("en-US"),
                )
                .format(
                    member=member.mention, group_name=group_name, count=member_count
                )
            )
            await ctx.followup.send(success_msg, ephemeral=True)
            _logger.info(
                "member_removed_from_static_group",
                member_id=member.id,
                group_name=group_name,
                guild_id=guild_id
            )

        except Exception as e:
            error_msg = (
                STATIC_GROUPS["static_remove"]["messages"]["error"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_remove"]["messages"]["error"].get("en-US"),
                )
                .format(error=e)
            )
            await ctx.followup.send(error_msg, ephemeral=True)
            _logger.error("error_removing_member_static_group", error=str(e))

    async def preview_groups(
        self,
        ctx: discord.ApplicationContext,
        event_id: str = discord.Option(
            str,
            description=STATIC_GROUPS["preview_groups"]["options"]["event_id"][
                "description"
            ]["en-US"],
            description_localizations=STATIC_GROUPS["preview_groups"]["options"][
                "event_id"
            ]["description"],
        ),
    ):
        """
        Preview auto-generated groups for an event before final creation.

        Args:
            ctx: Discord application context from the command
            event_id: Unique identifier of the event to preview groups for

        Returns:
            None
        """
        await ctx.defer(ephemeral=True)

        guild_id = ctx.guild.id

        settings = await self.bot.cache.get_guild_data(guild_id, "settings")

        user_locale = await get_effective_locale(self.bot, guild_id, ctx.user.id)
        guild_lang = (
            settings.get("guild_lang")
            if settings and settings.get("guild_lang")
            else "en-US"
        )

        if not settings:
            error_msg = await get_user_message(
                ctx, STATIC_GROUPS, "preview_groups.messages.no_guild_config"
            )
            await ctx.followup.send(error_msg, ephemeral=True)
            return

        try:
            event_id_int = int(event_id)
        except ValueError:
            error_msg = await get_user_message(
                ctx, STATIC_GROUPS, "preview_groups.messages.invalid_event_id"
            )
            embed = discord.Embed(
                description=error_msg,
                color=discord.Color.red()
            )
            embed.set_footer(text="💡 Tip: Use /events_list to see all available event IDs")
            await ctx.followup.send(embed=embed, ephemeral=True)
            return

        event = await self.get_event_from_cache(guild_id, event_id_int)
        if not event:
            error_msg = await get_user_message(
                ctx, STATIC_GROUPS, "preview_groups.messages.event_not_found"
            )
            embed = discord.Embed(
                description=error_msg,
                color=discord.Color.red()
            )
            embed.set_footer(text="💡 Tip: Use /events_list to see all available events")
            await ctx.followup.send(embed=embed, ephemeral=True)
            return

        registrations = event["registrations"]

        presence_ids = registrations.get("presence", [])
        tentative_ids = registrations.get("tentative", [])

        if not presence_ids and not tentative_ids:
            error_msg = await get_user_message(
                ctx, STATIC_GROUPS, "preview_groups.messages.no_registrations"
            )
            embed = discord.Embed(
                description=error_msg,
                color=discord.Color.orange()
            )
            embed.set_footer(text="💡 Tip: Members need to react to the event first")
            await ctx.followup.send(embed=embed, ephemeral=True)
            return

        try:
            guild_members_cache = (
                await self.bot.cache.get("roster_data", "guild_members") or {}
            )
            _logger.debug(
                "guild_members_cache_status",
                operation="preview_groups",
                cache_entries_count=len(guild_members_cache)
            )

            roster_data = {"members": {}}
            for member in ctx.guild.members:
                key = (guild_id, member.id)
                md = guild_members_cache.get(key, {})
                _logger.debug(
                    "preview_groups_member_data",
                    member_id=member.id,
                    member_data=md
                )
                roster_data["members"][str(member.id)] = {
                    "pseudo": member.display_name,
                    "GS": md.get("GS", "N/A"),
                    "weapons": md.get("weapons", "N/A"),
                    "class": md.get("class", "Unknown"),
                }
        except Exception as exc:
            _logger.error(
                "error_building_roster",
                guild_id=guild_id,
                error=str(exc)
            )
            error_msg = await get_user_message(
                ctx,
                STATIC_GROUPS,
                "preview_groups.messages.error_building_roster",
                error=str(exc),
            )
            await ctx.followup.send(error_msg, ephemeral=True)
            return

        try:
            all_groups = await self._assign_groups_enhanced(
                guild_id, presence_ids, tentative_ids, roster_data
            )
        except Exception as exc:
            _logger.error(
                "error_generating_groups",
                event_id=event_id,
                error=str(exc)
            )
            error_msg = await get_user_message(
                ctx,
                STATIC_GROUPS,
                "preview_groups.messages.error_generating_groups",
                error=str(exc),
            )
            await ctx.followup.send(error_msg, ephemeral=True)
            return

        if not all_groups:
            error_msg = await get_user_message(
                ctx, STATIC_GROUPS, "preview_groups.messages.no_groups_formed"
            )
            await ctx.followup.send(error_msg, ephemeral=True)
            return

        embeds = []
        total = len(all_groups)

        preview_title = STATIC_GROUPS["preview_groups"]["embeds"]["preview_title"].get(
            guild_lang,
            STATIC_GROUPS["preview_groups"]["embeds"]["preview_title"].get("en-US"),
        )
        total_members = len(presence_ids) + len(tentative_ids)
        preview_description = (
            STATIC_GROUPS["preview_groups"]["embeds"]["preview_description"]
            .get(
                guild_lang,
                STATIC_GROUPS["preview_groups"]["embeds"]["preview_description"].get(
                    "en-US"
                ),
            )
            .format(
                event_name=event["name"],
                event_date=event["event_date"],
                event_time=event["event_time"],
                total_members=total_members,
            )
        )

        header_embed = discord.Embed(
            title=preview_title,
            description=preview_description,
            color=discord.Color.orange(),
        )
        embeds.append(header_embed)

        for idx, grp in enumerate(all_groups, 1):
            group_title = (
                STATIC_GROUPS["preview_groups"]["embeds"]["group_title"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["preview_groups"]["embeds"]["group_title"].get(
                        "en-US"
                    ),
                )
                .format(group_number=idx, member_count=len(grp))
            )

            e = discord.Embed(title=group_title, color=discord.Color.blue())
            lines = []
            for m in grp:
                cls_emoji = CLASS_EMOJIS.get(m.get("class", ""), "")
                weapon_parts = [
                    c.strip() for c in (m.get("weapons") or "").split("/") if c.strip()
                ]
                weapons_emoji = " ".join(
                    [WEAPON_EMOJIS.get(c, c) for c in weapon_parts]
                )
                pseudo = m.get('pseudo', 'Unknown')
                gs = m.get('GS', 'N/A')
                if m.get("tentative"):
                    lines.append(
                        f"{cls_emoji} {weapons_emoji} *{pseudo}* ({gs}) 🔶"
                    )
                else:
                    lines.append(
                        f"{cls_emoji} {weapons_emoji} {pseudo} ({gs})"
                    )

            no_members_text = STATIC_GROUPS["preview_groups"]["embeds"][
                "no_members"
            ].get(
                guild_lang,
                STATIC_GROUPS["preview_groups"]["embeds"]["no_members"].get("en-US"),
            )
            e.description = "\n".join(lines) or no_members_text

            if any(m.get("tentative") for m in grp):
                e.set_footer(text="🔶 Tentative")
            
            embeds.append(e)

        if len(embeds) > 10:
            embeds = embeds[:9]

            truncated_title = STATIC_GROUPS["preview_groups"]["embeds"][
                "truncated_title"
            ].get(
                guild_lang,
                STATIC_GROUPS["preview_groups"]["embeds"]["truncated_title"].get(
                    "en-US"
                ),
            )
            truncated_description = (
                STATIC_GROUPS["preview_groups"]["embeds"]["truncated_description"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["preview_groups"]["embeds"][
                        "truncated_description"
                    ].get("en-US"),
                )
                .format(total=total)
            )

            warning_embed = discord.Embed(
                title=truncated_title,
                description=truncated_description,
                color=discord.Color.yellow(),
            )
            embeds.append(warning_embed)

        await ctx.followup.send(embeds=embeds, ephemeral=True)
        _logger.info(
            "groups_preview_generated",
            event_id=event_id,
            guild_id=guild_id
        )

    async def update_static_groups_message_for_cron(self, guild_id: int) -> None:
        """
        Update static groups message for automated tasks.

        Args:
            guild_id: Discord guild ID

        Returns:
            None
        """
        try:
            await self.update_static_groups_message(guild_id)
        except Exception as e:
            _logger.error(
                "error_cron_static_groups_update",
                guild_id=guild_id,
                error=str(e)
            )

    async def update_static_groups_message(self, guild_id: int) -> bool:
        """
        Update static groups message in the groups channel.

        Args:
            guild_id: Discord guild ID

        Returns:
            Boolean indicating whether the update was successful
        """
        try:
            guild_ptb_config = await self.bot.cache.get_guild_data(
                guild_id, "ptb_settings"
            )
            if guild_ptb_config and guild_ptb_config.get("ptb_guild_id") == guild_id:
                _logger.debug(
                    "skipping_statics_update_ptb_guild",
                    guild_id=guild_id
                )
                return False

            guild_settings = await self.get_guild_settings(guild_id)
            guild_lang = guild_settings.get("guild_lang", "en-US")

            channels_data = await self.bot.cache.get_guild_data(guild_id, "channels")
            result = (channels_data.get("statics_channel"), channels_data.get("statics_message")) if channels_data else (None, None)

            if not result or not result[0] or not result[1]:
                _logger.debug(
                    "no_statics_channel_message_configured",
                    guild_id=guild_id
                )
                return False

            channel_id, message_id = result

            channel = self.bot.get_channel(channel_id)
            if not channel:
                channel = await self.bot.fetch_channel(channel_id)
            if not channel:
                _logger.error(
                    "statics_channel_not_found",
                    channel_id=channel_id,
                    guild_id=guild_id
                )
                return False

            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                _logger.error(
                    "statics_message_not_found",
                    message_id=message_id,
                    guild_id=guild_id
                )
                return False

            title = STATIC_GROUPS["static_update"]["messages"]["title"].get(
                guild_lang,
                STATIC_GROUPS["static_update"]["messages"]["title"].get("en-US"),
            )

            embeds = []
            guild_obj = self.bot.get_guild(guild_id)

            static_groups = await self.get_static_groups_data(guild_id)
            if not static_groups:
                no_groups_text = STATIC_GROUPS["static_update"]["messages"][
                    "no_groups"
                ].get(
                    guild_lang,
                    STATIC_GROUPS["static_update"]["messages"]["no_groups"].get(
                        "en-US"
                    ),
                )
                embed = discord.Embed(
                    title=title, description=no_groups_text, color=discord.Color.blue()
                )
                embeds.append(embed)
            else:
                header_embed = discord.Embed(
                    title=title,
                    description=f"*Updated: <t:{int(time.time())}:R>*",
                    color=discord.Color.blue(),
                )
                embeds.append(header_embed)

                leader_label = STATIC_GROUPS["static_update"]["messages"]["leader"].get(
                    guild_lang,
                    STATIC_GROUPS["static_update"]["messages"]["leader"].get("en-US"),
                )
                members_count_template = STATIC_GROUPS["static_update"]["messages"][
                    "members_count"
                ].get(
                    guild_lang,
                    STATIC_GROUPS["static_update"]["messages"]["members_count"].get(
                        "en-US"
                    ),
                )
                no_members_text = STATIC_GROUPS["static_update"]["messages"][
                    "no_members"
                ].get(
                    guild_lang,
                    STATIC_GROUPS["static_update"]["messages"]["no_members"].get(
                        "en-US"
                    ),
                )
                absent_text = STATIC_GROUPS["static_update"]["messages"]["absent"].get(
                    guild_lang,
                    STATIC_GROUPS["static_update"]["messages"]["absent"].get("en-US"),
                )

                for group_name, group_data in static_groups.items():
                    member_ids = group_data["member_ids"]
                    member_count = len(member_ids)
                    leader_id = group_data["leader_id"]

                    leader = guild_obj.get_member(leader_id) if guild_obj else None
                    leader_mention = (
                        leader.mention if leader else f"<@{leader_id}> ({absent_text})"
                    )

                    formatted_members = await self._format_static_group_members(
                        member_ids, guild_obj, absent_text
                    )

                    members_count = members_count_template.format(count=member_count)
                    description = (
                        f"{leader_label} {leader_mention}\n{members_count}\n\n"
                    )

                    if formatted_members:
                        description += "\n".join(
                            f"• {member_line}" for member_line in formatted_members
                        )
                    else:
                        description += no_members_text

                    group_embed = discord.Embed(
                        title=f"🛡️ {group_name}",
                        description=description,
                        color=discord.Color.gold(),
                    )
                    embeds.append(group_embed)

            MAX_EMBEDS = 10
            if len(embeds) > MAX_EMBEDS:

                settings = await self.bot.cache.get_guild_data(guild_id, "settings")
                guild_lang = settings.get("guild_lang", "en-US") if settings else "en-US"
                
                total = len(embeds) - 1
                truncated_title = STATIC_GROUPS["preview_groups"]["embeds"]["truncated_title"].get(
                    guild_lang,
                    STATIC_GROUPS["preview_groups"]["embeds"]["truncated_title"].get("en-US")
                )
                truncated_description = STATIC_GROUPS["preview_groups"]["embeds"]["truncated_description"].get(
                    guild_lang,
                    STATIC_GROUPS["preview_groups"]["embeds"]["truncated_description"].get("en-US")
                ).format(total=total)
                
                embeds = embeds[:MAX_EMBEDS-1] + [discord.Embed(
                    title=truncated_title,
                    description=truncated_description,
                    color=discord.Color.yellow()
                )]

            await message.edit(embeds=embeds)
            _logger.info(
                "static_groups_message_updated",
                guild_id=guild_id
            )
            return True

        except Exception as e:
            _logger.error(
                "error_updating_static_groups_message",
                guild_id=guild_id,
                error=str(e)
            )
            return False

    async def static_update(self, ctx: discord.ApplicationContext):
        """
        Update static groups message manually via command.

        Args:
            ctx: Discord application context from the command

        Returns:
            None
        """
        await ctx.defer(ephemeral=True)

        guild_id = ctx.guild.id
        guild_settings = await self.get_guild_settings(guild_id)
        guild_lang = guild_settings.get("guild_lang", "en-US")

        channels_data = await self.bot.cache.get_guild_data(guild_id, "channels")
        result = (channels_data.get("statics_channel"), channels_data.get("statics_message")) if channels_data else (None, None)

        if not result or not result[0] or not result[1]:
            no_channel_msg = STATIC_GROUPS["static_update"]["messages"][
                "no_channel"
            ].get(
                guild_lang,
                STATIC_GROUPS["static_update"]["messages"]["no_channel"].get("en-US"),
            )
            await ctx.followup.send(no_channel_msg, ephemeral=True)
            return

        success = await self.update_static_groups_message(guild_id)

        if success:
            success_msg = STATIC_GROUPS["static_update"]["messages"]["success"].get(
                guild_lang,
                STATIC_GROUPS["static_update"]["messages"]["success"].get("en-US"),
            )
            await ctx.followup.send(success_msg, ephemeral=True)
        else:
            error_msg = STATIC_GROUPS["static_update"]["messages"]["no_message"].get(
                guild_lang,
                STATIC_GROUPS["static_update"]["messages"]["no_message"].get("en-US"),
            )
            await ctx.followup.send(error_msg, ephemeral=True)

    async def static_delete(
        self,
        ctx: discord.ApplicationContext,
        group_name: str = discord.Option(
            str,
            description=STATIC_GROUPS["static_delete"]["options"]["group_name"][
                "description"
            ]["en-US"],
            description_localizations=STATIC_GROUPS["static_delete"]["options"][
                "group_name"
            ]["description"],
        ),
    ):
        """
        Delete an existing static group permanently.

        Args:
            ctx: Discord application context from the command
            group_name: Name of the static group to delete

        Returns:
            None
        """
        await ctx.defer(ephemeral=True)

        guild_id = ctx.guild.id
        guild_lang = (
            await self.bot.cache.get_guild_data(guild_id, "guild_lang") or "en-US"
        )

        group_data = await self.get_static_group_data(guild_id, group_name)
        if not group_data:
            error_msg = (
                STATIC_GROUPS["static_delete"]["messages"]["not_found"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_delete"]["messages"]["not_found"].get(
                        "en-US"
                    ),
                )
                .format(group_name=group_name)
            )
            await ctx.followup.send(error_msg, ephemeral=True)
            return

        try:
            query = "UPDATE guild_static_groups SET is_active = FALSE WHERE guild_id = %s AND group_name = %s"
            await self.bot.run_db_query(query, (guild_id, group_name), commit=True)

            await self.bot.cache_loader.reload_category("static_groups")

            success_msg = (
                STATIC_GROUPS["static_delete"]["messages"]["success"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_delete"]["messages"]["success"].get("en-US"),
                )
                .format(group_name=group_name)
            )
            await ctx.followup.send(success_msg, ephemeral=True)
            _logger.info(
                "static_group_deleted",
                group_name=group_name,
                guild_id=guild_id,
                author=str(ctx.author)
            )

        except Exception as e:
            error_msg = (
                STATIC_GROUPS["static_delete"]["messages"]["error"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_delete"]["messages"]["error"].get("en-US"),
                )
                .format(error=e)
            )
            await ctx.followup.send(error_msg, ephemeral=True)
            _logger.error("error_deleting_static_group", error=str(e))

    async def _notify_ptb_groups(
        self, guild_id: int, event_id: int, all_groups: list
    ) -> None:
        """
        Notify the PTB (Pick The Best) system about created groups.

        Args:
            guild_id: Discord guild ID
            event_id: Unique event identifier
            all_groups: List of created group assignments

        Returns:
            None
        """
        try:
            ptb_cog = self.bot.get_cog("GuildPTB")
            if not ptb_cog:
                _logger.debug(
                    "ptb_cog_not_available",
                    guild_id=guild_id
                )
                return

            groups_data = {}
            for idx, group_members in enumerate(all_groups, 1):
                group_name = f"G{idx}"
                member_ids = [m["user_id"] for m in group_members if "user_id" in m]
                if member_ids:
                    groups_data[group_name] = member_ids

            if groups_data:
                success = await ptb_cog.assign_event_permissions(
                    guild_id, event_id, groups_data
                )
                if success:
                    _logger.info(
                        "ptb_permissions_assigned_success",
                        event_id=event_id
                    )

                    await self._schedule_ptb_cleanup(guild_id, event_id)
                else:
                    _logger.error(
                        "ptb_permission_assignment_failed",
                        event_id=event_id
                    )

        except Exception as e:
            _logger.error(
                "ptb_groups_notification_error",
                error=str(e),
                exc_info=True
            )

    async def _schedule_ptb_cleanup(self, guild_id: int, event_id: int) -> None:
        """
        Schedule cleanup of PTB data after event completion.

        Args:
            guild_id: Discord guild ID
            event_id: Unique event identifier

        Returns:
            None
        """
        try:
            event_data = await self.get_event_from_cache(guild_id, event_id)
            if not event_data:
                _logger.error(
                    "ptb_event_data_not_found",
                    guild_id=guild_id,
                    event_id=event_id
                )
                return

            duration = int(event_data.get("duration", 60))
            
            settings = await self.bot.cache.get_guild_data(guild_id, "settings")
            tz = get_guild_timezone(settings)
            

            try:
                event_start = normalize_event_datetime(
                    event_data["event_date"], 
                    event_data["event_time"], 
                    tz
                )
            except (ValueError, TypeError) as e:
                _logger.warning(
                    "ptb_notification_datetime_normalization_failed",
                    event_id=event_id,
                    guild_id=guild_id,
                    raw_date=event_data.get('event_date'),
                    raw_time=event_data.get('event_time'),
                    error=str(e)
                )
                return
            cleanup_time = event_start + timedelta(minutes=duration + 15)

            now = datetime.now(tz)
            delay_seconds = (cleanup_time - now).total_seconds()

            if delay_seconds > 0:
                task = asyncio.create_task(
                    self._delayed_ptb_cleanup(guild_id, event_id, delay_seconds)
                )
                self.scheduled_tasks.add(task)
                task.add_done_callback(lambda t: self.scheduled_tasks.discard(t))
                _logger.info(
                    "scheduled_ptb_cleanup",
                    operation="GuildEvents",
                    event_id=event_id,
                    delay_minutes=round(delay_seconds/60, 1)
                )
            else:
                _logger.warning(
                    "event_ended_immediate_cleanup",
                    operation="GuildEvents",
                    event_id=event_id
                )
                task = asyncio.create_task(self._delayed_ptb_cleanup(guild_id, event_id, 0))
                self.scheduled_tasks.add(task)
                task.add_done_callback(lambda t: self.scheduled_tasks.discard(t))

        except Exception as e:
            _logger.error(
                "ptb_cleanup_scheduling_error",
                error=str(e),
                exc_info=True
            )

    async def _delayed_ptb_cleanup(
        self, guild_id: int, event_id: int, delay_seconds: float
    ) -> None:
        """
        Execute delayed cleanup of PTB data after specified delay.

        Args:
            guild_id: Discord guild ID
            event_id: Unique event identifier
            delay_seconds: Number of seconds to wait before cleanup

        Returns:
            None
        """
        try:
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)

            ptb_cog = self.bot.get_cog("GuildPTB")
            if ptb_cog:
                success = await ptb_cog.remove_event_permissions(guild_id, event_id)
                if success:
                    _logger.info(
                        "ptb_permissions_removed",
                        event_id=event_id
                    )
                else:
                    _logger.error(
                        "ptb_permissions_removal_failed",
                        event_id=event_id
                    )

        except Exception as e:
            _logger.error(
                "ptb_delayed_cleanup_error",
                error=str(e),
                exc_info=True
            )

    def cog_unload(self):
        """
        Cleanup method called when the cog is unloaded.
        Cancels all scheduled cleanup tasks to prevent memory leaks.
        
        Returns:
            None
        """
        _logger.info("cleaning_up_scheduled_tasks", task_count=len(self.scheduled_tasks))
        
        for task in self.scheduled_tasks.copy():
            if not task.done():
                task.cancel()
                _logger.debug("cancelled_scheduled_task", task_name=str(task))
        
        self.scheduled_tasks.clear()

def setup(bot: discord.Bot):
    """
    Setup function for the cog.

    Args:
        bot: Discord bot instance to add the cog to

    Returns:
        None
    """
    bot.add_cog(GuildEvents(bot))
