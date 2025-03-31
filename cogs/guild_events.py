import discord
import logging
import asyncio
import pytz
from discord.ext import commands, tasks
from datetime import datetime, timedelta, time as dt_time
import time
from translation import translations as global_translations
from typing import Optional
import json
import random

GUILD_EVENTS = global_translations.get("guild_events", {})

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
            logging.debug(f"[GuildEvents] Chargement réussi : {self.guild_settings}")
        except Exception as e:
            logging.error(f"[GuildEvents] Erreur lors du chargement : {e}", exc_info=True)

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
            logging.debug(f"[GuildEvents] Calendrier des événements chargé : {self.events_calendar}")
        except Exception as e:
            logging.error(f"[GuildEvents] Erreur lors du chargement du calendrier des événements : {e}", exc_info=True)

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
            logging.error(f"[GuildEvents] Error loading events_data: {e}", exc_info=True)

    async def load_guild_members(self) -> None:
        query = "SELECT guild_id, member_id, classe FROM guild_members"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.guild_members_cache = {}
            for row in rows:
                guild_id, member_id, member_class = row
                guild_id = int(guild_id)
                member_id = int(member_id)
                if guild_id not in self.guild_members_cache:
                    self.guild_members_cache[guild_id] = {}
                self.guild_members_cache[guild_id][member_id] = member_class
            logging.debug(f"Guild members cache loaded: {self.guild_members_cache}")
        except Exception as e:
            logging.error("Erreur lors du chargement du cache des membres de guilde", exc_info=True)

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

        jours = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6
        }
        day_key = day_name.lower()
        if day_key not in jours:
            logging.error(f"Jour invalide: {day_name}")
            return None
        target_weekday = jours[day_key]

        now = datetime.now(tz)
        current_weekday = now.weekday()
        days_ahead = target_weekday - current_weekday
        if days_ahead < 0 or (days_ahead == 0 and now.strftime("%H:%M") >= event_time_str):
            days_ahead += 7
        event_date = now.date() + timedelta(days=days_ahead)

        if tomorrow_only:
            tomorrow = now.date() + timedelta(days=1)
            if event_date != tomorrow:
                return None

        try:
            hour, minute = map(int, event_time_str.split(":"))
        except Exception as e:
            logging.error(f"Erreur de parsing de l'heure '{event_time_str}': {e}")
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
                        logging.info(f"[GuildEvents] Événements créés pour la guilde premium {guild_id}.")
                    except Exception as e:
                        logging.exception(f"[GuildEvents] Erreur lors de la création d'événements pour la guilde {guild_id} : {e}")
                else:
                    logging.error(f"❌ [GuildEvents] Guilde {guild_id} introuvable.")
        await self.load_events_data()

    async def create_events_for_guild(self, guild: discord.Guild) -> None:
        guild_id = guild.id

        settings = self.guild_settings.get(guild_id)
        if not settings:
            logging.error(f"[GuildEvents] Aucune configuration pour la guilde {guild_id}.")
            return

        guild_lang = settings.get("guild_lang")
        events_channel = guild.get_channel(settings.get("events_channel"))
        conference_channel = guild.get_channel(settings.get("war_channel"))
        if not events_channel:
            logging.error(f"[GuildEvents] Canal des événements introuvable pour la guilde {guild_id}.")
            return
        if not conference_channel:
            logging.error(f"[GuildEvents] Canal de conférence introuvable pour la guilde {guild_id}.")
            return

        try:
            game_id = int(settings.get("guild_game"))
        except Exception as e:
            logging.error(f"[GuildEvents] Erreur lors de la conversion du guild_game pour la guilde {guild_id}: {e}")
            return

        calendar = self.events_calendar.get(game_id, [])
        if not calendar:
            logging.info(f"[GuildEvents] Aucun événement défini dans le calendrier pour le game_id {game_id}.")
            return

        tz = pytz.timezone("Europe/Paris")
        for cal_event in calendar:
            day = cal_event.get("day")
            event_time_str = cal_event.get("time", "21:00")
            start_time = self.get_next_date_for_day(day, event_time_str, tz, tomorrow_only=True)
            if not start_time:
                logging.error(f"[GuildEvents] Jour invalide: {day} pour la guilde {guild_id}.")
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
                    logging.info(f"[GuildEvents] L'événement {cal_event.get('name')} n'est pas prévu cette semaine (pair).")
                    continue
                elif week_setting == "even" and week_number % 2 != 0:
                    logging.info(f"[GuildEvents] L'événement {cal_event.get('name')} n'est pas prévu cette semaine (impair).")
                    continue

            event_key = cal_event.get("name")
            event_info = GUILD_EVENTS["events_infos"].get(event_key)
            if event_info:
                event_name = event_info.get(guild_lang, event_info.get("en-US"))
            else:
                event_name = event_key

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

            statut = GUILD_EVENTS["events_infos"]["status_planified"].get(guild_lang,GUILD_EVENTS["events_infos"]["status_planified"].get("en-US"))
            statut_db = GUILD_EVENTS["events_infos"]["status_planified"].get("en-US")
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
                embed.add_field(name=event_status, value=statut, inline=True)
                embed.add_field(name=event_dkp_v, value=str(cal_event.get("dkp_value", 0)), inline=True)
                embed.add_field(name=event_dkp_i, value=str(cal_event.get("dkp_ins", 0)), inline=True)
                embed.add_field(name=f"{event_present} <:_yes_:1340109996666388570> (0)", value="Aucun", inline=False)
                embed.add_field(name=f"{event_attempt} <:_attempt_:1340110058692018248> (0)", value="Aucun", inline=False)
                embed.add_field(name=f"{event_absence} <:_no_:1340110124521357313> (0)", value="Aucun", inline=False)
                conference_link = f"https://discord.com/channels/{guild.id}/{conference_channel.id}"
                embed.add_field(name=event_voice_channel, value=f"[🏹 WAR]({conference_link})", inline=False)
                embed.add_field(name=event_groups, value=event_auto_grouping, inline=False)
                announcement = await events_channel.send(embed=embed)
                message_link = f"https://discord.com/channels/{guild.id}/{announcement.channel.id}/{announcement.id}"
                embed.set_footer(text=f"Event ID = {announcement.id}")
                await announcement.edit(embed=embed)
                await announcement.add_reaction("<:_yes_:1340109996666388570>")
                await announcement.add_reaction("<:_attempt_:1340110058692018248>")
                await announcement.add_reaction("<:_no_:1340110124521357313>")
            except Exception as e:
                logging.error(f"[GuildEvents] Erreur lors de l'envoi du message d'annonce: {e}")
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
            except discord.Forbidden:
                logging.error(f"[GuildEvents] Permissions insuffisantes pour créer l'événement dans la guilde {guild_id}.")
                continue
            except discord.HTTPException as e:
                logging.error(f"[GuildEvents] Erreur HTTP lors de la création de l'événement dans la guilde {guild_id}: {e}")
                continue

            members_role_id = settings.get("members_role")
            if members_role_id:
                role = guild.get_role(int(members_role_id))
                if role:
                    # Filtrer les membres possédant le rôle
                    initial_members = [member.id for member in guild.members if role in member.roles]
                else:
                    initial_members = []
            else:
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
                "status": statut_db,
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
                await self.bot.run_db_query(query, record)
                logging.info(f"[GuildEvents] Enregistrement de l'événement en BDD réussi : {announcement.id}")
            except Exception as e:
                logging.error(f"[GuildEvents] Erreur lors de l'enregistrement en BDD pour la guilde {guild_id} : {e}")

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

        query = "UPDATE events_data SET status = ? WHERE guild_id = ? AND event_id = ?"
        try:
            await self.bot.run_db_query(query, ("Confirmed", guild.id, event_id), commit=True)
            target_event["status"] = "Confirmed"
            logging.info(f"[GuildEvents] Statut de l'événement {event_id} mis à jour à 'Confirmed' pour la guilde {guild.id}.")
        except Exception as e:
            logging.error(f"[GuildEvents] Erreur lors de la mise à jour du statut de l'événement {event_id} pour la guilde {guild.id} : {e}", exc_info=True)

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
        statut_localized = GUILD_EVENTS["event_confirm"]["confirmed"].get(guild_locale,GUILD_EVENTS["event_confirm"]["confirmed"].get("en-US"))

        new_fields = []
        statut_found = False
        for field in new_embed.fields:
            if field.name.lower() == status_key:
                new_fields.append({"name": status_name, "value": statut_localized, "inline": field.inline})
                statut_found = True
            else:
                new_fields.append({"name": field.name, "value": field.value, "inline": field.inline})
        if not statut_found:
            new_fields.append({"name": status_name, "value": statut_localized, "inline": False})
        new_embed.clear_fields()
        for field in new_fields:
            new_embed.add_field(name=field["name"], value=field["value"], inline=field["inline"])

        try:
            members_role = settings.get("members_role")
            update_message = GUILD_EVENTS["event_confirm"]["confirmed_notif"].get(user_locale,GUILD_EVENTS["event_confirm"]["confirmed_notif"].get("en-US")).format(role=members_role)
            await message.edit(
                content=update_message,
                embed=new_embed
            )
            follow_message = GUILD_EVENTS["event_confirm"]["event_updated"].get(user_locale,GUILD_EVENTS["event_confirm"]["event_updated"].get("en-US")).format(event_id=event_id)
            await ctx.followup.send(follow_message, ephemeral=True)
        except Exception as e:
            follow_message = GUILD_EVENTS["event_confirm"]["event_embed_ko"].get(user_locale,GUILD_EVENTS["event_confirm"]["event_embed_ko"].get("en-US")).format(e=e)
            await ctx.followup.send(follow_message, ephemeral=True)
            return

    @event_confirm.error
    async def event_confirm_error(self, ctx, error):
        logging.error(f"❌ [GuildEvents] event_confirm: {error}")
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

        query = "UPDATE events_data SET status = ? WHERE guild_id = ? AND event_id = ?"
        try:
            await self.bot.run_db_query(query, ("Canceled", guild.id, event_id_int), commit=True)
            target_event["status"] = "Canceled"
            logging.info(f"[GuildEvents] Statut de l'événement {event_id_int} mis à jour à 'Canceled' pour la guilde {guild.id}.")
        except Exception as e:
            logging.error(f"[GuildEvents] Erreur lors de la mise à jour du statut de l'événement {event_id_int} pour la guilde {guild.id} : {e}", exc_info=True)

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
            logging.error(f"❌ [ERROR] event_cancel (clear_reactions): {e}")

        if not message.embeds:
            follow_message = GUILD_EVENTS["event_cancel"]["no_events_message_embed"].get(user_locale,GUILD_EVENTS["event_cancel"]["no_events_message_embed"].get("en-US"))
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        embed = message.embeds[0]
        embed.color = discord.Color.red()

        status_key   = GUILD_EVENTS["events_infos"]["status"].get(guild_locale, GUILD_EVENTS["events_infos"]["status"].get("en-US")).lower()
        status_name  = GUILD_EVENTS["events_infos"]["status"].get(guild_locale, GUILD_EVENTS["events_infos"]["status"].get("en-US"))
        statut_localized = GUILD_EVENTS["event_cancel"]["canceled"].get(guild_locale,GUILD_EVENTS["event_cancel"]["canceled"].get("en-US"))
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
                new_fields.append({"name": status_name, "value": statut_localized, "inline": False})
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
        logging.error(f"❌ [GuildEvents] event_cancel: {error}")
        error_msg = GUILD_EVENTS["event_cancel"]["event_embed_ko"].get(ctx.locale,GUILD_EVENTS["event_cancel"]["event_embed_ko"].get("en-US")).format(error=error)
        await ctx.send(error_msg, delete_after=10)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        logging.debug(f"[GuildEvents - on_raw_reaction_add] Début avec payload: {payload}")
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            logging.debug("[GuildEvents - on_raw_reaction_add] Guilde non trouvée.")
            return

        settings = self.guild_settings.get(guild.id)
        if not settings:
            logging.debug("[GuildEvents - on_raw_reaction_add] Settings non trouvées pour cette guilde.")
            return

        events_channel_id = settings.get("events_channel")
        if payload.channel_id != events_channel_id:
            logging.debug("[GuildEvents - on_raw_reaction_add] Le channel ID ne correspond pas.")
            return

        valid_emojis = [
            "<:_yes_:1340109996666388570>",
            "<:_attempt_:1340110058692018248>",
            "<:_no_:1340110124521357313>"
        ]
        if str(payload.emoji) not in valid_emojis:
            logging.debug(f"[GuildEvents - on_raw_reaction_add] Emoji non valide: {payload.emoji}")
            return

        channel = guild.get_channel(payload.channel_id)
        try:
            message = await channel.fetch_message(payload.message_id)
        except Exception as e:
            logging.error(f"❌ [GuildEvents - on_raw_reaction_add] Erreur lors de la récupération du message : {e}")
            return

        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            logging.debug("[GuildEvents - on_raw_reaction_add] Membre non trouvé ou est un bot.")
            return

        for emoji in valid_emojis:
            if emoji != str(payload.emoji):
                try:
                    key = (message.id, member.id, emoji)
                    self.ignore_removals[key] = time.time()
                    await message.remove_reaction(emoji, member)
                except Exception as e:
                    logging.error(f"❌ [GuildEvents - on_raw_reaction_add] Erreur lors de la suppression de la réaction {emoji} pour {member}: {e}")

        async with self.json_lock:
            target_event = None
            for ev in self.events_data.values():
                if ev.get("event_id") == message.id:
                    target_event = ev
                    break
            if not target_event:
                logging.debug("[GuildEvents - on_raw_reaction_add] Aucun événement trouvé pour ce message.")
                return
            
            logging.debug(f"[GuildEvents - on_raw_reaction_add] Événement trouvé: {target_event}")

            if isinstance(target_event.get("registrations"), str):
                try:
                    target_event["registrations"] = json.loads(target_event["registrations"])
                    logging.debug("[GuildEvents - on_raw_reaction_add] Registrations décodées depuis JSON.")
                except Exception as e:
                    logging.error(f"[GuildEvents - on_raw_reaction_add] Erreur lors du décodage de registrations: {e}")
                    target_event["registrations"] = {"presence": [], "tentative": [], "absence": []}

            logging.debug(f"[GuildEvents - on_raw_reaction_add] Registrations AVANT update: {target_event['registrations']}")

            for key in ["presence", "tentative", "absence"]:
                if payload.user_id in target_event["registrations"].get(key, []):
                    target_event["registrations"][key].remove(payload.user_id)
            if str(payload.emoji) == "<:_yes_:1340109996666388570>":
                target_event["registrations"]["presence"].append(payload.user_id)
            elif str(payload.emoji) == "<:_attempt_:1340110058692018248>":
                target_event["registrations"]["tentative"].append(payload.user_id)
            elif str(payload.emoji) == "<:_no_:1340110124521357313>":
                target_event["registrations"]["absence"].append(payload.user_id)

            logging.debug(f"[on_raw_reaGuildEvents - on_raw_reaction_addction_add] Registrations APRÈS update: {target_event['registrations']}")

        await self.update_event_embed(message, target_event)

        try:
            new_registrations = json.dumps(target_event["registrations"])
            update_query = "UPDATE events_data SET registrations = ? WHERE guild_id = ? AND event_id = ?"
            await self.bot.run_db_query(update_query, (new_registrations, target_event["guild_id"], target_event["event_id"]), commit=True)
            logging.debug("[GuildEvents - on_raw_reaction_addction_add] MàJ BDD réussie pour registrations.")
        except Exception as e:
            logging.error(f"[GuildEvents - on_raw_reaction_addction_add] Erreur lors de la mise à jour en BDD de registrations : {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        key = (payload.message_id, payload.user_id, str(payload.emoji))
        if key in self.ignore_removals:
            ts = self.ignore_removals.pop(key)
            if time.time() - ts < 3:
                logging.debug(f"[GuildEvent - on_raw_reaction_remove] Ignorer retrait automatique pour key {key}")
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
            logging.error(f"❌ [GuildEvent - on_raw_reaction_remove] Erreur lors de la récupération du message : {e}")
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
                logging.debug(f"[GuildEvents - on_raw_reaction_remove] Ignorer le retrait car l'événement {target_event['event_id']} est Closed.")
                return

            for key in ["presence", "tentative", "absence"]:
                if payload.user_id in target_event["registrations"].get(key, []):
                    target_event["registrations"][key].remove(payload.user_id)

        await self.update_event_embed(message, target_event)

        try:
            new_registrations = json.dumps(target_event["registrations"])
            update_query = "UPDATE events_data SET registrations = ? WHERE guild_id = ? AND event_id = ?"
            await self.bot.run_db_query(update_query, (new_registrations, target_event["guild_id"], target_event["event_id"]), commit=True)
            logging.debug("[GuildEvents - on_raw_reaction_addction_add] MàJ BDD réussie pour registrations.")
        except Exception as e:
            logging.error(f"[GuildEvents - on_raw_reaction_addction_add] Erreur lors de la mise à jour en BDD de registrations : {e}")

    async def update_event_embed(self, message, event_record):
        logging.debug("✅ [GuildEvent] Début de MAJ de l'embed !")
        guild = self.bot.get_guild(message.guild.id)
        def format_list(id_list):
            membres = [guild.get_member(uid) for uid in id_list if guild.get_member(uid)]
            return ", ".join(m.mention for m in membres) if membres else "Aucun"

        presence_ids = event_record["registrations"].get("presence", [])
        tentative_ids = event_record["registrations"].get("tentative", [])
        absence_ids = event_record["registrations"].get("absence", [])
        
        presence_str = format_list(presence_ids)
        tentative_str = format_list(tentative_ids)
        absence_str = format_list(absence_ids)

        if not message.embeds:
            logging.error("❌ [GuildEvent] Aucun embed trouvé dans le message.")
            return
        embed = message.embeds[0]

        new_fields = []
        for field in embed.fields:
            lower_name = field.name.lower()
            if lower_name.startswith("présent"):
                new_name = f"Présent <:_yes_:1340109996666388570> ({len(presence_ids)})"
                new_fields.append((new_name, presence_str, field.inline))
            elif lower_name.startswith("tentative"):
                new_name = f"Tentative <:_attempt_:1340110058692018248> ({len(tentative_ids)})"
                new_fields.append((new_name, tentative_str, field.inline))
            elif lower_name.startswith("absence"):
                new_name = f"Absence <:_no_:1340110124521357313> ({len(absence_ids)})"
                new_fields.append((new_name, absence_str, field.inline))
            else:
                new_fields.append((field.name, field.value, field.inline))

        embed.clear_fields()
        for name, value, inline in new_fields:
            embed.add_field(name=name, value=value, inline=inline)

        try:
            await message.edit(embed=embed)
            logging.debug("✅ [GuildEvent] Mise à jour de l'embed réussie !")
        except Exception as e:
            logging.error(f"❌ [GuildEvent] Erreur lors de la mise à jour de l'embed : {e}")

    async def event_delete_cron(self, ctx=None) -> None:
        tz = pytz.timezone("Europe/Paris")
        now = datetime.now(tz)
        total_deleted = 0

        for guild_id, settings in self.guild_settings.items():
            guild = self.bot.get_guild(guild_id)
            if not guild:
                logging.error(f"❌ [GuildEvents] CRON - Guilde {guild_id} introuvable.")
                continue

            events_channel = guild.get_channel(settings.get("events_channel"))
            if not events_channel:
                logging.error(f"❌ [GuildEvents] CRON -  Canal des événements introuvable pour la guilde {guild_id}.")
                continue

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
                        logging.warning(f"[GuildEvents] Type d'heure inconnu pour l'événement {ev['event_id']}. Utilisation de '21:00'.")
                        event_time = datetime.strptime("21:00", "%H:%M").time()

                    start_dt = tz.localize(datetime.combine(event_date, event_time))
                    end_dt = start_dt + timedelta(minutes=int(ev["duration"]))
                except Exception as e:
                    logging.error(f"❌ [GuildEvents] CRON - Erreur lors du parsing de l'événement {ev['event_id']} : {e}", exc_info=True)
                    continue

                if end_dt < now:
                    try:
                        msg = await events_channel.fetch_message(ev["event_id"])
                        await msg.delete()
                        total_deleted += 1
                        del self.events_data[key]
                    except Exception as e:
                        logging.error(f"❌ [GuildEvents] CRON - Erreur lors de la suppression du message {ev['event_id']} : {e}", exc_info=True)
                        continue

                    if str(ev.get("status", "")).lower() == "canceled":
                        try:
                            delete_query = "DELETE FROM events_data WHERE guild_id = ? AND event_id = ?"
                            await self.bot.run_db_query(delete_query, (ev["guild_id"], ev["event_id"]), commit=True)
                            logging.debug(f"[GuildEvents] CRON - Enregistrement supprimé en BDD pour l'événement {ev['event_id']}")
                        except Exception as e:
                            logging.error(f"❌ [GuildEvents] CRON - Erreur lors de la suppression en BDD de l'événement {ev['event_id']} : {e}", exc_info=True)
                    else:
                        logging.debug(f"[GuildEvents] L'événement {ev['event_id']} est terminé mais son statut n'est pas 'Canceled' => enregistrement conservé.")

            logging.info(f"[GuildEvents] Pour la guilde {guild_id}, messages supprimés: {total_deleted}")

    async def event_reminder_cron(self) -> None:
        tz = pytz.timezone("Europe/Paris")
        today_str = datetime.now(tz).strftime("%Y-%m-%d")
        overall_results = []

        logging.info(f"[GuildEvents - event_reminder_cron] Début du rappel automatique des inscriptions. Date d'aujourd'hui: {today_str}")

        for guild_id, settings in self.guild_settings.items():
            guild = self.bot.get_guild(guild_id)
            if not guild:
                logging.error(f"❌ [GuildEvents] Guilde {guild_id} introuvable.")
                continue

            guild_locale = settings.get("guild_lang") or "en-US"

            notifications_channel = guild.get_channel(settings.get("notifications_channel"))
            events_channel = guild.get_channel(settings.get("events_channel"))
            if not events_channel or not notifications_channel:
                logging.error(f"❌ [GuildEvents] Canal des événements introuvable pour la guilde {guild.name}.")
                continue

            guild_events = [ev for ev in self.events_data.values() if ev["guild_id"] == guild_id]
            for ev in guild_events:
                logging.debug(f"Comparaison pour l'événement {ev['event_id']}: event_date={repr(ev.get('event_date'))} (type {type(ev.get('event_date'))}), "
                            f"today_str={repr(today_str)}, status={repr(ev.get('status', ''))} (lowercased: {repr(ev.get('status', '').strip().lower())})")

            confirmed_events = [
                ev for ev in guild_events
                if str(ev.get("event_date")).strip() == today_str and str(ev.get("status", "")).strip().lower() == "confirmed"
            ]

            logging.info(f"[GuildEvents - event_reminder_cron] Pour la guilde {guild.name}, {len(confirmed_events)} événement(s) confirmé(s) trouvé(s) pour aujourd'hui.")

            if not confirmed_events:
                overall_results.append(f"{guild.name} : Aucun événement confirmé aujourd'hui.")
                continue

            for event in confirmed_events:
                regs_obj = event.get("registrations", {})
                if isinstance(regs_obj, str):
                    try:
                        regs_obj = json.loads(regs_obj)
                    except Exception as e:
                        logging.error(f"Erreur lors du parsing de 'registrations' pour l'événement {event['event_id']} : {e}", exc_info=True)
                        regs_obj = {"presence": [], "tentative": [], "absence": []}
                
                regs = set(regs_obj.get("presence", [])) | set(regs_obj.get("tentative", [])) | set(regs_obj.get("absence", []))

                initial_members = event.get("initial_members", [])
                if isinstance(initial_members, str):
                    try:
                        initial_members = json.loads(initial_members)
                    except Exception as e:
                        logging.error(f"Erreur lors du parsing de 'initial_members' pour l'événement {event['event_id']} : {e}", exc_info=True)
                        initial_members = []
                initial = set(initial_members)
                
                members_role_id = settings.get("members_role")
                if members_role_id:
                    role = guild.get_role(int(members_role_id))
                    if role:
                        current_members = {member.id for member in guild.members if role in member.roles}
                    else:
                        current_members = set()
                else:
                    current_members = set()
                
                updated_initial = current_members

                to_remind = list(updated_initial - regs)

                reminded = []
                event_link = f"https://discord.com/channels/{guild.id}/{events_channel.id}/{event['event_id']}"
                dm_template = GUILD_EVENTS.get("event_reminder", {}).get("dm_message", {}).get(guild_locale,GUILD_EVENTS.get("event_reminder", {}).get("dm_message", {}).get("en-US"))
                logging.debug(f"[GuildEvents - event_reminder_cron] Pour l'événement {event['event_id']}, membres initiaux: {initial}, inscrits: {regs}, à rappeler: {to_remind}")
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
                            logging.debug(f"[GuildEvents - event_reminder_cron] DM envoyé à {member.name} pour l'événement {event['name']}")
                        except Exception as e:
                            logging.error(f"Erreur lors de l'envoi du MP à {member_id} dans {guild.name} : {e}")
                    else:
                        logging.warning(f"Membre {member_id} introuvable dans la guilde {guild.name}.")

                if reminded:
                    reminder_template = GUILD_EVENTS.get("event_reminder", {}).get("notification_reminded", {}).get(guild_locale)
                    if reminder_template is None:
                        reminder_template = GUILD_EVENTS.get("event_reminder", {}).get("notification_reminded", {}).get("en-US", 
                            "## :bell: **Reminder d'événement**\n Pour l'événement **{event}**\n({event_link})\n\n{len} membre(s) ont été relancés : {members}"
                        )
                    try:
                        reminder_msg = reminder_template.format(event=event["name"], event_link=event_link, len=len(reminded), members=", ".join(reminded))
                    except Exception as e:
                        logging.error(f"Erreur lors du formatage du template de reminder: {e}", exc_info=True)
                        reminder_msg = f"Reminder: {event['name']} - {event_link}"
                    result = f"Pour l'événement **{event['name']}** dans {guild.name} : {len(reminded)} membre(s) rappelé(s) : " + ", ".join(reminded)
                    try:
                        await notifications_channel.send(reminder_msg)
                        overall_results.append(result)
                    except Exception as e:
                        logging.error(f"Erreur lors de l'envoi du message de reminder dans le canal notifications de {guild.name} : {e}", exc_info=True)
                        overall_results.append(f"{guild.name} : Erreur lors de l'envoi du reminder.")

                else:
                    reminder_template = GUILD_EVENTS.get("event_reminder", {}).get("notification_all_OK", {}).get(guild_locale)
                    if reminder_template is None:
                        reminder_template = GUILD_EVENTS.get("event_reminder", {}).get("notification_all_OK", {}).get("en-US", 
                            "## :bell: **Reminder d'événement**\n Pour l'événement **{event}**\n({event_link})\n\n**Tous les membres ont répondu.**"
                        )
                    try:
                        reminder_msg = reminder_template.format(event=event["name"], event_link=event_link)
                    except Exception as e:
                        logging.error(f"Erreur lors du formatage du template de reminder (all OK): {e}", exc_info=True)
                        reminder_msg = f"Reminder: {event['name']} - {event_link}"
                    result = f"Pour l'événement **{event['name']}** dans {guild.name}, tous les membres ont répondu."
                    try:
                        await notifications_channel.send(reminder_msg)
                        overall_results.append(result)
                    except Exception as e:
                        logging.error(f"Erreur lors de l'envoi du message de reminder dans le canal notifications de {guild.name} : {e}", exc_info=True)
                        overall_results.append(f"{guild.name} : Erreur lors de l'envoi du reminder.")

        response = "\n".join(overall_results)
        logging.info(response)

    async def event_close_cron(self) -> None:
        tz = pytz.timezone("Europe/Paris")
        now = datetime.now(tz)

        for guild_id, settings in self.guild_settings.items():
            guild = self.bot.get_guild(guild_id)
            if not guild:
                logging.error(f"❌ [GuildEvents] CRON - Guilde {guild_id} introuvable.")
                continue

            events_channel = guild.get_channel(settings.get("events_channel"))
            if not events_channel:
                logging.error(f"❌ [GuildEvents] CRON - Canal des événements introuvable pour la guilde {guild_id}.")
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
                        logging.warning(f"[GuildEvents] Type d'heure inconnu pour l'événement {ev['event_id']}. Utilisation de '21:00'.")
                        event_time = datetime.strptime("21:00", "%H:%M").time()

                    start_dt = tz.localize(datetime.combine(event_date, event_time))
                except Exception as e:
                    logging.error(f"❌ [GuildEvents] CRON - Erreur lors du parsing de l'événement {ev['event_id']} : {e}", exc_info=True)
                    continue

                if timedelta(0) <= (start_dt - now) <= timedelta(minutes=15) and ev.get("status", "").strip().lower() in ["confirmed", "planned"]:
                    await self.load_guild_members()
                    closed_localized = GUILD_EVENTS["events_infos"]["status_closed"].get(guild_lang, GUILD_EVENTS["events_infos"]["status_closed"].get("en-US"))
                    closed_db = GUILD_EVENTS["events_infos"]["status_closed"].get("en-US")
                    try:
                        msg = await events_channel.fetch_message(ev["event_id"])
                    except Exception as e:
                        logging.error(f"❌ [GuildEvents] CRON - Erreur lors de la récupération du message {ev['event_id']} : {e}", exc_info=True)
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
                            update_query = "UPDATE events_data SET status = ? WHERE guild_id = ? AND event_id = ?"
                            await self.bot.run_db_query(update_query, (closed_db, guild_id, ev["event_id"]), commit=True)
                            ev["status"] = closed_db
                            logging.info(f"[GuildEvents] CRON - Événement {ev['event_id']} passé au statut Closed.")
                            await msg.clear_reactions()
                            logging.info(f"[GuildEvents] CRON - Retrait des réactions de l'événement {ev['event_id']}.")
                            await self.create_groups(guild_id,ev["event_id"])
                        except Exception as e:
                            logging.error(f"❌ [GuildEvents] CRON - Erreur lors de la mise à jour de l'événement {ev['event_id']} : {e}", exc_info=True)

        logging.info(f"[GuildEvents] CRON - Fin de l'opération event_close_cron.")

    @staticmethod
    def group_members_by_class(member_ids, roster_data):
        """
        Regroupe les membres (identifiés par leur ID) par classe à partir du roster.
        Retourne un dictionnaire et une liste des IDs pour lesquels les informations sont manquantes.
        """
        classes = {
            "Tank": [],
            "Melee DPS": [],
            "Ranged DPS": [],
            "Healer": [],
            "Flanker": []
        }
        missing = []
        for member_id in member_ids:
            member_key = str(member_id)
            member_info = roster_data.get("membres", {}).get(member_key)
            if member_info:
                pseudo = member_info.get("pseudo", "Pseudo inconnu")
                gs = member_info.get("GS", "N/A")
                member_class = member_info.get("classe", "Inconnue")
                if member_class in classes:
                    classes[member_class].append((pseudo, gs))
                else:
                    if "Inconnue" not in classes:
                        classes["Inconnue"] = []
                    classes["Inconnue"].append((pseudo, gs))
            else:
                missing.append(member_id)
        return classes, missing

    @discord.slash_command(
        name="groups_test",
        description="création des groupes (commande en attente de suppression)"
    )
    @commands.has_permissions(manage_guild=True)
    async def create_groups(self, guild_id: int, event_id: str) -> None:
        guild_id : int = 1345893638798049321
        event_id : int = event_id
        logging.info(f"Création des groupes pour guild_id: {guild_id}, event_id: {event_id}")

        guild = self.bot.get_guild(guild_id)
        if not guild:
            logging.error(f"Guilde introuvée pour guild_id: {guild_id}")
            return

        settings = self.guild_settings.get(guild_id)
        if not settings:
            logging.error(f"Aucune configuration trouvée pour la guilde {guild_id}")
            return

        groups_channel_id = settings.get("groups_channel")
        if not groups_channel_id:
            logging.error(f"ID du canal des groupes introuvable dans la configuration pour la guilde {guild_id}")
            return

        groups_channel = guild.get_channel(int(groups_channel_id))
        if not groups_channel:
            logging.error(f"Canal des groupes non trouvé pour l'ID {groups_channel_id}")
            return

        key = f"{guild_id}_{event_id}"
        event = self.events_data.get(key)
        if not event:
            logging.error(f"Événement non trouvé pour guild_id: {guild_id} et event_id: {event_id}")
            return

        registrations = event.get("registrations")
        if isinstance(registrations, str):
            try:
                registrations = json.loads(registrations)
            except Exception as e:
                logging.error(f"Erreur lors du décodage des registrations pour event_id {event_id} : {e}")
                return
        if not isinstance(registrations, dict):
            logging.error(f"Les registrations pour event_id {event_id} ne sont pas au format attendu (dictionnaire).")
            return

        presence_ids = registrations.get("presence", [])
        tentative_ids = registrations.get("tentative", [])

        roster_data = {"membres": {}}
        for member in guild.members:
            member_id_str = str(member.id)
            pseudo = member.display_name
            member_class = self.guild_members_cache.get(guild_id, {}).get(member.id, "Inconnue")
            roster_data["membres"][member_id_str] = {"pseudo": pseudo, "GS": "N/A", "classe": member_class}

        presence_groups, presence_missing = self.group_members_by_class(presence_ids, roster_data)
        tentative_groups, tentative_missing = self.group_members_by_class(tentative_ids, roster_data)

        event_name = event.get("name", "Nom non défini")
        event_date = event.get("event_date", "Date non définie")
        event_time = event.get("event_time", "Heure non définie")

        embed = discord.Embed(
            title=f"Groupes pour l'événement : {event_name}",
            description=f"Date : {event_date} - Heure : {event_time}",
            color=discord.Color.blue()
        )

        expected_classes = ["Tank", "Melee DPS", "Ranged DPS", "Healer", "Flanker"]

        for cls in expected_classes:
            group = presence_groups.get(cls, [])
            count = len(group)
            details = "\n".join([f"• {pseudo}" for pseudo, gs in group]) if count > 0 else "Aucun"
            embed.add_field(name=f"**{count}** - **{cls} (Présents)**", value=f"{details}\n\u200b", inline=False)

        if presence_missing:
            missing_str = ", ".join(str(mid) for mid in presence_missing)
            embed.add_field(name="Informations manquantes (Présents)", value=missing_str, inline=False)

        tentative_summary = ""
        for cls in expected_classes:
            group = tentative_groups.get(cls, [])
            count = len(group)
            tentative_summary += f"**{count}** - **{cls}**\n"
        if tentative_summary:
            embed.add_field(name="Tentatives (par catégorie)", value=tentative_summary + "\n\u200b", inline=False)
        if tentative_missing:
            missing_str = ", ".join(str(mid) for mid in tentative_missing)
            embed.add_field(name="Informations manquantes (Tentatives)", value=missing_str, inline=False)

        embed.set_footer(text=f"Message généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}")

        try:
            await groups_channel.send(embed=embed)
            logging.info(f"Groupes créés et publiés dans le canal {groups_channel.id} pour event_id {event_id}")
        except Exception as e:
            logging.error(f"Erreur lors de l'envoi de l'embed des groupes : {e}")

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
            description=GUILD_EVENTS["event_create"]["event_time"]["en-US"],
            description_localizations=GUILD_EVENTS["event_create"]["event_time"]
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
            default=0,
            description=GUILD_EVENTS["event_create"]["dkp_value"]["en-US"],
            description_localizations=GUILD_EVENTS["event_create"]["dkp_value"]
        ),
        dkp_ins: int = discord.Option(
            default=0,
            description=GUILD_EVENTS["event_create"]["dkp_ins"]["en-US"],
            description_localizations=GUILD_EVENTS["event_create"]["dkp_ins"]
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

        logging.debug(f"[GuildEvents - event_create] Paramètres reçus: event_name={event_name}, event_date={event_date}, event_time={event_time}, duration={duration}, status={status}, dkp_value={dkp_value}, dkp_ins={dkp_ins}")
        
        tz = pytz.timezone("Europe/Paris")
        try:
            event_date = event_date.replace("/", "-")
            start_date = datetime.strptime(event_date, "%Y-%m-%d").date()
            start_time_obj = datetime.strptime(event_time, "%H:%M").time()
            logging.debug(f"[GuildEvents - event_create] Dates parsées: start_date={start_date}, start_time_obj={start_time_obj}")
        except Exception as e:
            logging.error("[GuildEvents - event_create] Erreur lors du parsing de la date ou de l'heure.", exc_info=True)
            follow_message = GUILD_EVENTS["event_create"]["date_ko"].get(user_locale,GUILD_EVENTS["event_create"]["date_ko"].get("en-US"))
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        try:
            duration = int(duration)
            start_dt = tz.localize(datetime.combine(start_date, start_time_obj))
            end_dt = start_dt + timedelta(minutes=duration)
            logging.debug(f"[GuildEvents - event_create] start_dt calculé: {start_dt}, end_dt: {end_dt}")
        except Exception as e:
            logging.error("[GuildEvents - event_create] Erreur lors de la localisation ou du calcul de la date de fin.", exc_info=True)
            await ctx.followup.send("Une erreur est survenue lors du traitement des dates.", ephemeral=True)
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
            logging.error(f"[GuildEvents - event_create] Salons introuvables: events_channel={events_channel}, conference_channel={conference_channel}")
            follow_message = GUILD_EVENTS["event_create"]["no_events_canal"].get(user_locale,GUILD_EVENTS["event_create"]["no_events_canal"].get("en-US"))
            await ctx.followup.send(follow_message, ephemeral=True)
            return

        if status.lower() == "confirmed":
            embed_color = discord.Color.green()
        else:
            embed_color = discord.Color.blue()
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
            logging.error(f"[GuildEvents - event_create] Erreur lors de l'envoi de l'annonce: {e}", exc_info=True)
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
            logging.debug(f"[GuildEvents - event_create] Événement programmé créé: {scheduled_event.id if scheduled_event else 'None'}")
        except Exception as e:
            logging.error(f"[GuildEvents - create_events] Error creating scheduled event: {e}")

        members_role_id = settings.get("members_role")
        if members_role_id:
            role = guild.get_role(int(members_role_id))
            if role:
                initial_members = [member.id for member in guild.members if role in member.roles]
            else:
                initial_members = []
        else:
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
            await self.bot.run_db_query(query, record)
            self.events_data[f"{guild.id}_{announcement.id}"] = record
            logging.info(f"[GuildEvents - create_events] Enregistrement de l'événement en BDD réussi : {announcement.id}")
            follow_message = GUILD_EVENTS["event_create"]["events_created"].get(user_locale,GUILD_EVENTS["event_create"]["events_created"].get("en-US")).format(event_id=announcement.id)
            await ctx.followup.send(follow_message, ephemeral=True)
        except Exception as e:
            logging.error(f"[GuildEvents - create_events] Erreur lors de l'enregistrement en BDD pour la guilde {guild.id} : {e}")
            follow_message = GUILD_EVENTS["event_create"]["event_ko"].get(user_locale,GUILD_EVENTS["event_create"]["event_ko"].get("en-US")).format(e=e)
            await ctx.followup.send(follow_message, ephemeral=True)

    @commands.Cog.listener() 
    async def on_ready(self):
        asyncio.create_task(self.load_guild_settings())
        asyncio.create_task(self.load_events_calendar())
        asyncio.create_task(self.load_events_data())
        asyncio.create_task(self.load_guild_members())
        logging.debug("[GuildEvents] Tâche de récupérations des infos dans le cache lancée depuis on_ready")

def setup(bot: discord.Bot):
    bot.add_cog(GuildEvents(bot))
