import discord
from discord.ext import commands
import asyncio
import logging
import re
from typing import Dict, List, Tuple, Any, Optional, Union
from discord.ext import commands, tasks
from functions import get_user_message
from datetime import datetime
from translation import translations as global_translations
from urllib.parse import urlparse

GUILD_MEMBERS = global_translations.get("guild_members", {})
CONFIG_ROSTER_DATA = global_translations.get("commands", {}).get("config_roster", {})

class GuildMembers(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.forum_channels: Dict[int, Dict[str, Any]] = {}
        self.roles: Dict[int, Dict[str, int]] = {}
        self.weapons: Dict[int, Dict[str, str]] = {}
        self.weapons_combinations: Dict[int, List[Dict[str, str]]] = {}
        self.user_setup_members: Dict[Tuple[int, int], Dict[str, Any]] = {}
        self.guild_members: Dict[Tuple[int, int], Dict[str, Any]] = {}
        self.ideal_staff: Dict[int, Dict[str, int]] = {}
        
        self.allowed_build_domains = ['questlog.gg', 'maxroll.gg']
        self.max_username_length = 32
        self.max_gs_value = 9999
        self.min_gs_value = 500
    
    def _sanitize_string(self, text: str, max_length: int = 100) -> str:
        if not isinstance(text, str):
            return ""
        sanitized = re.sub(r'[<>"\';\\\x00-\x1f\x7f]', '', text.strip())
        return sanitized[:max_length]
    
    def _validate_url(self, url: str) -> bool:
        if not isinstance(url, str) or not url.strip():
            return False
        
        try:
            parsed = urlparse(url.strip())
            if not parsed.scheme or not parsed.netloc:
                return False
            
            if parsed.scheme.lower() != 'https':
                return False
            
            domain = parsed.netloc.lower()
            return any(allowed_domain in domain for allowed_domain in self.allowed_build_domains)
        except Exception:
            return False
    
    def _validate_integer(self, value: Any, min_val: int = None, max_val: int = None) -> Optional[int]:
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
        if not isinstance(weapon, str):
            return None
        
        sanitized = self._sanitize_string(weapon.strip().upper(), 10)
        if not re.match(r'^[A-Z0-9_]{1,10}$', sanitized):
            return None
        return sanitized

    async def load_forum_channels(self) -> None:
        logging.debug("[GuildMembers] Loading forum channels from database")
        query = """
        SELECT gc.guild_id,
            gc.members_channel,
            gc.members_m1,
            gc.members_m2,
            gc.members_m3,
            gc.members_m4,
            gc.members_m5,
            gc.external_recruitment_channel,
            gc.external_recruitment_message,
            gs.guild_lang,
            gs.guild_game,
            gl.max_members
        FROM guild_channels gc
        JOIN guild_settings gs ON gc.guild_id = gs.guild_id
        JOIN games_list gl ON gs.guild_game = gl.id;
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.forum_channels = {}
            for row in rows:
                (guild_id, members_channel, members_m1, members_m2, members_m3,
                members_m4, members_m5, external_recruitment_channel,
                external_recruitment_message, guild_lang, guild_game, max_members) = row
                self.forum_channels[guild_id] = {
                    "members_channel": members_channel,
                    "members_m1": members_m1,
                    "members_m2": members_m2,
                    "members_m3": members_m3,
                    "members_m4": members_m4,
                    "members_m5": members_m5,
                    "external_recruitment_channel": external_recruitment_channel,
                    "external_recruitment_message": external_recruitment_message,
                    "guild_lang": guild_lang,
                    "guild_game": guild_game,
                    "max_members": max_members
                }
            logging.debug(f"[GuildMembers] Forum channels loaded: {len(self.forum_channels)} guilds")
        except Exception as e:
            logging.error(f"[GuildMembers] Error loading forum channels: {e}", exc_info=True)
            self.forum_channels = {}

    async def load_roles(self) -> None:
        logging.debug("[GuildMembers] Loading roles from database")
        query = """
            SELECT guild_id, members, absent_members
            FROM guild_roles 
            WHERE members IS NOT NULL AND absent_members IS NOT NULL
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.roles = {}
            for row in rows:
                guild_id, members_id, absent_members_id = row
                self.roles[guild_id] = {
                    "members": members_id,
                    "absent_members": absent_members_id,
                }
            logging.debug(f"[GuildMembers] Roles loaded: {self.roles}")
        except Exception as e:
            logging.error(f"[GuildMembers] Error loading roles: {e}", exc_info=True)
            self.roles = {}

    async def load_weapons(self) -> None:
        logging.debug("[GuildMembers] Loading weapons from database")
        query = "SELECT game_id, code, name FROM weapons ORDER BY game_id;"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.weapons = {}
            for row in rows:
                game_id, code, name = row
                if game_id not in self.weapons:
                    self.weapons[game_id] = {}
                self.weapons[game_id][code] = name
            logging.debug(f"[GuildMembers] Weapons loaded: {self.weapons}")
        except Exception as e:
            logging.error(f"[GuildMembers] Error loading weapons: {e}", exc_info=True)
            self.weapons = {}

    async def load_weapons_combinations(self) -> None:
        logging.debug("[GuildMembers] Loading weapon combinations from database")
        query = "SELECT game_id, role, weapon1, weapon2 FROM weapons_combinations ORDER BY game_id;"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.weapons_combinations = {}
            for row in rows:
                game_id, role, weapon1, weapon2 = row
                if game_id not in self.weapons_combinations:
                    self.weapons_combinations[game_id] = []
                self.weapons_combinations[game_id].append({
                    "role": role,
                    "weapon1": weapon1.upper(),
                    "weapon2": weapon2.upper()
                })
            logging.debug(f"[GuildMembers] Weapon combinations loaded: {self.weapons_combinations}")
        except Exception as e:
            logging.error(f"[GuildMembers] Error loading weapon combinations: {e}", exc_info=True)
            self.weapons_combinations = {}

    async def load_user_setup_members(self) -> Dict[Tuple[int, int], Dict[str, Any]]:
        logging.debug("[GuildMembers] Loading Guilds users settings from database")
        query = """
            SELECT guild_id, user_id, username, locale, gs, weapons
            FROM user_setup
            WHERE motif IN ('member', 'application')
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.user_setup_members = {}
            for row in rows:
                guild_id, user_id, username, locale, gs, weapons = row
                key = (int(guild_id), int(user_id))
                self.user_setup_members[key] = {
                    "username": username,
                    "locale": locale,
                    "gs": gs,
                    "weapons": weapons
                }
            logging.debug(f"[GuildMembers] User setup members loaded: {self.user_setup_members}")
        except Exception as e:
            logging.error(f"[GuildMembers] Error loading user setup members: {e}", exc_info=True)
            self.user_setup_members = {}

    async def load_guild_members(self) -> None:
        logging.debug("[GuildMembers] Loading Guilds members infos from database")
        query = """
            SELECT guild_id, member_id, username, language, GS, build, weapons, DKP, nb_events, registrations, attendances, `class`
            FROM guild_members
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.guild_members = {}
            for row in rows:
                guild_id, member_id, username, language, GS, build, weapons, DKP, nb_events, registrations, attendances, class_name = row
                key = (guild_id, member_id)
                self.guild_members[key] = {
                    "username": username,
                    "language": language,
                    "GS": GS,
                    "build": build,
                    "weapons": weapons,
                    "DKP": DKP,
                    "nb_events": nb_events,
                    "registrations": registrations,
                    "attendances": attendances,
                    "class": class_name
                }
            logging.debug(f"[GuildMembers] Members loaded: {self.guild_members}")
        except Exception as e:
            logging.error(f"[GuildMembers] Error loading guild members: {e}", exc_info=True)
            self.guild_members = {}

    async def load_ideal_staff(self) -> None:
        logging.debug("[GuildMembers] Loading ideal staff configuration from database")
        query = "SELECT guild_id, class_name, ideal_count FROM guild_ideal_staff"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.ideal_staff = {}
            for row in rows:
                guild_id, class_name, ideal_count = row
                if guild_id not in self.ideal_staff:
                    self.ideal_staff[guild_id] = {}
                self.ideal_staff[guild_id][class_name] = ideal_count
            logging.debug(f"[GuildMembers] Ideal staff loaded: {self.ideal_staff}")
        except Exception as e:
            logging.error(f"[GuildMembers] Error loading ideal staff: {e}", exc_info=True)
            self.ideal_staff = {}

    def determine_class(self, weapons_list: list, guild_id: int) -> str:
        if not isinstance(weapons_list, list) or not weapons_list:
            return "NULL"
        
        guild_info = self.forum_channels.get(guild_id, {})
        game = guild_info.get("guild_game")
        if not game:
            return "NULL"
        
        game_id = self._validate_integer(game)
        if game_id is None:
            return "NULL"
        combinations = self.weapons_combinations.get(game_id, [])
        sorted_weapons = sorted(weapons_list)
        for combo in combinations:
            if sorted([combo["weapon1"], combo["weapon2"]]) == sorted_weapons:
                return combo["role"]
        return "NULL"

    def get_valid_weapons(self, guild_id: int) -> set:
        valid = set()
        if not isinstance(guild_id, int):
            return valid
            
        guild_info = self.forum_channels.get(guild_id, {})
        game = guild_info.get("guild_game")
        if not game:
            return valid
        
        game_id = self._validate_integer(game)
        if game_id is None:
            return valid
        combinations = self.weapons_combinations.get(game_id, [])
        for combo in combinations:
            valid.add(combo["weapon1"])
            valid.add(combo["weapon2"])
        return valid

    @discord.slash_command(
        name=GUILD_MEMBERS["gs"]["name"]["en-US"],
        description=GUILD_MEMBERS["gs"]["description"]["en-US"],
        name_localizations=GUILD_MEMBERS["gs"]["name"],
        description_localizations=GUILD_MEMBERS["gs"]["description"]
    )
    async def gs(
        self,
        ctx: discord.ApplicationContext,
        value: int = discord.Option(
            description=GUILD_MEMBERS["gs"]["value_comment"]["en-US"],
            description_localizations=GUILD_MEMBERS["gs"]["value_comment"]
        )
    ):
        await ctx.defer(ephemeral=True)
        
        if not ctx.guild or not ctx.author:
            logging.error("[GuildMembers - GS] Invalid context: missing guild or author")
            await ctx.followup.send("❌ Invalid request context", ephemeral=True)
            return
        
        guild_id = ctx.guild.id
        member_id = ctx.author.id
        key = (guild_id, member_id)

        validated_value = self._validate_integer(value, self.min_gs_value, self.max_gs_value)
        if validated_value is None:
            logging.debug(f"[GuildMembers - GS] Invalid GS value provided by {ctx.author}: {value}")
            msg = get_user_message(ctx, GUILD_MEMBERS["gs"], "not_positive")
            try:
                await ctx.followup.send(msg, ephemeral=True)
            except Exception as ex:
                logging.exception(f"[GuildMembers - GS] Error sending followup message for invalid value: {ex}")
            return
        
        if key not in self.guild_members:
            logging.debug(f"[GuildMembers - GS] Profile not found for key {key}")
            msg = get_user_message(ctx, GUILD_MEMBERS["gs"], "not_registered")
            await ctx.followup.send(msg, ephemeral=True)
            return

        try: 
            query = "UPDATE guild_members SET GS = %s WHERE guild_id = %s AND member_id = %s"
            await self.bot.run_db_query(query, (validated_value, guild_id, member_id), commit=True)
            self.guild_members[key]["GS"] = validated_value
            logging.debug(f"[GuildMembers - GS] Successfully updated GS for {ctx.author} (ID: {member_id}) to {validated_value}")
            msg = get_user_message(ctx, GUILD_MEMBERS["gs"], "updated", username=ctx.author.display_name, value=validated_value)
            await ctx.followup.send(msg, ephemeral=True)
        except Exception as e:
            logging.exception(f"[GuildMembers - GS] Error updating GS for {ctx.author} (ID: {member_id}): {e}")
            await ctx.followup.send("❌ Database error occurred", ephemeral=True)

    @discord.slash_command(
        name=GUILD_MEMBERS["weapons"]["name"]["en-US"],
        description=GUILD_MEMBERS["weapons"]["description"]["en-US"],
        name_localizations=GUILD_MEMBERS["weapons"]["name"],
        description_localizations=GUILD_MEMBERS["weapons"]["description"]
    )
    async def weapons(
        self,
        ctx: discord.ApplicationContext,
        weapon1: str = discord.Option(
            description=GUILD_MEMBERS["weapons"]["value_comment"]["en-US"],
            description_localizations=GUILD_MEMBERS["weapons"]["value_comment"]
        ),
        weapon2: str = discord.Option(
            description=GUILD_MEMBERS["weapons"]["value_comment"]["en-US"],
            description_localizations=GUILD_MEMBERS["weapons"]["value_comment"]
        )
    ):
        await ctx.defer(ephemeral=True)
        
        if not ctx.guild or not ctx.author:
            logging.error("[GuildMembers - Weapons] Invalid context: missing guild or author")
            await ctx.followup.send("❌ Invalid request context", ephemeral=True)
            return
        
        guild_id = ctx.guild.id
        member_id = ctx.author.id
        key = (guild_id, member_id)
        
        if key not in self.guild_members:
            msg = get_user_message(ctx, GUILD_MEMBERS["weapons"], "not_registered")
            await ctx.followup.send(msg, ephemeral=True)
            return

        weapon1_code = self._validate_weapon_code(weapon1)
        weapon2_code = self._validate_weapon_code(weapon2)
        
        if not weapon1_code or not weapon2_code:
            msg = get_user_message(ctx, GUILD_MEMBERS["weapons"], "not_valid")
            await ctx.followup.send(msg, ephemeral=True)
            return
        
        if weapon1_code == weapon2_code:
            msg = get_user_message(ctx, GUILD_MEMBERS["weapons"], "not_valid_same")
            await ctx.followup.send(msg, ephemeral=True)
            return

        valid_weapons = self.get_valid_weapons(guild_id)
        if weapon1_code not in valid_weapons or weapon2_code not in valid_weapons:
            msg = get_user_message(ctx, GUILD_MEMBERS["weapons"], "not_valid")
            await ctx.followup.send(msg, ephemeral=True)
            return

        try:
            weapons_normalized = sorted([weapon1_code, weapon2_code])
            player_class = self.determine_class(weapons_normalized, guild_id)
            weapons_str = "/".join(weapons_normalized)
            
            query = "UPDATE guild_members SET weapons = %s, `class` = %s WHERE guild_id = %s AND member_id = %s"
            await self.bot.run_db_query(query, (weapons_str, player_class, guild_id, member_id), commit=True)
            
            self.guild_members[key]["weapons"] = weapons_str
            self.guild_members[key]["class"] = player_class

            msg = get_user_message(ctx, GUILD_MEMBERS["weapons"], "updated", username=ctx.author.display_name, weapons_str=weapons_str)
            await ctx.followup.send(msg, ephemeral=True)
        except Exception as e:
            logging.exception(f"[GuildMembers - Weapons] Error updating weapons for {ctx.author} (ID: {member_id}): {e}")
            await ctx.followup.send("❌ Database error occurred", ephemeral=True)

    @discord.slash_command(
        name=GUILD_MEMBERS["build"]["name"]["en-US"],
        description=GUILD_MEMBERS["build"]["description"]["en-US"],
        name_localizations=GUILD_MEMBERS["build"]["name"],
        description_localizations=GUILD_MEMBERS["build"]["description"]
    )
    async def build(
        self,
        ctx: discord.ApplicationContext,
        url: str = discord.Option(
            description=GUILD_MEMBERS["build"]["value_comment"]["en-US"],
            description_localizations=GUILD_MEMBERS["build"]["value_comment"]
        ),
    ):
        await ctx.defer(ephemeral=True)
        
        if not ctx.guild or not ctx.author:
            logging.error("[GuildMembers - Build] Invalid context: missing guild or author")
            await ctx.followup.send("❌ Invalid request context", ephemeral=True)
            return

        if not self._validate_url(url):
            msg = get_user_message(ctx, GUILD_MEMBERS["build"], "not_correct")
            await ctx.followup.send(msg, ephemeral=True)
            return
        
        guild_id = ctx.guild.id
        member_id = ctx.author.id
        key = (guild_id, member_id)
        
        if key not in self.guild_members:
            msg = get_user_message(ctx, GUILD_MEMBERS["build"], "not_registered")
            await ctx.followup.send(msg, ephemeral=True)
            return

        try:
            sanitized_url = self._sanitize_string(url.strip(), 500)
            query = "UPDATE guild_members SET build = %s WHERE guild_id = %s AND member_id = %s"
            await self.bot.run_db_query(query, (sanitized_url, guild_id, member_id), commit=True)
            self.guild_members[key]["build"] = sanitized_url
            msg = get_user_message(ctx, GUILD_MEMBERS["build"], "updated", username=ctx.author.display_name)
            await ctx.followup.send(msg, ephemeral=True)
        except Exception as e:
            logging.exception(f"[GuildMembers - Build] Error updating build for {ctx.author} (ID: {member_id}): {e}")
            await ctx.followup.send("❌ Database error occurred", ephemeral=True)

    @discord.slash_command(
        name=GUILD_MEMBERS["username"]["name"]["en-US"],
        description=GUILD_MEMBERS["username"]["description"]["en-US"],
        name_localizations=GUILD_MEMBERS["username"]["name"],
        description_localizations=GUILD_MEMBERS["username"]["description"]
    )
    async def username(
        self,
        ctx: discord.ApplicationContext,
        new_name: str = discord.Option(
            description=GUILD_MEMBERS["username"]["value_comment"]["en-US"],
            description_localizations=GUILD_MEMBERS["username"]["value_comment"]
        ),
    ):
        await ctx.defer(ephemeral=True)
        
        if not ctx.guild or not ctx.author:
            logging.error("[GuildMembers - Username] Invalid context: missing guild or author")
            await ctx.followup.send("❌ Invalid request context", ephemeral=True)
            return
        
        guild_id = ctx.guild.id
        member_id = ctx.author.id
        key = (guild_id, member_id)
        
        if key not in self.guild_members:
            msg = get_user_message(ctx, GUILD_MEMBERS["username"], "not_registered")
            await ctx.followup.send(msg, ephemeral=True)
            return

        new_username = self._sanitize_string(new_name, self.max_username_length)
        if not new_username or len(new_username.strip()) == 0:
            await ctx.followup.send("❌ Invalid username name", ephemeral=True)
            return
        
        try:
            query = "UPDATE guild_members SET username = %s WHERE guild_id = %s AND member_id = %s"
            await self.bot.run_db_query(query, (new_username, guild_id, member_id), commit=True)
            self.guild_members[key]["username"] = new_username
            
            try:
                await ctx.author.edit(nick=new_username)
            except discord.Forbidden:
                logging.warning(f"[GuildMembers - Username] Unable to update nickname for {ctx.author.display_name}")
            except Exception as e:
                logging.warning(f"[GuildMembers - Username] Error updating nickname for {ctx.author.display_name}: {e}")
            
            msg = get_user_message(ctx, GUILD_MEMBERS["username"], "updated", username=new_username)
            await ctx.followup.send(msg, ephemeral=True)
        except Exception as e:
            logging.exception(f"[GuildMembers - Username] Error updating username for {ctx.author} (ID: {member_id}): {e}")
            await ctx.followup.send("❌ Database error occurred", ephemeral=True)

    @discord.slash_command(
        name=GUILD_MEMBERS["maj_roster"]["name"]["en-US"],
        description=GUILD_MEMBERS["maj_roster"]["description"]["en-US"],
        name_localizations=GUILD_MEMBERS["maj_roster"]["name"],
        description_localizations=GUILD_MEMBERS["maj_roster"]["description"]
    )
    @commands.has_permissions(manage_roles=True)
    async def maj_roster(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        guild_id = ctx.guild.id
        roles_config = self.roles.get(guild_id)
        guild_config = self.forum_channels.get(guild_id)
        locale = guild_config.get("guild_lang")
        if not roles_config:
            msg = get_user_message(ctx, GUILD_MEMBERS["maj_roster"], "not_config")
            await ctx.followup.send(msg, ephemeral=True)
            return
        
        members_role_id = roles_config.get("members")
        absent_role_id = roles_config.get("absent_members")
        if not members_role_id:
            msg = get_user_message(ctx, GUILD_MEMBERS["maj_roster"], "roles_ko")
            await ctx.followup.send(msg, ephemeral=True)
            return

        actual_members = {
            m.id: m for m in ctx.guild.members
            if not m.bot and (members_role_id in [role.id for role in m.roles] or absent_role_id in [role.id for role in m.roles])
        }

        keys_to_remove = []
        for (g, user_id), data in self.guild_members.items():
            if g == guild_id and user_id not in actual_members:
                delete_query = "DELETE FROM guild_members WHERE guild_id = %s AND member_id = %s"
                await self.bot.run_db_query(delete_query, (guild_id, user_id), commit=True)
                keys_to_remove.append((g, user_id))
        for key in keys_to_remove:
            del self.guild_members[key]

        for member in actual_members.values():
            key = (int(guild_id), int(member.id))
            if key in self.guild_members:
                record = self.guild_members[key]
                if record.get("username") != member.display_name:
                    record["username"] = member.display_name
                    update_query = "UPDATE guild_members SET username = %s WHERE guild_id = %s AND member_id = %s"
                    await self.bot.run_db_query(update_query, (member.display_name, guild_id, member.id), commit=True)
                    logging.debug(f"[GuildMembers - UpdateRoster] Username updated for {member.display_name} (ID: {member.id})")
            else:
                user_setup = self.user_setup_members.get(key, {})
                if user_setup:
                    language = user_setup.get("locale") or locale
                    gs_value = user_setup.get("gs")
                    logging.debug(f"[GuildMembers - UpdateRoster] Values retrieved from user_setup for {member.display_name}: language={language}, gs={gs_value}")

                    weapons_raw = user_setup.get("weapons")
                    if weapons_raw and isinstance(weapons_raw, str):
                        weapons_raw = weapons_raw.strip()
                        if "/" not in weapons_raw:
                            if "," in weapons_raw:
                                weapons_raw = weapons_raw.replace(",", "/")
                            else:
                                weapons_raw = None
                        if weapons_raw:
                            weapons_list = [w.strip().upper() for w in weapons_raw.split("/") if w.strip()]
                            if len(weapons_list) == 2:
                                valid = self.get_valid_weapons(guild_id)
                                if weapons_list[0] in valid and weapons_list[1] in valid:
                                    weapons_normalized = "/".join(sorted(weapons_list))
                                    computed_class = self.determine_class(sorted(weapons_list), guild_id)
                                else:
                                    weapons_normalized = "NULL"
                                    computed_class = "NULL"
                            else:
                                weapons_normalized = "NULL"
                                computed_class = "NULL"
                        else:
                            weapons_normalized = "NULL"
                            computed_class = "NULL"
                    else:
                        weapons_normalized = "NULL"
                        computed_class = "NULL"

                else:
                    language = locale
                    gs_value = 0
                    weapons_normalized = "NULL"
                    computed_class = "NULL"
                    logging.debug(f"[GuildMembers - UpdateRoster] No user_setup info for {member.display_name}. Default values: language={language}, gs={gs_value}")

                if language and '-' in language:
                    language = language.split('-')[0]

                if gs_value in (None, "", "NULL"):
                    gs_value = 0

                new_record = {
                    "username": member.display_name,
                    "language": language,
                    "GS": gs_value,
                    "build": None,
                    "weapons": weapons_normalized,
                    "DKP": 0,
                    "nb_events": 0,
                    "registrations": 0,
                    "attendances": 0,
                    "class": computed_class
                }
                insert_query = """
                    INSERT INTO guild_members 
                    (guild_id, member_id, username, language, GS, build, weapons, DKP, nb_events, registrations, attendances, `class`)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        new_record["class"]
                    ),
                    commit=True
                )
                self.guild_members[key] = new_record
                logging.debug(f"[GuildMembers - UpdateRoster] New member added: {member.display_name} (ID: {member.id})")

        try:
            await self.load_guild_members()
            await self.update_recruitment_message(ctx)
            await self.update_members_message(ctx)

            msg = get_user_message(ctx, GUILD_MEMBERS["maj_roster"], "updated")
            await ctx.followup.send(msg, ephemeral=True)
        except Exception as e:
            logging.exception(f"[GuildMembers - UpdateRoster] Error during roster update: {e}")
            await ctx.followup.send("❌ Error occurred during roster update", ephemeral=True)

    async def update_recruitment_message(self, ctx):
        if hasattr(ctx, "guild"):
            guild_obj = ctx.guild
        else:
            guild_obj = ctx
        guild_id = guild_obj.id
        guild_config = self.forum_channels.get(guild_id)
        locale = guild_config.get("guild_lang", "en-US")
        if not guild_config:
            logging.error(f"[GuildMembers] No configuration found for guild {guild_id}")
            return

        channel_id = guild_config.get("external_recruitment_channel")
        message_id = guild_config.get("external_recruitment_message")
        channel = self.bot.get_channel(channel_id)
        if not channel:
            logging.error("[GuildMembers] Unable to retrieve recruitment channel")
            return

        members_in_roster = [v for (g, _), v in self.guild_members.items() if g == guild_id]
        total_members = len(members_in_roster)
        roster_size_max = guild_config.get("max_members")

        ideal_staff = self.ideal_staff.get(guild_id, {
            "Tank": 20,
            "Healer": 20,
            "Flanker": 10,
            "Ranged DPS": 10,
            "Melee DPS": 10
        })

        class_counts = { key: 0 for key in ideal_staff.keys() }
        for m in members_in_roster:
            cls = m.get("class", "NULL")
            if cls in ideal_staff:
                class_counts[cls] += 1

        remaining_slots = max(0, roster_size_max - total_members)

        title = GUILD_MEMBERS["post_recruitment"]["name"][locale]
        roster_size_template = GUILD_MEMBERS["post_recruitment"]["roster_size"][locale]
        roster_size_line = roster_size_template.format(total_members=total_members, roster_size_max=roster_size_max)
        places_template = GUILD_MEMBERS["post_recruitment"]["places"][locale]
        places_line = places_template.format(remaining_slots=remaining_slots)
        post_availability_template = GUILD_MEMBERS["post_recruitment"]["post_availability"][locale]
        updated_template = GUILD_MEMBERS["post_recruitment"]["updated"][locale]

        positions_details = ""
        for cls_key, ideal_number in ideal_staff.items():
            class_name = GUILD_MEMBERS["class"][cls_key][locale]
            current_count = class_counts.get(cls_key, 0)
            available = max(0, ideal_number - current_count)
            positions_details += f"- **{class_name}** : {available} \n"

        description = roster_size_line + places_line + post_availability_template + positions_details

        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.blue()
        )
        now = datetime.now().strftime("%d/%m/%Y à %H:%M")
        embed.set_footer(text=updated_template.format(now=now))

        try:
            message = await channel.fetch_message(message_id)
            await message.edit(embed=embed)
        except discord.NotFound:
            new_message = await channel.send(embed=embed)
            guild_config["external_recruitment_message"] = new_message.id

    async def update_members_message(self, ctx):
        if hasattr(ctx, "guild"):
            guild_obj = ctx.guild
        else:
            guild_obj = ctx
        guild_id = guild_obj.id
        guild_config = self.forum_channels.get(guild_id)
        if not guild_config:
            logging.error(f"[GuildMembers] No configuration found for guild {guild_id}")
            return
        
        locale = guild_config.get("guild_lang", "en-US")

        channel_id = guild_config.get("members_channel")
        message_ids = [
            guild_config.get("members_m1"),
            guild_config.get("members_m2"),
            guild_config.get("members_m3"),
            guild_config.get("members_m4"),
            guild_config.get("members_m5")
        ]

        channel = self.bot.get_channel(channel_id)
        if not channel:
            logging.error("[GuildMembers] Unable to retrieve roster channel")
            return

        members_in_roster = [v for (g, _), v in self.guild_members.items() if g == guild_id]
        sorted_members = sorted(members_in_roster, key=lambda x: x.get("username", "").lower())

        tank_count = sum(1 for m in sorted_members if (m.get("class") or "").lower() == "tank")
        dps_melee_count = sum(1 for m in sorted_members if (m.get("class") or "").lower() == "melee dps")
        dps_distant_count = sum(1 for m in sorted_members if (m.get("class") or "").lower() == "ranged dps")
        heal_count = sum(1 for m in sorted_members if (m.get("class") or "").lower() == "healer")
        flank_count = sum(1 for m in sorted_members if (m.get("class") or "").lower() == "flanker")

        username_width = 20
        language_width = 8
        gs_width = 8
        build_width = 7
        weapons_width = 9
        class_width = 14
        dkp_width = 10
        reg_width = 8
        att_width = 8

        header_labels = GUILD_MEMBERS.get("table", {}).get("header", {}).get(locale)
        
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
            username = m.get("username", "")[:username_width].ljust(username_width)
            language_text = str(m.get("language", "en-US"))[:language_width].center(language_width)
            gs = str(m.get("GS", "NULL")).center(gs_width)
            build_flag = "Y" if m.get("build", "NULL") != "NULL" else " "
            build_flag = build_flag.center(build_width)
            weapons = m.get("weapons", "NULL")
            if isinstance(weapons, str) and weapons != "NULL":
                weapons_str = weapons.center(weapons_width)
            else:
                weapons_str = " ".center(weapons_width)
            member_class = m.get("class", "NULL")
            if isinstance(member_class, str) and member_class != "NULL":
                class_str = member_class.center(class_width)
            else :
                class_str = " ".center(class_width)
            dkp = str(m.get("DKP", 0)).center(dkp_width)
            nb_events = m.get("nb_events", 0)
            if nb_events > 0:
                reg_pct = round((m.get("registrations", 0) / nb_events) * 100)
                att_pct = round((m.get("attendances", 0) / nb_events) * 100)
            else:
                reg_pct = 0
                att_pct = 0
            registrations = f"{reg_pct}%".center(reg_width)
            attendances = f"{att_pct}%".center(att_width)
            rows.append(f"{username}│{language_text}│{gs}│{build_flag}│{weapons_str}│{class_str}│{dkp}│{registrations}│{attendances}")

        if not rows:
            logging.warning("[GuildMembers] No members found in roster")
            return

        now_str = datetime.now().strftime("%d/%m/%Y à %H:%M")
        role_labels = GUILD_MEMBERS.get("table", {}).get("role_stats", {}).get(locale)
        
        role_stats = (
            f"{role_labels[0]}: {tank_count}\n"
            f"{role_labels[1]}: {dps_melee_count}\n"
            f"{role_labels[2]}: {dps_distant_count}\n"
            f"{role_labels[3]}: {heal_count}\n"
            f"{role_labels[4]}: {flank_count}"
        )
        footer_template = GUILD_MEMBERS.get("table", {}).get("footer", {}).get(locale,
            "Number of members: {count}\\n{stats}\\nUpdated {date}")
        update_footer = "\n" + footer_template.format(count=len(rows), stats=role_stats, date=now_str).replace("\\n", "\n")
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
            for i in range(5):
                try:
                    message = await channel.fetch_message(message_ids[i])
                    new_content = message_contents[i] if i < len(message_contents) else "."

                    if message.content != new_content:
                        await message.edit(content=new_content)
                        if i < 4:
                            await asyncio.sleep(0.25)
                except discord.NotFound:
                    logging.warning(f"[GuildMembers] Roster message {i+1}/5 not found")
                except Exception as e:
                    logging.error(f"[GuildMembers] Error updating roster message {i+1}/5: {e}")
        except Exception as e:
            logging.exception(f"[GuildMembers] Error updating member messages: {e}")
        logging.info("[GuildMembers] Member message update completed")

    @discord.slash_command(
        name=GUILD_MEMBERS["show_build"]["name"]["en-US"],
        description=GUILD_MEMBERS["show_build"]["description"]["en-US"],
        name_localizations=GUILD_MEMBERS["show_build"]["name"],
        description_localizations=GUILD_MEMBERS["show_build"]["description"]
    )
    async def show_build(
        self,
        ctx: discord.ApplicationContext,
        username: str = discord.Option(
            description=GUILD_MEMBERS["show_build"]["value_comment"]["en-US"],
            description_localizations=GUILD_MEMBERS["show_build"]["value_comment"]
        ),
    ):
        await ctx.defer(ephemeral=True)
        
        if not ctx.guild or not ctx.author:
            logging.error("[GuildMembers - ShowBuild] Invalid context: missing guild or author")
            await ctx.followup.send("❌ Invalid request context", ephemeral=True)
            return
        
        sanitized_username = self._sanitize_string(username, 32)
        if not sanitized_username:
            await ctx.followup.send("❌ Invalid username format", ephemeral=True)
            return
        
        guild_id = ctx.guild.id
        matching = [m for (g, _), m in self.guild_members.items() 
                   if g == guild_id and m.get("username", "").lower().startswith(sanitized_username.lower())]

        if not matching:
            msg = get_user_message(ctx, GUILD_MEMBERS["show_build"], "not_found", username=username)
            await ctx.followup.send(msg, ephemeral=True)
            return

        member_data = matching[0]
        build_url = member_data.get("build", "NULL")
        if build_url == "NULL":
            msg = get_user_message(ctx, GUILD_MEMBERS["show_build"], "no_build", username=username)
            await ctx.followup.send(msg, ephemeral=True)
            return

        try:
            msg = get_user_message(ctx, GUILD_MEMBERS["show_build"], "build_sent", member=member_data.get('username'), build_url=build_url)
            await ctx.author.send(msg)
            msg = get_user_message(ctx, GUILD_MEMBERS["show_build"], "sent")
            await ctx.followup.send(msg, ephemeral=True)
        except discord.Forbidden:
            msg = get_user_message(ctx, GUILD_MEMBERS["show_build"], "cannot_send")
            await ctx.followup.send(msg, ephemeral=True)

    @discord.slash_command(
        name=GUILD_MEMBERS["notify_profile"]["name"]["en-US"],
        description=GUILD_MEMBERS["notify_profile"]["description"]["en-US"],
        name_localizations=GUILD_MEMBERS["notify_profile"]["name"],
        description_localizations=GUILD_MEMBERS["notify_profile"]["description"]
    )
    @commands.has_permissions(manage_roles=True)
    async def notify_incomplete_profiles(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        guild = ctx.guild
        guild_id = guild.id

        incomplete_members = []
        for (g, member_id), data in self.guild_members.items():
            if g == guild_id:
                gs = data.get("GS", 0)
                weapons = data.get("weapons", "NULL")
                if gs in (0, "0", 0.0) or weapons == "NULL":
                    incomplete_members.append(member_id)

        if not incomplete_members:
            msg = get_user_message(ctx, GUILD_MEMBERS["notify_profile"], "no_inc_profiles")
            await ctx.followup.send(msg, ephemeral=True)
            return

        successes = 0
        failures = 0
        for member_id in incomplete_members:
            member = guild.get_member(member_id)
            msg = get_user_message(ctx, GUILD_MEMBERS["notify_profile"], "mp_sent")
            if member:
                try:
                    await member.send(msg)
                    successes += 1
                except Exception as e:
                    logging.error(f"[GuildMembers] Error sending DM to {member.display_name} (ID: {member_id}): {e}")
                    failures += 1
            else:
                failures += 1

        msg = get_user_message(ctx, GUILD_MEMBERS["notify_profile"], "success", successes=successes, failures=failures)
        await ctx.followup.send(msg,ephemeral=True)

    @discord.slash_command(
        name=CONFIG_ROSTER_DATA.get("name", {}).get("en-US", "config_roster"),
        description=CONFIG_ROSTER_DATA.get("description", {}).get("en-US", "Configure ideal roster sizes by class for the guild"),
        name_localizations=CONFIG_ROSTER_DATA.get("name", {}),
        description_localizations=CONFIG_ROSTER_DATA.get("description", {})
    )
    @commands.has_permissions(administrator=True)
    async def config_roster(
        self,
        ctx: discord.ApplicationContext,
        tank: int = discord.Option(
            int,
            description=CONFIG_ROSTER_DATA.get("options", {}).get("tank", {}).get("description", {}).get("en-US", "Ideal number of Tanks"),
            description_localizations=CONFIG_ROSTER_DATA.get("options", {}).get("tank", {}).get("description", {}),
            min_value=0,
            max_value=100,
            default=20
        ),
        healer: int = discord.Option(
            int,
            description=CONFIG_ROSTER_DATA.get("options", {}).get("healer", {}).get("description", {}).get("en-US", "Ideal number of Healers"),
            description_localizations=CONFIG_ROSTER_DATA.get("options", {}).get("healer", {}).get("description", {}),
            min_value=0,
            max_value=100,
            default=20
        ),
        flanker: int = discord.Option(
            int,
            description=CONFIG_ROSTER_DATA.get("options", {}).get("flanker", {}).get("description", {}).get("en-US", "Ideal number of Flankers"),
            description_localizations=CONFIG_ROSTER_DATA.get("options", {}).get("flanker", {}).get("description", {}),
            min_value=0,
            max_value=100,
            default=10
        ),
        ranged_dps: int = discord.Option(
            int,
            description=CONFIG_ROSTER_DATA.get("options", {}).get("ranged_dps", {}).get("description", {}).get("en-US", "Ideal number of Ranged DPS"),
            description_localizations=CONFIG_ROSTER_DATA.get("options", {}).get("ranged_dps", {}).get("description", {}),
            min_value=0,
            max_value=100,
            default=10
        ),
        melee_dps: int = discord.Option(
            int,
            description=CONFIG_ROSTER_DATA.get("options", {}).get("melee_dps", {}).get("description", {}).get("en-US", "Ideal number of Melee DPS"),
            description_localizations=CONFIG_ROSTER_DATA.get("options", {}).get("melee_dps", {}).get("description", {}),
            min_value=0,
            max_value=100,
            default=10
        )
    ):
        await ctx.defer(ephemeral=True)
        
        if not ctx.guild or not ctx.author:
            logging.error("[GuildMembers - ConfigRoster] Invalid context: missing guild or author")
            invalid_context_msg = get_user_message(ctx, CONFIG_ROSTER_DATA, "messages.invalid_context")
            await ctx.followup.send(invalid_context_msg, ephemeral=True)
            return
        
        guild_id = ctx.guild.id
        
        class_config = {
            "Tank": tank,
            "Healer": healer,
            "Flanker": flanker,
            "Ranged DPS": ranged_dps,
            "Melee DPS": melee_dps
        }
        
        try:
            for class_name, count in class_config.items():
                query = """
                    INSERT INTO guild_ideal_staff (guild_id, class_name, ideal_count) 
                    VALUES (%s, %s, %s) 
                    ON DUPLICATE KEY UPDATE ideal_count = VALUES(ideal_count)
                """
                await self.bot.run_db_query(query, (guild_id, class_name, count), commit=True)
            
            await self.load_ideal_staff()
            
            await self.update_recruitment_message(ctx)
            
            config_summary = "\n".join([f"- **{class_name}** : {count}" for class_name, count in class_config.items()])
            success_msg = get_user_message(ctx, CONFIG_ROSTER_DATA, "messages.success", config_summary=config_summary)
            
            await ctx.followup.send(success_msg, ephemeral=True)
            logging.debug(f"[GuildMembers - ConfigRoster] Ideal staff configuration updated for guild {guild_id}: {class_config}")
            
        except Exception as e:
            logging.exception(f"[GuildMembers - ConfigRoster] Error updating ideal staff config for guild {guild_id}: {e}")
            error_msg = get_user_message(ctx, CONFIG_ROSTER_DATA, "messages.update_error")
            await ctx.followup.send(error_msg, ephemeral=True)

    @discord.slash_command(
        name=GUILD_MEMBERS["change_language"]["name"]["en-US"],
        description=GUILD_MEMBERS["change_language"]["description"]["en-US"],
        name_localizations=GUILD_MEMBERS["change_language"]["name"],
        description_localizations=GUILD_MEMBERS["change_language"]["description"]
    )
    async def change_language(
        self,
        ctx: discord.ApplicationContext,
        language: str = discord.Option(
            str,
            description=GUILD_MEMBERS["change_language"]["options"]["language"]["description"]["en-US"],
            description_localizations=GUILD_MEMBERS["change_language"]["options"]["language"]["description"],
            choices=[
                discord.OptionChoice(name=global_translations["language_names"][locale], value=locale)
                for locale in global_translations.get("supported_locales", ["en-US"])
            ]
        )
    ):
        await ctx.defer(ephemeral=True)
        
        if not ctx.guild or not ctx.author:
            logging.error("[GuildMembers - ChangeLanguage] Invalid context: missing guild or author")
            return
        
        guild_id = ctx.guild.id
        member_id = ctx.author.id

        key = (guild_id, member_id)
        if key not in self.guild_members:
            not_registered_msg = get_user_message(ctx, GUILD_MEMBERS["change_language"], "messages.not_registered")
            await ctx.followup.send(not_registered_msg, ephemeral=True)
            return
        
        try:
            short_language = language[:2] if len(language) >= 2 else language
            
            query = "UPDATE guild_members SET language = %s WHERE guild_id = %s AND member_id = %s"
            await self.bot.run_db_query(query, (short_language, guild_id, member_id), commit=True)
            
            self.guild_members[key]["language"] = short_language
            
            language_name = global_translations.get("language_names", {}).get(language, language)
            
            success_msg = get_user_message(ctx, GUILD_MEMBERS["change_language"], "messages.success", language_name=language_name)
            await ctx.followup.send(success_msg, ephemeral=True)
            
            logging.debug(f"[GuildMembers - ChangeLanguage] Language updated for user {member_id} in guild {guild_id}: {language}")
            
        except Exception as e:
            logging.exception(f"[GuildMembers - ChangeLanguage] Error updating language for user {member_id} in guild {guild_id}: {e}")
            error_msg = get_user_message(ctx, GUILD_MEMBERS["change_language"], "messages.error", error=str(e))
            await ctx.followup.send(error_msg, ephemeral=True)

    async def run_maj_roster(self, guild_id: int) -> None:
        roles_config = self.roles.get(guild_id)
        if not roles_config:
            logging.error(f"[GuildMembers] No roles configured for guild {guild_id}")
            return

        members_role_id = roles_config.get("members")
        absent_role_id = roles_config.get("absent_members")
        if not members_role_id:
            logging.error(f"[GuildMembers] Members role not configured for guild {guild_id}")
            return

        guild = self.bot.get_guild(guild_id)
        if not guild:
            logging.error(f"[GuildMembers] Guild {guild_id} not found on Discord")
            return

        actual_members = {
            m.id: m for m in guild.members
            if not m.bot and (members_role_id in [r.id for r in m.roles] or absent_role_id in [r.id for r in m.roles])
        }

        keys_to_remove = []
        for (g, user_id), data in self.guild_members.items():
            if g == guild_id and user_id not in actual_members:
                delete_query = "DELETE FROM guild_members WHERE guild_id = %s AND member_id = %s"
                await self.bot.run_db_query(delete_query, (guild_id, user_id), commit=True)
                keys_to_remove.append((g, user_id))
        for key in keys_to_remove:
            del self.guild_members[key]

        for member in actual_members.values():
            key = (guild_id, member.id)
            if key in self.guild_members:
                record = self.guild_members[key]
                if record.get("username") != member.display_name:
                    record["username"] = member.display_name
                    update_query = "UPDATE guild_members SET username = %s WHERE guild_id = %s AND member_id = %s"
                    await self.bot.run_db_query(update_query, (member.display_name, guild_id, member.id), commit=True)
                    logging.debug(f"[GuildMembers] Username updated for {member.display_name} (ID: {member.id})")
            else:
                key_setup = (guild_id, member.id)
                user_setup = self.user_setup_members.get(key_setup, {})
                if user_setup:
                    language = user_setup.get("locale") or "en-US"
                    if language and '-' in language:
                        language = language.split('-')[0]
                    gs_value = user_setup.get("gs")
                    logging.debug(f"[GuildMembers] User setup values for {member.display_name}: language={language}, gs={gs_value}")
                else:
                    language = "en-US"
                    gs_value = 0
                    logging.debug(f"[GuildMembers] No user_setup info for {member.display_name}. Default values: language={language}, gs={gs_value}")
                if gs_value in (None, "", "NULL"):
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
                    "class": None
                }
                insert_query = """
                    INSERT INTO guild_members 
                    (guild_id, member_id, username, language, GS, build, weapons, DKP, nb_events, registrations, attendances, `class`)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        new_record["class"]
                    ),
                    commit=True
                )
                self.guild_members[key] = new_record
                logging.debug(f"[GuildMembers] New member added: {member.display_name} (ID: {member.id})")

        try:
            await self.load_guild_members()
            await self.update_recruitment_message(guild)
            await self.update_members_message(guild)
            logging.info(f"[GuildMembers] Roster synchronization completed for guild {guild_id}")
        except Exception as e:
            logging.exception(f"[GuildMembers] Error during roster synchronization for guild {guild_id}: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            asyncio.create_task(self.load_forum_channels())
            asyncio.create_task(self.load_roles())
            asyncio.create_task(self.load_weapons())
            asyncio.create_task(self.load_weapons_combinations())
            asyncio.create_task(self.load_user_setup_members())
            asyncio.create_task(self.load_guild_members())
            asyncio.create_task(self.load_ideal_staff())
            logging.debug("[GuildMembers] Database info caching tasks launched from on_ready")
        except Exception as e:
            logging.exception(f"[GuildMembers] Error during on_ready initialization: {e}")
    
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        try:
            if before.display_name == after.display_name:
                return

            guild_ptb_cog = self.bot.get_cog("GuildPTB")
            if not guild_ptb_cog:
                return
            
            main_guild_id = after.guild.id
            if main_guild_id not in guild_ptb_cog.guild_settings:
                return
            
            ptb_guild_id = guild_ptb_cog.guild_settings[main_guild_id].get("ptb_guild_id")
            if not ptb_guild_id:
                return

            ptb_guild = self.bot.get_guild(ptb_guild_id)
            if not ptb_guild:
                return

            ptb_member = ptb_guild.get_member(after.id)
            if not ptb_member:
                return

            try:
                await ptb_member.edit(nick=after.display_name, reason="Auto sync from main Discord server")
                logging.info(f"[GuildMembers] Synchronized PTB nickname for {after.id}: '{before.display_name}' -> '{after.display_name}'")
            except discord.Forbidden:
                logging.warning(f"[GuildMembers] Cannot change PTB nickname for {after.id} - insufficient permissions")
            except Exception as e:
                logging.error(f"[GuildMembers] Error changing PTB nickname for {after.id}: {e}")
                
        except Exception as e:
            logging.error(f"[GuildMembers] Error in on_member_update: {e}", exc_info=True)

def setup(bot: discord.Bot):
    bot.add_cog(GuildMembers(bot))
