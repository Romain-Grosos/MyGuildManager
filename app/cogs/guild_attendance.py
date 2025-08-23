"""
Guild Attendance Cog - Manages event attendance tracking and DKP distribution.
"""

import asyncio
import json
import time
from datetime import datetime, timedelta, time as dt_time
from typing import Dict, List, Set, Tuple, Optional, Any, TypedDict, cast

import discord
import pytz
from discord.ext import commands

from core.reliability import discord_resilient
from core.logger import ComponentLogger
from core.translation import translations as global_translations

GUILD_ATTENDANCE = global_translations.get("guild_attendance", {})

_logger = ComponentLogger("guild_attendance")

CACHE_TTL_SECONDS = 300
CACHE_CLEANUP_INTERVAL_SECONDS = 600
EVENT_CHECK_DELAY_MINUTES = 5
EVENT_CHECK_BUFFER_MINUTES = 10
MAX_NOTIFICATION_DETAILS = 10

def _gt(path: List[str], lang: str, default: str = "") -> str:
    """
    Safe translation lookup with fallback to avoid KeyError crashes.
    
    Args:
        path: List of keys to traverse in GUILD_ATTENDANCE dictionary
        lang: Language code to look up
        default: Default value if translation not found
        
    Returns:
        Translated string or default value
    """
    node = GUILD_ATTENDANCE
    for k in path:
        node = node.get(k, {})
    return node.get(lang, node.get("en-US", default))

class AttendanceData(TypedDict):
    """Type definition for attendance data structure."""
    event_id: int
    member_id: int
    attendance_status: str
    dkp_awarded: int
    notes: Optional[str]
    recorded_at: str

class EventAttendanceData(TypedDict):
    """Type definition for event attendance summary."""
    event_id: int
    total_registered: int
    total_present: int
    total_absent: int
    dkp_distributed: int
    last_updated: str

class AttendanceChange(TypedDict):
    """Type definition for attendance change structure."""
    member_id: int
    dkp_change: int
    attendance_change: int
    reason: str

class EventData(TypedDict):
    """Type definition for event data structure."""
    guild_id: int
    event_id: int
    name: str
    event_date: Any
    event_time: Any
    duration: int
    dkp_value: int
    dkp_ins: int
    status: str
    registrations: Dict[str, List[int]]
    actual_presence: List[int]

class GuildAttendance(commands.Cog):
    """Cog for managing event attendance tracking and DKP distribution."""

    def __init__(self, bot: discord.Bot) -> None:
        """
        Initialize the GuildAttendance cog.

        Args:
            bot: Discord bot instance
        """
        self.bot = bot
        self._attendance_cache: Dict[str, Tuple[Any, float]] = {}
        self._cache_ttl = CACHE_TTL_SECONDS 
        self._last_cache_cleanup = time.time()
        self._cache_cleanup_interval = CACHE_CLEANUP_INTERVAL_SECONDS

    def _to_int_ids(self, values) -> List[int]:
        """
        Safely convert a list of values to integer IDs.
        
        Args:
            values: List of values that may be strings or integers
            
        Returns:
            List of valid integer IDs, skipping invalid entries
        """
        out = []
        for v in values or []:
            try:
                out.append(int(v))
            except (TypeError, ValueError):
                pass
        return out

    @commands.Cog.listener()
    async def on_ready(self):
        """Initialize attendance data on bot ready."""
        asyncio.create_task(self.bot.cache_loader.wait_for_initial_load())
        _logger.debug("waiting_for_initial_cache_load")

    async def get_event_from_cache(
        self, guild_id: int, event_id: int
    ) -> Optional[EventData]:
        """
        Get event data from global cache.

        Args:
            guild_id: Discord guild ID
            event_id: Event ID to retrieve

        Returns:
            Event data dictionary or None if not found
        """
        try:
            event_data = await self.bot.cache.get_guild_data(
                guild_id, f"event_{event_id}"
            )
            if event_data:
                event_data["guild_id"] = guild_id
                if not event_data.get("registrations"):
                    event_data["registrations"] = {
                        "presence": [],
                        "tentative": [],
                        "absence": [],
                    }
                elif isinstance(event_data["registrations"], str):
                    try:
                        event_data["registrations"] = json.loads(
                            event_data["registrations"]
                        )
                    except (json.JSONDecodeError, TypeError):
                        event_data["registrations"] = {
                            "presence": [],
                            "tentative": [],
                            "absence": [],
                        }

                if not event_data.get("actual_presence"):
                    event_data["actual_presence"] = []
                elif isinstance(event_data["actual_presence"], str):
                    try:
                        event_data["actual_presence"] = json.loads(
                            event_data["actual_presence"]
                        )
                    except (json.JSONDecodeError, TypeError):
                        event_data["actual_presence"] = []
            return event_data
        except Exception as e:
            _logger.error("error_retrieving_event_from_cache", 
                         guild_id=guild_id, event_id=event_id, error=str(e), exc_info=True)
            return None

    async def set_event_in_cache(
        self, guild_id: int, event_id: int, event_data: EventData
    ) -> None:
        """
        Set event data in global cache.

        Args:
            guild_id: Discord guild ID
            event_id: Event ID to store
            event_data: Event data dictionary to store
        """
        try:
            cache_data = event_data.copy()
            cache_data.pop("guild_id", None)
            await self.bot.cache.set_guild_data(
                guild_id, f"event_{event_id}", cache_data
            )
        except Exception as e:
            _logger.error("error_storing_event_in_cache",
                         guild_id=guild_id, event_id=event_id, error=str(e), exc_info=True)

    def _get_cached_data(self, cache_key: str) -> Optional[Any]:
        """
        Get data from TTL cache if not expired.
        
        Args:
            cache_key: Unique cache key
            
        Returns:
            Cached data if not expired, None otherwise
        """
        if cache_key in self._attendance_cache:
            data, timestamp = self._attendance_cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                _logger.debug("cache_hit", cache_key=cache_key)
                return data
            else:
                del self._attendance_cache[cache_key]
                _logger.debug("cache_expired", cache_key=cache_key)
        return None

    def _set_cached_data(self, cache_key: str, data: Any) -> None:
        """
        Store data in TTL cache with current timestamp.
        
        Args:
            cache_key: Unique cache key
            data: Data to cache
        """
        self._attendance_cache[cache_key] = (data, time.time())
        _logger.debug("cache_set", cache_key=cache_key)

    def _invalidate_cache(self, cache_pattern: Optional[str] = None) -> None:
        """
        Invalidate cache entries matching pattern or all if no pattern.
        
        Args:
            cache_pattern: Pattern to match cache keys, None to clear all
        """
        if cache_pattern is None:
            self._attendance_cache.clear()
            _logger.debug("cache_cleared_all")
        else:
            keys_to_remove = [
                key for key in self._attendance_cache.keys() 
                if cache_pattern in key
            ]
            for key in keys_to_remove:
                del self._attendance_cache[key]
            _logger.debug("cache_invalidated", pattern=cache_pattern, removed_count=len(keys_to_remove))

    def _cleanup_expired_cache(self) -> None:
        """
        Clean up expired cache entries to prevent memory leaks.
        Called periodically to maintain memory efficiency.
        """
        current_time = time.time()

        if current_time - self._last_cache_cleanup < self._cache_cleanup_interval:
            return
            
        expired_keys = []
        for cache_key, (_, timestamp) in self._attendance_cache.items():
            if current_time - timestamp >= self._cache_ttl:
                expired_keys.append(cache_key)
                
        for key in expired_keys:
            del self._attendance_cache[key]
            
        self._last_cache_cleanup = current_time
        
        if expired_keys:
            _logger.debug("cleaned_up_expired_cache", removed_count=len(expired_keys))

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
        
        if isinstance(guild_id, str):
            try:
                guild_id = int(guild_id)
            except ValueError:
                raise ValueError(f"guild_id must be a valid integer, got: {guild_id}")
        
        if not isinstance(guild_id, int):
            raise ValueError(f"guild_id must be an integer, got: {type(guild_id)}")
        
        if guild_id <= 0:
            raise ValueError(f"guild_id must be positive, got: {guild_id}")
            
        return guild_id

    def _validate_event_id(self, event_id: Any) -> int:
        """
        Validate event ID parameter defensively.
        
        Args:
            event_id: Event ID to validate
            
        Returns:
            Validated event ID as integer
            
        Raises:
            ValueError: If event_id is invalid
        """
        if event_id is None:
            raise ValueError("event_id cannot be None")
        
        if isinstance(event_id, str):
            try:
                event_id = int(event_id)
            except ValueError:
                raise ValueError(f"event_id must be a valid integer, got: {event_id}")
        
        if not isinstance(event_id, int):
            raise ValueError(f"event_id must be an integer, got: {type(event_id)}")
        
        if event_id <= 0:
            raise ValueError(f"event_id must be positive, got: {event_id}")
            
        return event_id

    def _validate_event_data(self, event_data: Any) -> EventData:
        """
        Validate event data parameter defensively.
        
        Args:
            event_data: Event data to validate
            
        Returns:
            Validated event data as EventData TypedDict
            
        Raises:
            ValueError: If event_data is invalid
        """
        if event_data is None:
            raise ValueError("event_data cannot be None")
        
        if not isinstance(event_data, dict):
            raise ValueError(f"event_data must be a dictionary, got: {type(event_data)}")
        
        if not event_data:
            raise ValueError("event_data cannot be empty")

        if "event_id" not in event_data:
            raise ValueError("event_data must contain 'event_id' key")
            
        return cast(EventData, event_data)

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
        
        if isinstance(member_id, str):
            try:
                member_id = int(member_id)
            except ValueError:
                raise ValueError(f"member_id must be a valid integer, got: {member_id}")
        
        if not isinstance(member_id, int):
            raise ValueError(f"member_id must be an integer, got: {type(member_id)}")
        
        if member_id <= 0:
            raise ValueError(f"member_id must be positive, got: {member_id}")
            
        return member_id

    async def get_closed_events_for_guild(self, guild_id: int) -> List[EventData]:
        """
        Get all closed events for a specific guild from global cache.

        Args:
            guild_id: Discord guild ID

        Returns:
            List of closed event dictionaries
        """
        try:
            query = """
                SELECT event_id, name, event_date, event_time, duration, 
                       dkp_value, dkp_ins, status, registrations, actual_presence
                FROM events_data WHERE guild_id = %s AND status = 'Closed'
            """
            rows = await self.bot.run_db_query(query, (guild_id,), fetch_all=True)
            events = []
            if rows:
                for row in rows:
                    (
                        event_id,
                        name,
                        event_date,
                        event_time,
                        duration,
                        dkp_value,
                        dkp_ins,
                        status,
                        registrations,
                        actual_presence,
                    ) = row
                    event_data = {
                        "guild_id": guild_id,
                        "event_id": event_id,
                        "name": name,
                        "event_date": event_date,
                        "event_time": event_time,
                        "duration": duration,
                        "dkp_value": dkp_value,
                        "dkp_ins": dkp_ins,
                        "status": status,
                        "registrations": (
                            json.loads(registrations)
                            if registrations
                            else {"presence": [], "tentative": [], "absence": []}
                        ),
                        "actual_presence": (
                            json.loads(actual_presence) if actual_presence else []
                        ),
                    }
                    events.append(event_data)
            return events
        except Exception as e:
            _logger.error("error_retrieving_closed_events",
                         guild_id=guild_id, error=str(e), exc_info=True)
            return []

    async def get_guild_settings(self, guild_id: int) -> Dict[str, Any]:
        """
        Get guild settings from centralized cache with TTL caching.

        Args:
            guild_id: Discord guild ID

        Returns:
            Dictionary containing guild settings (language, premium, channels, roles)
        """
        try:
            guild_id = self._validate_guild_id(guild_id)
        except ValueError as e:
            _logger.error("invalid_guild_id_in_get_settings", error=str(e), guild_id=guild_id)
            return {}
            
        cache_key = f"guild_settings_{guild_id}"

        cached_data = self._get_cached_data(cache_key)
        if cached_data is not None:
            return cached_data
            
        try:
            guild_lang = (
                await self.bot.cache.get_guild_data(guild_id, "guild_lang") or "en-US"
            )
            premium = await self.bot.cache.get_guild_data(guild_id, "premium")

            channels_data = await self.bot.cache.get_guild_data(guild_id, "channels")
            events_channel = (
                channels_data.get("events_channel") if channels_data else None
            )
            notifications_channel = (
                channels_data.get("notifications_channel") if channels_data else None
            )

            roles_data = await self.bot.cache.get_guild_data(guild_id, "roles")
            members_role = roles_data.get("members") if roles_data else None

            timezone = await self.bot.cache.get_guild_data(guild_id, "timezone") or "Europe/Paris"
            voice_channels_whitelist = await self.bot.cache.get_guild_data(guild_id, "voice_channels_whitelist") or []
            voice_categories_whitelist = await self.bot.cache.get_guild_data(guild_id, "voice_categories_whitelist") or []

            settings = {
                "guild_lang": guild_lang,
                "premium": premium,
                "events_channel": events_channel,
                "notifications_channel": notifications_channel,
                "members_role": members_role,
                "timezone": timezone,
                "voice_channels_whitelist": voice_channels_whitelist,
                "voice_categories_whitelist": voice_categories_whitelist,
            }

            self._set_cached_data(cache_key, settings)
            return settings
        except Exception as e:
            _logger.error("error_getting_guild_settings",
                         guild_id=guild_id, error=str(e), exc_info=True)
            return {}

    async def get_guild_members(self, guild_id: int) -> Dict[int, Dict[str, Any]]:
        """
        Get guild members from centralized cache with TTL caching.

        Args:
            guild_id: Discord guild ID

        Returns:
            Dictionary mapping member IDs to member data
        """
        try:
            guild_id = self._validate_guild_id(guild_id)
        except ValueError as e:
            _logger.error("invalid_guild_id_in_get_members", error=str(e), guild_id=guild_id)
            return {}
            
        cache_key = f"guild_members_{guild_id}"

        cached_data = self._get_cached_data(cache_key)
        if cached_data is not None:
            return cached_data
            
        try:
            guild_members_cache = (
                await self.bot.cache.get("roster_data", "guild_members") or {}
            )
            guild_specific_members = {}

            for (g_id, member_id), member_data in guild_members_cache.items():
                if g_id == guild_id:
                    guild_specific_members[member_id] = member_data

            self._set_cached_data(cache_key, guild_specific_members)
            return guild_specific_members
        except Exception as e:
            _logger.error("error_getting_guild_members",
                         guild_id=guild_id, error=str(e), exc_info=True)
            return {}

    async def _update_centralized_cache(
        self, guild_id: int, guild_members: Dict[int, Dict[str, Any]]
    ) -> None:
        """
        Update the centralized cache with modified guild members.

        Args:
            guild_id: Discord guild ID
            guild_members: Dictionary of updated member data to store
        """
        try:
            current_cache = (
                await self.bot.cache.get("roster_data", "guild_members") or {}
            )

            for member_id, member_data in guild_members.items():
                key = (guild_id, member_id)
                current_cache[key] = member_data

            await self.bot.cache.set("roster_data", current_cache, "guild_members")

            self._invalidate_cache(f"guild_members_{guild_id}")
            
            _logger.debug("updated_centralized_cache",
                         guild_id=guild_id, member_count=len(guild_members))
        except Exception as e:
            _logger.error("error_updating_centralized_cache",
                         error=str(e), exc_info=True)

    @discord_resilient()
    async def process_event_registrations(
        self, guild_id: int, event_id: int, event_data: EventData
    ) -> None:
        """
        Process event registrations and calculate attendance/DKP.

        Args:
            guild_id: Discord guild ID
            event_id: Event ID to process
            event_data: Event data containing registration information
        """
        try:
            guild_id = self._validate_guild_id(guild_id)
            event_id = self._validate_event_id(event_id)
            event_data = self._validate_event_data(event_data)
        except ValueError as e:
            _logger.error("invalid_parameters_in_process_registrations", 
                         error=str(e), guild_id=guild_id, event_id=event_id)
            return
            
        _logger.info(
            "processing_event_registrations", 
            guild_id=guild_id, 
            event_id=event_id
        )

        guild = self.bot.get_guild(guild_id)
        if not guild:
            _logger.error("guild_not_found", guild_id=guild_id)
            return

        settings = await self.get_guild_settings(guild_id)
        if not settings.get("guild_lang"):
            _logger.error("guild_settings_not_found", guild_id=guild_id)
            return

        dkp_registration = int(event_data.get("dkp_ins", 0))
        dkp_presence = int(event_data.get("dkp_value", 0))

        registrations_raw = event_data.get("registrations", {})
        if isinstance(registrations_raw, str):
            try:
                registrations = json.loads(registrations_raw)
            except (json.JSONDecodeError, TypeError) as e:
                _logger.warning(
                    "failed_parse_registrations_json", 
                    event_id=event_id, 
                    error=str(e)
                )
                registrations = {}
        else:
            registrations = registrations_raw

        presence_ids = set(registrations.get("presence", []))
        tentative_ids = set(registrations.get("tentative", []))
        absence_ids = set(registrations.get("absence", []))

        all_registered = presence_ids | tentative_ids | absence_ids

        updates_dict = {}
        guild_members = await self.get_guild_members(guild_id)

        members_role_id = settings.get("members_role")
        members_role = guild.get_role(members_role_id) if members_role_id else None
        
        def has_members_role(member_id: int) -> bool:
            """Check if member has the members role efficiently."""
            if not members_role:
                return False
            member = guild.get_member(member_id)
            return bool(member and members_role in member.roles)

        for member_id in all_registered:
            if member_id not in guild_members:
                initial_nb_events = 1 if has_members_role(member_id) else 0
                guild_members[member_id] = {
                    "class": "Unknown",
                    "GS": 0,
                    "weapons": "",
                    "DKP": 0,
                    "nb_events": initial_nb_events,
                    "registrations": 0,
                    "attendances": 0,
                }
            else:
                if has_members_role(member_id):
                    guild_members[member_id]["nb_events"] += 1

            member_data = guild_members[member_id]

            member_data["registrations"] += 1

            if dkp_registration > 0:
                member_data["DKP"] += dkp_registration
                _logger.debug(
                    "member_earned_registration_dkp", 
                    member_id=member_id, 
                    dkp_amount=dkp_registration
                )

            updates_dict[member_id] = (
                member_data["DKP"],
                member_data["nb_events"],
                member_data["registrations"],
                member_data["attendances"],
                guild_id,
                member_id,
            )

        updates_to_batch = list(updates_dict.values())
        
        if updates_to_batch:
            try:
                update_query = """
                UPDATE guild_members 
                SET DKP = %s, nb_events = %s, registrations = %s, attendances = %s 
                WHERE guild_id = %s AND member_id = %s
                """
                transaction_queries = [(update_query, params) for params in updates_to_batch]
                await self.bot.run_db_transaction(transaction_queries)

                _logger.info(
                    "updated_registration_stats", 
                    event_id=event_id, 
                    member_count=len(updates_to_batch)
                )

                await self._update_centralized_cache(guild_id, guild_members)

                await self._send_registration_notification(
                    guild_id,
                    event_id,
                    len(all_registered),
                    len(presence_ids),
                    len(tentative_ids),
                    len(absence_ids),
                    dkp_registration,
                )

            except Exception as e:
                _logger.error(
                    "error_updating_registration_stats", 
                    error=str(e), 
                    exc_info=True
                )

    async def check_voice_presence(self):
        """
        Check voice presence for all guilds and process attendance.

        This method is called periodically by the scheduler to monitor voice channels
        and update event attendance based on member presence. It processes all guilds
        concurrently to improve performance.
        """
        try:
            tz = pytz.timezone("UTC")
            now = datetime.now(tz)

            self._cleanup_expired_cache()

            _logger.debug("starting_voice_presence_check")
            _logger.debug("starting_guild_processing")

            guild_tasks = []
            for guild in self.bot.guilds:
                guild_id = guild.id
                guild_tasks.append(self._process_guild_attendance(guild, now))

            if guild_tasks:
                await asyncio.gather(*guild_tasks, return_exceptions=True)
                _logger.debug(
                    "completed_guild_processing", 
                    guild_count=len(guild_tasks)
                )

        except Exception as e:
            _logger.error(
                "error_in_voice_presence_check", 
                error=str(e), 
                exc_info=True
            )

    async def get_event_data(self, guild_id: int, event_id: int) -> Optional[EventData]:
        """
        Get event data from centralized cache with full normalization.

        Args:
            guild_id: Discord guild ID
            event_id: Event ID to retrieve

        Returns:
            EventData dictionary or None if not found
        """
        return await self.get_event_from_cache(guild_id, event_id)

    async def _get_current_events_for_guild(
        self, guild_id: int, now: datetime
    ) -> List[EventData]:
        """
        Get current events for a guild.

        Args:
            guild_id: Discord guild ID
            now: Current datetime for filtering events

        Returns:
            List of event dictionaries currently active for the guild
        """
        current_events = []
        settings = await self.get_guild_settings(guild_id)
        guild_tz = settings.get("timezone", "Europe/Paris")
        tz = pytz.timezone(guild_tz)

        _logger.debug(
            "filtering_events_for_guild", 
            guild_id=guild_id, 
            timestamp=now.isoformat()
        )

        query = """
        SELECT guild_id, event_id, name, event_date, event_time, duration, 
               dkp_value, dkp_ins, status, registrations, actual_presence
        FROM events_data 
        WHERE guild_id = %s AND status LIKE '%Closed%'
        """
        try:
            rows = await self.bot.run_db_query(query, (guild_id,), fetch_all=True)

            for row in rows:
                try:
                    event_data = {
                        "guild_id": int(row[0]),
                        "event_id": int(row[1]),
                        "name": row[2],
                        "event_date": row[3],
                        "event_time": row[4],
                        "duration": row[5],
                        "dkp_value": row[6],
                        "dkp_ins": row[7],
                        "status": row[8],
                        "registrations": json.loads(row[9]) if row[9] else {},
                        "actual_presence": json.loads(row[10]) if row[10] else [],
                    }
                except (ValueError, TypeError, json.JSONDecodeError) as e:
                    _logger.warning(
                        "invalid_event_data", 
                        guild_id=row[0], 
                        event_id=row[1], 
                        error=str(e)
                    )
                    continue

                try:
                    if isinstance(event_data["event_date"], str):
                        event_date = datetime.strptime(
                            event_data["event_date"], "%Y-%m-%d"
                        ).date()
                    else:
                        event_date = event_data["event_date"]

                    if isinstance(event_data["event_time"], str):
                        event_time = datetime.strptime(
                            event_data["event_time"][:5], "%H:%M"
                        ).time()
                    elif isinstance(event_data["event_time"], timedelta):
                        total_seconds = int(event_data["event_time"].total_seconds())
                        hours = total_seconds // 3600
                        minutes = (total_seconds % 3600) // 60
                        event_time = dt_time(hours, minutes)
                    elif isinstance(event_data["event_time"], dt_time):
                        event_time = event_data["event_time"]
                    elif isinstance(event_data["event_time"], datetime):
                        event_time = event_data["event_time"].time()
                    else:
                        _logger.warning(
                            "unknown_event_time_type", 
                            event_id=event_data['event_id'], 
                            time_type=str(type(event_data['event_time']))
                        )
                        event_time = datetime.strptime("21:00", "%H:%M").time()

                    try:
                        event_start = tz.localize(datetime.combine(event_date, event_time), is_dst=None)
                    except Exception as dst_error:
                        _logger.warning(
                            "ambiguous_dst_time_detected", 
                            event_id=event_data['event_id'], 
                            date=str(event_date), 
                            time=str(event_time),
                            dst_error=str(dst_error)
                        )
                        event_start = tz.localize(datetime.combine(event_date, event_time), is_dst=False)
                    event_check_time = event_start + timedelta(minutes=EVENT_CHECK_DELAY_MINUTES)
                    event_end = event_start + timedelta(
                        minutes=int(event_data.get("duration", 60))
                    )

                    event_check_end = event_end + timedelta(minutes=EVENT_CHECK_BUFFER_MINUTES)

                    _logger.debug(
                        "event_time_analysis", 
                        event_id=event_data['event_id'], 
                        event_start=event_start.isoformat(), 
                        event_check_time=event_check_time.isoformat(), 
                        event_end=event_end.isoformat(), 
                        event_check_end=event_check_end.isoformat(), 
                        current_time=now.isoformat()
                    )
                    _logger.debug(
                        "event_time_condition_check", 
                        event_id=event_data['event_id'], 
                        is_in_time_window=bool(event_check_time <= now <= event_check_end)
                    )

                    if event_check_time <= now <= event_check_end:
                        current_events.append(event_data)
                        _logger.debug(
                            "event_added_to_current", 
                            event_id=event_data['event_id']
                        )

                except Exception as e:
                    _logger.error(
                        "error_parsing_event_time", 
                        event_id=event_data['event_id'], 
                        error=str(e)
                    )
                    continue

        except Exception as e:
            _logger.error(
                "error_loading_guild_events", 
                guild_id=guild_id, 
                error=str(e), 
                exc_info=True
            )

        _logger.debug(
            "returning_current_events", 
            guild_id=guild_id, 
            event_count=len(current_events)
        )
        return current_events

    async def _process_voice_attendance(
        self, guild: discord.Guild, event_data: EventData, now: datetime
    ) -> None:
        """
        Process voice attendance for a specific event.

        Args:
            guild: Discord guild where the event is taking place
            event_data: Dictionary containing event information
            now: Current datetime for processing
        """
        event_id = event_data["event_id"]
        _logger.debug(
            "processing_voice_attendance", 
            event_id=event_id
        )

        try:
            if self._was_already_processed(event_data):
                return

            voice_members = await self._get_voice_connected_members(guild)
            _logger.debug(
                "found_voice_members", 
                member_count=len(voice_members)
            )

            try:
                dkp_presence = int(event_data.get("dkp_value", 0))
                dkp_registration = int(event_data.get("dkp_ins", 0))
            except (ValueError, TypeError) as e:
                _logger.error(
                    "error_parsing_dkp_values", 
                    event_id=event_id, 
                    error=str(e)
                )
                dkp_presence = 0
                dkp_registration = 0

            _logger.debug(
                "event_dkp_values", 
                event_id=event_id, 
                dkp_presence=dkp_presence, 
                dkp_registration=dkp_registration
            )

            registrations = event_data.get("registrations", {})
            presence_ids = set(registrations.get("presence", []))
            tentative_ids = set(registrations.get("tentative", []))
            absence_ids = set(registrations.get("absence", []))

            _logger.debug(
                "event_registration_counts", 
                event_id=event_id, 
                present_count=len(presence_ids), 
                tentative_count=len(tentative_ids), 
                absent_count=len(absence_ids)
            )

            attendance_changes = await self._calculate_attendance_changes(
                voice_members,
                presence_ids,
                tentative_ids,
                absence_ids,
                event_data.get("actual_presence", []),
                event_data,
                dkp_presence,
                dkp_registration,
            )

            _logger.debug(
                "calculated_attendance_changes", 
                event_id=event_id, 
                change_count=len(attendance_changes)
            )

            if attendance_changes:
                _logger.info(
                    "applying_attendance_changes", 
                    event_id=event_id, 
                    change_count=len(attendance_changes)
                )
                await self._apply_attendance_changes(
                    guild.id, event_id, attendance_changes
                )
                already = set(event_data.get("actual_presence", []))
                processed_now = {c["member_id"] for c in attendance_changes}
                new_processed = list(already | processed_now | voice_members)
                await self._update_event_actual_presence(
                    guild.id, event_id, new_processed
                )
                await self._send_attendance_notification(
                    guild.id, event_id, attendance_changes
                )

            else:
                _logger.debug(
                    "no_attendance_changes", 
                    event_id=event_id
                )

        except Exception as e:
            _logger.error(
                "error_processing_voice_attendance", 
                event_id=event_id, 
                error=str(e), 
                exc_info=True
            )

    @discord_resilient()
    async def _get_voice_connected_members(self, guild: discord.Guild) -> Set[int]:
        """
        Get voice connected members for attendance tracking.
        
        Supports filtering to specific voice channels or categories to avoid
        counting unrelated chatter (e.g., PTB/event-only channels).

        Args:
            guild: Discord guild to check voice channels

        Returns:
            Set of member IDs currently connected to voice channels
        """
        voice_members = set()

        settings = await self.get_guild_settings(guild.id)
        voice_channel_whitelist = self._to_int_ids(settings.get("voice_channels_whitelist", []))
        voice_category_whitelist = self._to_int_ids(settings.get("voice_categories_whitelist", []))

        if not voice_channel_whitelist and not voice_category_whitelist:
            channels_to_check = guild.voice_channels
        else:
            channels_to_check = []

            for channel_id in voice_channel_whitelist:
                channel = guild.get_channel(channel_id)
                if channel and isinstance(channel, discord.VoiceChannel):
                    channels_to_check.append(channel)

            for category_id in voice_category_whitelist:
                category = guild.get_channel(category_id)
                if category and isinstance(category, discord.CategoryChannel):
                    channels_to_check.extend([
                        ch for ch in category.voice_channels
                    ])

        for channel in channels_to_check:
            for member in channel.members:
                if not member.bot:
                    voice_members.add(member.id)

        _logger.debug(
            "found_voice_members_in_channels", 
            member_count=len(voice_members)
        )
        return voice_members

    def _check_notification_permissions(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> bool:
        """
        Check if bot has required permissions to send notifications.
        
        Args:
            guild: Discord guild
            channel: Channel to check permissions for
            
        Returns:
            True if bot has send_messages and embed_links permissions
        """
        bot_member = guild.me
        if not bot_member:
            _logger.warning("bot_not_in_guild_for_notification", guild_id=guild.id)
            return False
            
        permissions = channel.permissions_for(bot_member)
        if not permissions.send_messages:
            _logger.warning("missing_send_messages_permission", 
                           guild_id=guild.id, channel_id=channel.id)
            return False
            
        if not permissions.embed_links:
            _logger.warning("missing_embed_links_permission", 
                           guild_id=guild.id, channel_id=channel.id)
            return False
            
        return True

    def _was_already_processed(self, event_data: EventData) -> bool:
        """
        Check if event was already processed to avoid duplicate attendance processing.

        Note: Event-level gate removed to allow late joiners to be processed.
        Deduplication now relies on per-member idempotency via actual_presence tracking.

        Args:
            event_data: Dictionary containing event information

        Returns:
            Always returns False to allow continuous processing of late joiners
        """
        return False

    async def _calculate_attendance_changes(
        self,
        voice_members: Set[int],
        presence_ids: Set[int],
        tentative_ids: Set[int],
        absence_ids: Set[int],
        current_actual_presence: List[int],
        event_data: EventData,
        dkp_presence: int,
        dkp_registration: int,
    ) -> List[AttendanceChange]:
        """
        Calculate attendance changes based on voice presence.

        Args:
            voice_members: Set of member IDs currently in voice channels
            presence_ids: Set of member IDs registered as present
            tentative_ids: Set of member IDs registered as tentative
            absence_ids: Set of member IDs registered as absent
            current_actual_presence: List of member IDs already processed
            event_data: Dictionary containing event information
            dkp_presence: DKP value for attendance
            dkp_registration: DKP value for registration

        Returns:
            List of dictionaries containing attendance changes to apply
        """
        changes = []
        all_registered = presence_ids | tentative_ids | absence_ids
        current_actual_set = set(current_actual_presence)

        guild_id = event_data.get("guild_id")
        guild_lang = "en-US"
        if guild_id:
            settings = await self.get_guild_settings(guild_id)
            guild_lang = settings.get("guild_lang", "en-US")

        for member_id in all_registered:
            is_voice_present = member_id in voice_members
            was_checked_present = member_id in current_actual_set

            if was_checked_present:
                continue

            change = {
                "member_id": member_id,
                "dkp_change": 0,
                "attendance_change": 0,
                "reason": "",
            }

            if member_id in presence_ids:
                if is_voice_present:
                    change["dkp_change"] = dkp_presence
                    change["attendance_change"] = 1
                    change["reason"] = _gt(["reasons", "present_and_present"], guild_lang, "Present and Present")
                else:
                    change["dkp_change"] = -dkp_registration
                    change["attendance_change"] = 0
                    change["reason"] = _gt(["reasons", "present_but_absent"], guild_lang, "Present but Absent")

            elif member_id in tentative_ids:
                if is_voice_present:
                    change["dkp_change"] = dkp_presence
                    change["attendance_change"] = 1
                    change["reason"] = _gt(["reasons", "tentative_and_present"], guild_lang, "Tentative and Present")
                else:
                    change["reason"] = _gt(["reasons", "tentative_and_absent"], guild_lang, "Tentative and Absent")

            elif member_id in absence_ids:
                if is_voice_present:
                    change["dkp_change"] = dkp_presence
                    change["attendance_change"] = 1
                    change["reason"] = _gt(["reasons", "absent_but_present"], guild_lang, "Absent but Present")
                else:
                    change["reason"] = _gt(["reasons", "absent_and_absent"], guild_lang, "Absent and Absent")

            if change["dkp_change"] != 0 or change["attendance_change"] != 0:
                changes.append(change)
                _logger.debug(
                    "added_attendance_change", 
                    member_id=member_id, 
                    dkp_change=change['dkp_change'], 
                    attendance_change=change['attendance_change'], 
                    reason=change['reason']
                )
            else:
                _logger.debug(
                    "no_attendance_change", 
                    member_id=member_id, 
                    dkp_change=change['dkp_change'], 
                    attendance_change=change['attendance_change']
                )

        _logger.debug("total_changes_calculated", change_count=len(changes))
        return changes

    async def _apply_attendance_changes(
        self, guild_id: int, event_id: int, changes: List[AttendanceChange]
    ) -> None:
        """
        Apply attendance changes to database.

        Args:
            guild_id: Discord guild ID
            event_id: Event ID to update
            changes: List of attendance changes to apply
        """
        if not changes:
            return

        updates_to_batch = []
        guild_members = await self.get_guild_members(guild_id)

        for change in changes:
            member_id = change["member_id"]
            dkp_change = change["dkp_change"]
            attendance_change = change["attendance_change"]

            if member_id not in guild_members:
                guild_members[member_id] = {
                    "class": "Unknown",
                    "GS": 0,
                    "weapons": "",
                    "DKP": 0,
                    "nb_events": 0,
                    "registrations": 0,
                    "attendances": 0,
                }
                _logger.debug(
                    "created_default_record_for_attendee",
                    member_id=member_id,
                    guild_id=guild_id
                )

            member_data = guild_members[member_id]
            member_data["DKP"] += dkp_change
            member_data["attendances"] += attendance_change

            updates_to_batch.append(
                (
                    member_data["DKP"],
                    member_data["attendances"],
                    guild_id,
                    member_id,
                )
            )

        if updates_to_batch:
            try:
                upsert_query = """
                INSERT INTO guild_members (guild_id, member_id, DKP, attendances, class, GS, weapons, nb_events, registrations)
                VALUES (%s, %s, %s, %s, 'Unknown', 0, '', 0, 0)
                ON DUPLICATE KEY UPDATE 
                    DKP = VALUES(DKP), 
                    attendances = VALUES(attendances)
                """
                upsert_batch = [
                    (update_data[2], update_data[3], update_data[0], update_data[1])
                    for update_data in updates_to_batch
                ]
                transaction_queries = [(upsert_query, params) for params in upsert_batch]
                await self.bot.run_db_transaction(transaction_queries)

                _logger.info(
                    "applied_attendance_changes", 
                    event_id=event_id, 
                    member_count=len(updates_to_batch)
                )

                await self._update_centralized_cache(guild_id, guild_members)

            except Exception as e:
                _logger.error(
                    "error_applying_attendance_changes", 
                    error=str(e), 
                    exc_info=True
                )

    async def _update_event_actual_presence(
        self, guild_id: int, event_id: int, voice_members: List[int]
    ) -> None:
        """
        Update event's actual presence count.

        Args:
            guild_id: Discord guild ID
            event_id: Event ID to update
            voice_members: List of member IDs currently in voice channels
        """
        try:
            actual_presence_json = json.dumps(voice_members)
            update_query = "UPDATE events_data SET actual_presence = %s WHERE guild_id = %s AND event_id = %s"
            await self.bot.run_db_query(
                update_query, (actual_presence_json, guild_id, event_id), commit=True
            )

            event_data = await self.bot.cache.get_guild_data(
                guild_id, f"event_{event_id}"
            )
            if event_data:
                event_data["actual_presence"] = voice_members
                await self.bot.cache.set_guild_data(
                    guild_id, f"event_{event_id}", event_data
                )
                _logger.debug(
                    "updated_actual_presence_in_cache", 
                    event_id=event_id
                )

        except Exception as e:
            _logger.error(
                "error_updating_actual_presence", 
                event_id=event_id, 
                error=str(e)
            )

    @discord_resilient()
    async def _send_registration_notification(
        self,
        guild_id: int,
        event_id: int,
        total: int,
        present: int,
        tentative: int,
        absent: int,
        dkp_registration: int = 0,
    ) -> None:
        """
        Send registration summary notification.

        Args:
            guild_id: Discord guild ID
            event_id: Event ID for the notification
            total: Total number of registrations
            present: Number of present registrations
            tentative: Number of tentative registrations
            absent: Number of absent registrations
            dkp_registration: Number of DKP-only registrations (default: 0)
        """
        settings = await self.get_guild_settings(guild_id)
        if not settings or not settings.get("notifications_channel"):
            return

        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        channel = guild.get_channel(settings["notifications_channel"])
        if not channel:
            return

        if not self._check_notification_permissions(guild, channel):
            return

        try:
            guild_lang = settings.get("guild_lang", "en-US")
            guild_tz = settings.get("timezone", "Europe/Paris")
            tz = pytz.timezone(guild_tz)
            current_date = datetime.now(tz).strftime("%Y-%m-%d")

            title = _gt(["notifications", "registration", "title"], guild_lang, "Registration Summary")
            description_template = _gt(["notifications", "registration", "description"], guild_lang, "Registration completed for event {event_id}")
            description = description_template.format(event_id=event_id)

            embed = discord.Embed(
                title=title,
                description=description,
                color=0x00FF00,
                timestamp=datetime.now(tz),
            )

            total_dkp_given = total * dkp_registration

            total_field = _gt(["notifications", "registration", "total_registered"], guild_lang, "Total Registered")
            members_text = _gt(["notifications", "attendance", "members"], guild_lang, "members")
            dkp_total_text = _gt(["notifications", "attendance", "dkp_total"], guild_lang, "DKP total")
            embed.add_field(
                name=total_field,
                value=f"{total} {members_text} (+{total_dkp_given} {dkp_total_text})",
                inline=False,
            )

            present_field = _gt(["notifications", "registration", "present"], guild_lang, "Present")
            tentative_field = _gt(["notifications", "registration", "tentative"], guild_lang, "Tentative")
            absent_field = _gt(["notifications", "registration", "absent"], guild_lang, "Absent")

            embed.add_field(name=present_field, value=str(present), inline=True)
            embed.add_field(name=tentative_field, value=str(tentative), inline=True)
            embed.add_field(name=absent_field, value=str(absent), inline=True)

            date_field = _gt(["notifications", "attendance", "date"], guild_lang, "Date")
            embed.add_field(name=date_field, value=current_date, inline=False)

            await channel.send(embed=embed)

        except Exception as e:
            _logger.error(
                "error_sending_registration_notification", 
                error=str(e)
            )

    @discord_resilient()
    async def _send_attendance_notification(
        self, guild_id: int, event_id: int, changes: List[AttendanceChange]
    ) -> None:
        """
        Send attendance change notification.

        Args:
            guild_id: Discord guild ID
            event_id: Event ID for the notification
            changes: List of attendance changes to report
        """
        _logger.debug(
            "attempting_send_attendance_notification", 
            event_id=event_id, 
            change_count=len(changes)
        )

        settings = await self.get_guild_settings(guild_id)
        if not settings:
            _logger.warning(
                "no_guild_settings_for_notification", 
                guild_id=guild_id
            )
            return
        if not settings.get("notifications_channel"):
            _logger.warning(
                "no_notifications_channel_configured", 
                guild_id=guild_id
            )
            return
        if not changes:
            _logger.debug(
                "no_changes_to_report_skipping", 
                event_id=event_id
            )
            return

        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        channel = guild.get_channel(settings["notifications_channel"])
        if not channel:
            return

        if not self._check_notification_permissions(guild, channel):
            return

        try:
            guild_lang = settings.get("guild_lang", "en-US")
            guild_tz = settings.get("timezone", "Europe/Paris")
            tz = pytz.timezone(guild_tz)
            current_date = datetime.now(tz).strftime("%Y-%m-%d")

            title = _gt(["notifications", "attendance", "title"], guild_lang, "Attendance Update")
            description_template = _gt(["notifications", "attendance", "description"], guild_lang, "Attendance processed for event {event_id}")
            description = description_template.format(event_id=event_id)

            embed = discord.Embed(
                title=title,
                description=description,
                color=0x0099FF,
                timestamp=datetime.now(tz),
            )

            dkp_total = sum(change["dkp_change"] for change in changes)
            attendance_total = sum(change["attendance_change"] for change in changes)

            dkp_sign = "+" if dkp_total > 0 else ("" if dkp_total == 0 else "")
            dkp_modifications_title = _gt(["notifications", "attendance", "dkp_modifications_summary"], guild_lang, "DKP Modifications Summary")
            confirmed_presences_text = _gt(["notifications", "attendance", "confirmed_presences"], guild_lang, "confirmed presences")
            impacted_members_text = _gt(["notifications", "attendance", "impacted_members"], guild_lang, "impacted members")
            embed.add_field(
                name=dkp_modifications_title,
                value=f"{dkp_sign}{dkp_total} DKP | {attendance_total} {confirmed_presences_text} | {len(changes)} {impacted_members_text}",
                inline=False,
            )

            details_field = _gt(["notifications", "attendance", "details"], guild_lang, "Details")

            if len(changes) <= MAX_NOTIFICATION_DETAILS:
                details = []
                for change in changes:
                    member = guild.get_member(change["member_id"])
                    member_name = (
                        member.display_name if member else f"ID: {change['member_id']}"
                    )
                    dkp_change_str = (
                        f"{'+' if change['dkp_change'] > 0 else ''}{change['dkp_change']}"
                        if change["dkp_change"] != 0
                        else "0"
                    )
                    details.append(
                        f"**{member_name}**: {change['reason']} ({dkp_change_str} DKP)"
                    )
                embed.add_field(
                    name=details_field, value="\n".join(details), inline=False
                )
            else:
                too_many_template = _gt(["notifications", "attendance", "too_many_changes"], guild_lang, "{count} changes - too many to display")
                too_many_msg = too_many_template.format(count=len(changes))
                embed.add_field(name=details_field, value=too_many_msg, inline=False)

            date_field = _gt(["notifications", "attendance", "date"], guild_lang, "Date")
            embed.add_field(name=date_field, value=current_date, inline=False)

            await channel.send(embed=embed)
            _logger.info(
                "successfully_sent_attendance_notification", 
                event_id=event_id, 
                channel_id=settings['notifications_channel']
            )

        except Exception as e:
            _logger.error(
                "error_sending_attendance_notification", 
                error=str(e), 
                exc_info=True
            )

    @discord_resilient()
    async def _process_guild_attendance(self, guild: discord.Guild, now: datetime):
        """
        Process attendance for a specific guild.

        Args:
            guild: Discord guild to process attendance for
            now: Current datetime for processing
        """
        try:
            guild_id = guild.id
            settings = await self.get_guild_settings(guild_id)
            if not settings.get("guild_lang"):
                return

            _logger.debug(
                "processing_guild_attendance", 
                guild_id=guild_id, 
                guild_name=guild.name
            )
            current_events = await self._get_current_events_for_guild(guild_id, now)
            _logger.debug(
                "found_current_events_for_guild", 
                guild_id=guild_id, 
                event_count=len(current_events)
            )

            for event_data in current_events:
                _logger.info(
                    "processing_event_voice_attendance", 
                    event_id=event_data['event_id'], 
                    timestamp=now.isoformat()
                )
                try:
                    await self._process_voice_attendance(guild, event_data, now)
                except Exception as e:
                    _logger.error(
                        "error_processing_event_voice_attendance", 
                        event_id=event_data.get('event_id'), 
                        error=str(e)
                    )

            _logger.debug(
                "completed_processing_guild_events", 
                guild_id=guild_id, 
                event_count=len(current_events)
            )

        except Exception as e:
            _logger.error(
                "error_processing_guild", 
                guild_id=guild.id, 
                error=str(e), 
                exc_info=True
            )

def setup(bot: discord.Bot):
    """
    Setup function to add the GuildAttendance cog to the bot.

    Args:
        bot: Discord bot instance
    """
    bot.add_cog(GuildAttendance(bot))
