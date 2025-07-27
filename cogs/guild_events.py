import discord
from discord import NotFound, HTTPException
import logging
import asyncio
import pytz
from discord.ext import commands, tasks
from datetime import datetime, timedelta, time as dt_time
import time
from translation import translations as global_translations
from typing import Optional, List, Dict, Set, Tuple
import json
import math
import statistics

GUILD_EVENTS = global_translations.get("guild_events", {})
STATIC_GROUPS = global_translations.get("static_groups", {})

WEAPON_EMOJIS = {
    "B":  "<:TL_B:1362340360470270075>",
    "CB": "<:TL_CB:1362340413142335619>",
    "DG": "<:TL_DG:1362340445148938251>",
    "GS": "<:TL_GS:1362340479819059211>",
    "S":  "<:TL_S:1362340495447167048>",
    "SNS":"<:TL_SNS:1362340514002763946>",
    "SP": "<:TL_SP:1362340530062888980>",
    "W":  "<:TL_W:1362340545376030760>"
}

CLASS_EMOJIS = {
    "Tank":    "<:tank:1374760483164524684>",
    "Healer":  "<:healer:1374760495613218816>",
    "Melee DPS":   "<:DPS:1374760287491850312>",
    "Ranged DPS":  "<:DPS:1374760287491850312>",
    "Flanker": "<:flank:1374762529036959854>",
}

class GuildEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild_settings = {} 
        self.events_calendar = {}
        self.events_data = {}
        self.guild_members_cache = {}
        self.static_groups_cache = {}
        self.ideal_staff_cache = {}
        self.json_lock = asyncio.Lock()
        self.ignore_removals = {}

    async def load_guild_settings(self) -> None:
        query = """
        SELECT gs.guild_id, gs.guild_lang, gs.guild_game, gc.events_channel, gc.notifications_channel, gc.groups_channel, gr.members, gs.premium, gc.voice_war_channel
        FROM guild_settings gs
        JOIN guild_channels gc ON gs.guild_id = gc.guild_id
        JOIN guild_roles gr ON gs.guild_id = gr.guild_id;
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.guild_settings = {}
            for row in rows:
                (guild_id, guild_lang, guild_game, events_channel, 
                 notifications_channel, groups_channel, members_role, premium, voice_war_channel) = row
                self.guild_settings[int(guild_id)] = {
                    "guild_lang": guild_lang,
                    "guild_game": guild_game,
                    "events_channel": events_channel,
                    "notifications_channel": notifications_channel,
                    "groups_channel": groups_channel,
                    "members_role": members_role,
                    "premium": premium,
                    "war_channel": voice_war_channel
                }
            logging.debug(f"[GuildEvents] Successfully loaded guild settings: {self.guild_settings}")
        except Exception as e:
            logging.error(f"[GuildEvents] Error loading guild settings: {e}", exc_info=True)

    async def load_events_calendar(self) -> None:
        query = """
        SELECT game_id, day, time, duration, dkp_value, dkp_ins, week, name
        FROM events_calendar;
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.events_calendar = {}
            for row in rows:
                game_id, day, time_str, duration, dkp_value, dkp_ins, week, name = row
                game_id = int(game_id)
                event = {
                    "day": day,
                    "time": time_str,
                    "duration": duration,
                    "dkp_value": dkp_value,
                    "dkp_ins": dkp_ins,
                    "week": week,
                    "name": name
                }
                if game_id not in self.events_calendar:
                    self.events_calendar[game_id] = []
                self.events_calendar[game_id].append(event)
            logging.debug(f"[GuildEvents] Events calendar loaded: {self.events_calendar}")
        except Exception as e:
            logging.error(f"[GuildEvents] Error loading events calendar: {e}", exc_info=True)

    async def load_events_data(self) -> None:
        query = """
        SELECT guild_id, event_id, game_id, name, event_date, event_time, duration, dkp_value, dkp_ins, status, initial_members, registrations, actual_presence
        FROM events_data
        WHERE status <> 'Finished';
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.events_data = {}
            for row in rows:
                try:
                    (guild_id, event_message_id, game_id, name, event_date,
                    event_time, duration, dkp_value, dkp_ins, status,
                    initial_members, registrations, actual_presence) = row
                    key = f"{int(guild_id)}_{int(event_message_id)}"
                    self.events_data[key] = {
                        "guild_id": int(guild_id),
                        "event_id": int(event_message_id),
                    "game_id": game_id,
                    "name": name,
                    "event_date": event_date,
                    "event_time": event_time,
                    "duration": duration,
                    "dkp_value": dkp_value,
                    "dkp_ins": dkp_ins,
                    "status": status,
                    "initial_members": initial_members,
                    "registrations": registrations,
                    "actual_presence": actual_presence
                }
                except (ValueError, TypeError) as e:
                    logging.warning(f"[GuildEvents] Invalid data for event {event_message_id} in guild {guild_id}: {e}")
                    continue
            logging.debug(f"[GuildEvents] Events data loaded: {self.events_data}")
        except Exception as e:
            logging.error(f"[GuildEvents] Error loading events data: {e}", exc_info=True)

    async def load_guild_members(self) -> None:
        query = "SELECT guild_id, member_id, class, GS, weapons FROM guild_members"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.guild_members_cache = {}
            for row in rows:
                guild_id, member_id, member_class, gs, weapons = row
                guild_id = int(guild_id)
                member_id = int(member_id)
                if guild_id not in self.guild_members_cache:
                    self.guild_members_cache[guild_id] = {}
                self.guild_members_cache[guild_id][member_id] = {
                    "class": member_class,
                    "GS": gs if gs is not None else "N/A",
                    "weapons": weapons if weapons is not None else "N/A"
                }
            logging.debug(f"[GuildEvents] Guild members cache loaded: {self.guild_members_cache}")
        except Exception as e:
            logging.error(f"[GuildEvents] Error loading guild members cache: {e}", exc_info=True)

    async def load_static_groups_cache(self) -> None:
        logging.debug("[GuildEvents] Loading static groups cache from database")
        query = """
            SELECT sg.guild_id, sg.group_name, sg.leader_id, 
                   GROUP_CONCAT(sm.member_id ORDER BY sm.position_order) as member_ids,
                   COUNT(sm.member_id) as member_count
            FROM guild_static_groups sg
            LEFT JOIN guild_static_members sm ON sg.id = sm.group_id
            WHERE sg.is_active = TRUE
            GROUP BY sg.id, sg.guild_id, sg.group_name, sg.leader_id
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.static_groups_cache = {}
            for row in rows:
                guild_id, group_name, leader_id, member_ids_str, member_count = row
                member_ids = [int(mid) for mid in member_ids_str.split(',')] if member_ids_str else []
                
                if guild_id not in self.static_groups_cache:
                    self.static_groups_cache[guild_id] = {}
                
                self.static_groups_cache[guild_id][group_name] = {
                    "leader_id": leader_id,
                    "member_ids": member_ids,
                    "member_count": member_count
                }
            logging.debug(f"[GuildEvents] Static groups cache loaded: {self.static_groups_cache}")
        except Exception as e:
            logging.error(f"[GuildEvents] Error loading static groups cache: {e}", exc_info=True)

    async def load_ideal_staff_cache(self) -> None:
        logging.debug("[GuildEvents] Loading ideal staff cache from database")
        query = "SELECT guild_id, class_name, ideal_count FROM guild_ideal_staff"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.ideal_staff_cache = {}
            for row in rows:
                guild_id, class_name, ideal_count = row
                if guild_id not in self.ideal_staff_cache:
                    self.ideal_staff_cache[guild_id] = {}
                self.ideal_staff_cache[guild_id][class_name] = ideal_count
            logging.debug(f"[GuildEvents] Ideal staff cache loaded: {self.ideal_staff_cache}")
        except Exception as e:
            logging.error(f"[GuildEvents] Error loading ideal staff cache: {e}", exc_info=True)

    def get_next_date_for_day(self, day_name: str, event_time_value, tz, tomorrow_only: bool = False) -> Optional[datetime]:
        if isinstance(event_time_value, timedelta):
            total_seconds = int(event_time_value.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            event_time_str = f"{hours:02d}:{minutes:02d}"
        elif isinstance(event_time_value, str):
            parts = event_time_value.split(":")
            if len(parts) >= 2:
                event_time_str = f"{parts[0]}:{parts[1]}"
            else:
                event_time_str = event_time_value
        else:
            event_time_str = "21:00"

        days = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6
        }
        day_key = day_name.lower()
        if day_key not in days:
            logging.debug(f"Invalid day: {day_name}")
            return None
        target_weekday = days[day_key]

        now = datetime.now(tz)

        if tomorrow_only:
            tomorrow = now.date() + timedelta(days=1)
            if tomorrow.weekday() != target_weekday:
                logging.debug(f"Event day '{day_name}' is not scheduled for tomorrow ({tomorrow}). Skipping.")
                return None
            event_date = tomorrow
        else:
            current_weekday = now.weekday()
            days_ahead = target_weekday - current_weekday
            if days_ahead < 0 or (days_ahead == 0 and now.strftime("%H:%M") >= event_time_str):
                days_ahead += 7
            event_date = now.date() + timedelta(days=days_ahead)

        try:
            hour, minute = map(int, event_time_str.split(":"))
        except Exception as e:
            logging.error(f"Error parsing time '{event_time_str}': {e}")
            hour, minute = 0, 0

        naive_dt = datetime.combine(event_date, dt_time(hour, minute))
        return tz.localize(naive_dt)

    async def create_events_for_all_premium_guilds(self) -> None:
        for guild_id, settings in self.guild_settings.items():
            if settings.get("premium") in [True, 1, "1"]:
                guild = self.bot.get_guild(guild_id)
                if guild:
                    try:
                        await self.create_events_for_guild(guild)
                        logging.info(f"[GuildEvents] Events created for premium guild {guild_id}.")
                    except Exception as e:
                        logging.exception(f"[GuildEvents] Error creating events for guild {guild_id}: {e}")
                else:
                    logging.error(f"❌ [GuildEvents] Guild {guild_id} not found.")
        await self.load_events_data()

        attendance_cog = self.bot.get_cog("GuildAttendance")
        if attendance_cog:
            await attendance_cog.reload_events_cache_all_guilds()
            logging.debug("[GuildEvents] Reloaded events cache in attendance cog after bulk creation")

    async def create_events_for_guild(self, guild: discord.Guild) -> None:
        guild_id = guild.id
        settings = self.guild_settings.get(guild_id)
        if not settings:
            logging.error(f"[GuildEvents - create_events_for_guild] No configuration for guild {guild_id}.")
            return

        guild_lang = settings.get("guild_lang")
        events_channel = guild.get_channel(settings.get("events_channel"))
        conference_channel = guild.get_channel(settings.get("war_channel"))
        if not events_channel:
            logging.error(f"[GuildEvents - create_events_for_guild] Events channel not found for guild {guild_id}.")
            return
        if not conference_channel:
            logging.error(f"[GuildEvents - create_events_for_guild] Conference channel not found for guild {guild_id}.")
            return

        try:
            game_id = int(settings.get("guild_game"))
        except Exception as e:
            logging.error(f"[GuildEvents - create_events_for_guild] Error converting guild_game for guild {guild_id}: {e}")
            return

        calendar = self.events_calendar.get(game_id, [])
        if not calendar:
            logging.info(f"[GuildEvents - create_events_for_guild] No events defined in calendar for game_id {game_id}.")
            return

        tz = pytz.timezone("Europe/Paris")

        for cal_event in calendar:
            try:
                day = cal_event.get("day")
                event_time_str = cal_event.get("time", "21:00")
                start_time = self.get_next_date_for_day(day, event_time_str, tz, tomorrow_only=True)

                if start_time is None:
                    logging.debug(f"[GuildEvents - create_events_for_guild] Event day '{day}' is not scheduled for tomorrow. Skipping.")
                    continue

                try:
                    duration_minutes = int(cal_event.get("duration", 60))
                except (ValueError, TypeError) as e:
                    logging.warning(f"[GuildEvents] Invalid duration value for event, using default 60min: {e}")
                    duration_minutes = 60
                end_time = start_time + timedelta(minutes=duration_minutes)

                week_setting = cal_event.get("week", "all")
                if week_setting != "all":
                    week_number = start_time.isocalendar()[1]
                    if week_setting == "odd" and week_number % 2 == 0:
                        logging.info(f"[GuildEvents - create_events_for_guild] Event {cal_event.get('name')} not scheduled this week (even).")
                        continue
                    elif week_setting == "even" and week_number % 2 != 0:
                        logging.info(f"[GuildEvents - create_events_for_guild] Event {cal_event.get('name')} not scheduled this week (odd).")
                        continue

                event_key = cal_event.get("name")
                event_info = GUILD_EVENTS["events_infos"].get(event_key)
                event_name = event_info.get(guild_lang, event_info.get("en-US")) if event_info else event_key
                event_date = GUILD_EVENTS["events_infos"]["date"].get(guild_lang,GUILD_EVENTS["events_infos"]["date"].get("en-US"))
                event_hour = GUILD_EVENTS["events_infos"]["hour"].get(guild_lang,GUILD_EVENTS["events_infos"]["hour"].get("en-US"))
                event_duration = GUILD_EVENTS["events_infos"]["duration"].get(guild_lang,GUILD_EVENTS["events_infos"]["duration"].get("en-US"))
                event_status = GUILD_EVENTS["events_infos"]["status"].get(guild_lang,GUILD_EVENTS["events_infos"]["status"].get("en-US"))
                event_dkp_v = GUILD_EVENTS["events_infos"]["dkp_v"].get(guild_lang,GUILD_EVENTS["events_infos"]["dkp_v"].get("en-US"))
                event_dkp_i = GUILD_EVENTS["events_infos"]["dkp_i"].get(guild_lang,GUILD_EVENTS["events_infos"]["dkp_i"].get("en-US"))
                event_present = GUILD_EVENTS["events_infos"]["present"].get(guild_lang,GUILD_EVENTS["events_infos"]["present"].get("en-US"))
                event_attempt = GUILD_EVENTS["events_infos"]["attempt"].get(guild_lang,GUILD_EVENTS["events_infos"]["attempt"].get("en-US"))
                event_absence = GUILD_EVENTS["events_infos"]["absence"].get(guild_lang,GUILD_EVENTS["events_infos"]["absence"].get("en-US"))
                event_voice_channel = GUILD_EVENTS["events_infos"]["voice_channel"].get(guild_lang,GUILD_EVENTS["events_infos"]["voice_channel"].get("en-US"))
                event_groups = GUILD_EVENTS["events_infos"]["groups"].get(guild_lang,GUILD_EVENTS["events_infos"]["groups"].get("en-US"))
                event_auto_grouping = GUILD_EVENTS["events_infos"]["auto_grouping"].get(guild_lang,GUILD_EVENTS["events_infos"]["auto_grouping"].get("en-US"))

                status = GUILD_EVENTS["events_infos"]["status_planned"].get(guild_lang,GUILD_EVENTS["events_infos"]["status_planned"].get("en-US"))
                status_db = GUILD_EVENTS["events_infos"]["status_planned"].get("en-US")
                description = GUILD_EVENTS["events_infos"]["description"].get(guild_lang,GUILD_EVENTS["events_infos"]["description"].get("en-US"))

                try:
                    embed = discord.Embed(
                        title=event_name,
                        description=description,
                        color=discord.Color.blue()
                    )
                    embed.add_field(name=event_date, value=start_time.strftime("%d-%m-%Y"), inline=True)
                    embed.add_field(name=event_hour, value=start_time.strftime("%H:%M"), inline=True)
                    embed.add_field(name=event_duration, value=f"{duration_minutes}", inline=True)
                    embed.add_field(name=event_status, value=status, inline=True)
                    embed.add_field(name=event_dkp_v, value=str(cal_event.get("dkp_value", 0)), inline=True)
                    embed.add_field(name=event_dkp_i, value=str(cal_event.get("dkp_ins", 0)), inline=True)
                    none_text = GUILD_EVENTS["events_infos"]["none"].get(guild_lang, "None")
                    embed.add_field(name=f"{event_present} <:_yes_:1340109996666388570> (0)", value=none_text, inline=False)
                    embed.add_field(name=f"{event_attempt} <:_attempt_:1340110058692018248> (0)", value=none_text, inline=False)
                    embed.add_field(name=f"{event_absence} <:_no_:1340110124521357313> (0)", value=none_text, inline=False)
                    conference_link = f"https://discord.com/channels/{guild.id}/{conference_channel.id}"
                    embed.add_field(name=event_voice_channel, value=f"[🏹 WAR]({conference_link})", inline=False)
                    embed.add_field(name=event_groups, value=event_auto_grouping, inline=False)
                except Exception as e:
                    logging.error(f"[GuildEvents - create_events_for_guild] Error building embed for event '{event_name}': {e}", exc_info=True)
                    continue

                try:
                    announcement = await events_channel.send(embed=embed)
                    logging.debug(f"[GuildEvents - create_events_for_guild] Announcement sent: id={announcement.id} in channel {announcement.channel.id}")
                    message_link = f"https://discord.com/channels/{guild.id}/{announcement.channel.id}/{announcement.id}"
                    embed.set_footer(text=f"Event ID = {announcement.id}")
                    await announcement.edit(embed=embed)
                    await announcement.add_reaction("<:_yes_:1340109996666388570>")
                    await announcement.add_reaction("<:_attempt_:1340110058692018248>")
                    await announcement.add_reaction("<:_no_:1340110124521357313>")
                except Exception as e:
                    logging.error(f"[GuildEvents - create_events_for_guild] Error sending announcement message: {e}", exc_info=True)
                    continue

                try:
                    description_scheduled = GUILD_EVENTS["events_infos"]["description_scheduled"].get(guild_lang,GUILD_EVENTS["events_infos"]["description_scheduled"].get("en-US")).format(link=message_link)
                    scheduled_event = await guild.create_scheduled_event(
                        name=event_name,
                        description=description_scheduled,
                        start_time=start_time,
                        end_time=end_time,
                        location=conference_channel
                    )
                    logging.debug(f"[GuildEvents - create_events_for_guild] Scheduled event created: {scheduled_event.id if scheduled_event else 'None'}")
                except discord.Forbidden:
                    logging.error(f"[GuildEvents - create_events_for_guild] Insufficient permissions to create scheduled event in guild {guild_id}.")
                    continue
                except discord.HTTPException as e:
                    logging.error(f"[GuildEvents - create_events_for_guild] HTTP error creating scheduled event in guild {guild_id}: {e}")
                    continue

                try:
                    members_role_id = settings.get("members_role")
                    if members_role_id:
                        role = guild.get_role(int(members_role_id))
                        if role:
                            initial_members = [member.id for member in guild.members if role in member.roles]
                        else:
                            initial_members = []
                    else:
                        initial_members = []
                except Exception as e:
                    logging.error(f"[GuildEvents - create_events_for_guild] Error determining initial members for guild {guild_id}: {e}", exc_info=True)
                    initial_members = []

                record = {
                    "guild_id": guild_id,
                    "event_id": announcement.id,
                    "game_id": settings.get("guild_game"),
                    "name": event_name,
                    "event_date": start_time.strftime("%Y-%m-%d"),
                    "event_time": start_time.strftime("%H:%M:%S"),
                    "duration": duration_minutes,
                    "dkp_value": cal_event.get("dkp_value", 0),
                    "dkp_ins": cal_event.get("dkp_ins", 0),
                    "status": status_db,
                    "initial_members": json.dumps(initial_members),
                    "registrations": json.dumps({"presence": [], "tentative": [], "absence": []}),
                    "actual_presence": json.dumps([])
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
                    logging.info(f"[GuildEvents - create_events - create_events_for_guild] Event saved in DB successfully: {announcement.id}")
                except Exception as e:
                    error_msg = str(e).lower()
                    if "duplicate entry" in error_msg or "1062" in error_msg:
                        logging.warning(f"[GuildEvents] Duplicate event entry for guild {guild_id}: {e}")
                    elif "foreign key constraint" in error_msg or "1452" in error_msg:
                        logging.error(f"[GuildEvents] Foreign key constraint failed for guild {guild_id}: {e}")
                    else:
                        logging.error(f"[GuildEvents - create_events - create_events_for_guild] Error saving event in DB for guild {guild_id}: {e}")
            except Exception as outer_e:
                logging.error(f"[GuildEvents - create_events_for_guild] Unexpected error in create_events_for_guild for guild {guild_id}: {outer_e}", exc_info=True)

    @discord.slash_command(
        name=GUILD_EVENTS.get("event_confirm", {}).get("name", {}).get("en-US", "event_confirm"),
        description=GUILD_EVENTS.get("event_confirm", {}).get("description", {}).get("en-US", "Confirm a guild event."),
        name_localizations=GUILD_EVENTS.get("event_confirm", {}).get("name", {}),
        description_localizations=GUILD_EVENTS.get("event_confirm", {}).get("description", {})
    )
    @commands.has_permissions(manage_guild=True)
    async def event_confirm(self, ctx: discord.ApplicationContext, event_id: str):
        await ctx.defer(ephemeral=True)

        guild = ctx.guild
        settings = self.guild_settings.get(ctx.guild.id)
        user_locale = ctx.locale if hasattr(ctx, "locale") and ctx.locale else "en-US"
        guild_locale = settings.get("guild_lang") if settings and settings.get("guild_lang") else "en-US"

        try:
            event_id_int = int(event_id)
        except ValueError:
            follow_message = GUILD_EVENTS["events_infos"]["id_ko"].get(user_locale,GUILD_EVENTS["events_infos"]["id_ko"].get("en-US"))
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        if not settings:
            follow_message = GUILD_EVENTS["event_confirm"]["no_settings"].get(user_locale,GUILD_EVENTS["event_confirm"]["no_settings"].get("en-US"))
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        target_event = None
        for key, ev in self.events_data.items():
            if ev.get("event_id") == event_id_int:
                target_event = ev
                break
        if not target_event:
            follow_message = GUILD_EVENTS["event_confirm"]["no_events"].get(user_locale,GUILD_EVENTS["event_confirm"]["no_events"].get("en-US")).format(event_id=event_id)
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        query = "UPDATE events_data SET status = %s WHERE guild_id = %s AND event_id = %s"
        try:
            await self.bot.run_db_query(query, ("Confirmed", guild.id, event_id), commit=True)
            target_event["status"] = "Confirmed"
            logging.info(f"[GuildEvents] Event {event_id} status updated to 'Confirmed' for guild {guild.id}.")

            attendance_cog = self.bot.get_cog("GuildAttendance")
            if attendance_cog:
                await attendance_cog.reload_events_cache_for_guild(guild.id)
                logging.debug(f"[GuildEvents] Reloaded events cache for guild {guild.id} in attendance cog")
                
        except Exception as e:
            logging.error(f"[GuildEvents] Error updating event {event_id} status for guild {guild.id}: {e}", exc_info=True)

        events_channel = guild.get_channel(settings.get("events_channel"))
        if not events_channel:
            follow_message = GUILD_EVENTS["event_confirm"]["no_events_canal"].get(user_locale,GUILD_EVENTS["event_confirm"]["no_events_canal"].get("en-US"))
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        try:
            message = await events_channel.fetch_message(event_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            logging.warning(f"[GuildEvents] Cannot fetch event message {event_id}: {e}")
            follow_message = GUILD_EVENTS["event_confirm"]["no_events_message"].get(user_locale,GUILD_EVENTS["event_confirm"]["no_events_message"].get("en-US"))
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        if not message.embeds:
            follow_message = GUILD_EVENTS["event_confirm"]["no_events_message_embed"].get(user_locale,GUILD_EVENTS["event_confirm"]["no_events_message_embed"].get("en-US"))
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        new_embed = message.embeds[0]
        new_embed.color = discord.Color.green()

        status_key   = GUILD_EVENTS["events_infos"]["status"].get(guild_locale, GUILD_EVENTS["events_infos"]["status"].get("en-US")).lower()
        status_name  = GUILD_EVENTS["events_infos"]["status"].get(guild_locale, GUILD_EVENTS["events_infos"]["status"].get("en-US"))
        status_localized = GUILD_EVENTS["event_confirm"]["confirmed"].get(guild_locale,GUILD_EVENTS["event_confirm"]["confirmed"].get("en-US"))

        new_fields = []
        status_found = False
        for field in new_embed.fields:
            if field.name.lower() == status_key:
                new_fields.append({"name": status_name, "value": status_localized, "inline": field.inline})
                status_found = True
            else:
                new_fields.append({"name": field.name, "value": field.value, "inline": field.inline})
        if not status_found:
            new_fields.append({"name": status_name, "value": status_localized, "inline": False})
        new_embed.clear_fields()
        for field in new_fields:
            new_embed.add_field(name=field["name"], value=field["value"], inline=field["inline"])

        try:
            members_role = settings.get("members_role")
            update_message = GUILD_EVENTS["event_confirm"]["confirmed_notif"].get(user_locale,GUILD_EVENTS["event_confirm"]["confirmed_notif"].get("en-US")).format(role=members_role)
            await message.edit(content=update_message,embed=new_embed)
            follow_message = GUILD_EVENTS["event_confirm"]["event_updated"].get(user_locale,GUILD_EVENTS["event_confirm"]["event_updated"].get("en-US")).format(event_id=event_id)
            await ctx.followup.send(follow_message, ephemeral=True)
        except Exception as e:
            follow_message = GUILD_EVENTS["event_confirm"]["event_embed_ko"].get(user_locale,GUILD_EVENTS["event_confirm"]["event_embed_ko"].get("en-US")).format(e=e)
            await ctx.followup.send(follow_message, ephemeral=True)
            return

    @event_confirm.error
    async def event_confirm_error(self, ctx, error):
        logging.error(f"❌ [GuildEvents] event_confirm error: {error}")
        follow_message = GUILD_EVENTS["event_confirm"]["event_ko"].get(ctx.locale,GUILD_EVENTS["event_confirm"]["event_ko"].get("en-US")).format(error=error)
        await ctx.send(follow_message, delete_after=10)

    @discord.slash_command(
        name=GUILD_EVENTS.get("event_cancel", {}).get("name", {}).get("en-US", "event_cancel"),
        description=GUILD_EVENTS.get("event_cancel", {}).get("description", {}).get("en-US", "Cancel a guild event."),
        name_localizations=GUILD_EVENTS.get("event_cancel", {}).get("name", {}),
        description_localizations=GUILD_EVENTS.get("event_cancel", {}).get("description", {})
    )
    @commands.has_permissions(manage_guild=True)
    async def event_cancel(self, ctx: discord.ApplicationContext, event_id: str):
        await ctx.defer(ephemeral=True)

        guild = ctx.guild
        settings = self.guild_settings.get(ctx.guild.id)
        user_locale = ctx.locale if hasattr(ctx, "locale") and ctx.locale else "en-US"
        guild_locale = settings.get("guild_lang") if settings and settings.get("guild_lang") else "en-US"

        try:
            event_id_int = int(event_id)
        except ValueError:
            follow_message = GUILD_EVENTS["events_infos"]["id_ko"].get(user_locale,GUILD_EVENTS["events_infos"]["id_ko"].get("en-US"))
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        if not settings:
            follow_message = GUILD_EVENTS["event_cancel"]["no_settings"].get(user_locale,GUILD_EVENTS["event_cancel"]["no_settings"].get("en-US"))
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        target_event = None
        for key, ev in self.events_data.items():
            if ev.get("event_id") == event_id_int:
                target_event = ev
                break
        if not target_event:
            follow_message = GUILD_EVENTS["event_cancel"]["no_events"].get(user_locale,GUILD_EVENTS["event_cancel"]["no_events"].get("en-US")).format(event_id=event_id)
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        query = "UPDATE events_data SET status = %s WHERE guild_id = %s AND event_id = %s"
        try:
            await self.bot.run_db_query(query, ("Canceled", guild.id, event_id_int), commit=True)
            target_event["status"] = "Canceled"
            logging.info(f"[GuildEvents] Event {event_id_int} status updated to 'Canceled' for guild {guild.id}.")

            attendance_cog = self.bot.get_cog("GuildAttendance")
            if attendance_cog:
                await attendance_cog.reload_events_cache_for_guild(guild.id)
                logging.debug(f"[GuildEvents] Reloaded events cache for guild {guild.id} in attendance cog")
                
        except Exception as e:
            logging.error(f"[GuildEvents] Error updating status for event {event_id_int} in guild {guild.id}: {e}", exc_info=True)

        events_channel = guild.get_channel(settings.get("events_channel"))
        if not events_channel:
            follow_message = GUILD_EVENTS["event_cancel"]["no_settings"].get(user_locale,GUILD_EVENTS["event_cancel"]["no_settings"].get("en-US"))
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        try:
            message = await events_channel.fetch_message(event_id_int)
        except Exception as e:
            follow_message = GUILD_EVENTS["event_cancel"]["no_events_message"].get(user_locale,GUILD_EVENTS["event_cancel"]["no_events_message"].get("en-US"))
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        try:
            await message.clear_reactions()
        except Exception as e:
            logging.error(f"❌ [GuildEvents] Error clearing reactions in event_cancel: {e}", exc_info=True)

        if not message.embeds:
            follow_message = GUILD_EVENTS["event_cancel"]["no_events_message_embed"].get(user_locale,GUILD_EVENTS["event_cancel"]["no_events_message_embed"].get("en-US"))
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        embed = message.embeds[0]
        embed.color = discord.Color.red()

        status_key   = GUILD_EVENTS["events_infos"]["status"].get(guild_locale, GUILD_EVENTS["events_infos"]["status"].get("en-US")).lower()
        status_name  = GUILD_EVENTS["events_infos"]["status"].get(guild_locale, GUILD_EVENTS["events_infos"]["status"].get("en-US"))
        status_localized = GUILD_EVENTS["event_cancel"]["canceled"].get(guild_locale,GUILD_EVENTS["event_cancel"]["canceled"].get("en-US"))
        present_key   = GUILD_EVENTS["events_infos"]["present"].get(guild_locale, GUILD_EVENTS["events_infos"]["present"].get("en-US")).lower()
        tentative_key = GUILD_EVENTS["events_infos"]["attempt"].get(guild_locale, GUILD_EVENTS["events_infos"]["attempt"].get("en-US")).lower()
        absence_key   = GUILD_EVENTS["events_infos"]["absence"].get(guild_locale, GUILD_EVENTS["events_infos"]["absence"].get("en-US")).lower()
        dkp_v_key   = GUILD_EVENTS["events_infos"]["dkp_v"].get(guild_locale, GUILD_EVENTS["events_infos"]["dkp_v"].get("en-US")).lower()
        dkp_i_key   = GUILD_EVENTS["events_infos"]["dkp_i"].get(guild_locale, GUILD_EVENTS["events_infos"]["dkp_i"].get("en-US")).lower()
        groups_key   = GUILD_EVENTS["events_infos"]["groups"].get(guild_locale, GUILD_EVENTS["events_infos"]["groups"].get("en-US")).lower()
        chan_key   = GUILD_EVENTS["events_infos"]["voice_channel"].get(guild_locale, GUILD_EVENTS["events_infos"]["voice_channel"].get("en-US")).lower()

        new_fields = []
        for field in embed.fields:
            field_name = field.name.lower()
            if (field_name.startswith(present_key) or 
                field_name.startswith(tentative_key) or 
                field_name.startswith(absence_key) or 
                field_name in [dkp_v_key, dkp_i_key, groups_key, chan_key]):
                continue
            elif field_name == status_key:
                new_fields.append({"name": status_name, "value": status_localized, "inline": False})
            else:
                new_fields.append({"name": field.name, "value": field.value, "inline": field.inline})
        embed.clear_fields()
        for field in new_fields:
            embed.add_field(name=field["name"], value=field["value"], inline=field["inline"])

        try:
            await message.edit(content="", embed=embed)
            follow_message = GUILD_EVENTS["event_cancel"]["event_updated"].get(user_locale,GUILD_EVENTS["event_cancel"]["event_updated"].get("en-US")).format(event_id=event_id)
            await ctx.followup.send(follow_message, ephemeral=True)
        except Exception as e:
            follow_message = GUILD_EVENTS["event_cancel"]["event_embed_ko"].get(user_locale,GUILD_EVENTS["event_cancel"]["event_embed_ko"].get("en-US")).format(e=e)
            await ctx.followup.send(follow_message, ephemeral=True)
            return

    @event_cancel.error
    async def event_cancel_error(self, ctx, error):
        logging.error(f"❌ [GuildEvents] event_cancel error: {error}")
        error_msg = GUILD_EVENTS["event_cancel"]["event_embed_ko"].get(ctx.locale,GUILD_EVENTS["event_cancel"]["event_embed_ko"].get("en-US")).format(error=error)
        await ctx.send(error_msg, delete_after=10)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        logging.debug(f"[GuildEvents - on_raw_reaction_add] Starting with payload: {payload}")
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            logging.debug("[GuildEvents - on_raw_reaction_add] Guild not found.")
            return

        settings = self.guild_settings.get(guild.id)
        if not settings:
            logging.debug("[GuildEvents - on_raw_reaction_add] Settings not found for this guild.")
            return

        events_channel_id = settings.get("events_channel")
        if payload.channel_id != events_channel_id:
            logging.debug("[GuildEvents - on_raw_reaction_add] Channel ID does not match events channel.")
            return

        valid_emojis = [
            "<:_yes_:1340109996666388570>",
            "<:_attempt_:1340110058692018248>",
            "<:_no_:1340110124521357313>"
        ]
        if str(payload.emoji) not in valid_emojis:
            logging.debug(f"[GuildEvents - on_raw_reaction_add] Invalid emoji: {payload.emoji}")
            return

        channel = guild.get_channel(payload.channel_id)
        try:
            message = await channel.fetch_message(payload.message_id)
        except Exception as e:
            logging.error(f"[GuildEvents - on_raw_reaction_add] Error fetching message: {e}")
            return

        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            logging.debug("[GuildEvents - on_raw_reaction_add] Member not found or is a bot.")
            return

        for emoji in valid_emojis:
            if emoji != str(payload.emoji):
                try:
                    key = (message.id, member.id, emoji)
                    self.ignore_removals[key] = time.time()
                    await message.remove_reaction(emoji, member)
                except Exception as e:
                    logging.error(f"[GuildEvents - on_raw_reaction_add] Error removing reaction {emoji} for {member}: {e}")

        async with self.json_lock:
            target_event = None
            for ev in self.events_data.values():
                if ev.get("event_id") == message.id:
                    target_event = ev
                    break
            if not target_event:
                logging.debug("[GuildEvents - on_raw_reaction_add] No event found for this message.")
                return

            logging.debug(f"[GuildEvents - on_raw_reaction_add] Event found: {target_event}")

            if isinstance(target_event.get("registrations"), str):
                try:
                    target_event["registrations"] = json.loads(target_event["registrations"])
                    logging.debug("[GuildEvents - on_raw_reaction_add] Registrations decoded from JSON.")
                except Exception as e:
                    logging.error(f"[GuildEvents - on_raw_reaction_add] Error during registration decoding: {e}")
                    target_event["registrations"] = {"presence": [], "tentative": [], "absence": []}

            logging.debug(f"[GuildEvents - on_raw_reaction_add] Registrations BEFORE update: {target_event['registrations']}")

            for key in ["presence", "tentative", "absence"]:
                if payload.user_id in target_event["registrations"].get(key, []):
                    target_event["registrations"][key].remove(payload.user_id)
            if str(payload.emoji) == "<:_yes_:1340109996666388570>":
                target_event["registrations"]["presence"].append(payload.user_id)
            elif str(payload.emoji) == "<:_attempt_:1340110058692018248>":
                target_event["registrations"]["tentative"].append(payload.user_id)
            elif str(payload.emoji) == "<:_no_:1340110124521357313>":
                target_event["registrations"]["absence"].append(payload.user_id)

            logging.debug(f"[GuildEvents - on_raw_reaction_add] Registrations AFTER update: {target_event['registrations']}")

        try:
            new_registrations = json.dumps(target_event["registrations"])
            update_query = "UPDATE events_data SET registrations = %s WHERE guild_id = %s AND event_id = %s"
            await self.bot.run_db_query(update_query, (new_registrations, target_event["guild_id"], target_event["event_id"]), commit=True)
            logging.debug("[GuildEvents - on_raw_reaction_add] DB update successful for registrations.")
        except Exception as e:
            logging.error(f"[GuildEvents - on_raw_reaction_add] Error updating DB for registrations: {e}")

        await self.update_event_embed(message, target_event)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        key = (payload.message_id, payload.user_id, str(payload.emoji))
        if key in self.ignore_removals:
            ts = self.ignore_removals.pop(key)
            if time.time() - ts < 3:
                logging.debug(f"[GuildEvents - on_raw_reaction_remove] Ignoring automatic removal for key {key}")
                return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        settings = self.guild_settings.get(guild.id)
        if not settings:
            return
        events_channel_id = settings.get("events_channel")
        if payload.channel_id != events_channel_id:
            return

        try:
            channel = guild.get_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
        except Exception as e:
            logging.error(f"[GuildEvents - on_raw_reaction_remove] Error fetching message: {e}")
            return

        async with self.json_lock:
            target_event = None
            for ev in self.events_data.values():
                if ev.get("event_id") == message.id:
                    target_event = ev
                    break
            if not target_event:
                return
            if target_event.get("status", "").strip().lower() == "closed":
                logging.debug(f"[GuildEvents - on_raw_reaction_remove] Ignoring removal since event {target_event['event_id']} is Closed.")
                return

            for key in ["presence", "tentative", "absence"]:
                if payload.user_id in target_event["registrations"].get(key, []):
                    target_event["registrations"][key].remove(payload.user_id)

        await self.update_event_embed(message, target_event)

        try:
            new_registrations = json.dumps(target_event["registrations"])
            update_query = "UPDATE events_data SET registrations = %s WHERE guild_id = %s AND event_id = %s"
            await self.bot.run_db_query(update_query, (new_registrations, target_event["guild_id"], target_event["event_id"]), commit=True)
            logging.debug("[GuildEvents - on_raw_reaction_remove] DB update successful for registrations.")
        except Exception as e:
            logging.error(f"[GuildEvents - on_raw_reaction_remove] Error updating DB for registrations: {e}")

    async def update_event_embed(self, message, event_record):
        logging.debug("✅ [GuildEvents] Starting embed update for event.")
        guild = self.bot.get_guild(message.guild.id)
        guild_id = guild.id
        guild_lang = self.guild_settings.get(guild_id, {}).get("guild_lang", "en-US")

        present_key = GUILD_EVENTS["events_infos"]["present"] \
            .get(guild_lang, GUILD_EVENTS["events_infos"]["present"]["en-US"]) \
            .lower()
        attempt_key = GUILD_EVENTS["events_infos"]["attempt"] \
            .get(guild_lang, GUILD_EVENTS["events_infos"]["attempt"]["en-US"]) \
            .lower()
        absence_key = GUILD_EVENTS["events_infos"]["absence"] \
            .get(guild_lang, GUILD_EVENTS["events_infos"]["absence"]["en-US"]) \
            .lower()
        none_key = GUILD_EVENTS["events_infos"]["none"] \
            .get(guild_lang, GUILD_EVENTS["events_infos"]["none"]["en-US"])

        def format_list(id_list):
            members = [guild.get_member(uid) for uid in id_list if guild.get_member(uid)]
            return ", ".join(m.mention for m in members) if members else none_key

        presence_ids = event_record["registrations"].get("presence", [])
        tentative_ids = event_record["registrations"].get("tentative", [])
        absence_ids = event_record["registrations"].get("absence", [])
        
        presence_str = format_list(presence_ids)
        tentative_str = format_list(tentative_ids)
        absence_str = format_list(absence_ids)

        if not message.embeds:
            logging.error("[GuildEvents] No embed found in the message.")
            return
        embed = message.embeds[0]

        new_fields = []
        for field in embed.fields:
            lower_name = field.name.lower()
            if lower_name.startswith(present_key):
                new_name = f"{GUILD_EVENTS['events_infos']['present'][guild_lang]} <:_yes_:1340109996666388570> ({len(presence_ids)})"
                new_fields.append((new_name, presence_str, field.inline))
            elif lower_name.startswith(attempt_key):
                new_name = f"{GUILD_EVENTS['events_infos']['attempt'][guild_lang]} <:_attempt_:1340110058692018248> ({len(tentative_ids)})"
                new_fields.append((new_name, tentative_str, field.inline))
            elif lower_name.startswith(absence_key):
                new_name = f"{GUILD_EVENTS['events_infos']['absence'][guild_lang]} <:_no_:1340110124521357313> ({len(absence_ids)})"
                new_fields.append((new_name, absence_str, field.inline))
            else:
                new_fields.append((field.name, field.value, field.inline))

        embed.clear_fields()
        for name, value, inline in new_fields:
            embed.add_field(name=name, value=value, inline=inline)

        try:
            await message.edit(embed=embed)
            logging.debug("[GuildEvents] Embed update successful.")
        except Exception as e:
            logging.error(f"[GuildEvents] Error updating embed: {e}")

    async def event_delete_cron(self, ctx=None) -> None:
        tz = pytz.timezone("Europe/Paris")
        now = datetime.now(tz)

        for guild_id, settings in self.guild_settings.items():
            total_deleted = 0
            canceled_events_to_delete = []
            guild = self.bot.get_guild(guild_id)
            if not guild:
                logging.error(f"[GuildEvents CRON] Guild {guild_id} not found.")
                continue

            events_channel = guild.get_channel(settings.get("events_channel"))
            if not events_channel:
                logging.error(f"[GuildEvents CRON] Events channel not found for guild {guild_id}.")
                continue

            guild_events_keys = [key for key, ev in list(self.events_data.items())if ev["guild_id"] == guild_id]

            for key in guild_events_keys:
                ev = self.events_data.get(key)
                try:
                    if isinstance(ev["event_date"], str):
                        event_date = datetime.strptime(ev["event_date"], "%Y-%m-%d").date()
                    else:
                        event_date = ev["event_date"]

                    raw_time = ev["event_time"]
                    if isinstance(raw_time, str):
                        event_time = datetime.strptime(raw_time[:5], "%H:%M").time()
                    elif isinstance(ev["event_time"], dt_time):
                        event_time = raw_time
                    elif isinstance(raw_time, timedelta):
                        seconds = int(raw_time.total_seconds())
                        event_time = dt_time(seconds // 3600, (seconds % 3600) // 60)
                    elif isinstance(ev["event_time"], datetime):
                        event_time = ev["event_time"].time()
                    else:
                        logging.warning(f"[GuildEvents CRON] Unknown time type for event {ev['event_id']}. Defaulting to '21:00'.")
                        event_time = datetime.strptime("21:00", "%H:%M").time()

                    start_dt = tz.localize(datetime.combine(event_date, event_time))
                    end_dt = start_dt + timedelta(minutes=int(ev.get("duration", 0)))
                except Exception as e:
                    logging.error(f"[GuildEvents CRON] Error parsing event {ev['event_id']}: {e}", exc_info=True)
                    continue

                if end_dt < now:
                    try:
                        msg = await events_channel.fetch_message(ev["event_id"])
                        await msg.delete()
                        logging.debug(f"[GuildEvents CRON] Message {ev['event_id']} deleted in channel {events_channel.id}")
                    except HTTPException as http_e:
                        logging.error(f"[GuildEvents CRON] HTTP error deleting message {ev['event_id']}: {http_e}", exc_info=True)
                    except NotFound:
                        logging.debug(f"[GuildEvents CRON] Message {ev['event_id']} already gone (404), removing record.")
                    except Exception as e:
                        logging.error(f"[GuildEvents CRON] Error deleting message for event {ev['event_id']}: {e}", exc_info=True)
                        continue

                    total_deleted += 1
                    del self.events_data[key]

                    if str(ev.get("status", "")).lower() == "canceled":
                        canceled_events_to_delete.append((ev["guild_id"], ev["event_id"]))
                    else:
                        logging.debug(f"[GuildEvents CRON] Event {ev['event_id']} ended but status is not 'Canceled' => record kept.")

            if canceled_events_to_delete:
                try:
                    placeholders = ",".join(["(%s,%s)"] * len(canceled_events_to_delete))
                    delete_query = f"DELETE FROM events_data WHERE (guild_id, event_id) IN ({placeholders})"
                    params = [item for sublist in canceled_events_to_delete for item in sublist]
                    await self.bot.run_db_query(delete_query, params, commit=True)
                    logging.debug(f"[GuildEvents CRON] Batch deleted {len(canceled_events_to_delete)} canceled events from DB for guild {guild_id}")
                except Exception as e:
                    logging.error(f"[GuildEvents CRON] Error batch deleting events for guild {guild_id}: {e}", exc_info=True)

            logging.info(f"[GuildEvents CRON] For guild {guild_id}, messages deleted: {total_deleted}")

    async def event_reminder_cron(self) -> None:
        tz = pytz.timezone("Europe/Paris")
        today_str = datetime.now(tz).strftime("%Y-%m-%d")
        overall_results = []

        logging.info(f"[GuildEvents - event_reminder_cron] Starting automatic reminder for {today_str}.")

        for guild_id, settings in self.guild_settings.items():
            guild = self.bot.get_guild(guild_id)
            if not guild:
                logging.error(f"[GuildEvents] Guild {guild_id} not found.")
                continue

            guild_locale = settings.get("guild_lang") or "en-US"

            notifications_channel = guild.get_channel(settings.get("notifications_channel"))
            events_channel = guild.get_channel(settings.get("events_channel"))
            if not events_channel or not notifications_channel:
                logging.error(f"[GuildEvents] Events or notifications channel not found for guild {guild.name}.")
                continue

            guild_events = [ev for ev in self.events_data.values() if ev["guild_id"] == guild_id]
            for ev in guild_events:
                logging.debug(f"[GuildEvents - event_reminder_cron] Comparing event {ev['event_id']}: event_date={repr(ev.get('event_date'))} (type {type(ev.get('event_date'))}), "
                            f"today_str={repr(today_str)}, status={repr(ev.get('status', ''))} (lowercased: {repr(ev.get('status', '').strip().lower())})")

            confirmed_events = [
                ev for ev in guild_events
                if str(ev.get("event_date")).strip() == today_str and str(ev.get("status", "")).strip().lower() == "confirmed"
            ]
            logging.info(f"[GuildEvents - event_reminder_cron] For guild {guild.name}, {len(confirmed_events)} confirmed event(s) found for today.")

            if not confirmed_events:
                overall_results.append(f"{guild.name}: No confirmed events today.")
                continue

            for event in confirmed_events:
                registrations_obj = event.get("registrations", {})
                if isinstance(registrations_obj, str):
                    try:
                        registrations_obj = json.loads(registrations_obj)
                    except Exception as e:
                        logging.error(f"[GuildEvents - event_reminder_cron] Error parsing 'registrations' for event {event['event_id']}: {e}", exc_info=True)
                        registrations_obj = {"presence": [], "tentative": [], "absence": []}
                registrations = set(registrations_obj.get("presence", [])) | set(registrations_obj.get("tentative", [])) | set(registrations_obj.get("absence", []))
                initial_members = event.get("initial_members", [])
                if isinstance(initial_members, str):
                    try:
                        initial_members = json.loads(initial_members)
                    except Exception as e:
                        logging.error(f"[GuildEvents - event_reminder_cron] Error parsing 'initial_members' for event {event['event_id']}: {e}", exc_info=True)
                        initial_members = []
                initial = set(initial_members)
                
                try:
                    members_role_id = settings.get("members_role")
                    if members_role_id:
                        role = guild.get_role(int(members_role_id))
                        if role:
                            current_members = {member.id for member in guild.members if role in member.roles}
                        else:
                            current_members = set()
                    else:
                        current_members = set()
                except Exception as e:
                    logging.error(f"[GuildEvents - event_reminder_cron] Error retrieving current members for guild {guild.id}: {e}", exc_info=True)
                    current_members = set()
                
                updated_initial = current_members
                to_remind = list(updated_initial - registrations)
                reminded = []
                event_link = f"https://discord.com/channels/{guild.id}/{events_channel.id}/{event['event_id']}"
                dm_template = GUILD_EVENTS.get("event_reminder", {}).get("dm_message", {}).get(guild_locale,GUILD_EVENTS.get("event_reminder", {}).get("dm_message", {}).get("en-US"))
                logging.debug(f"[GuildEvents - event_reminder_cron] For event {event['event_id']}, initial members: {initial}, registered: {registrations}, to remind: {to_remind}")
                for member_id in to_remind:
                    member = guild.get_member(member_id)
                    if member:
                        try:
                            dm_message = dm_template.format(
                                member_name=member.name,
                                event_name=event["name"],
                                date=event["event_date"],
                                time=event["event_time"],
                                link=event_link
                            )
                            await member.send(dm_message)
                            reminded.append(member.mention)
                            logging.debug(f"[GuildEvents - event_reminder_cron] DM sent to {member.name} for event {event['name']}")
                        except Exception as e:
                            logging.error(f"[GuildEvents - event_reminder_cron] Error sending DM to {member_id} in guild {guild.name}: {e}")
                    else:
                        logging.warning(f"[GuildEvents - event_reminder_cron] Member {member_id} not found in guild {guild.name}.")

                try:
                    if reminded:
                        reminder_template = GUILD_EVENTS.get("event_reminder", {}).get("notification_reminded", {}).get(guild_locale)
                        if reminder_template is None:
                            reminder_template = GUILD_EVENTS.get("event_reminder", {}).get("notification_reminded", {}).get("en-US", 
                                "## :bell: Event Reminder\nFor event **{event}**\n({event_link})\n\n{len} member(s) were reminded: {members}"
                            )
                        try:
                            reminder_msg = reminder_template.format(event=event["name"], event_link=event_link, len=len(reminded), members=", ".join(reminded))
                        except Exception as e:
                            logging.error(f"[GuildEvents - event_reminder_cron] Error formatting reminder template: {e}", exc_info=True)
                            reminder_msg = f"Reminder: {event['name']} - {event_link}"
                        result = f"For event **{event['name']}** in guild {guild.name}: {len(reminded)} member(s) reminded: " + ", ".join(reminded)
                        await notifications_channel.send(reminder_msg)
                        overall_results.append(result)
                    else:
                        reminder_template = GUILD_EVENTS.get("event_reminder", {}).get("notification_all_OK", {}).get(guild_locale)
                        if reminder_template is None:
                            reminder_template = GUILD_EVENTS.get("event_reminder", {}).get("notification_all_OK", {}).get("en-US", 
                                "## :bell: Event Reminder\nFor event **{event}**\n({event_link})\n\nAll members have responded."
                            )
                        try:
                            reminder_msg = reminder_template.format(event=event["name"], event_link=event_link)
                        except Exception as e:
                            logging.error(f"[GuildEvents - event_reminder_cron] Error formatting 'all OK' reminder template: {e}", exc_info=True)
                            reminder_msg = f"Reminder: {event['name']} - {event_link}"
                        result = f"For event **{event['name']}** in guild {guild.name}, all members have responded."
                        await notifications_channel.send(reminder_msg)
                        overall_results.append(result)
                except Exception as e:
                    logging.error(f"[GuildEvents - event_reminder_cron] Error sending reminder message in guild {guild.name}: {e}", exc_info=True)
                    overall_results.append(f"{guild.name}: Error sending reminder.")
        logging.info("Reminder results:\n" + "\n".join(overall_results))

    async def event_close_cron(self) -> None:
        tz = pytz.timezone("Europe/Paris")
        now = datetime.now(tz)

        for guild_id, settings in self.guild_settings.items():
            closed_events_to_update = []
            guild = self.bot.get_guild(guild_id)
            if not guild:
                logging.error(f"[GuildEvents CRON] Guild {guild_id} not found.")
                continue

            events_channel = guild.get_channel(settings.get("events_channel"))
            if not events_channel:
                logging.error(f"[GuildEvents CRON] Events channel not found for guild {guild_id}.")
                continue

            guild_lang = settings.get("guild_lang") or "en-US"

            guild_events_keys = [key for key, ev in self.events_data.items() if ev["guild_id"] == guild_id]
            for key in guild_events_keys:
                ev = self.events_data[key]
                try:
                    if isinstance(ev["event_date"], str):
                        event_date = datetime.strptime(ev["event_date"], "%Y-%m-%d").date()
                    else:
                        event_date = ev["event_date"]
                    if isinstance(ev["event_time"], str):
                        time_str = ev["event_time"][:5]
                        event_time = datetime.strptime(time_str, "%H:%M").time()
                    elif isinstance(ev["event_time"], timedelta):
                        total_seconds = int(ev["event_time"].total_seconds())
                        hours = total_seconds // 3600
                        minutes = (total_seconds % 3600) // 60
                        event_time = dt_time(hours, minutes)
                    elif isinstance(ev["event_time"], dt_time):
                        event_time = ev["event_time"]
                    elif isinstance(ev["event_time"], datetime):
                        event_time = ev["event_time"].time()
                    else:
                        logging.warning(f"[GuildEvents CRON] Unknown time type for event {ev['event_id']}. Defaulting to '21:00'.")
                        event_time = datetime.strptime("21:00", "%H:%M").time()

                    start_dt = tz.localize(datetime.combine(event_date, event_time))
                except Exception as e:
                    logging.error(f"[GuildEvents CRON] Error parsing event {ev['event_id']}: {e}", exc_info=True)
                    continue

                time_diff = start_dt - now
                time_condition = timedelta(minutes=-60) <= time_diff <= timedelta(minutes=15)
                status_condition = ev.get("status", "").strip().lower() in ["confirmed", "planned"]
                
                logging.debug(f"[GuildEvents CRON] Event {ev['event_id']}: time_diff={time_diff}, condition={time_condition and status_condition}")
                
                if time_condition and status_condition:
                    try:
                        await self.load_guild_members()
                    except Exception as e:
                        logging.error(f"[GuildEvents CRON] Error loading guild members for guild {guild_id}: {e}", exc_info=True)
                    closed_localized = GUILD_EVENTS["events_infos"]["status_closed"].get(guild_lang, GUILD_EVENTS["events_infos"]["status_closed"].get("en-US"))
                    closed_db = GUILD_EVENTS["events_infos"]["status_closed"].get("en-US")
                    try:
                        msg = await events_channel.fetch_message(ev["event_id"])
                    except Exception as e:
                        logging.error(f"[GuildEvents CRON] Error fetching message for event {ev['event_id']}: {e}", exc_info=True)
                        continue

                    if msg.embeds:
                        embed = msg.embeds[0]
                        new_fields = []
                        for field in embed.fields:
                            expected_field_name = GUILD_EVENTS["events_infos"]["status"].get(guild_lang, GUILD_EVENTS["events_infos"]["status"].get("en-US"))
                            if field.name.lower() == expected_field_name.lower():
                                new_fields.append({"name": field.name, "value": closed_localized, "inline": field.inline})
                            else:
                                new_fields.append({"name": field.name, "value": field.value, "inline": field.inline})
                        embed.clear_fields()
                        for field in new_fields:
                            embed.add_field(name=field["name"], value=field["value"], inline=field["inline"])
                        try:
                            await msg.edit(embed=embed)
                            closed_events_to_update.append((closed_db, guild_id, ev["event_id"]))
                            ev["status"] = closed_db
                            logging.info(f"[GuildEvents CRON] Event {ev['event_id']} marked as Closed.")
                            await msg.clear_reactions()
                            logging.info(f"[GuildEvents CRON] Reactions cleared for event {ev['event_id']}.")
                            await self.create_groups(guild_id, ev["event_id"])
                            
                            attendance_cog = self.bot.get_cog("GuildAttendance")
                            if attendance_cog:
                                try:
                                    await attendance_cog.process_event_registrations(guild_id, ev["event_id"], ev)
                                    logging.debug(f"[GuildEvents CRON] Registrations processed for event {ev['event_id']}")
                                except Exception as e:
                                    logging.error(f"[GuildEvents CRON] Error processing registrations for event {ev['event_id']}: {e}", exc_info=True)
                        except Exception as e:
                            logging.error(f"[GuildEvents CRON] Error updating event {ev['event_id']}: {e}", exc_info=True)

            if closed_events_to_update:
                try:
                    event_ids = [str(item[2]) for item in closed_events_to_update]
                    placeholders = ",".join(["%s"] * len(event_ids))
                    update_query = f"UPDATE events_data SET status = %s WHERE guild_id = %s AND event_id IN ({placeholders})"
                    params = [closed_events_to_update[0][0], guild_id] + event_ids
                    await self.bot.run_db_query(update_query, params, commit=True)
                    logging.debug(f"[GuildEvents CRON] Batch updated {len(closed_events_to_update)} events to Closed status for guild {guild_id}")

                    attendance_cog = self.bot.get_cog("GuildAttendance")
                    if attendance_cog:
                        await attendance_cog.reload_events_cache_for_guild(guild_id)
                        logging.debug(f"[GuildEvents CRON] Reloaded events cache for guild {guild_id} in attendance cog")
                        
                except Exception as e:
                    logging.error(f"[GuildEvents CRON] Error batch updating event statuses for guild {guild_id}: {e}", exc_info=True)

        logging.info("[GuildEvents CRON] Finished event_close_cron.")

    @staticmethod
    def group_members_by_class(member_ids, roster_data):
        logging.debug("[Guild_Events - GroupsMembersByClass] Building class buckets…")
        classes = {c: [] for c in ("Tank", "Melee DPS", "Ranged DPS",
                                "Healer", "Flanker")}
        missing = []

        for mid in member_ids:
            try:
                info = roster_data["members"][str(mid)]
            except KeyError:
                logging.warning(f"[Guild_Events - GroupsMembersByClass] Member ID {mid} not found in roster.")
                missing.append(mid)
                continue

            pseudo = info.get("pseudo", "Unknown")
            gs     = info.get("GS", "N/A")
            weapons  = info.get("weapons", "")
            member_class = info.get("class", "Unknown")

            emojis = " ".join(
                WEAPON_EMOJIS.get(c.strip(), c.strip())
                for c in weapons.split("/") if c.strip()
            ) or "N/A"

            classes.setdefault(member_class, []).append(f"{pseudo} {emojis} - GS: {gs}")

        logging.info(f"[Guild_Events - GroupsMembersByClass] Buckets built – {sum(len(v) for v in classes.values())} "
                    f"entries, {len(missing)} missing.")
        return classes, missing

    @staticmethod
    def _get_optimal_grouping(n: int, min_size: int = 4, max_size: int = 6) -> list[int]:
        logging.debug(f"[Guild_Events - GetOptimalGrouping] Start – n={n}, min={min_size}, max={max_size}")
        possible = []
        try:
            for k in range(math.ceil(n/max_size), n // min_size + 1):
                base  = n // k
                extra = n % k
                if base < min_size or base + 1 > max_size:
                    continue
                grouping = [base+1]*extra + [base]*(k-extra)
                possible.append((k, grouping))

            if not possible:
                k = math.ceil(n/max_size)
                base  = n // k
                extra = n % k
                result = [base+1]*extra + [base]*(k-extra)
                logging.debug(f"[Guild_Events - GetOptimalGrouping] Fallback result → {result}")
                return result

            possible.sort(key=lambda t: (sum(1 for s in t[1] if s == max_size), -t[0]),
                        reverse=True)
            result = possible[0][1]
            logging.debug(f"[Guild_Events - GetOptimalGrouping] Best result → {result}")
            return result
        except Exception as exc:
            logging.exception("[Guild_Events - GetOptimalGrouping] Unexpected error.", exc_info=exc)
            return [min_size] * math.ceil(n / min_size)

    def _calculate_gs_ranges(self, members_data: List[Dict]) -> List[Tuple[int, int]]:
        gs_values = []
        for member in members_data:
            try:
                gs_str = member.get("GS", "0")
                if isinstance(gs_str, str) and gs_str.lower() in ["n/a", "na", "", "unknown"]:
                    continue
                gs = int(float(gs_str))
                if gs > 0:
                    gs_values.append(gs)
            except (ValueError, TypeError):
                continue
        
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
        
        ranges = []
        current_min = min_gs
        
        while current_min < max_gs:
            range_max = min(current_min + tolerance, max_gs)
            ranges.append((int(current_min), int(range_max)))
            current_min = range_max - (tolerance * 0.1)
            
            if len(ranges) >= 5:
                break
        
        logging.debug(f"[GuildEvents - GS Ranges] Calculated ranges for {total_members} members: {ranges}")
        return ranges

    def _get_member_gs_range(self, member_gs, gs_ranges: List[Tuple[int, int]]) -> int:
        try:
            if isinstance(member_gs, str) and member_gs.lower() in ["n/a", "na", ""]:
                return 0
            gs = int(float(member_gs))
            for i, (min_gs, max_gs) in enumerate(gs_ranges):
                if min_gs <= gs <= max_gs:
                    return i
            for i, (min_gs, max_gs) in enumerate(gs_ranges):
                if gs < min_gs:
                    return i
                if gs > max_gs and i == len(gs_ranges) - 1:
                    return i
        except (ValueError, TypeError):
            pass
        return 0

    def _format_static_group_members(self, member_ids: List[int], guild_obj, absent_text: str) -> List[str]:
        member_info_list = []

        for member_id in member_ids:
            member = guild_obj.get_member(member_id) if guild_obj else None
            member_data = self.guild_members_cache.get(guild_obj.id, {}).get(member_id, {}) if guild_obj else {}
            
            member_info = {
                "member": member,
                "member_id": member_id,
                "class": member_data.get("class", "Unknown"),
                "gs": member_data.get("GS", "N/A"),
                "weapons": member_data.get("weapons", "N/A"),
                "mention": member.mention if member else f"<@{member_id}> ({absent_text})",
                "is_present": member is not None
            }
            member_info_list.append(member_info)

        class_priority = {
            "Tank": 1,
            "Healer": 2,
            "Melee DPS": 3,
            "Ranged DPS": 4,
            "Flanker": 5,
            "Unknown": 99
        }

        member_info_list.sort(key=lambda x: (class_priority.get(x["class"], 99), not x["is_present"]))

        formatted_members = []
        for info in member_info_list:
            class_emoji = CLASS_EMOJIS.get(info["class"], "❓")

            weapons_emoji = ""
            if info["weapons"] and info["weapons"] != "N/A":
                weapon_list = [w.strip() for w in info["weapons"].split("/") if w.strip()]
                weapons_emoji = " ".join(WEAPON_EMOJIS.get(weapon, weapon) for weapon in weapon_list)

            gs_display = f"({info['gs']})" if info["gs"] and info["gs"] != "N/A" else "(N/A)"

            if info["is_present"]:
                line = f"{class_emoji} {info['mention']} {weapons_emoji} {gs_display}"
            else:
                line = f"{class_emoji} {info['mention']} {weapons_emoji} {gs_display}"
            
            formatted_members.append(line)
        
        return formatted_members

    def _calculate_member_score(self, member: Dict, target_class: str, target_gs_range: int, 
                               gs_ranges: List[Tuple[int, int]], is_tentative: bool = False) -> float:
        score = 0.0
        
        if member.get("class") == target_class:
            score += 0.7
        elif target_class in ["Melee DPS", "Ranged DPS"] and member.get("class") in ["Melee DPS", "Ranged DPS"]:
            score += 0.5
        elif member.get("class") in ["Melee DPS", "Ranged DPS", "Flanker"]:
            score += 0.3
        
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

    def _assign_groups_enhanced(self, guild_id: int, presence_ids: List[int], tentative_ids: List[int], roster_data: Dict) -> List[List[Dict]]:
        logging.info("[GuildEvents - Groups Enhanced] Starting enhanced group assignment")
        
        all_inscribed = set(presence_ids + tentative_ids)
        final_groups = []
        used_members = set()
        incomplete_static_groups = []
        
        def get_member_info(uid: int, tentative: bool = False):
            info = roster_data["members"].get(str(uid))
            if not info:
                return None
            return {**info, "tentative": tentative, "user_id": uid}
        
        all_members_data = [get_member_info(uid) for uid in all_inscribed if get_member_info(uid)]
        gs_ranges = self._calculate_gs_ranges(all_members_data)
        logging.info(f"[GuildEvents - Groups Enhanced] GS ranges calculated: {gs_ranges}")
        
        logging.info("[GuildEvents - Groups Enhanced] Step 1: Processing static groups (complete or N-1)")
        
        static_groups = self.static_groups_cache.get(guild_id, {})
        for group_name, group_data in static_groups.items():
            member_ids = group_data["member_ids"]
            configured_count = len(member_ids)
            present_members = [mid for mid in member_ids if mid in presence_ids and mid not in used_members]
            present_count = len(present_members)
            
            logging.debug(f"[GuildEvents - Groups Enhanced] Static '{group_name}': {present_count}/{configured_count} present")
            
            if present_count == configured_count or present_count == (configured_count - 1):
                group_members = []
                for mid in present_members:
                    is_tentative = mid in tentative_ids
                    member_info = get_member_info(mid, is_tentative)
                    if member_info:
                        group_members.append(member_info)
                        used_members.add(mid)
                
                if group_members:
                    incomplete_static_groups.append({
                        "name": group_name,
                        "members": group_members,
                        "missing_slots": 6 - len(group_members),
                        "original_ids": member_ids
                    })
                    logging.info(f"[GuildEvents - Groups Enhanced] Static '{group_name}' created with {len(group_members)}/6 members")
            else:
                logging.debug(f"[GuildEvents - Groups Enhanced] Static '{group_name}' not eligible ({present_count}/{configured_count})")

        logging.info("[GuildEvents - Groups Enhanced] Step 2: Completing static groups")
        
        for static_group in incomplete_static_groups:
            if static_group["missing_slots"] > 0:
                existing_classes = [m["class"] for m in static_group["members"]]
                missing_classes = []

                if len(static_group["members"]) == (len(static_group["original_ids"]) - 1):
                    missing_id = [mid for mid in static_group["original_ids"] if mid not in [m["user_id"] for m in static_group["members"]]][0]
                    missing_info = get_member_info(missing_id)
                    if missing_info:
                        missing_classes.append(missing_info["class"])

                essential_classes = ["Tank", "Healer"]
                for essential in essential_classes:
                    if essential not in existing_classes:
                        missing_classes.append(essential)

                available_members = [uid for uid in all_inscribed if uid not in used_members and uid not in static_group["original_ids"]]
                
                for _ in range(static_group["missing_slots"]):
                    best_candidate = None
                    best_score = 0
                    
                    for uid in available_members:
                        member_info = get_member_info(uid, uid in tentative_ids)
                        if not member_info:
                            continue

                        if missing_classes and member_info["class"] in missing_classes:
                            score = self._calculate_member_score(
                                member_info, missing_classes[0], 0, gs_ranges, uid in tentative_ids
                            )
                        else:
                            score = self._calculate_member_score(
                                member_info, "Melee DPS", 0, gs_ranges, uid in tentative_ids
                            )
                        
                        if score > best_score:
                            best_score = score
                            best_candidate = uid
                    
                    if best_candidate:
                        member_info = get_member_info(best_candidate, best_candidate in tentative_ids)
                        static_group["members"].append(member_info)
                        used_members.add(best_candidate)
                        available_members.remove(best_candidate)
                        static_group["missing_slots"] -= 1
                        
                        if missing_classes and member_info["class"] in missing_classes:
                            missing_classes.remove(member_info["class"])
                        
                        logging.info(f"[GuildEvents - Groups Enhanced] Added {member_info['class']} to static '{static_group['name']}'")
            
            final_groups.append(static_group["members"])

        logging.info("[GuildEvents - Groups Enhanced] Step 3: Creating optimized groups with GS matching")
        
        remaining_members = [uid for uid in all_inscribed if uid not in used_members]
        present_remaining = [uid for uid in remaining_members if uid in presence_ids]
        tentative_remaining = [uid for uid in remaining_members if uid in tentative_ids]

        gs_buckets = {}
        for i, gs_range in enumerate(gs_ranges):
            gs_buckets[i] = {"Tank": [], "Healer": [], "Melee DPS": [], "Ranged DPS": [], "Flanker": []}

        for uid in present_remaining:
            member_info = get_member_info(uid, False)
            if member_info:
                gs_range_idx = self._get_member_gs_range(member_info.get("GS", 0), gs_ranges)
                if member_info["class"] in gs_buckets[gs_range_idx]:
                    gs_buckets[gs_range_idx][member_info["class"]].append(member_info)
        
        for gs_idx in sorted(gs_buckets.keys(), reverse=True):
            bucket = gs_buckets[gs_idx]

            while len(bucket["Flanker"]) >= 5:
                flanker_group = bucket["Flanker"][:6] if len(bucket["Flanker"]) >= 6 else bucket["Flanker"][:5]
                final_groups.append(flanker_group)
                bucket["Flanker"] = bucket["Flanker"][len(flanker_group):]
                for member in flanker_group:
                    used_members.add(member["user_id"])
                logging.info(f"[GuildEvents - Groups Enhanced] Flanker group formed for GS range {gs_ranges[gs_idx]}")

            while (len(bucket["Tank"]) >= 1 and len(bucket["Healer"]) >= 1):
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
                    logging.info(f"[GuildEvents - Groups Enhanced] Optimized group formed for GS range {gs_ranges[gs_idx]} with {len(group)} members")
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
                        if len(group) < 6:
                            valid_gs_values = [int(m.get("GS", 0)) for m in group if m.get("GS", "0").isdigit()]
                            group_gs_avg = sum(valid_gs_values) / len(valid_gs_values) if valid_gs_values else 0
                            gs_range_idx = self._get_member_gs_range(group_gs_avg, gs_ranges)
                            score = self._calculate_member_score(member_info, "Melee DPS", gs_range_idx, gs_ranges, True)
                            
                            if score > best_score:
                                best_score = score
                                best_group = group
                    
                    if best_group:
                        best_group.append(member_info)
                        used_members.add(uid)
                        logging.info(f"[GuildEvents - Groups Enhanced] Added tentative {member_info['class']} to optimized group")

        logging.info("[GuildEvents - Groups Enhanced] Step 4: Creating non-optimized groups")
        
        remaining_members = [uid for uid in all_inscribed if uid not in used_members]
        
        while len(remaining_members) >= 4:
            group = []

            for uid in remaining_members[:6]:
                member_info = get_member_info(uid, uid in tentative_ids)
                if member_info:
                    group.append(member_info)
                    used_members.add(uid)
            
            remaining_members = [uid for uid in remaining_members if uid not in used_members]
            
            if len(group) >= 4:
                final_groups.append(group)
                logging.info(f"[GuildEvents - Groups Enhanced] Non-optimized group formed with {len(group)} members")

        logging.info("[GuildEvents - Groups Enhanced] Step 5: Final redistribution")
        
        final_remaining = [uid for uid in all_inscribed if uid not in used_members]

        for uid in final_remaining[:]:
            member_info = get_member_info(uid, uid in tentative_ids)
            if member_info:
                for group in final_groups:
                    if len(group) < 6:
                        group.append(member_info)
                        used_members.add(uid)
                        final_remaining.remove(uid)
                        logging.info(f"[GuildEvents - Groups Enhanced] Added remaining member to existing group")
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
                logging.info(f"[GuildEvents - Groups Enhanced] Final isolation group formed with {len(last_group)} members")
        
        logging.info(f"[GuildEvents - Groups Enhanced] Completed: {len(final_groups)} groups formed with enhanced logic")
        return final_groups

    def _assign_groups_legacy(self, presence_ids: list[int], tentative_ids: list[int], roster_data: dict) -> list[list[dict]]:
        logging.debug("[Guild_Events - AssignGroups] Starting group assignment…")

        buckets = {c: [] for c in ("Tank", "Healer",
                                   "Melee DPS", "Ranged DPS", "Flanker")}

        def _push(uid: int, tentative: bool):
            info = roster_data["members"].get(str(uid))
            if not info:
                logging.warning(f"[Guild_Events - AssignGroups] UID {uid} missing from roster, skipped.")
                return
            try:
                buckets[info["class"]].append({**info, "tentative": tentative})
            except KeyError:
                logging.error(f"[Guild_Events - AssignGroups] Unknown class '{info.get('class')}' for UID {uid}.")

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
                    extra = [m for m in buckets["Flanker"] if m["tentative"]][:6-len(grp)]
                    grp.extend(extra)
                groups.append(grp)
                used = {id(m) for m in grp}
                buckets["Flanker"] = [m for m in buckets["Flanker"] if id(m) not in used]

            buckets["Ranged DPS"].extend(buckets.pop("Flanker"))

            sizes = self._get_optimal_grouping(len(presence_ids), 4, 6)

            def _pop(role, titular_first=True):
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
                classes = [m["class"] for m in g]
                if "Healer" not in classes and buckets["Healer"]:
                    return "Healer"
                if "Tank" not in classes and buckets["Tank"]:
                    return "Tank"
                melee  = sum(c == "Melee DPS"   for c in classes)
                ranged = sum(c == "Ranged DPS"  for c in classes)
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
                    groups.append(remaining[start:start+cs])
                    start += cs

            logging.info(f"[Guild_Events - AssignGroups] Finished – {len(groups)} group(s) built.")
            return groups

        except Exception as exc:
            logging.exception("[Guild_Events - AssignGroups] Unexpected error during grouping.", exc_info=exc)
            return []

    async def create_groups(self, guild_id: int, event_id: int) -> None:
        logging.info(f"[GuildEvent - Cron Create_Groups] Creating groups for guild {guild_id}, event {event_id}")

        guild = self.bot.get_guild(guild_id)
        if not guild:
            logging.error(f"[GuildEvent - Cron Create_Groups] Guild not found for guild_id: {guild_id}")
            return

        settings = self.guild_settings.get(guild_id)
        if not settings:
            logging.error(f"[GuildEvent - Cron Create_Groups] No configuration found for guild {guild_id}")
            return

        guild_lang = settings.get("guild_lang", "en-US")

        groups_channel = guild.get_channel(int(settings.get("groups_channel")))
        events_channel = guild.get_channel(int(settings.get("events_channel")))
        members_role_id = settings.get("members_role")
        mention_role = f"<@&{members_role_id}>" if members_role_id else ""
        if not groups_channel or not events_channel:
            logging.error(f"[GuildEvent - Cron Create_Groups] Channels not found (groups/events) for guild {guild_id}")
            return

        key = f"{guild_id}_{event_id}"
        event = self.events_data.get(key)
        if not event:
            logging.error(f"[GuildEvent - Cron Create_Groups] Event not found for guild {guild_id} and event {event_id}")
            return

        registrations = event.get("registrations", {})
        if isinstance(registrations, str):
            try:
                registrations = json.loads(registrations)
            except (json.JSONDecodeError, ValueError) as e:
                logging.warning(f"[GuildEvents] Invalid JSON in registrations, using defaults: {e}")
                registrations = {"presence": [], "tentative": [], "absence": []}
        presence_ids  = registrations.get("presence", [])
        tentative_ids = registrations.get("tentative", [])

        presence_count  = len(presence_ids)
        tentative_count = len(tentative_ids)
        event_link = f"https://discord.com/channels/{guild.id}/{events_channel.id}/{event_id}"
        header = (
            f"{mention_role}\n\n"
            f"**__{GUILD_EVENTS['events_infos']['event_name'].get(guild_lang, 'Event')} :__ {event['name']}**\n"
            f"{event['event_date']} {GUILD_EVENTS['events_infos']['time_at'].get(guild_lang, 'at')} {event['event_time']}\n"
            f"{GUILD_EVENTS['events_infos']['present_count'].get(guild_lang, 'Present')} : {presence_count}\n{GUILD_EVENTS['events_infos']['attempt_count'].get(guild_lang, 'Attempts')} : {tentative_count}\n\n"
            f"[{GUILD_EVENTS['events_infos']['view_event'].get(guild_lang, 'View Event and registrations')}]({event_link})\n\n"
            f"{GUILD_EVENTS['events_infos']['groups_below'].get(guild_lang, 'Groups below')}\n"
        )

        try:
            roster_data = {"members": {}}
            for member in guild.members:
                md = self.guild_members_cache.get(guild_id, {}).get(member.id, {})
                roster_data["members"][str(member.id)] = {
                    "pseudo": member.display_name,
                    "GS": md.get("GS", "N/A"),
                    "weapons": md.get("weapons", "N/A"),
                    "class": md.get("class", "Unknown"),
                }
        except Exception as exc:
            logging.exception("[Guild_Events - CreateGroups] Failed to build roster.", exc_info=exc)
            return

        try:
            all_groups = self._assign_groups_enhanced(guild_id, presence_ids, tentative_ids, roster_data)
        except Exception as exc:
            logging.exception("[Guild_Events - CreateGroups] _assign_groups_enhanced crashed.", exc_info=exc)
            return

        try:
            embeds = []
            total = len(all_groups)
            for idx, grp in enumerate(all_groups, 1):
                e = discord.Embed(title=f"Groupe {idx} / {total}",
                                color=discord.Color.blue())
                lines = []
                for m in grp:
                    cls_emoji = CLASS_EMOJIS.get(m["class"], "")
                    weapons_emoji = " ".join(
                        WEAPON_EMOJIS.get(c.strip(), c.strip())
                        for c in m["weapons"].split("/") if c.strip()
                    )
                    if m.get("tentative"):
                        lines.append(f"{cls_emoji} {weapons_emoji} *{m['pseudo']}* ({m['GS']}) 🔶")
                    else:
                        lines.append(f"{cls_emoji} {weapons_emoji} {m['pseudo']} ({m['GS']})")
                no_member_text = GUILD_EVENTS.get("no_member", {}).get(guild_lang, "No member")
                e.description = "\n".join(lines) or no_member_text
                embeds.append(e)

            await groups_channel.send(content=header, embeds=embeds)
            logging.info(f"[GuildEvents - Create_Groups] Groups sent to channel {groups_channel.id}.")
        except Exception as exc:
            logging.exception("[GuildEvents - Create_Groups] Failed to send embeds.", exc_info=exc)

    @discord.slash_command(
        name=GUILD_EVENTS.get("event_create", {}).get("name", {}).get("en-US", "event_create"),
        description=GUILD_EVENTS.get("event_create", {}).get("description", {}).get("en-US", "Create a guild event manually."),
        name_localizations=GUILD_EVENTS.get("event_create", {}).get("name", {}),
        description_localizations=GUILD_EVENTS.get("event_create", {}).get("description", {})
    )
    @commands.has_permissions(manage_guild=True)
    async def event_create(
        self, 
        ctx: discord.ApplicationContext, 
        event_name: str = discord.Option(
            description=GUILD_EVENTS["event_create"]["event_name"]["en-US"],
            description_localizations=GUILD_EVENTS["event_create"]["event_name"]
        ),
        event_date: str = discord.Option(
            description=GUILD_EVENTS["event_create"]["event_date"]["en-US"],
            description_localizations=GUILD_EVENTS["event_create"]["event_date"]
        ),
        event_time: str = discord.Option(
            description=GUILD_EVENTS["event_create"]["event_hour"]["en-US"],
            description_localizations=GUILD_EVENTS["event_create"]["event_hour"]
        ),
        duration: int = discord.Option(
            int,
            description=GUILD_EVENTS["event_create"]["event_time"]["en-US"],
            description_localizations=GUILD_EVENTS["event_create"]["event_time"],
            min_value=1,
            max_value=1440
        ),
        status: str = discord.Option(
            default="Confirmed",
            description=GUILD_EVENTS["event_create"]["status"]["en-US"],
            description_localizations=GUILD_EVENTS["event_create"]["status"],
            choices=[
                discord.OptionChoice(
                    name=choice_data["name_localizations"].get("en-US", key),
                    value=choice_data["value"],
                    name_localizations=choice_data["name_localizations"]
                )
                for key, choice_data in GUILD_EVENTS["event_create"]["choices"].items()
            ]
        ),
        dkp_value: int = discord.Option(
            int,
            default=0,
            description=GUILD_EVENTS["event_create"]["dkp_value"]["en-US"],
            description_localizations=GUILD_EVENTS["event_create"]["dkp_value"],
            min_value=0,
            max_value=9999
        ),
        dkp_ins: int = discord.Option(
            int,
            default=0,
            description=GUILD_EVENTS["event_create"]["dkp_ins"]["en-US"],
            description_localizations=GUILD_EVENTS["event_create"]["dkp_ins"],
            min_value=0,
            max_value=9999
        )
    ):
        await ctx.defer(ephemeral=True)

        guild = ctx.guild
        settings = self.guild_settings.get(ctx.guild.id)
        user_locale = ctx.locale if hasattr(ctx, "locale") and ctx.locale else "en-US"
        guild_lang = settings.get("guild_lang") if settings and settings.get("guild_lang") else "en-US"

        if not settings:
            follow_message = GUILD_EVENTS["event_create"]["no_settings"].get(user_locale,GUILD_EVENTS["event_create"]["no_settings"].get("en-US"))
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        logging.debug(f"[GuildEvents - event_create] Received parameters: event_name={event_name}, event_date={event_date}, event_time={event_time}, duration={duration}, status={status}, dkp_value={dkp_value}, dkp_ins={dkp_ins}")
        
        if not event_name or not event_name.strip():
            follow_message = GUILD_EVENTS.get("event_create", {}).get("name_empty", {}).get(user_locale, "❌ Event name cannot be empty.")
            await ctx.followup.send(follow_message, ephemeral=True)
            return
            
        event_name = event_name.strip()
        if len(event_name) > 100:
            follow_message = GUILD_EVENTS.get("event_create", {}).get("name_too_long", {}).get(user_locale, "❌ Event name is too long (max 100 characters).")
            await ctx.followup.send(follow_message, ephemeral=True)
            return
            
        if dkp_value < 0 or dkp_value > 9999:
            follow_message = GUILD_EVENTS.get("event_create", {}).get("dkp_value_invalid", {}).get(user_locale, "❌ DKP value must be between 0 and 9999.")
            await ctx.followup.send(follow_message, ephemeral=True)
            return
            
        if dkp_ins < 0 or dkp_ins > 9999:
            follow_message = GUILD_EVENTS.get("event_create", {}).get("dkp_ins_invalid", {}).get(user_locale, "❌ DKP inscription value must be between 0 and 9999.")
            await ctx.followup.send(follow_message, ephemeral=True)
            return
            
        if duration <= 0 or duration > 1440:
            follow_message = GUILD_EVENTS.get("event_create", {}).get("duration_invalid", {}).get(user_locale, "❌ Duration must be between 1 and 1440 minutes (24 hours).")
            await ctx.followup.send(follow_message, ephemeral=True)
            return
        
        tz = pytz.timezone("Europe/Paris")
        try:
            event_date = event_date.replace("/", "-")
            start_date = datetime.strptime(event_date, "%Y-%m-%d").date()
            start_time_obj = datetime.strptime(event_time, "%H:%M").time()
            logging.debug(f"[GuildEvents - event_create] Parsed dates: start_date={start_date}, start_time={start_time_obj}")
        except Exception as e:
            logging.error("[GuildEvents - event_create] Error parsing date or time.", exc_info=True)
            follow_message = GUILD_EVENTS["event_create"]["date_ko"].get(user_locale,GUILD_EVENTS["event_create"]["date_ko"].get("en-US"))
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        try:
            duration = int(duration)
            start_dt = tz.localize(datetime.combine(start_date, start_time_obj))
            end_dt = start_dt + timedelta(minutes=duration)
            logging.debug(f"[GuildEvents - event_create] Calculated start_dt: {start_dt}, end_dt: {end_dt}")
        except Exception as e:
            logging.error("[GuildEvents - event_create] Error localizing or calculating end date.", exc_info=True)
            follow_message = GUILD_EVENTS["event_create"]["date_ko_2"].get(user_locale,GUILD_EVENTS["event_create"]["date_ko_2"].get("en-US"))
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        description = GUILD_EVENTS["events_infos"]["description"].get(guild_lang, GUILD_EVENTS["events_infos"]["description"].get("en-US"))
        if status.lower() == "confirmed":
            localized_status = GUILD_EVENTS["events_infos"]["status_confirmed"].get(guild_lang, GUILD_EVENTS["events_infos"]["status_confirmed"].get("en-US"))
        else:
            localized_status = GUILD_EVENTS["events_infos"]["status_planned"].get(guild_lang, GUILD_EVENTS["events_infos"]["status_planned"].get("en-US"))
        event_present = GUILD_EVENTS["events_infos"]["present"].get(guild_lang,GUILD_EVENTS["events_infos"]["present"].get("en-US"))
        event_attempt = GUILD_EVENTS["events_infos"]["attempt"].get(guild_lang,GUILD_EVENTS["events_infos"]["attempt"].get("en-US"))
        event_absence = GUILD_EVENTS["events_infos"]["absence"].get(guild_lang,GUILD_EVENTS["events_infos"]["absence"].get("en-US"))
        event_voice_channel = GUILD_EVENTS["events_infos"]["voice_channel"].get(guild_lang,GUILD_EVENTS["events_infos"]["voice_channel"].get("en-US"))
        event_groups = GUILD_EVENTS["events_infos"]["groups"].get(guild_lang,GUILD_EVENTS["events_infos"]["groups"].get("en-US"))
        event_auto_grouping = GUILD_EVENTS["events_infos"]["auto_grouping"].get(guild_lang,GUILD_EVENTS["events_infos"]["auto_grouping"].get("en-US"))
        conference_channel = guild.get_channel(settings.get("war_channel"))
        events_channel = guild.get_channel(settings.get("events_channel"))
        if not events_channel or not conference_channel:
            logging.error(f"[GuildEvents - event_create] Channels not found: events_channel={events_channel}, conference_channel={conference_channel}")
            follow_message = GUILD_EVENTS["event_create"]["no_events_canal"].get(user_locale,GUILD_EVENTS["event_create"]["no_events_canal"].get("en-US"))
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        embed_color = discord.Color.green() if status.lower() == "confirmed" else discord.Color.blue()
        embed = discord.Embed(title=event_name, description=description, color=embed_color)
        embed.add_field(name=GUILD_EVENTS["events_infos"]["date"].get(guild_lang, GUILD_EVENTS["events_infos"]["date"].get("en-US")), value=event_date, inline=True)
        embed.add_field(name=GUILD_EVENTS["events_infos"]["hour"].get(guild_lang, GUILD_EVENTS["events_infos"]["hour"].get("en-US")), value=event_time, inline=True)
        embed.add_field(name=GUILD_EVENTS["events_infos"]["duration"].get(guild_lang, GUILD_EVENTS["events_infos"]["duration"].get("en-US")), value=str(duration), inline=True)
        embed.add_field(name=GUILD_EVENTS["events_infos"]["status"].get(guild_lang, GUILD_EVENTS["events_infos"]["status"].get("en-US")), value=localized_status, inline=True)
        embed.add_field(name=GUILD_EVENTS["events_infos"]["dkp_v"].get(guild_lang, GUILD_EVENTS["events_infos"]["dkp_v"].get("en-US")), value=str(dkp_value), inline=True)
        embed.add_field(name=GUILD_EVENTS["events_infos"]["dkp_i"].get(guild_lang, GUILD_EVENTS["events_infos"]["dkp_i"].get("en-US")), value=str(dkp_ins), inline=True)
        none_text = GUILD_EVENTS["events_infos"]["none"].get(guild_lang, "None")
        embed.add_field(name=f"{event_present} <:_yes_:1340109996666388570> (0)", value=none_text, inline=False)
        embed.add_field(name=f"{event_attempt} <:_attempt_:1340110058692018248> (0)", value=none_text, inline=False)
        embed.add_field(name=f"{event_absence} <:_no_:1340110124521357313> (0)", value=none_text, inline=False)
        conference_link = f"https://discord.com/channels/{guild.id}/{conference_channel.id}"
        embed.add_field(name=event_voice_channel, value=f"[🏹 WAR]({conference_link})", inline=False)
        embed.add_field(name=event_groups, value=event_auto_grouping, inline=False)

        try:
            if status.lower() == "confirmed":
                members_role = settings.get("members_role")
                update_message = GUILD_EVENTS["event_confirm"]["confirmed_notif"].get(
                    user_locale,
                    GUILD_EVENTS["event_confirm"]["confirmed_notif"].get("en-US")
                ).format(role=members_role)
                announcement = await events_channel.send(content=update_message, embed=embed)
            else:
                announcement = await events_channel.send(embed=embed)
            logging.debug(f"[GuildEvents - event_create] Announcement message sent: id={announcement.id} in channel {announcement.channel.id}")
            message_link = f"https://discord.com/channels/{guild.id}/{announcement.channel.id}/{announcement.id}"
            embed.set_footer(text=f"Event ID = {announcement.id}")
            await announcement.edit(embed=embed)
            await announcement.add_reaction("<:_yes_:1340109996666388570>")
            await announcement.add_reaction("<:_attempt_:1340110058692018248>")
            await announcement.add_reaction("<:_no_:1340110124521357313>")
        except Exception as e:
            logging.error(f"[GuildEvents - event_create] Error sending announcement: {e}", exc_info=True)
            follow_message = GUILD_EVENTS["event_create"]["error_event"].get(user_locale,GUILD_EVENTS["event_create"]["error_event"].get("en-US")).format(e=e)
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        try:
            description_scheduled = GUILD_EVENTS["events_infos"]["description_scheduled"].get(guild_lang, GUILD_EVENTS["events_infos"]["description_scheduled"].get("en-US")).format(link=message_link)
            scheduled_event = await guild.create_scheduled_event(
                name=event_name,
                description=description_scheduled,
                start_time=start_dt,
                end_time=end_dt,
                location=conference_channel
            )
            logging.debug(f"[GuildEvents - event_create] Scheduled event created: {scheduled_event.id if scheduled_event else 'None'}")
        except Exception as e:
            logging.error(f"[GuildEvents - event_create] Error creating scheduled event: {e}", exc_info=True)

        try:
            members_role_id = settings.get("members_role")
            if members_role_id:
                role = guild.get_role(int(members_role_id))
                if role:
                    initial_members = [member.id for member in guild.members if role in member.roles]
                else:
                    initial_members = []
            else:
                initial_members = []
        except Exception as e:
            logging.error(f"[GuildEvents - event_create] Error determining initial members: {e}", exc_info=True)
            initial_members = []

        record = {
            "guild_id": guild.id,
            "event_id": announcement.id,
            "game_id": settings.get("guild_game"),
            "name": event_name,
            "event_date": start_dt.strftime("%Y-%m-%d"),
            "event_time": start_dt.strftime("%H:%M:%S"),
            "duration": duration,
            "dkp_value": dkp_value,
            "dkp_ins": dkp_ins,
            "status": status,
            "initial_members": json.dumps(initial_members),
            "registrations": json.dumps({"presence": [], "tentative": [], "absence": []}),
            "actual_presence": json.dumps([])
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
            self.events_data[f"{guild.id}_{announcement.id}"] = record
            logging.info(f"[GuildEvents - event_create] Event saved in DB successfully: {announcement.id}")

            attendance_cog = self.bot.get_cog("GuildAttendance")
            if attendance_cog:
                await attendance_cog.reload_events_cache_for_guild(guild.id)
                logging.debug(f"[GuildEvents - event_create] Reloaded events cache for guild {guild.id} in attendance cog")
            
            follow_message = GUILD_EVENTS["event_create"]["events_created"].get(user_locale,GUILD_EVENTS["event_create"]["events_created"].get("en-US")).format(event_id=announcement.id)
            await ctx.followup.send(follow_message, ephemeral=True)
        except Exception as e:
            logging.error(f"[GuildEvents - event_create] Error saving event in DB for guild {guild.id}: {e}", exc_info=True)
            follow_message = GUILD_EVENTS["event_create"]["event_ko"].get(user_locale,GUILD_EVENTS["event_create"]["event_ko"].get("en-US")).format(e=e)
            await ctx.followup.send(follow_message, ephemeral=True)

    @discord.slash_command(
        name=STATIC_GROUPS["static_create"]["name"]["en-US"],
        description=STATIC_GROUPS["static_create"]["description"]["en-US"],
        name_localizations=STATIC_GROUPS["static_create"]["name"],
        description_localizations=STATIC_GROUPS["static_create"]["description"]
    )
    @commands.has_permissions(manage_roles=True)
    async def static_create(
        self,
        ctx: discord.ApplicationContext,
        group_name: str = discord.Option(
            str,
            description=STATIC_GROUPS["static_create"]["options"]["group_name"]["description"]["en-US"],
            description_localizations=STATIC_GROUPS["static_create"]["options"]["group_name"]["description"],
            min_length=2,
            max_length=50
        )
    ):
        await ctx.defer(ephemeral=True)
        
        guild_id = ctx.guild.id
        leader_id = ctx.author.id
        guild_lang = self.guild_settings.get(guild_id, {}).get("guild_lang", "en-US")

        if guild_id in self.static_groups_cache and group_name in self.static_groups_cache[guild_id]:
            error_msg = STATIC_GROUPS["static_create"]["messages"]["already_exists"].get(guild_lang, STATIC_GROUPS["static_create"]["messages"]["already_exists"].get("en-US")).format(group_name=group_name)
            await ctx.followup.send(error_msg, ephemeral=True)
            return
        
        try:
            query = "INSERT INTO guild_static_groups (guild_id, group_name, leader_id) VALUES (%s, %s, %s)"
            await self.bot.run_db_query(query, (guild_id, group_name, leader_id), commit=True)

            if guild_id not in self.static_groups_cache:
                self.static_groups_cache[guild_id] = {}
            self.static_groups_cache[guild_id][group_name] = {
                "leader_id": leader_id,
                "member_ids": [],
                "member_count": 0
            }
            
            success_msg = STATIC_GROUPS["static_create"]["messages"]["success"].get(guild_lang, STATIC_GROUPS["static_create"]["messages"]["success"].get("en-US")).format(group_name=group_name)
            await ctx.followup.send(success_msg, ephemeral=True)
            logging.info(f"[GuildEvents] Static group '{group_name}' created in guild {guild_id} by {ctx.author}")
            
        except Exception as e:
            error_msg = str(e).lower()
            if "duplicate entry" in error_msg:
                duplicate_msg = STATIC_GROUPS["static_create"]["messages"]["already_exists"].get(guild_lang, STATIC_GROUPS["static_create"]["messages"]["already_exists"].get("en-US")).format(group_name=group_name)
                await ctx.followup.send(duplicate_msg, ephemeral=True)
            else:
                general_error_msg = STATIC_GROUPS["static_create"]["messages"]["error"].get(guild_lang, STATIC_GROUPS["static_create"]["messages"]["error"].get("en-US")).format(error=e)
                await ctx.followup.send(general_error_msg, ephemeral=True)
                logging.error(f"[GuildEvents] Error creating static group: {e}")

    @discord.slash_command(
        name=STATIC_GROUPS["static_add"]["name"]["en-US"],
        description=STATIC_GROUPS["static_add"]["description"]["en-US"],
        name_localizations=STATIC_GROUPS["static_add"]["name"],
        description_localizations=STATIC_GROUPS["static_add"]["description"]
    )
    @commands.has_permissions(manage_roles=True)
    async def static_add(
        self,
        ctx: discord.ApplicationContext,
        group_name: str = discord.Option(
            str, 
            description=STATIC_GROUPS["static_add"]["options"]["group_name"]["description"]["en-US"],
            description_localizations=STATIC_GROUPS["static_add"]["options"]["group_name"]["description"]
        ),
        member: discord.Member = discord.Option(
            discord.Member, 
            description=STATIC_GROUPS["static_add"]["options"]["member"]["description"]["en-US"],
            description_localizations=STATIC_GROUPS["static_add"]["options"]["member"]["description"]
        )
    ):
        await ctx.defer(ephemeral=True)
        
        guild_id = ctx.guild.id
        guild_lang = self.guild_settings.get(guild_id, {}).get("guild_lang", "en-US")

        if guild_id not in self.static_groups_cache or group_name not in self.static_groups_cache[guild_id]:
            error_msg = STATIC_GROUPS["static_add"]["messages"]["group_not_found"].get(guild_lang, STATIC_GROUPS["static_add"]["messages"]["group_not_found"].get("en-US")).format(group_name=group_name)
            await ctx.followup.send(error_msg, ephemeral=True)
            return

        current_members = self.static_groups_cache[guild_id][group_name]["member_ids"]
        if member.id in current_members:
            already_in_msg = STATIC_GROUPS["static_add"]["messages"]["already_in_group"].get(guild_lang, STATIC_GROUPS["static_add"]["messages"]["already_in_group"].get("en-US")).format(member=member.mention, group_name=group_name)
            await ctx.followup.send(already_in_msg, ephemeral=True)
            return

        if len(current_members) >= 6:
            full_group_msg = STATIC_GROUPS["static_add"]["messages"]["group_full"].get(guild_lang, STATIC_GROUPS["static_add"]["messages"]["group_full"].get("en-US")).format(group_name=group_name)
            await ctx.followup.send(full_group_msg, ephemeral=True)
            return
        
        try:
            query = "SELECT id FROM guild_static_groups WHERE guild_id = %s AND group_name = %s AND is_active = TRUE"
            result = await self.bot.run_db_query(query, (guild_id, group_name), fetch_one=True)
            
            if not result:
                not_found_msg = STATIC_GROUPS["static_add"]["messages"]["group_not_found"].get(guild_lang, STATIC_GROUPS["static_add"]["messages"]["group_not_found"].get("en-US")).format(group_name=group_name)
                await ctx.followup.send(not_found_msg, ephemeral=True)
                return

            group_id = result[0]
            position = len(current_members) + 1
            
            query = "INSERT INTO guild_static_members (group_id, member_id, position_order) VALUES (%s, %s, %s)"
            await self.bot.run_db_query(query, (group_id, member.id, position), commit=True)

            self.static_groups_cache[guild_id][group_name]["member_ids"].append(member.id)
            self.static_groups_cache[guild_id][group_name]["member_count"] += 1
            
            member_count = len(self.static_groups_cache[guild_id][group_name]["member_ids"])
            success_msg = STATIC_GROUPS["static_add"]["messages"]["success"].get(guild_lang, STATIC_GROUPS["static_add"]["messages"]["success"].get("en-US")).format(member=member.mention, group_name=group_name, count=member_count)
            await ctx.followup.send(success_msg, ephemeral=True)
            logging.info(f"[GuildEvents] Member {member.id} added to static group '{group_name}' in guild {guild_id}")
            
        except Exception as e:
            error_msg = STATIC_GROUPS["static_add"]["messages"]["error"].get(guild_lang, STATIC_GROUPS["static_add"]["messages"]["error"].get("en-US")).format(error=e)
            await ctx.followup.send(error_msg, ephemeral=True)
            logging.error(f"[GuildEvents] Error adding member to static group: {e}")

    @discord.slash_command(
        name=STATIC_GROUPS["static_remove"]["name"]["en-US"],
        description=STATIC_GROUPS["static_remove"]["description"]["en-US"],
        name_localizations=STATIC_GROUPS["static_remove"]["name"],
        description_localizations=STATIC_GROUPS["static_remove"]["description"]
    )
    @commands.has_permissions(manage_roles=True)
    async def static_remove(
        self,
        ctx: discord.ApplicationContext,
        group_name: str = discord.Option(
            str, 
            description=STATIC_GROUPS["static_remove"]["options"]["group_name"]["description"]["en-US"],
            description_localizations=STATIC_GROUPS["static_remove"]["options"]["group_name"]["description"]
        ),
        member: discord.Member = discord.Option(
            discord.Member, 
            description=STATIC_GROUPS["static_remove"]["options"]["member"]["description"]["en-US"],
            description_localizations=STATIC_GROUPS["static_remove"]["options"]["member"]["description"]
        )
    ):
        await ctx.defer(ephemeral=True)
        
        guild_id = ctx.guild.id
        guild_lang = self.guild_settings.get(guild_id, {}).get("guild_lang", "en-US")

        if guild_id not in self.static_groups_cache or group_name not in self.static_groups_cache[guild_id]:
            error_msg = STATIC_GROUPS["static_remove"]["messages"]["group_not_found"].get(guild_lang, STATIC_GROUPS["static_remove"]["messages"]["group_not_found"].get("en-US")).format(group_name=group_name)
            await ctx.followup.send(error_msg, ephemeral=True)
            return

        current_members = self.static_groups_cache[guild_id][group_name]["member_ids"]
        if member.id not in current_members:
            not_in_group_msg = STATIC_GROUPS["static_remove"]["messages"]["not_in_group"].get(guild_lang, STATIC_GROUPS["static_remove"]["messages"]["not_in_group"].get("en-US")).format(member=member.mention, group_name=group_name)
            await ctx.followup.send(not_in_group_msg, ephemeral=True)
            return
        
        try:
            query = "SELECT id FROM guild_static_groups WHERE guild_id = %s AND group_name = %s AND is_active = TRUE"
            result = await self.bot.run_db_query(query, (guild_id, group_name), fetch_one=True)
            
            if not result:
                not_found_msg = STATIC_GROUPS["static_remove"]["messages"]["group_not_found"].get(guild_lang, STATIC_GROUPS["static_remove"]["messages"]["group_not_found"].get("en-US")).format(group_name=group_name)
                await ctx.followup.send(not_found_msg, ephemeral=True)
                return
            
            group_id = result[0]

            query = "DELETE FROM guild_static_members WHERE group_id = %s AND member_id = %s"
            await self.bot.run_db_query(query, (group_id, member.id), commit=True)

            self.static_groups_cache[guild_id][group_name]["member_ids"].remove(member.id)
            self.static_groups_cache[guild_id][group_name]["member_count"] -= 1
            
            member_count = len(self.static_groups_cache[guild_id][group_name]["member_ids"])
            success_msg = STATIC_GROUPS["static_remove"]["messages"]["success"].get(guild_lang, STATIC_GROUPS["static_remove"]["messages"]["success"].get("en-US")).format(member=member.mention, group_name=group_name, count=member_count)
            await ctx.followup.send(success_msg, ephemeral=True)
            logging.info(f"[GuildEvents] Member {member.id} removed from static group '{group_name}' in guild {guild_id}")
            
        except Exception as e:
            error_msg = STATIC_GROUPS["static_remove"]["messages"]["error"].get(guild_lang, STATIC_GROUPS["static_remove"]["messages"]["error"].get("en-US")).format(error=e)
            await ctx.followup.send(error_msg, ephemeral=True)
            logging.error(f"[GuildEvents] Error removing member from static group: {e}")

    @discord.slash_command(
        name=STATIC_GROUPS.get("preview_groups", {}).get("name", {}).get("en-US", "preview_groups"),
        description=STATIC_GROUPS.get("preview_groups", {}).get("description", {}).get("en-US", "Preview groups before automatic creation for an event"),
        name_localizations=STATIC_GROUPS.get("preview_groups", {}).get("name", {}),
        description_localizations=STATIC_GROUPS.get("preview_groups", {}).get("description", {})
    )
    @commands.has_permissions(manage_guild=True)
    async def preview_groups(
        self,
        ctx: discord.ApplicationContext,
        event_id: str = discord.Option(
            str,
            description=STATIC_GROUPS["preview_groups"]["options"]["event_id"]["description"]["en-US"],
            description_localizations=STATIC_GROUPS["preview_groups"]["options"]["event_id"]["description"]
        )
    ):
        await ctx.defer(ephemeral=True)
        
        guild_id = ctx.guild.id
        settings = self.guild_settings.get(guild_id)
        user_locale = ctx.locale if hasattr(ctx, "locale") and ctx.locale else "en-US"
        guild_lang = settings.get("guild_lang") if settings and settings.get("guild_lang") else "en-US"
        
        if not settings:
            error_msg = STATIC_GROUPS["preview_groups"]["messages"]["no_guild_config"].get(user_locale, STATIC_GROUPS["preview_groups"]["messages"]["no_guild_config"].get("en-US"))
            await ctx.followup.send(error_msg, ephemeral=True)
            return
        
        try:
            event_id_int = int(event_id)
        except ValueError:
            error_msg = STATIC_GROUPS["preview_groups"]["messages"]["invalid_event_id"].get(user_locale, STATIC_GROUPS["preview_groups"]["messages"]["invalid_event_id"].get("en-US"))
            await ctx.followup.send(error_msg, ephemeral=True)
            return

        key = f"{guild_id}_{event_id_int}"
        event = self.events_data.get(key)
        if not event:
            error_msg = STATIC_GROUPS["preview_groups"]["messages"]["event_not_found"].get(user_locale, STATIC_GROUPS["preview_groups"]["messages"]["event_not_found"].get("en-US"))
            await ctx.followup.send(error_msg, ephemeral=True)
            return
        
        registrations = event.get("registrations", {})
        if isinstance(registrations, str):
            try:
                registrations = json.loads(registrations)
            except (json.JSONDecodeError, ValueError) as e:
                logging.warning(f"[GuildEvents] Invalid JSON in registrations, using defaults: {e}")
                registrations = {"presence": [], "tentative": [], "absence": []}
        
        presence_ids = registrations.get("presence", [])
        tentative_ids = registrations.get("tentative", [])
        
        if not presence_ids and not tentative_ids:
            error_msg = STATIC_GROUPS["preview_groups"]["messages"]["no_registrations"].get(user_locale, STATIC_GROUPS["preview_groups"]["messages"]["no_registrations"].get("en-US"))
            await ctx.followup.send(error_msg, ephemeral=True)
            return

        try:
            roster_data = {"members": {}}
            for member in ctx.guild.members:
                md = self.guild_members_cache.get(guild_id, {}).get(member.id, {})
                roster_data["members"][str(member.id)] = {
                    "pseudo": member.display_name,
                    "GS": md.get("GS", "N/A"),
                    "weapons": md.get("weapons", "N/A"),
                    "class": md.get("class", "Unknown"),
                }
        except Exception as exc:
            logging.error(f"[GuildEvents] Error building roster for guild {guild_id}: {exc}")
            error_msg = STATIC_GROUPS["preview_groups"]["messages"]["error_building_roster"].get(user_locale, STATIC_GROUPS["preview_groups"]["messages"]["error_building_roster"].get("en-US")).format(error=exc)
            await ctx.followup.send(error_msg, ephemeral=True)
            return

        try:
            all_groups = self._assign_groups_enhanced(guild_id, presence_ids, tentative_ids, roster_data)
        except Exception as exc:
            logging.error(f"[GuildEvents] Error generating groups for event {event_id}: {exc}")
            error_msg = STATIC_GROUPS["preview_groups"]["messages"]["error_generating_groups"].get(user_locale, STATIC_GROUPS["preview_groups"]["messages"]["error_generating_groups"].get("en-US")).format(error=exc)
            await ctx.followup.send(error_msg, ephemeral=True)
            return
        
        if not all_groups:
            error_msg = STATIC_GROUPS["preview_groups"]["messages"]["no_groups_formed"].get(user_locale, STATIC_GROUPS["preview_groups"]["messages"]["no_groups_formed"].get("en-US"))
            await ctx.followup.send(error_msg, ephemeral=True)
            return

        embeds = []
        total = len(all_groups)

        preview_title = STATIC_GROUPS["preview_groups"]["embeds"]["preview_title"].get(guild_lang, STATIC_GROUPS["preview_groups"]["embeds"]["preview_title"].get("en-US"))
        preview_description = STATIC_GROUPS["preview_groups"]["embeds"]["preview_description"].get(guild_lang, STATIC_GROUPS["preview_groups"]["embeds"]["preview_description"].get("en-US")).format(
            event_name=event['name'],
            event_date=event['event_date'],
            event_time=event['event_time'],
            total=total
        )
        
        header_embed = discord.Embed(
            title=preview_title,
            description=preview_description,
            color=discord.Color.orange()
        )
        embeds.append(header_embed)
        
        for idx, grp in enumerate(all_groups, 1):
            group_title = STATIC_GROUPS["preview_groups"]["embeds"]["group_title"].get(guild_lang, STATIC_GROUPS["preview_groups"]["embeds"]["group_title"].get("en-US")).format(
                index=idx,
                total=total
            )
            
            e = discord.Embed(
                title=group_title,
                color=discord.Color.blue()
            )
            lines = []
            for m in grp:
                cls_emoji = CLASS_EMOJIS.get(m["class"], "")
                weapons_emoji = " ".join(
                    WEAPON_EMOJIS.get(c.strip(), c.strip())
                    for c in m["weapons"].split("/") if c.strip()
                )
                if m.get("tentative"):
                    lines.append(f"{cls_emoji} {weapons_emoji} *{m['pseudo']}* ({m['GS']}) 🔶")
                else:
                    lines.append(f"{cls_emoji} {weapons_emoji} {m['pseudo']} ({m['GS']})")
            
            no_members_text = STATIC_GROUPS["preview_groups"]["embeds"]["no_members"].get(guild_lang, STATIC_GROUPS["preview_groups"]["embeds"]["no_members"].get("en-US"))
            e.description = "\n".join(lines) or no_members_text
            embeds.append(e)

        if len(embeds) > 10:
            embeds = embeds[:10]
            
            truncated_title = STATIC_GROUPS["preview_groups"]["embeds"]["truncated_title"].get(guild_lang, STATIC_GROUPS["preview_groups"]["embeds"]["truncated_title"].get("en-US"))
            truncated_description = STATIC_GROUPS["preview_groups"]["embeds"]["truncated_description"].get(guild_lang, STATIC_GROUPS["preview_groups"]["embeds"]["truncated_description"].get("en-US")).format(total=total)
            
            warning_embed = discord.Embed(
                title=truncated_title,
                description=truncated_description,
                color=discord.Color.yellow()
            )
            embeds.append(warning_embed)
        
        await ctx.followup.send(embeds=embeds, ephemeral=True)
        logging.info(f"[GuildEvents] Groups preview generated for event {event_id} in guild {guild_id}")

    async def update_static_groups_message_for_cron(self, guild_id: int) -> None:
        try:
            await self.update_static_groups_message(guild_id)
        except Exception as e:
            logging.error(f"[GuildEvents] Error in cron static groups update for guild {guild_id}: {e}")

    async def update_static_groups_message(self, guild_id: int) -> bool:
        try:
            guild_settings = self.guild_settings.get(guild_id, {})
            guild_lang = guild_settings.get("guild_lang", "en-US")
            
            query = "SELECT statics_channel, statics_message FROM guild_channels WHERE guild_id = %s"
            result = await self.bot.run_db_query(query, (guild_id,), fetch_one=True)
            
            if not result or not result[0] or not result[1]:
                logging.warning(f"[GuildEvents] No statics channel/message configured for guild {guild_id}")
                return False
                
            channel_id, message_id = result
            
            channel = self.bot.get_channel(channel_id)
            if not channel:
                channel = await self.bot.fetch_channel(channel_id)
            if not channel:
                logging.error(f"[GuildEvents] Statics channel {channel_id} not found for guild {guild_id}")
                return False
                
            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                logging.error(f"[GuildEvents] Statics message {message_id} not found for guild {guild_id}")
                return False
            
            title = STATIC_GROUPS["static_update"]["messages"]["title"].get(guild_lang, STATIC_GROUPS["static_update"]["messages"]["title"].get("en-US"))
            
            embeds = []
            guild_obj = self.bot.get_guild(guild_id)
            
            if not self.static_groups_cache.get(guild_id):
                no_groups_text = STATIC_GROUPS["static_update"]["messages"]["no_groups"].get(guild_lang, STATIC_GROUPS["static_update"]["messages"]["no_groups"].get("en-US"))
                embed = discord.Embed(
                    title=title,
                    description=no_groups_text,
                    color=discord.Color.blue()
                )
                embeds.append(embed)
            else:
                header_embed = discord.Embed(
                    title=title,
                    description=f"*Updated: <t:{int(time.time())}:R>*",
                    color=discord.Color.blue()
                )
                embeds.append(header_embed)
                
                leader_label = STATIC_GROUPS["static_update"]["messages"]["leader"].get(guild_lang, STATIC_GROUPS["static_update"]["messages"]["leader"].get("en-US"))
                members_count_template = STATIC_GROUPS["static_update"]["messages"]["members_count"].get(guild_lang, STATIC_GROUPS["static_update"]["messages"]["members_count"].get("en-US"))
                no_members_text = STATIC_GROUPS["static_update"]["messages"]["no_members"].get(guild_lang, STATIC_GROUPS["static_update"]["messages"]["no_members"].get("en-US"))
                absent_text = STATIC_GROUPS["static_update"]["messages"]["absent"].get(guild_lang, STATIC_GROUPS["static_update"]["messages"]["absent"].get("en-US"))
                
                for group_name, group_data in self.static_groups_cache[guild_id].items():
                    member_ids = group_data["member_ids"]
                    member_count = len(member_ids)
                    leader_id = group_data["leader_id"]
                    
                    leader = guild_obj.get_member(leader_id) if guild_obj else None
                    leader_mention = leader.mention if leader else f"<@{leader_id}> ({absent_text})"

                    formatted_members = self._format_static_group_members(member_ids, guild_obj, absent_text)
                    
                    members_count = members_count_template.format(count=member_count)
                    description = f"{leader_label} {leader_mention}\n{members_count}\n\n"
                    
                    if formatted_members:
                        description += "\n".join(f"• {member_line}" for member_line in formatted_members)
                    else:
                        description += no_members_text
                    
                    group_embed = discord.Embed(
                        title=f"🛡️ {group_name}",
                        description=description,
                        color=discord.Color.gold()
                    )
                    embeds.append(group_embed)
            
            await message.edit(embeds=embeds)
            logging.info(f"[GuildEvents] Static groups message updated for guild {guild_id}")
            return True
            
        except Exception as e:
            logging.error(f"[GuildEvents] Error updating static groups message for guild {guild_id}: {e}")
            return False

    @discord.slash_command(
        name=STATIC_GROUPS["static_update"]["name"]["en-US"],
        description=STATIC_GROUPS["static_update"]["description"]["en-US"],
        name_localizations=STATIC_GROUPS["static_update"]["name"],
        description_localizations=STATIC_GROUPS["static_update"]["description"]
    )
    @commands.has_permissions(manage_roles=True)
    async def static_update(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        
        guild_id = ctx.guild.id
        guild_lang = self.guild_settings.get(guild_id, {}).get("guild_lang", "en-US")
        
        query = "SELECT statics_channel, statics_message FROM guild_channels WHERE guild_id = %s"
        result = await self.bot.run_db_query(query, (guild_id,), fetch_one=True)
        
        if not result or not result[0] or not result[1]:
            no_channel_msg = STATIC_GROUPS["static_update"]["messages"]["no_channel"].get(guild_lang, STATIC_GROUPS["static_update"]["messages"]["no_channel"].get("en-US"))
            await ctx.followup.send(no_channel_msg, ephemeral=True)
            return
        
        success = await self.update_static_groups_message(guild_id)
        
        if success:
            success_msg = STATIC_GROUPS["static_update"]["messages"]["success"].get(guild_lang, STATIC_GROUPS["static_update"]["messages"]["success"].get("en-US"))
            await ctx.followup.send(success_msg, ephemeral=True)
        else:
            error_msg = STATIC_GROUPS["static_update"]["messages"]["no_message"].get(guild_lang, STATIC_GROUPS["static_update"]["messages"]["no_message"].get("en-US"))
            await ctx.followup.send(error_msg, ephemeral=True)

    @discord.slash_command(
        name=STATIC_GROUPS["static_delete"]["name"]["en-US"],
        description=STATIC_GROUPS["static_delete"]["description"]["en-US"],
        name_localizations=STATIC_GROUPS["static_delete"]["name"],
        description_localizations=STATIC_GROUPS["static_delete"]["description"]
    )
    @commands.has_permissions(manage_roles=True)
    async def static_delete(
        self,
        ctx: discord.ApplicationContext,
        group_name: str = discord.Option(
            str, 
            description=STATIC_GROUPS["static_delete"]["options"]["group_name"]["description"]["en-US"],
            description_localizations=STATIC_GROUPS["static_delete"]["options"]["group_name"]["description"]
        )
    ):
        await ctx.defer(ephemeral=True)
        
        guild_id = ctx.guild.id
        guild_lang = self.guild_settings.get(guild_id, {}).get("guild_lang", "en-US")

        if guild_id not in self.static_groups_cache or group_name not in self.static_groups_cache[guild_id]:
            error_msg = STATIC_GROUPS["static_delete"]["messages"]["not_found"].get(guild_lang, STATIC_GROUPS["static_delete"]["messages"]["not_found"].get("en-US")).format(group_name=group_name)
            await ctx.followup.send(error_msg, ephemeral=True)
            return
        
        try:
            query = "UPDATE guild_static_groups SET is_active = FALSE WHERE guild_id = %s AND group_name = %s"
            await self.bot.run_db_query(query, (guild_id, group_name), commit=True)

            del self.static_groups_cache[guild_id][group_name]
            
            success_msg = STATIC_GROUPS["static_delete"]["messages"]["success"].get(guild_lang, STATIC_GROUPS["static_delete"]["messages"]["success"].get("en-US")).format(group_name=group_name)
            await ctx.followup.send(success_msg, ephemeral=True)
            logging.info(f"[GuildEvents] Static group '{group_name}' deleted in guild {guild_id} by {ctx.author}")
            
        except Exception as e:
            error_msg = STATIC_GROUPS["static_delete"]["messages"]["error"].get(guild_lang, STATIC_GROUPS["static_delete"]["messages"]["error"].get("en-US")).format(error=e)
            await ctx.followup.send(error_msg, ephemeral=True)
            logging.error(f"[GuildEvents] Error deleting static group: {e}")

    @commands.Cog.listener() 
    async def on_ready(self):
        asyncio.create_task(self.load_guild_settings())
        asyncio.create_task(self.load_events_calendar())
        asyncio.create_task(self.load_events_data())
        asyncio.create_task(self.load_guild_members())
        asyncio.create_task(self.load_static_groups_cache())
        asyncio.create_task(self.load_ideal_staff_cache())
        logging.debug("[GuildEvents] Cache loading tasks started in on_ready.")

def setup(bot: discord.Bot):
    bot.add_cog(GuildEvents(bot))
