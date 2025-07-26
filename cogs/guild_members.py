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
CONFIG_EFFECTIFS_DATA = global_translations.get("commands", {}).get("config_effectifs", {})

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
        self.max_pseudo_length = 32
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
            SELECT guild_id, user_id, pseudo, locale, gs, weapons
            FROM user_setup
            WHERE motif IN ('membre', 'postulation')
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.user_setup_members = {}
            for row in rows:
                guild_id, user_id, pseudo, locale, gs, weapons = row
                key = (int(guild_id), int(user_id))
                self.user_setup_members[key] = {
                    "pseudo": pseudo,
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
            SELECT guild_id, member_id, pseudo, lang, GS, build, armes, DKP, nb_events, inscriptions, presences, classe
            FROM guild_members
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.guild_members = {}
            for row in rows:
                guild_id, member_id, pseudo, lang, GS, build, armes, DKP, nb_events, inscriptions, presences, classe = row
                key = (guild_id, member_id)
                self.guild_members[key] = {
                    "pseudo": pseudo,
                    "lang": lang,
                    "GS": GS,
                    "build": build,
                    "armes": armes,
                    "DKP": DKP,
                    "nb_events": nb_events,
                    "inscriptions": inscriptions,
                    "presences": presences,
                    "classe": classe
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

    def determine_class(self, armes_list: list, guild_id: int) -> str:
        if not isinstance(armes_list, list) or not armes_list:
            return "NULL"
        
        guild_info = self.forum_channels.get(guild_id, {})
        game = guild_info.get("guild_game")
        if not game:
            return "NULL"
        
        game_id = self._validate_integer(game)
        if game_id is None:
            return "NULL"
        combinations = self.weapons_combinations.get(game_id, [])
        sorted_armes = sorted(armes_list)
        for combo in combinations:
            if sorted([combo["weapon1"], combo["weapon2"]]) == sorted_armes:
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
            query = "UPDATE guild_members SET GS = ? WHERE guild_id = ? AND member_id = ?"
            await self.bot.run_db_query(query, (validated_value, guild_id, member_id), commit=True)
            self.guild_members[key]["GS"] = validated_value
            logging.debug(f"[GuildMembers - GS] Successfully updated GS for {ctx.author} (ID: {member_id}) to {validated_value}")
            msg = get_user_message(ctx, GUILD_MEMBERS["gs"], "updated", pseudo=ctx.author.display_name, value=validated_value)
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
    async def armes(
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

        arme1_code = self._validate_weapon_code(weapon1)
        arme2_code = self._validate_weapon_code(weapon2)
        
        if not arme1_code or not arme2_code:
            msg = get_user_message(ctx, GUILD_MEMBERS["weapons"], "not_valid")
            await ctx.followup.send(msg, ephemeral=True)
            return
        
        if arme1_code == arme2_code:
            msg = get_user_message(ctx, GUILD_MEMBERS["weapons"], "not_valid_same")
            await ctx.followup.send(msg, ephemeral=True)
            return

        valid_weapons = self.get_valid_weapons(guild_id)
        if arme1_code not in valid_weapons or arme2_code not in valid_weapons:
            msg = get_user_message(ctx, GUILD_MEMBERS["weapons"], "not_valid")
            await ctx.followup.send(msg, ephemeral=True)
            return

        try:
            armes_normalized = sorted([arme1_code, arme2_code])
            player_class = self.determine_class(armes_normalized, guild_id)
            armes_str = "/".join(armes_normalized)
            
            query = "UPDATE guild_members SET armes = ?, classe = ? WHERE guild_id = ? AND member_id = ?"
            await self.bot.run_db_query(query, (armes_str, player_class, guild_id, member_id), commit=True)
            
            self.guild_members[key]["armes"] = armes_str
            self.guild_members[key]["classe"] = player_class

            msg = get_user_message(ctx, GUILD_MEMBERS["weapons"], "updated", pseudo=ctx.author.display_name, armes_str=armes_str)
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
            query = "UPDATE guild_members SET build = ? WHERE guild_id = ? AND member_id = ?"
            await self.bot.run_db_query(query, (sanitized_url, guild_id, member_id), commit=True)
            self.guild_members[key]["build"] = sanitized_url
            msg = get_user_message(ctx, GUILD_MEMBERS["build"], "updated", pseudo=ctx.author.display_name)
            await ctx.followup.send(msg, ephemeral=True)
        except Exception as e:
            logging.exception(f"[GuildMembers - Build] Error updating build for {ctx.author} (ID: {member_id}): {e}")
            await ctx.followup.send("❌ Database error occurred", ephemeral=True)

    @discord.slash_command(
        name=GUILD_MEMBERS["pseudo"]["name"]["en-US"],
        description=GUILD_MEMBERS["pseudo"]["description"]["en-US"],
        name_localizations=GUILD_MEMBERS["pseudo"]["name"],
        description_localizations=GUILD_MEMBERS["pseudo"]["description"]
    )
    async def pseudo(
        self,
        ctx: discord.ApplicationContext,
        new_name: str = discord.Option(
            description=GUILD_MEMBERS["pseudo"]["value_comment"]["en-US"],
            description_localizations=GUILD_MEMBERS["pseudo"]["value_comment"]
        ),
    ):
        await ctx.defer(ephemeral=True)
        
        if not ctx.guild or not ctx.author:
            logging.error("[GuildMembers - Pseudo] Invalid context: missing guild or author")
            await ctx.followup.send("❌ Invalid request context", ephemeral=True)
            return
        
        guild_id = ctx.guild.id
        member_id = ctx.author.id
        key = (guild_id, member_id)
        
        if key not in self.guild_members:
            msg = get_user_message(ctx, GUILD_MEMBERS["pseudo"], "not_registered")
            await ctx.followup.send(msg, ephemeral=True)
            return

        new_pseudo = self._sanitize_string(new_name, self.max_pseudo_length)
        if not new_pseudo or len(new_pseudo.strip()) == 0:
            await ctx.followup.send("❌ Invalid pseudo name", ephemeral=True)
            return
        
        try:
            query = "UPDATE guild_members SET pseudo = ? WHERE guild_id = ? AND member_id = ?"
            await self.bot.run_db_query(query, (new_pseudo, guild_id, member_id), commit=True)
            self.guild_members[key]["pseudo"] = new_pseudo
            
            try:
                await ctx.author.edit(nick=new_pseudo)
            except discord.Forbidden:
                logging.warning(f"[GuildMembers - Pseudo] Unable to update nickname for {ctx.author.display_name}")
            except Exception as e:
                logging.warning(f"[GuildMembers - Pseudo] Error updating nickname for {ctx.author.display_name}: {e}")
            
            msg = get_user_message(ctx, GUILD_MEMBERS["pseudo"], "updated", pseudo=new_pseudo)
            await ctx.followup.send(msg, ephemeral=True)
        except Exception as e:
            logging.exception(f"[GuildMembers - Pseudo] Error updating pseudo for {ctx.author} (ID: {member_id}): {e}")
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
                delete_query = "DELETE FROM guild_members WHERE guild_id = ? AND member_id = ?"
                await self.bot.run_db_query(delete_query, (guild_id, user_id), commit=True)
                keys_to_remove.append((g, user_id))
        for key in keys_to_remove:
            del self.guild_members[key]

        for member in actual_members.values():
            key = (int(guild_id), int(member.id))
            if key in self.guild_members:
                record = self.guild_members[key]
                if record.get("pseudo") != member.display_name:
                    record["pseudo"] = member.display_name
                    update_query = "UPDATE guild_members SET pseudo = ? WHERE guild_id = ? AND member_id = ?"
                    await self.bot.run_db_query(update_query, (member.display_name, guild_id, member.id), commit=True)
                    logging.debug(f"[GuildMembers - MAJ_Roster] Pseudo updated for {member.display_name} (ID: {member.id})")
            else:
                user_setup = self.user_setup_members.get(key, {})
                if user_setup:
                    lang = user_setup.get("locale") or locale
                    gs_value = user_setup.get("gs")
                    logging.debug(f"[GuildMembers - MAJ_Roster] Values retrieved from user_setup for {member.display_name}: lang={lang}, gs={gs_value}")

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
                    lang = locale
                    gs_value = 0
                    weapons_normalized = "NULL"
                    computed_class = "NULL"
                    logging.debug(f"[GuildMembers - MAJ_Roster] No user_setup info for {member.display_name}. Default values: lang={lang}, gs={gs_value}")

                if lang and '-' in lang:
                    lang = lang.split('-')[0]

                if gs_value in (None, "", "NULL"):
                    gs_value = 0

                new_record = {
                    "pseudo": member.display_name,
                    "lang": lang,
                    "GS": gs_value,
                    "build": "NULL",
                    "armes": weapons_normalized,
                    "DKP": 0,
                    "nb_events": 0,
                    "inscriptions": 0,
                    "presences": 0,
                    "classe": computed_class
                }
                insert_query = """
                    INSERT INTO guild_members 
                    (guild_id, member_id, pseudo, lang, GS, build, armes, DKP, nb_events, inscriptions, presences, classe)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                await self.bot.run_db_query(
                    insert_query,
                    (
                        guild_id,
                        member.id,
                        new_record["pseudo"],
                        new_record["lang"],
                        new_record["GS"],
                        new_record["build"],
                        new_record["armes"],
                        new_record["DKP"],
                        new_record["nb_events"],
                        new_record["inscriptions"],
                        new_record["presences"],
                        new_record["classe"]
                    ),
                    commit=True
                )
                self.guild_members[key] = new_record
                logging.debug(f"[GuildMembers - MAJ_Roster] New member added: {member.display_name} (ID: {member.id})")

        try:
            await self.load_guild_members()
            await self.update_recruitment_message(ctx)
            await self.update_members_message(ctx)

            msg = get_user_message(ctx, GUILD_MEMBERS["maj_roster"], "updated")
            await ctx.followup.send(msg, ephemeral=True)
        except Exception as e:
            logging.exception(f"[GuildMembers - MAJ_Roster] Error during roster update: {e}")
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
        effectif_max = guild_config.get("max_members")

        ideal_staff = self.ideal_staff.get(guild_id, {
            "Tank": 20,
            "Healer": 20,
            "Flanker": 10,
            "Ranged DPS": 10,
            "Melee DPS": 10
        })

        class_counts = { key: 0 for key in ideal_staff.keys() }
        for m in members_in_roster:
            cls = m.get("classe", "NULL")
            if cls in ideal_staff:
                class_counts[cls] += 1

        places_restantes = max(0, effectif_max - total_members)

        title = GUILD_MEMBERS["post_recrut"]["name"][locale]
        effectif_template = GUILD_MEMBERS["post_recrut"]["effectif"][locale]
        effectif_line = effectif_template.format(total_members=total_members, effectif_max=effectif_max)
        places_template = GUILD_MEMBERS["post_recrut"]["places"][locale]
        places_line = places_template.format(places_restantes=places_restantes)
        post_dispos_template = GUILD_MEMBERS["post_recrut"]["post_dispos"][locale]
        updated_template = GUILD_MEMBERS["post_recrut"]["updated"][locale]

        positions_details = ""
        for cls_key, ideal_number in ideal_staff.items():
            class_name = GUILD_MEMBERS["class"][cls_key][locale]
            current_count = class_counts.get(cls_key, 0)
            available = max(0, ideal_number - current_count)
            positions_details += f"- **{class_name}** : {available} \n"

        description = effectif_line + places_line + post_dispos_template + positions_details

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
        sorted_members = sorted(members_in_roster, key=lambda x: x.get("pseudo", "").lower())

        tank_count = sum(1 for m in sorted_members if m.get("classe", "").lower() == "tank")
        dps_melee_count = sum(1 for m in sorted_members if m.get("classe", "").lower() == "melee dps")
        dps_distant_count = sum(1 for m in sorted_members if m.get("classe", "").lower() == "ranged dps")
        heal_count = sum(1 for m in sorted_members if m.get("classe", "").lower() == "healer")
        flank_count = sum(1 for m in sorted_members if m.get("classe", "").lower() == "flanker")

        pseudo_width = 20
        lang_width = 8
        gs_width = 8
        build_width = 7
        armes_width = 9
        classe_width = 14
        dkp_width = 10
        insc_width = 8
        pres_width = 8

        header_labels = GUILD_MEMBERS.get("table", {}).get("header", {}).get(locale, 
            ["Pseudo", "Langue", "GS", "Build", "Armes", "Classe", "DKP", "%Insc", "%Prés"])
        
        header = (
            f"{header_labels[0].ljust(pseudo_width)}│"
            f"{header_labels[1].center(lang_width)}│"
            f"{header_labels[2].center(gs_width)}│"
            f"{header_labels[3].center(build_width)}│"
            f"{header_labels[4].center(armes_width)}│"
            f"{header_labels[5].center(classe_width)}│"
            f"{header_labels[6].center(dkp_width)}│"
            f"{header_labels[7].center(insc_width)}│"
            f"{header_labels[8].center(pres_width)}"
        )
        separator = "─" * len(header)

        rows = []
        for m in sorted_members:
            pseudo = m.get("pseudo", "")[:pseudo_width].ljust(pseudo_width)
            lang_text = str(m.get("lang", "en-US"))[:lang_width].center(lang_width)
            gs = str(m.get("GS", "NULL")).center(gs_width)
            build_flag = "Y" if m.get("build", "NULL") != "NULL" else " "
            build_flag = build_flag.center(build_width)
            armes = m.get("armes", "NULL")
            if isinstance(armes, str) and armes != "NULL":
                armes_str = armes.center(armes_width)
            else:
                armes_str = " ".center(armes_width)
            classe = m.get("classe", "NULL")
            if isinstance(classe, str) and classe != "NULL":
                classe_str = classe.center(classe_width)
            else :
                classe_str = " ".center(classe_width)
            dkp = str(m.get("DKP", 0)).center(dkp_width)
            nb_events = m.get("nb_events", 0)
            if nb_events > 0:
                insc_pct = round((m.get("inscriptions", 0) / nb_events) * 100)
                pres_pct = round((m.get("presences", 0) / nb_events) * 100)
            else:
                insc_pct = 0
                pres_pct = 0
            inscriptions = f"{insc_pct}%".center(insc_width)
            presences = f"{pres_pct}%".center(pres_width)
            rows.append(f"{pseudo}│{lang_text}│{gs}│{build_flag}│{armes_str}│{classe_str}│{dkp}│{inscriptions}│{presences}")

        if not rows:
            logging.warning("[GuildMembers] No members found in roster")
            return

        now_str = datetime.now().strftime("%d/%m/%Y à %H:%M")
        role_labels = GUILD_MEMBERS.get("table", {}).get("role_stats", {}).get(locale,
            ["Tank", "DPS Mélée", "DPS Distance", "Healer", "Flanker"])
        
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
                message = await channel.fetch_message(message_ids[i])
                if i < len(message_contents):
                    await message.edit(content=message_contents[i])
                else:
                    await message.edit(content=".")
        except discord.NotFound:
            logging.warning("[GuildMembers] One or more roster messages not found")
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
        pseudo: str = discord.Option(
            description=GUILD_MEMBERS["show_build"]["value_comment"]["en-US"],
            description_localizations=GUILD_MEMBERS["show_build"]["value_comment"]
        ),
    ):
        await ctx.defer(ephemeral=True)
        
        if not ctx.guild or not ctx.author:
            logging.error("[GuildMembers - ShowBuild] Invalid context: missing guild or author")
            await ctx.followup.send("❌ Invalid request context", ephemeral=True)
            return
        
        sanitized_pseudo = self._sanitize_string(pseudo, 32)
        if not sanitized_pseudo:
            await ctx.followup.send("❌ Invalid pseudo format", ephemeral=True)
            return
        
        guild_id = ctx.guild.id
        matching = [m for (g, _), m in self.guild_members.items() 
                   if g == guild_id and m.get("pseudo", "").lower().startswith(sanitized_pseudo.lower())]

        if not matching:
            msg = get_user_message(ctx, GUILD_MEMBERS["show_build"], "not_found", pseudo=pseudo)
            await ctx.followup.send(msg, ephemeral=True)
            return

        member_data = matching[0]
        build_url = member_data.get("build", "NULL")
        if build_url == "NULL":
            msg = get_user_message(ctx, GUILD_MEMBERS["show_build"], "no_build", pseudo=pseudo)
            await ctx.followup.send(msg, ephemeral=True)
            return

        try:
            msg = get_user_message(ctx, GUILD_MEMBERS["show_build"], "build_sent", member=member_data.get('pseudo'), build_url=build_url)
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
                armes = data.get("armes", "NULL")
                if gs in (0, "0", 0.0) or armes == "NULL":
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
        name=CONFIG_EFFECTIFS_DATA.get("name", {}).get("en-US", "config_effectifs"),
        description=CONFIG_EFFECTIFS_DATA.get("description", {}).get("en-US", "Configure les effectifs idéaux par classe pour la guilde"),
        name_localizations=CONFIG_EFFECTIFS_DATA.get("name", {}),
        description_localizations=CONFIG_EFFECTIFS_DATA.get("description", {})
    )
    @commands.has_permissions(administrator=True)
    async def config_effectifs(
        self,
        ctx: discord.ApplicationContext,
        tank: int = discord.Option(
            int,
            description=CONFIG_EFFECTIFS_DATA.get("options", {}).get("tank", {}).get("description", {}).get("en-US", "Nombre idéal de Tank"),
            description_localizations=CONFIG_EFFECTIFS_DATA.get("options", {}).get("tank", {}).get("description", {}),
            min_value=0,
            max_value=100,
            default=20
        ),
        healer: int = discord.Option(
            int,
            description=CONFIG_EFFECTIFS_DATA.get("options", {}).get("healer", {}).get("description", {}).get("en-US", "Nombre idéal de Healer"),
            description_localizations=CONFIG_EFFECTIFS_DATA.get("options", {}).get("healer", {}).get("description", {}),
            min_value=0,
            max_value=100,
            default=20
        ),
        flanker: int = discord.Option(
            int,
            description=CONFIG_EFFECTIFS_DATA.get("options", {}).get("flanker", {}).get("description", {}).get("en-US", "Nombre idéal de Flanker"),
            description_localizations=CONFIG_EFFECTIFS_DATA.get("options", {}).get("flanker", {}).get("description", {}),
            min_value=0,
            max_value=100,
            default=10
        ),
        ranged_dps: int = discord.Option(
            int,
            description=CONFIG_EFFECTIFS_DATA.get("options", {}).get("ranged_dps", {}).get("description", {}).get("en-US", "Nombre idéal de Ranged DPS"),
            description_localizations=CONFIG_EFFECTIFS_DATA.get("options", {}).get("ranged_dps", {}).get("description", {}),
            min_value=0,
            max_value=100,
            default=10
        ),
        melee_dps: int = discord.Option(
            int,
            description=CONFIG_EFFECTIFS_DATA.get("options", {}).get("melee_dps", {}).get("description", {}).get("en-US", "Nombre idéal de Melee DPS"),
            description_localizations=CONFIG_EFFECTIFS_DATA.get("options", {}).get("melee_dps", {}).get("description", {}),
            min_value=0,
            max_value=100,
            default=10
        )
    ):
        await ctx.defer(ephemeral=True)
        
        if not ctx.guild or not ctx.author:
            logging.error("[GuildMembers - Config_Effectifs] Invalid context: missing guild or author")
            invalid_context_msg = get_user_message(ctx, CONFIG_EFFECTIFS_DATA, "messages.invalid_context")
            await ctx.followup.send(invalid_context_msg, ephemeral=True)
            return
        
        guild_id = ctx.guild.id
        
        classes_config = {
            "Tank": tank,
            "Healer": healer,
            "Flanker": flanker,
            "Ranged DPS": ranged_dps,
            "Melee DPS": melee_dps
        }
        
        try:
            for class_name, count in classes_config.items():
                query = """
                    INSERT INTO guild_ideal_staff (guild_id, class_name, ideal_count) 
                    VALUES (?, ?, ?) 
                    ON DUPLICATE KEY UPDATE ideal_count = VALUES(ideal_count)
                """
                await self.bot.run_db_query(query, (guild_id, class_name, count), commit=True)
            
            await self.load_ideal_staff()
            
            await self.update_recruitment_message(ctx)
            
            config_summary = "\\n".join([f"- **{class_name}** : {count}" for class_name, count in classes_config.items()])
            success_msg = get_user_message(ctx, CONFIG_EFFECTIFS_DATA, "messages.success", config_summary=config_summary)
            
            await ctx.followup.send(success_msg, ephemeral=True)
            logging.debug(f"[GuildMembers - Config_Effectifs] Ideal staff configuration updated for guild {guild_id}: {classes_config}")
            
        except Exception as e:
            logging.exception(f"[GuildMembers - Config_Effectifs] Error updating ideal staff config for guild {guild_id}: {e}")
            error_msg = get_user_message(ctx, CONFIG_EFFECTIFS_DATA, "messages.update_error")
            await ctx.followup.send(error_msg, ephemeral=True)

    @discord.slash_command(
        name=GUILD_MEMBERS["change_langue"]["name"]["en-US"],
        description=GUILD_MEMBERS["change_langue"]["description"]["en-US"],
        name_localizations=GUILD_MEMBERS["change_langue"]["name"],
        description_localizations=GUILD_MEMBERS["change_langue"]["description"]
    )
    async def change_langue(
        self,
        ctx: discord.ApplicationContext,
        langue: str = discord.Option(
            str,
            description=GUILD_MEMBERS["change_langue"]["options"]["langue"]["description"]["en-US"],
            description_localizations=GUILD_MEMBERS["change_langue"]["options"]["langue"]["description"],
            choices=[
                discord.OptionChoice(name="English", value="en-US"),
                discord.OptionChoice(name="Français", value="fr"),
                discord.OptionChoice(name="Español", value="es-ES"),
                discord.OptionChoice(name="Deutsch", value="de"),
                discord.OptionChoice(name="Italiano", value="it")
            ]
        )
    ):
        await ctx.defer(ephemeral=True)
        
        if not ctx.guild or not ctx.author:
            logging.error("[GuildMembers - Change_Langue] Invalid context: missing guild or author")
            return
        
        guild_id = ctx.guild.id
        member_id = ctx.author.id

        key = (guild_id, member_id)
        if key not in self.guild_members:
            not_registered_msg = get_user_message(ctx, GUILD_MEMBERS["change_langue"], "messages.not_registered")
            await ctx.followup.send(not_registered_msg, ephemeral=True)
            return
        
        try:
            query = "UPDATE guild_members SET lang = ? WHERE guild_id = ? AND member_id = ?"
            await self.bot.run_db_query(query, (langue, guild_id, member_id), commit=True)
            
            self.guild_members[key]["lang"] = langue
            
            language_names = {
                "en": "English",
                "fr": "Français", 
                "es": "Español",
                "de": "Deutsch",
                "it": "Italiano"
            }
            language_name = language_names.get(langue, langue)
            
            success_msg = get_user_message(ctx, GUILD_MEMBERS["change_langue"], "messages.success", language_name=language_name)
            await ctx.followup.send(success_msg, ephemeral=True)
            
            logging.debug(f"[GuildMembers - Change_Langue] Language updated for user {member_id} in guild {guild_id}: {langue}")
            
        except Exception as e:
            logging.exception(f"[GuildMembers - Change_Langue] Error updating language for user {member_id} in guild {guild_id}: {e}")
            error_msg = get_user_message(ctx, GUILD_MEMBERS["change_langue"], "messages.error", error=str(e))
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
                delete_query = "DELETE FROM guild_members WHERE guild_id = ? AND member_id = ?"
                await self.bot.run_db_query(delete_query, (guild_id, user_id), commit=True)
                keys_to_remove.append((g, user_id))
        for key in keys_to_remove:
            del self.guild_members[key]

        for member in actual_members.values():
            key = (guild_id, member.id)
            if key in self.guild_members:
                record = self.guild_members[key]
                if record.get("pseudo") != member.display_name:
                    record["pseudo"] = member.display_name
                    update_query = "UPDATE guild_members SET pseudo = ? WHERE guild_id = ? AND member_id = ?"
                    await self.bot.run_db_query(update_query, (member.display_name, guild_id, member.id), commit=True)
                    logging.debug(f"[GuildMembers] Pseudo updated for {member.display_name} (ID: {member.id})")
            else:
                key_setup = (guild_id, member.id)
                user_setup = self.user_setup_members.get(key_setup, {})
                if user_setup:
                    lang = user_setup.get("locale") or "en-US"
                    if lang and '-' in lang:
                        lang = lang.split('-')[0]
                    gs_value = user_setup.get("gs")
                    logging.debug(f"[GuildMembers] Valeurs user_setup pour {member.display_name} : lang={lang}, gs={gs_value}")
                else:
                    lang = "en-US"
                    gs_value = 0
                    logging.debug(f"[GuildMembers] Pas d'info user_setup pour {member.display_name}. Valeurs par défaut : lang={lang}, gs={gs_value}")
                if gs_value in (None, "", "NULL"):
                    gs_value = 0
                new_record = {
                    "pseudo": member.display_name,
                    "lang": lang,
                    "GS": gs_value,
                    "build": "NULL",
                    "armes": "NULL",
                    "DKP": 0,
                    "nb_events": 0,
                    "inscriptions": 0,
                    "presences": 0,
                    "classe": "NULL"
                }
                insert_query = """
                    INSERT INTO guild_members 
                    (guild_id, member_id, pseudo, lang, GS, build, armes, DKP, nb_events, inscriptions, presences, classe)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                await self.bot.run_db_query(
                    insert_query,
                    (
                        guild_id,
                        member.id,
                        new_record["pseudo"],
                        new_record["lang"],
                        new_record["GS"],
                        new_record["build"],
                        new_record["armes"],
                        new_record["DKP"],
                        new_record["nb_events"],
                        new_record["inscriptions"],
                        new_record["presences"],
                        new_record["classe"]
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

def setup(bot: discord.Bot):
    bot.add_cog(GuildMembers(bot))
