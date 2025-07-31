"""
Guild Attendance Cog - Manages event attendance tracking and DKP distribution.
"""

import discord
from discord.ext import commands
import asyncio
import json
import logging
from datetime import datetime, timedelta, time as dt_time
from typing import Dict, List, Set, Tuple, Optional, Any
import pytz

from translation import translations as global_translations

GUILD_EVENTS = global_translations.get("guild_events", {})
GUILD_ATTENDANCE = global_translations.get("guild_attendance", {})

class GuildAttendance(commands.Cog):
    """Cog for managing event attendance tracking and DKP distribution."""
    
    def __init__(self, bot):
        """Initialize the GuildAttendance cog."""
        self.bot = bot
        self.guild_settings = {}

    async def cog_load(self):
        """Handle cog loading event."""
        logging.info("[GuildAttendance] Cog loaded successfully. Caches will be loaded on bot ready.")
    
    async def cog_unload(self):
        """Handle cog unloading event."""
        logging.info("[GuildAttendance] Cog unloaded.")

    @commands.Cog.listener()
    async def on_ready(self):
        """Initialize attendance data on bot ready."""
        asyncio.create_task(self.load_attendance_data())
        logging.debug("[GuildAttendance] Cache loading tasks started in on_ready.")

    async def load_attendance_data(self) -> None:
        """Ensure all required data is loaded via centralized cache loader."""
        logging.debug("[GuildAttendance] Loading attendance data")
        
        await self.bot.cache_loader.ensure_category_loaded('guild_settings')
        await self.bot.cache_loader.ensure_category_loaded('guild_channels')
        await self.bot.cache_loader.ensure_category_loaded('guild_roles')
        await self.bot.cache_loader.ensure_category_loaded('guild_members')
        await self.bot.cache_loader.ensure_category_loaded('events_data')
        
        logging.debug("[GuildAttendance] Attendance data loading completed")

    async def load_guild_settings(self) -> None:
        """Method: Load guild settings."""
        query = """
        SELECT gs.guild_id, gs.guild_lang, gs.premium, gc.events_channel, gc.notifications_channel, gr.members
        FROM guild_settings gs
        JOIN guild_channels gc ON gs.guild_id = gc.guild_id
        LEFT JOIN guild_roles gr ON gs.guild_id = gr.guild_id
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.guild_settings = {}
            for row in rows:
                guild_id = int(row[0])
                self.guild_settings[guild_id] = {
                    "guild_lang": row[1] or "en-US",
                    "premium": row[2],
                    "events_channel": row[3],
                    "notifications_channel": row[4],
                    "members_role": row[5]
                }
            logging.debug(f"[GuildAttendance] Guild settings loaded: {len(self.guild_settings)} guilds")
        except Exception as e:
            logging.error(f"[GuildAttendance] Error loading guild settings: {e}", exc_info=True)

    async def get_guild_settings(self, guild_id: int) -> Dict[str, Any]:
        """Get guild settings from local cache."""
        if hasattr(self, 'guild_settings') and guild_id in self.guild_settings:
            return self.guild_settings[guild_id]
        else:
            await self.load_guild_settings()
            return self.guild_settings.get(guild_id, {})

    async def load_guild_members(self) -> None:
        """Method: Load guild members."""
        query = "SELECT guild_id, member_id, class, GS, weapons, DKP, nb_events, registrations, attendances FROM guild_members"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.guild_members_cache = {}
            for row in rows:
                try:
                    guild_id = int(row[0])
                    member_id = int(row[1])
                    
                    if guild_id not in self.guild_members_cache:
                        self.guild_members_cache[guild_id] = {}
                    
                    self.guild_members_cache[guild_id][member_id] = {
                        "class": row[2],
                        "GS": row[3],
                        "weapons": row[4],
                        "DKP": int(row[5]) if row[5] is not None else 0,
                        "nb_events": int(row[6]) if row[6] is not None else 0,
                        "registrations": int(row[7]) if row[7] is not None else 0,
                        "attendances": int(row[8]) if row[8] is not None else 0
                    }
                except (ValueError, TypeError) as e:
                    logging.warning(f"[GuildAttendance] Invalid member data for guild {guild_id}, member {member_id}: {e}")
                    continue
            logging.debug(f"[GuildAttendance] Guild members loaded: {len(self.guild_members_cache)} guilds")
        except Exception as e:
            logging.error(f"[GuildAttendance] Error loading guild members: {e}", exc_info=True)

    async def reload_events_cache_for_guild(self, guild_id: int) -> None:
        """Method: Reload events cache for guild."""
        query = """
        SELECT guild_id, event_id, name, event_date, event_time, duration, 
               dkp_value, status, registrations, actual_presence
        FROM events_data 
        WHERE guild_id = %s AND status = 'Closed'
        """
        try:
            rows = await self.bot.run_db_query(query, (guild_id,), fetch_all=True)

            keys_to_remove = [key for key in self.events_data.keys() if key.startswith(f"{guild_id}_")]
            for key in keys_to_remove:
                del self.events_data[key]

            for row in rows:
                try:
                    event_guild_id, event_id = int(row[0]), int(row[1])
                    key = f"{event_guild_id}_{event_id}"
                    
                    self.events_data[key] = {
                        "guild_id": event_guild_id,
                        "event_id": event_id,
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
            
            logging.debug(f"[GuildAttendance] Reloaded events cache for guild {guild_id}: {len(rows)} events")
                    
        except Exception as e:
            logging.error(f"[GuildAttendance] Error reloading events cache for guild {guild_id}: {e}", exc_info=True)

    async def reload_events_cache_all_guilds(self) -> None:
        """Method: Reload events cache all guilds."""
        await self._load_current_events()
        logging.debug(f"[GuildAttendance] Reloaded events cache for all guilds: {len(self.events_data)} events")

    async def process_event_registrations(self, guild_id: int, event_id: int, event_data: Dict) -> None:
        """Method: Process event registrations."""
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
                import json
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

        if guild_id in self.guild_members_cache:
            for member_id, member_data in self.guild_members_cache[guild_id].items():
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
            if guild_id not in self.guild_members_cache:
                self.guild_members_cache[guild_id] = {}
            
            if member_id not in self.guild_members_cache[guild_id]:
                initial_nb_events = 1 if await self._member_has_members_role(guild, member_id) else 0
                self.guild_members_cache[guild_id][member_id] = {
                    "class": "Unknown",
                    "GS": 0,
                    "weapons": "",
                    "DKP": 0,
                    "nb_events": initial_nb_events,
                    "registrations": 0,
                    "attendances": 0
                }
            
            member_data = self.guild_members_cache[guild_id][member_id]

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

                await self._send_registration_notification(guild_id, event_id, len(all_registered), len(presence_ids), len(tentative_ids), len(absence_ids), dkp_registration)
                
            except Exception as e:
                logging.error(f"[GuildAttendance] Error updating registration stats: {e}", exc_info=True)

    async def check_voice_presence(self):
        """Method: Check voice presence."""
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
        """Get event data from centralized cache."""
        await self.bot.cache_loader.ensure_category_loaded('events_data')
        
        event_data = await self.bot.cache.get_guild_data(guild_id, f'event_{event_id}')
        return event_data or {}

    async def _get_current_events_for_guild(self, guild_id: int, now: datetime) -> List[Dict]:
        """Internal method: Get current events for guild."""
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
        """Internal method: Process voice attendance."""
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
        """Internal method: Get voice connected members."""
        voice_members = set()
        
        for channel in guild.voice_channels:
            for member in channel.members:
                if not member.bot:
                    voice_members.add(member.id)
        
        logging.debug(f"[GuildAttendance] Found {len(voice_members)} members in voice channels")
        return voice_members

    def _was_recently_checked(self, event_data: Dict, now: datetime, threshold_minutes: int = 10) -> bool:
        """Internal method: Was recently checked."""
        return len(event_data.get("actual_presence", [])) > 0

    async def _member_has_members_role(self, guild: discord.Guild, member_id: int) -> bool:
        """Internal method: Member has members role."""
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
        """Internal method: Calculate attendance changes."""
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
        """Internal method: Apply attendance changes."""
        if not changes:
            return
            
        updates_to_batch = []
        
        for change in changes:
            member_id = change["member_id"]
            dkp_change = change["dkp_change"]
            attendance_change = change["attendance_change"]

            if guild_id in self.guild_members_cache and member_id in self.guild_members_cache[guild_id]:
                member_data = self.guild_members_cache[guild_id][member_id]
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
                
            except Exception as e:
                logging.error(f"[GuildAttendance] Error applying attendance changes: {e}", exc_info=True)

    async def _update_event_actual_presence(self, guild_id: int, event_id: int, voice_members: List[int]) -> None:
        """Internal method: Update event actual presence."""
        try:
            actual_presence_json = json.dumps(voice_members)
            update_query = "UPDATE events_data SET actual_presence = %s WHERE guild_id = %s AND event_id = %s"
            await self.bot.run_db_query(update_query, (actual_presence_json, guild_id, event_id), commit=True)

            key = f"{guild_id}_{event_id}"
            if key in self.events_data:
                self.events_data[key]["actual_presence"] = voice_members
                
        except Exception as e:
            logging.error(f"[GuildAttendance] Error updating actual presence for event {event_id}: {e}")

    async def _send_registration_notification(self, guild_id: int, event_id: int, total: int, 
                                            present: int, tentative: int, absent: int, dkp_registration: int = 0) -> None:
        """Internal method: Send registration notification."""
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
        """Internal method: Send attendance notification."""
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
        """Process guild attendance in an optimized way."""
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

def setup(bot):
    """Setup function for the cog."""
    bot.add_cog(GuildAttendance(bot))