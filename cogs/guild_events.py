import discord
from discord import NotFound, HTTPException
import logging
import asyncio
import pytz
from discord.ext import commands, tasks
from datetime import datetime, timedelta, time as dt_time
import time
from translation import translations as global_translations
from typing import Optional
import json
import math

GUILD_EVENTS = global_translations.get("guild_events", {})

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
        SELECT game_id, day, time, duree, dkp_value, dkp_ins, week, name
        FROM events_calendar;
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.events_calendar = {}
            for row in rows:
                game_id, day, time_str, duree, dkp_value, dkp_ins, week, name = row
                game_id = int(game_id)
                event = {
                    "day": day,
                    "time": time_str,
                    "duree": duree,
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
            logging.debug(f"[GuildEvents] Events data loaded: {self.events_data}")
        except Exception as e:
            logging.error(f"[GuildEvents] Error loading events data: {e}", exc_info=True)

    async def load_guild_members(self) -> None:
        query = "SELECT guild_id, member_id, classe, GS, armes FROM guild_members"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.guild_members_cache = {}
            for row in rows:
                guild_id, member_id, member_class, gs, armes = row
                guild_id = int(guild_id)
                member_id = int(member_id)
                if guild_id not in self.guild_members_cache:
                    self.guild_members_cache[guild_id] = {}
                self.guild_members_cache[guild_id][member_id] = {
                    "classe": member_class,
                    "GS": gs if gs is not None else "N/A",
                    "armes": armes if armes is not None else "N/A"
                }
            logging.debug(f"[GuildEvents] Guild members cache loaded: {self.guild_members_cache}")
        except Exception as e:
            logging.error(f"[GuildEvents] Error loading guild members cache: {e}", exc_info=True)

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
                    duration_minutes = int(cal_event.get("duree", 60))
                except:
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

                status = GUILD_EVENTS["events_infos"]["status_planified"].get(guild_lang,GUILD_EVENTS["events_infos"]["status_planified"].get("en-US"))
                status_db = GUILD_EVENTS["events_infos"]["status_planified"].get("en-US")
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
                    embed.add_field(name=f"{event_present} <:_yes_:1340109996666388570> (0)", value="Aucun", inline=False)
                    embed.add_field(name=f"{event_attempt} <:_attempt_:1340110058692018248> (0)", value="Aucun", inline=False)
                    embed.add_field(name=f"{event_absence} <:_no_:1340110124521357313> (0)", value="Aucun", inline=False)
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
        except Exception as e:
            logging.error(f"[GuildEvents] Error updating event {event_id} status for guild {guild.id}: {e}", exc_info=True)

        events_channel = guild.get_channel(settings.get("events_channel"))
        if not events_channel:
            follow_message = GUILD_EVENTS["event_confirm"]["no_events_canal"].get(user_locale,GUILD_EVENTS["event_confirm"]["no_events_canal"].get("en-US"))
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        try:
            message = await events_channel.fetch_message(event_id)
        except Exception as e:
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
            await message.edit(embed=embed)
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
                    logging.error(f"[GuildEvents - on_raw_reaction_add] Erreur lors du décodage de registrations: {e}")
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
            .get(guild_lang, GUILD_EVENTS["events_infos"]["none"]["en-US"]) \
            .lower()

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
                        try:
                            delete_query = "DELETE FROM events_data WHERE guild_id = %s AND event_id = %s"
                            await self.bot.run_db_query(delete_query, (ev["guild_id"], ev["event_id"]), commit=True)
                            logging.debug(f"[GuildEvents CRON] Record deleted in DB for event {ev['event_id']}")
                        except Exception as e:
                            logging.error(f"[GuildEvents CRON] Error deleting event {ev['event_id']} in DB: {e}", exc_info=True)
                    else:
                        logging.debug(f"[GuildEvents CRON] Event {ev['event_id']} ended but status is not 'Canceled' => record kept.")

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
                regs_obj = event.get("registrations", {})
                if isinstance(regs_obj, str):
                    try:
                        regs_obj = json.loads(regs_obj)
                    except Exception as e:
                        logging.error(f"[GuildEvents - event_reminder_cron] Error parsing 'registrations' for event {event['event_id']}: {e}", exc_info=True)
                        regs_obj = {"presence": [], "tentative": [], "absence": []}
                regs = set(regs_obj.get("presence", [])) | set(regs_obj.get("tentative", [])) | set(regs_obj.get("absence", []))
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
                to_remind = list(updated_initial - regs)
                reminded = []
                event_link = f"https://discord.com/channels/{guild.id}/{events_channel.id}/{event['event_id']}"
                dm_template = GUILD_EVENTS.get("event_reminder", {}).get("dm_message", {}).get(guild_locale,GUILD_EVENTS.get("event_reminder", {}).get("dm_message", {}).get("en-US"))
                logging.debug(f"[GuildEvents - event_reminder_cron] For event {event['event_id']}, initial members: {initial}, registered: {regs}, to remind: {to_remind}")
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

                if timedelta(0) <= (start_dt - now) <= timedelta(minutes=15) and ev.get("status", "").strip().lower() in ["confirmed", "planned"]:
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
                            update_query = "UPDATE events_data SET status = %s WHERE guild_id = %s AND event_id = %s"
                            await self.bot.run_db_query(update_query, (closed_db, guild_id, ev["event_id"]), commit=True)
                            ev["status"] = closed_db
                            logging.info(f"[GuildEvents CRON] Event {ev['event_id']} marked as Closed.")
                            await msg.clear_reactions()
                            logging.info(f"[GuildEvents CRON] Reactions cleared for event {ev['event_id']}.")
                            await self.create_groups(guild_id, ev["event_id"])
                        except Exception as e:
                            logging.error(f"[GuildEvents CRON] Error updating event {ev['event_id']}: {e}", exc_info=True)
        logging.info("[GuildEvents CRON] Finished event_close_cron.")

    @staticmethod
    def group_members_by_class(member_ids, roster_data):
        logging.debug("[Guild_Events - GroupsMembersByClass] Building class buckets…")
        classes = {c: [] for c in ("Tank", "Melee DPS", "Ranged DPS",
                                "Healer", "Flanker")}
        missing = []

        for mid in member_ids:
            try:
                info = roster_data["membres"][str(mid)]
            except KeyError:
                logging.warning(f"[Guild_Events - GroupsMembersByClass] Member ID {mid} not found in roster.")
                missing.append(mid)
                continue

            pseudo = info.get("pseudo", "Unknown")
            gs     = info.get("GS", "N/A")
            armes  = info.get("armes", "")
            mclass = info.get("classe", "Unknown")

            emojis = " ".join(
                WEAPON_EMOJIS.get(c.strip(), c.strip())
                for c in armes.split("/") if c.strip()
            ) or "N/A"

            classes.setdefault(mclass, []).append(f"{pseudo} {emojis} - GS: {gs}")

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

    def _assign_groups(self, presence_ids: list[int], tentative_ids: list[int], roster_data: dict) -> list[list[dict]]:
        logging.debug("[Guild_Events - AssignGroups] Starting group assignment…")

        buckets = {c: [] for c in ("Tank", "Healer",
                                   "Melee DPS", "Ranged DPS", "Flanker")}

        def _push(uid: int, tentative: bool):
            info = roster_data["membres"].get(str(uid))
            if not info:
                logging.warning(f"[Guild_Events - AssignGroups] UID {uid} missing from roster, skipped.")
                return
            try:
                buckets[info["classe"]].append({**info, "tentative": tentative})
            except KeyError:
                logging.error(f"[Guild_Events - AssignGroups] Unknown class '{info.get('classe')}' for UID {uid}.")

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
                classes = [m["classe"] for m in g]
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

        regs = event.get("registrations", {})
        if isinstance(regs, str):
            try:
                regs = json.loads(regs)
            except:
                regs = {"presence": [], "tentative": [], "absence": []}
        presence_ids  = regs.get("presence", [])
        tentative_ids = regs.get("tentative", [])

        presence_count  = len(presence_ids)
        tentative_count = len(tentative_ids)
        event_link = f"https://discord.com/channels/{guild.id}/{events_channel.id}/{event_id}"
        header = (
            f"{mention_role}\n\n"
            f"**__Évènement :__ {event['name']}**\n"
            f"{event['event_date']} à {event['event_time']}\n"
            f"Présents : {presence_count}\nTentatives : {tentative_count}\n\n"
            f"[Voir l'Évènement et les inscriptions]({event_link})\n\n"
            f"Groupes ci-dessous\n"
        )

        try:
            roster_data = {"membres": {}}
            for member in guild.members:
                md = self.guild_members_cache.get(guild_id, {}).get(member.id, {})
                roster_data["membres"][str(member.id)] = {
                    "pseudo": member.display_name,
                    "GS": md.get("GS", "N/A"),
                    "armes": md.get("armes", "N/A"),
                    "classe": md.get("classe", "Unknown"),
                }
        except Exception as exc:
            logging.exception("[Guild_Events - CreateGroups] Failed to build roster.", exc_info=exc)
            return

        try:
            all_groups = self._assign_groups(presence_ids, tentative_ids, roster_data)
        except Exception as exc:
            logging.exception("[Guild_Events - CreateGroups] _assign_groups crashed.", exc_info=exc)
            return

        try:
            embeds = []
            total = len(all_groups)
            for idx, grp in enumerate(all_groups, 1):
                e = discord.Embed(title=f"Groupe {idx} / {total}",
                                color=discord.Color.blue())
                lines = []
                for m in grp:
                    cls_emoji = CLASS_EMOJIS.get(m["classe"], "")
                    armes_emoji = " ".join(
                        WEAPON_EMOJIS.get(c.strip(), c.strip())
                        for c in m["armes"].split("/") if c.strip()
                    )
                    if m.get("tentative"):
                        lines.append(f"{cls_emoji} {armes_emoji} *{m['pseudo']}* ({m['GS']}) 🔶")
                    else:
                        lines.append(f"{cls_emoji} {armes_emoji} {m['pseudo']} ({m['GS']})")
                e.description = "\n".join(lines) or "Aucun membre"
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
            localized_status = GUILD_EVENTS["events_infos"]["status_planified"].get(guild_lang, GUILD_EVENTS["events_infos"]["status_planified"].get("en-US"))
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
        embed.add_field(name=f"{event_present} <:_yes_:1340109996666388570> (0)", value="Aucun", inline=False)
        embed.add_field(name=f"{event_attempt} <:_attempt_:1340110058692018248> (0)", value="Aucun", inline=False)
        embed.add_field(name=f"{event_absence} <:_no_:1340110124521357313> (0)", value="Aucun", inline=False)
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
            logging.debug(f"[GuildEvents - event_create] Message d'annonce envoyé: id={announcement.id} dans le salon {announcement.channel.id}")
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
            follow_message = GUILD_EVENTS["event_create"]["events_created"].get(user_locale,GUILD_EVENTS["event_create"]["events_created"].get("en-US")).format(event_id=announcement.id)
            await ctx.followup.send(follow_message, ephemeral=True)
        except Exception as e:
            logging.error(f"[GuildEvents - event_create] Error saving event in DB for guild {guild.id}: {e}", exc_info=True)
            follow_message = GUILD_EVENTS["event_create"]["event_ko"].get(user_locale,GUILD_EVENTS["event_create"]["event_ko"].get("en-US")).format(e=e)
            await ctx.followup.send(follow_message, ephemeral=True)

    @commands.Cog.listener() 
    async def on_ready(self):
        asyncio.create_task(self.load_guild_settings())
        asyncio.create_task(self.load_events_calendar())
        asyncio.create_task(self.load_events_data())
        asyncio.create_task(self.load_guild_members())
        logging.debug("[GuildEvents] Cache loading tasks started in on_ready.")

def setup(bot: discord.Bot):
    bot.add_cog(GuildEvents(bot))
