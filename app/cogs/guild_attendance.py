"""
Guild Attendance Cog - Manages event attendance tracking and DKP distribution.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, time as dt_time
from typing import Dict, List, Set, Tuple, Optional, Any

import discord
import pytz
from discord.ext import commands

from core.translation import translations as global_translations

GUILD_EVENTS = global_translations.get("guild_events", {})
GUILD_ATTENDANCE = global_translations.get("guild_attendance", {})

class GuildAttendance(commands.Cog):
    """Cog for managing event attendance tracking and DKP distribution."""
    
    def __init__(self, bot: discord.Bot) -> None:
        """
        Initialize the GuildAttendance cog.
        
        Args:
            bot: Discord bot instance
        """
        self.bot = bot


    @commands.Cog.listener()
    async def on_ready(self):
        """Initialize attendance data on bot ready."""
        asyncio.create_task(self.load_attendance_data())
        logging.debug("[GuildAttendance] Cache loading tasks started in on_ready.")

    async def load_attendance_data(self) -> None:
        """
        Ensure all required data is loaded via centralized cache loader.
        
        Loads guild settings, channels, roles, members, and events data needed
        for attendance tracking. This method is called during bot initialization
        to warm up the cache.
        """
        logging.debug("[GuildAttendance] Loading attendance data")
        
        await self.bot.cache_loader.ensure_category_loaded('guild_settings')
        await self.bot.cache_loader.ensure_category_loaded('guild_channels')
        await self.bot.cache_loader.ensure_category_loaded('guild_roles')
        await self.bot.cache_loader.ensure_category_loaded('guild_members')
        await self.bot.cache_loader.ensure_category_loaded('events_data')
        
        logging.debug("[GuildAttendance] Attendance data loading completed")

    async def get_event_from_cache(self, guild_id: int, event_id: int) -> Optional[Dict]:
        """
        Get event data from global cache.
        
        Args:
            guild_id: Discord guild ID
            event_id: Event ID to retrieve
            
        Returns:
            Event data dictionary or None if not found
        """
        try:
            event_data = await self.bot.cache.get_guild_data(guild_id, f'event_{event_id}')
            if event_data:
                event_data['guild_id'] = guild_id
                if not event_data.get('registrations'):
                    event_data['registrations'] = {"presence":[],"tentative":[],"absence":[]}
                elif isinstance(event_data['registrations'], str):
                    try:
                        event_data['registrations'] = json.loads(event_data['registrations'])
                    except:
                        event_data['registrations'] = {"presence":[],"tentative":[],"absence":[]}
                        
                if not event_data.get('actual_presence'):
                    event_data['actual_presence'] = []
                elif isinstance(event_data['actual_presence'], str):
                    try:
                        event_data['actual_presence'] = json.loads(event_data['actual_presence'])
                    except:
                        event_data['actual_presence'] = []
            return event_data
        except Exception as e:
            logging.error(f"[GuildAttendance] Error retrieving event {event_id} for guild {guild_id}: {e}", exc_info=True)
            return None

    async def set_event_in_cache(self, guild_id: int, event_id: int, event_data: Dict) -> None:
        """
        Set event data in global cache.
        
        Args:
            guild_id: Discord guild ID
            event_id: Event ID to store
            event_data: Event data dictionary to store
        """
        try:
            cache_data = event_data.copy()
            cache_data.pop('guild_id', None)
            await self.bot.cache.set_guild_data(guild_id, f'event_{event_id}', cache_data)
        except Exception as e:
            logging.error(f"[GuildAttendance] Error storing event {event_id} for guild {guild_id}: {e}", exc_info=True)

    async def get_closed_events_for_guild(self, guild_id: int) -> List[Dict]:
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
                       dkp_value, status, registrations, actual_presence
                FROM events_data WHERE guild_id = ? AND status = 'Closed'
            """
            rows = await self.bot.run_db_query(query, (guild_id,), fetch_all=True)
            events = []
            if rows:
                for row in rows:
                    event_id, name, event_date, event_time, duration, dkp_value, status, registrations, actual_presence = row
                    event_data = {
                        'guild_id': guild_id,
                        'event_id': event_id,
                        'name': name,
                        'event_date': event_date,
                        'event_time': event_time,
                        'duration': duration,
                        'dkp_value': dkp_value,
                        'status': status,
                        'registrations': json.loads(registrations) if registrations else {"presence":[],"tentative":[],"absence":[]},
                        'actual_presence': json.loads(actual_presence) if actual_presence else []
                    }
                    events.append(event_data)
            return events
        except Exception as e:
            logging.error(f"[GuildAttendance] Error retrieving closed events for guild {guild_id}: {e}", exc_info=True)
            return []

    async def get_guild_settings(self, guild_id: int) -> Dict[str, Any]:
        """
        Get guild settings from centralized cache.
        
        Args:
            guild_id: Discord guild ID
            
        Returns:
            Dictionary containing guild settings (language, premium, channels, roles)
        """
        await self.bot.cache_loader.ensure_category_loaded('guild_settings')
        await self.bot.cache_loader.ensure_category_loaded('guild_channels')
        await self.bot.cache_loader.ensure_category_loaded('guild_roles')
        
        try:
            guild_lang = await self.bot.cache.get_guild_data(guild_id, 'guild_lang') or "en-US"
            premium = await self.bot.cache.get_guild_data(guild_id, 'premium')
            
            channels_data = await self.bot.cache.get_guild_data(guild_id, 'channels')
            events_channel = channels_data.get('events_channel') if channels_data else None
            notifications_channel = channels_data.get('notifications_channel') if channels_data else None
            
            roles_data = await self.bot.cache.get_guild_data(guild_id, 'roles')
            members_role = roles_data.get('members') if roles_data else None
            
            return {
                "guild_lang": guild_lang,
                "premium": premium,
                "events_channel": events_channel,
                "notifications_channel": notifications_channel,
                "members_role": members_role
            }
        except Exception as e:
            logging.error(f"[GuildAttendance] Error getting guild settings for {guild_id}: {e}", exc_info=True)
            return {}

    async def get_guild_members(self, guild_id: int) -> Dict[int, Dict[str, Any]]:
        """
        Get guild members from centralized cache.
        
        Args:
            guild_id: Discord guild ID
            
        Returns:
            Dictionary mapping member IDs to member data
        """
        await self.bot.cache_loader.ensure_category_loaded('guild_members')
        
        try:
            guild_members_cache = await self.bot.cache.get('roster_data', 'guild_members') or {}
            guild_specific_members = {}
            
            for (g_id, member_id), member_data in guild_members_cache.items():
                if g_id == guild_id:
                    guild_specific_members[member_id] = member_data
                    
            return guild_specific_members
        except Exception as e:
            logging.error(f"[GuildAttendance] Error getting guild members for {guild_id}: {e}", exc_info=True)
            return {}

    async def _update_centralized_cache(self, guild_id: int, guild_members: Dict[int, Dict[str, Any]]) -> None:
        """
        Update the centralized cache with modified guild members.
        
        Args:
            guild_id: Discord guild ID
            guild_members: Dictionary of updated member data to store
        """
        try:
            current_cache = await self.bot.cache.get('roster_data', 'guild_members') or {}
            
            for member_id, member_data in guild_members.items():
                key = (guild_id, member_id)
                current_cache[key] = member_data
            
            await self.bot.cache.set('roster_data', current_cache, 'guild_members')
            logging.debug(f"[GuildAttendance] Updated centralized cache for {len(guild_members)} members in guild {guild_id}")
        except Exception as e:
            logging.error(f"[GuildAttendance] Error updating centralized cache: {e}", exc_info=True)


    async def process_event_registrations(self, guild_id: int, event_id: int, event_data: Dict) -> None:
        """
        Process event registrations and calculate attendance/DKP.
        
        Args:
            guild_id: Discord guild ID
            event_id: Event ID to process
            event_data: Event data containing registration information
        """
        logging.info(f"[GuildAttendance] Processing registrations for event {event_id} in guild {guild_id}")
        
        guild = self.bot.get_guild(guild_id)
        if not guild:
            logging.error(f"[GuildAttendance] Guild {guild_id} not found")
            return
        
        settings = await self.get_guild_settings(guild_id)
        if not settings.get('guild_lang'):
            logging.error(f"[GuildAttendance] Guild {guild_id} settings not found")
            return

        dkp_registration = int(event_data.get("dkp_ins", 0))
        dkp_presence = int(event_data.get("dkp_value", 0))

        registrations_raw = event_data.get("registrations", {})
        if isinstance(registrations_raw, str):
            try:
                registrations = json.loads(registrations_raw)
            except (json.JSONDecodeError, TypeError) as e:
                logging.warning(f"[GuildAttendance] Failed to parse registrations JSON for event {event_id}: {e}")
                registrations = {}
        else:
            registrations = registrations_raw

        presence_ids = set(registrations.get("presence", []))
        tentative_ids = set(registrations.get("tentative", []))
        absence_ids = set(registrations.get("absence", []))

        all_registered = presence_ids | tentative_ids | absence_ids

        updates_to_batch = []
        guild_members = await self.get_guild_members(guild_id)

        for member_id, member_data in guild_members.items():
            if await self._member_has_members_role(guild, member_id):
                member_data["nb_events"] += 1
            updates_to_batch.append((
                member_data["DKP"],
                member_data["nb_events"], 
                member_data["registrations"],
                member_data["attendances"],
                guild_id,
                member_id
            ))

        for member_id in all_registered:
            if member_id not in guild_members:
                initial_nb_events = 1 if await self._member_has_members_role(guild, member_id) else 0
                guild_members[member_id] = {
                    "class": "Unknown",
                    "GS": 0,
                    "weapons": "",
                    "DKP": 0,
                    "nb_events": initial_nb_events,
                    "registrations": 0,
                    "attendances": 0
                }
            
            member_data = guild_members[member_id]

            member_data["registrations"] += 1

            if dkp_registration > 0:
                member_data["DKP"] += dkp_registration
                logging.debug(f"[GuildAttendance] Member {member_id} earned {dkp_registration} DKP for registration")

            found = False
            for i, update_data in enumerate(updates_to_batch):
                if update_data[4] == guild_id and update_data[5] == member_id:
                    updates_to_batch[i] = (
                        member_data["DKP"],
                        member_data["nb_events"], 
                        member_data["registrations"],
                        member_data["attendances"],
                        guild_id,
                        member_id
                    )
                    found = True
                    break
            
            if not found:
                updates_to_batch.append((
                    member_data["DKP"],
                    member_data["nb_events"], 
                    member_data["registrations"],
                    member_data["attendances"],
                    guild_id,
                    member_id
                ))

        if updates_to_batch:
            try:
                update_query = """
                UPDATE guild_members 
                SET DKP = %s, nb_events = %s, registrations = %s, attendances = %s 
                WHERE guild_id = %s AND member_id = %s
                """
                for update_data in updates_to_batch:
                    await self.bot.run_db_query(update_query, update_data, commit=True)
                
                logging.info(f"[GuildAttendance] Updated registration stats for {len(updates_to_batch)} members in event {event_id}")

                await self._update_centralized_cache(guild_id, guild_members)

                await self._send_registration_notification(guild_id, event_id, len(all_registered), len(presence_ids), len(tentative_ids), len(absence_ids), dkp_registration)
                
            except Exception as e:
                logging.error(f"[GuildAttendance] Error updating registration stats: {e}", exc_info=True)

    async def check_voice_presence(self):
        """
        Check voice presence for all guilds and process attendance.
        
        This method is called periodically by the scheduler to monitor voice channels
        and update event attendance based on member presence. It processes all guilds
        concurrently to improve performance.
        """
        try:
            tz = pytz.timezone("Europe/Paris")
            now = datetime.now(tz)
            
            logging.debug("[GuildAttendance] Starting voice presence check")
            logging.debug("[GuildAttendance] Starting guild processing")

            guild_tasks = []
            for guild in self.bot.guilds:
                guild_id = guild.id
                guild_tasks.append(self._process_guild_attendance(guild, now))
            
            if guild_tasks:
                await asyncio.gather(*guild_tasks, return_exceptions=True)
                logging.debug(f"[GuildAttendance] Completed processing {len(guild_tasks)} guilds")
                        
        except Exception as e:
            logging.error(f"[GuildAttendance] Error in voice presence check: {e}", exc_info=True)

    async def get_event_data(self, guild_id: int, event_id: int) -> Dict:
        """
        Get event data from centralized cache.
        
        Args:
            guild_id: Discord guild ID
            event_id: Event ID to retrieve
            
        Returns:
            Dictionary containing event data or empty dict if not found
        """
        await self.bot.cache_loader.ensure_category_loaded('events_data')
        
        event_data = await self.bot.cache.get_guild_data(guild_id, f'event_{event_id}')
        return event_data or {}

    async def _get_current_events_for_guild(self, guild_id: int, now: datetime) -> List[Dict]:
        """
        Get current events for a guild.
        
        Args:
            guild_id: Discord guild ID
            now: Current datetime for filtering events
            
        Returns:
            List of event dictionaries currently active for the guild
        """
        current_events = []
        tz = pytz.timezone("Europe/Paris")
        
        logging.debug(f"[GuildAttendance] Filtering events for guild {guild_id} at {now}")

        query = """
        SELECT guild_id, event_id, name, event_date, event_time, duration, 
               dkp_value, status, registrations, actual_presence
        FROM events_data 
        WHERE guild_id = %s AND status = 'Closed'
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
                        "status": row[7],
                        "registrations": json.loads(row[8]) if row[8] else {},
                        "actual_presence": json.loads(row[9]) if row[9] else []
                    }
                except (ValueError, TypeError, json.JSONDecodeError) as e:
                    logging.warning(f"[GuildAttendance] Invalid event data for {row[0]}_{row[1]}: {e}")
                    continue
                
                try:
                    if isinstance(event_data["event_date"], str):
                        event_date = datetime.strptime(event_data["event_date"], "%Y-%m-%d").date()
                    else:
                        event_date = event_data["event_date"]
                    
                    if isinstance(event_data["event_time"], str):
                        event_time = datetime.strptime(event_data["event_time"][:5], "%H:%M").time()
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
                        logging.warning(f"[GuildAttendance] Unknown time type for event {event_data['event_id']}: {type(event_data['event_time'])}")
                        event_time = datetime.strptime("21:00", "%H:%M").time()
                    
                    event_start = tz.localize(datetime.combine(event_date, event_time))
                    event_check_time = event_start + timedelta(minutes=5)
                    event_end = event_start + timedelta(minutes=int(event_data.get("duration", 60)))

                    event_check_end = event_end + timedelta(minutes=10)
                    
                    logging.debug(f"[GuildAttendance] Event {event_data['event_id']}: start={event_start}, check_time={event_check_time}, end={event_end}, check_end={event_check_end}, now={now}")
                    logging.debug(f"[GuildAttendance] Event {event_data['event_id']}: condition {event_check_time} <= {now} <= {event_check_end} = {event_check_time <= now <= event_check_end}")
                    
                    if event_check_time <= now <= event_check_end:
                        current_events.append(event_data)
                        logging.debug(f"[GuildAttendance] Event {event_data['event_id']} matches time window, added to current events")
                        
                except Exception as e:
                    logging.error(f"[GuildAttendance] Error parsing event time for {event_data['event_id']}: {e}")
                    continue
        
        except Exception as e:
            logging.error(f"[GuildAttendance] Error loading events for guild {guild_id}: {e}", exc_info=True)
        
        logging.debug(f"[GuildAttendance] Returning {len(current_events)} events for guild {guild_id}")
        return current_events

    async def _process_voice_attendance(self, guild: discord.Guild, event_data: Dict, now: datetime) -> None:
        """
        Process voice attendance for a specific event.
        
        Args:
            guild: Discord guild where the event is taking place
            event_data: Dictionary containing event information
            now: Current datetime for processing
        """
        event_id = event_data["event_id"]
        logging.debug(f"[GuildAttendance] Processing voice attendance for event {event_id}")

        if self._was_recently_checked(event_data, now):
            return

        voice_members = await self._get_voice_connected_members(guild)

        dkp_presence = int(event_data.get("dkp_value", 0))
        dkp_registration = int(event_data.get("dkp_ins", 0))

        registrations = event_data.get("registrations", {})
        presence_ids = set(registrations.get("presence", []))
        tentative_ids = set(registrations.get("tentative", []))
        absence_ids = set(registrations.get("absence", []))

        attendance_changes = await self._calculate_attendance_changes(
            voice_members, presence_ids, tentative_ids, absence_ids, 
            event_data.get("actual_presence", []), event_data, dkp_presence, dkp_registration
        )
        
        if attendance_changes:
            await self._apply_attendance_changes(guild.id, event_id, attendance_changes)

            await self._update_event_actual_presence(guild.id, event_id, list(voice_members))

            await self._send_attendance_notification(guild.id, event_id, attendance_changes)

    async def _get_voice_connected_members(self, guild: discord.Guild) -> Set[int]:
        """
        Get voice connected members for attendance tracking.
        
        Args:
            guild: Discord guild to check voice channels
            
        Returns:
            Set of member IDs currently connected to voice channels
        """
        voice_members = set()
        
        for channel in guild.voice_channels:
            for member in channel.members:
                if not member.bot:
                    voice_members.add(member.id)
        
        logging.debug(f"[GuildAttendance] Found {len(voice_members)} members in voice channels")
        return voice_members

    def _was_recently_checked(self, event_data: Dict, now: datetime, threshold_minutes: int = 10) -> bool:
        """
        Check if event was recently processed to avoid spam.
        
        Args:
            event_data: Dictionary containing event information
            now: Current datetime for comparison
            threshold_minutes: Minimum minutes between checks (default: 10)
            
        Returns:
            True if event was checked recently, False otherwise
        """
        return len(event_data.get("actual_presence", [])) > 0

    async def _member_has_members_role(self, guild: discord.Guild, member_id: int) -> bool:
        """
        Check if member has the members role.
        
        Args:
            guild: Discord guild to check in
            member_id: Discord member ID to check
            
        Returns:
            True if member has the members role, False otherwise
        """
        try:
            settings = await self.get_guild_settings(guild.id)
            members_role_id = settings.get("members_role")
            if not members_role_id:
                return False
            
            member = guild.get_member(member_id)
            if not member:
                return False
            
            members_role = guild.get_role(members_role_id)
            if not members_role:
                return False
            
            return members_role in member.roles
        except Exception as e:
            logging.error(f"[GuildAttendance] Error checking member role for {member_id}: {e}")
            return False

    async def _calculate_attendance_changes(self, voice_members: Set[int], presence_ids: Set[int], 
                                   tentative_ids: Set[int], absence_ids: Set[int], 
                                   current_actual_presence: List[int], event_data: Dict,
                                   dkp_presence: int, dkp_registration: int) -> List[Dict]:
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
                "reason": ""
            }

            if member_id in presence_ids:
                if is_voice_present:
                    change["dkp_change"] = dkp_presence
                    change["attendance_change"] = 1
                    change["reason"] = GUILD_ATTENDANCE["reasons"]["present_and_present"].get(
                        guild_lang, GUILD_ATTENDANCE["reasons"]["present_and_present"].get("en-US")
                    )
                else:
                    change["dkp_change"] = -dkp_registration
                    change["attendance_change"] = 0
                    change["reason"] = GUILD_ATTENDANCE["reasons"]["present_but_absent"].get(
                        guild_lang, GUILD_ATTENDANCE["reasons"]["present_but_absent"].get("en-US")
                    )
                    
            elif member_id in tentative_ids:
                if is_voice_present:
                    change["dkp_change"] = dkp_presence
                    change["attendance_change"] = 1
                    change["reason"] = GUILD_ATTENDANCE["reasons"]["tentative_and_present"].get(
                        guild_lang, GUILD_ATTENDANCE["reasons"]["tentative_and_present"].get("en-US")
                    )
                else:
                    change["reason"] = GUILD_ATTENDANCE["reasons"]["tentative_and_absent"].get(
                        guild_lang, GUILD_ATTENDANCE["reasons"]["tentative_and_absent"].get("en-US")
                    )
                    
            elif member_id in absence_ids:
                if is_voice_present:
                    change["dkp_change"] = dkp_presence
                    change["attendance_change"] = 1
                    change["reason"] = GUILD_ATTENDANCE["reasons"]["absent_but_present"].get(
                        guild_lang, GUILD_ATTENDANCE["reasons"]["absent_but_present"].get("en-US")
                    )
                else:
                    change["reason"] = GUILD_ATTENDANCE["reasons"]["absent_and_absent"].get(
                        guild_lang, GUILD_ATTENDANCE["reasons"]["absent_and_absent"].get("en-US")
                    )

            if change["dkp_change"] != 0 or change["attendance_change"] != 0:
                changes.append(change)
        
        return changes

    async def _apply_attendance_changes(self, guild_id: int, event_id: int, changes: List[Dict]) -> None:
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

            if member_id in guild_members:
                member_data = guild_members[member_id]
                member_data["DKP"] += dkp_change
                member_data["attendances"] += attendance_change
                
                updates_to_batch.append((
                    member_data["DKP"],
                    member_data["attendances"],
                    guild_id,
                    member_id
                ))

        if updates_to_batch:
            try:
                update_query = "UPDATE guild_members SET DKP = %s, attendances = %s WHERE guild_id = %s AND member_id = %s"
                for update_data in updates_to_batch:
                    await self.bot.run_db_query(update_query, update_data, commit=True)
                
                logging.info(f"[GuildAttendance] Applied attendance changes for {len(updates_to_batch)} members in event {event_id}")

                await self._update_centralized_cache(guild_id, guild_members)
                
            except Exception as e:
                logging.error(f"[GuildAttendance] Error applying attendance changes: {e}", exc_info=True)

    async def _update_event_actual_presence(self, guild_id: int, event_id: int, voice_members: List[int]) -> None:
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
            await self.bot.run_db_query(update_query, (actual_presence_json, guild_id, event_id), commit=True)

            event_data = await self.get_event_from_cache(guild_id, event_id)
            if event_data:
                event_data["actual_presence"] = voice_members
                await self.set_event_in_cache(guild_id, event_id, event_data)
                
        except Exception as e:
            logging.error(f"[GuildAttendance] Error updating actual presence for event {event_id}: {e}")

    async def _send_registration_notification(self, guild_id: int, event_id: int, total: int, 
                                            present: int, tentative: int, absent: int, dkp_registration: int = 0) -> None:
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
        
        try:
            guild_lang = settings.get("guild_lang", "en-US")
            tz = pytz.timezone("Europe/Paris")
            current_date = datetime.now(tz).strftime("%Y-%m-%d")

            title = GUILD_ATTENDANCE["notifications"]["registration"]["title"].get(
                guild_lang, GUILD_ATTENDANCE["notifications"]["registration"]["title"].get("en-US")
            )
            description = GUILD_ATTENDANCE["notifications"]["registration"]["description"].get(
                guild_lang, GUILD_ATTENDANCE["notifications"]["registration"]["description"].get("en-US")
            ).format(event_id=event_id)
            
            embed = discord.Embed(
                title=title,
                description=description,
                color=0x00ff00,
                timestamp=datetime.now(tz)
            )

            total_dkp_given = total * dkp_registration

            total_field = GUILD_ATTENDANCE["notifications"]["registration"]["total_registered"].get(
                guild_lang, GUILD_ATTENDANCE["notifications"]["registration"]["total_registered"].get("en-US")
            )
            members_text = GUILD_ATTENDANCE["notifications"]["attendance"]["members"].get(
                guild_lang, GUILD_ATTENDANCE["notifications"]["attendance"]["members"].get("en-US")
            )
            dkp_total_text = GUILD_ATTENDANCE["notifications"]["attendance"]["dkp_total"].get(
                guild_lang, GUILD_ATTENDANCE["notifications"]["attendance"]["dkp_total"].get("en-US")
            )
            embed.add_field(name=total_field, value=f"{total} {members_text} (+{total_dkp_given} {dkp_total_text})", inline=False)

            present_field = GUILD_ATTENDANCE["notifications"]["registration"]["present"].get(
                guild_lang, GUILD_ATTENDANCE["notifications"]["registration"]["present"].get("en-US")
            )
            tentative_field = GUILD_ATTENDANCE["notifications"]["registration"]["tentative"].get(
                guild_lang, GUILD_ATTENDANCE["notifications"]["registration"]["tentative"].get("en-US")
            )
            absent_field = GUILD_ATTENDANCE["notifications"]["registration"]["absent"].get(
                guild_lang, GUILD_ATTENDANCE["notifications"]["registration"]["absent"].get("en-US")
            )
            
            embed.add_field(name=present_field, value=str(present), inline=True)
            embed.add_field(name=tentative_field, value=str(tentative), inline=True)
            embed.add_field(name=absent_field, value=str(absent), inline=True)

            date_field = GUILD_ATTENDANCE["notifications"]["attendance"]["date"].get(
                guild_lang, GUILD_ATTENDANCE["notifications"]["attendance"]["date"].get("en-US")
            )
            embed.add_field(name=date_field, value=current_date, inline=False)
            
            await channel.send(embed=embed)
            
        except Exception as e:
            logging.error(f"[GuildAttendance] Error sending registration notification: {e}")

    async def _send_attendance_notification(self, guild_id: int, event_id: int, changes: List[Dict]) -> None:
        """
        Send attendance change notification.
        
        Args:
            guild_id: Discord guild ID
            event_id: Event ID for the notification
            changes: List of attendance changes to report
        """
        settings = await self.get_guild_settings(guild_id)
        if not settings or not settings.get("notifications_channel") or not changes:
            return
            
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
            
        channel = guild.get_channel(settings["notifications_channel"])
        if not channel:
            return
        
        try:
            guild_lang = settings.get("guild_lang", "en-US")
            tz = pytz.timezone("Europe/Paris")
            current_date = datetime.now(tz).strftime("%Y-%m-%d")

            title = GUILD_ATTENDANCE["notifications"]["attendance"]["title"].get(
                guild_lang, GUILD_ATTENDANCE["notifications"]["attendance"]["title"].get("en-US")
            )
            description = GUILD_ATTENDANCE["notifications"]["attendance"]["description"].get(
                guild_lang, GUILD_ATTENDANCE["notifications"]["attendance"]["description"].get("en-US")
            ).format(event_id=event_id)
            
            embed = discord.Embed(
                title=title,
                description=description,
                color=0x0099ff,
                timestamp=datetime.now(tz)
            )

            dkp_total = sum(change["dkp_change"] for change in changes)
            attendance_total = sum(change["attendance_change"] for change in changes)

            dkp_sign = "+" if dkp_total >= 0 else ""
            dkp_modifications_title = GUILD_ATTENDANCE["notifications"]["attendance"]["dkp_modifications_summary"].get(
                guild_lang, GUILD_ATTENDANCE["notifications"]["attendance"]["dkp_modifications_summary"].get("en-US")
            )
            confirmed_presences_text = GUILD_ATTENDANCE["notifications"]["attendance"]["confirmed_presences"].get(
                guild_lang, GUILD_ATTENDANCE["notifications"]["attendance"]["confirmed_presences"].get("en-US")
            )
            impacted_members_text = GUILD_ATTENDANCE["notifications"]["attendance"]["impacted_members"].get(
                guild_lang, GUILD_ATTENDANCE["notifications"]["attendance"]["impacted_members"].get("en-US")
            )
            embed.add_field(name=dkp_modifications_title, value=f"{dkp_sign}{dkp_total} DKP | {attendance_total} {confirmed_presences_text} | {len(changes)} {impacted_members_text}", inline=False)

            details_field = GUILD_ATTENDANCE["notifications"]["attendance"]["details"].get(
                guild_lang, GUILD_ATTENDANCE["notifications"]["attendance"]["details"].get("en-US")
            )
            
            if len(changes) <= 10:
                details = []
                for change in changes:
                    member = guild.get_member(change["member_id"])
                    member_name = member.display_name if member else f"ID: {change['member_id']}"
                    dkp_change_str = f"{'+' if change['dkp_change'] >= 0 else ''}{change['dkp_change']}" if change['dkp_change'] != 0 else "0"
                    details.append(f"**{member_name}**: {change['reason']} ({dkp_change_str} DKP)")
                embed.add_field(name=details_field, value="\n".join(details), inline=False)
            else:
                too_many_msg = GUILD_ATTENDANCE["notifications"]["attendance"]["too_many_changes"].get(
                    guild_lang, GUILD_ATTENDANCE["notifications"]["attendance"]["too_many_changes"].get("en-US")
                ).format(count=len(changes))
                embed.add_field(name=details_field, value=too_many_msg, inline=False)

            date_field = GUILD_ATTENDANCE["notifications"]["attendance"]["date"].get(
                guild_lang, GUILD_ATTENDANCE["notifications"]["attendance"]["date"].get("en-US")
            )
            embed.add_field(name=date_field, value=current_date, inline=False)
            
            await channel.send(embed=embed)
            
        except Exception as e:
            logging.error(f"[GuildAttendance] Error sending attendance notification: {e}")
    
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
            if not settings.get('guild_lang'):
                return

            logging.debug(f"[GuildAttendance] Processing guild {guild_id} ({guild.name})")
            current_events = await self._get_current_events_for_guild(guild_id, now)
            logging.debug(f"[GuildAttendance] Found {len(current_events)} current events for guild {guild_id}")

            for event_data in current_events:
                logging.info(f"[GuildAttendance] Processing voice attendance for event {event_data['event_id']} at {now}")
                try:
                    await self._process_voice_attendance(guild, event_data, now)
                except Exception as e:
                    logging.error(f"[GuildAttendance] Error processing voice attendance for event {event_data.get('event_id')}: {e}")
            
            logging.debug(f"[GuildAttendance] Completed processing {len(current_events)} events for guild {guild_id}")
                    
        except Exception as e:
            logging.error(f"[GuildAttendance] Error processing guild {guild.id}: {e}", exc_info=True)

def setup(bot: discord.Bot):
    """
    Setup function to add the GuildAttendance cog to the bot.
    
    Args:
        bot: Discord bot instance
    """
    bot.add_cog(GuildAttendance(bot))
