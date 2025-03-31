import discord
from discord.ext import commands
import asyncio
import pytz
import logging
from typing import Dict, List, Tuple, Any
from discord.ext import commands, tasks
from functions import get_user_message
from datetime import datetime, timedelta
from translation import translations as global_translations

GUILD_MEMBERS = global_translations.get("guild_members", {})

class GuildMembers(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.forum_channels: Dict[int, Dict[str, Any]] = {}
        self.roles: Dict[int, Dict[str, int]] = {}
        self.weapons: Dict[int, Dict[str, str]] = {}
        self.weapons_combinations: Dict[int, List[Dict[str, str]]] = {}
        self.user_setup_members: Dict[Tuple[int, int], Dict[str, Any]] = {}
        self.guild_members: Dict[Tuple[int, int], Dict[str, Any]] = {}

    async def load_forum_channels(self) -> None:
        logging.debug("[GuildMembers] Chargement des channels de forum depuis la BDD")
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
            logging.debug(f"[GuildMembers] Channels chargés : {self.forum_channels}")
        except Exception as e:
            logging.error(f"[GuildMembers] Erreur lors du chargement des channels de forum : {e}")

    async def load_roles(self) -> None:
        logging.debug("[GuildMembers] Chargement des rôles depuis la BDD")
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
            logging.debug(f"[GuildMembers] Rôles chargés : {self.roles}")
        except Exception as e:
            logging.error(f"[GuildMembers] Erreur lors du chargement des rôles : {e}")

    async def load_weapons(self) -> None:
        query = "SELECT game_id, code, name FROM weapons ORDER BY game_id;"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.weapons = {}
            for row in rows:
                game_id, code, name = row
                if game_id not in self.weapons:
                    self.weapons[game_id] = {}
                self.weapons[game_id][code] = name
            logging.debug(f"[GuildMembers] Armes chargées: {self.weapons}")
        except Exception as e:
            logging.error(f"[GuildMembers] Erreur lors du chargement des armes : {e}")

    async def load_weapons_combinations(self) -> None:
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
            logging.debug(f"[GuildMembers] Combinaisons d'armes chargées: {self.weapons_combinations}")
        except Exception as e:
            logging.error("Erreur lors du chargement des combinaisons d'armes", exc_info=True)

    async def load_user_setup_members(self) -> Dict[Tuple[int, int], Dict[str, Any]]:
        """
        Charge depuis la BDD les informations de la table user_setup pour les membres dont le motif est "membre".
        Retourne un dictionnaire indexé par (guild_id, user_id) contenant :
            - pseudo
            - locale
            - gs
            - weapons
        """
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
            logging.error("Error loading user setup members", exc_info=True)

    async def load_guild_members(self) -> None:
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
                    "armes": armes,  # stocké en chaîne (ex: "SNS/GS")
                    "DKP": DKP,
                    "nb_events": nb_events,
                    "inscriptions": inscriptions,
                    "presences": presences,
                    "classe": classe
                }
            logging.debug(f"[GuildMembers] Membres chargés: {self.guild_members}")
        except Exception as e:
            logging.error("Erreur lors du chargement des membres de la guilde", exc_info=True)

    def determine_class(self, armes_list: list, guild_id: int) -> str:
        """
        Détermine la classe du joueur en se basant sur la combinaison d'armes.
        Utilise le mapping chargé depuis la BDD.
        """
        guild_info = self.forum_channels.get(guild_id, {})
        game = guild_info.get("guild_game")
        if not game:
            return "NULL"
        try:
            game_id = int(game)
        except:
            return "NULL"
        combinations = self.weapons_combinations.get(game_id, [])
        sorted_armes = sorted(armes_list)
        for combo in combinations:
            if sorted([combo["weapon1"], combo["weapon2"]]) == sorted_armes:
                return combo["role"]
        return "NULL"

    def get_valid_weapons(self, guild_id: int) -> set:
        """
        Construit un ensemble des armes valides en se basant sur le mapping pour la guilde.
        """
        valid = set()
        guild_info = self.forum_channels.get(guild_id, {})
        game = guild_info.get("guild_game")
        if not game:
            return valid
        try:
            game_id = int(game)
        except:
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
        guild_id = ctx.guild.id
        member_id = ctx.author.id
        key = (guild_id, member_id)
        value = int(value)
        if key not in self.guild_members:
            logging.debug(f"[GS] Profil non trouvé pour la clé {key}.")
            msg = get_user_message(ctx, GUILD_MEMBERS["gs"], "not_registered")
            await ctx.followup.send(msg, ephemeral=True)
            return

        if value <= 0:
            logging.debug(f"[GS] Valeur non positive fournie par {ctx.author} : {value}.")
            msg = get_user_message(ctx, GUILD_MEMBERS["gs"], "not_positive")
            try:
                await ctx.followup.send(msg, ephemeral=True)
            except Exception as ex:
                logging.exception(f"[GS] Erreur lors de ctx.followup.send dans la branche valeur non positive: {ex}")
            return

        try: 
            query = "UPDATE guild_members SET GS = ? WHERE guild_id = ? AND member_id = ?"
            await self.bot.run_db_query(query, (value, guild_id, member_id), commit=True)
            self.guild_members[key]["GS"] = value
            logging.debug(f"[GS] Mise à jour réussie : GS de {ctx.author} (ID: {member_id}) mis à jour à {value}.")
            msg = get_user_message(ctx, GUILD_MEMBERS["gs"], "updated", pseudo=ctx.author.display_name, value=value)
            await ctx.followup.send(msg, ephemeral=True)
        except Exception as e:
            logging.exception(f"[GS] Erreur lors de la mise à jour du GS pour {ctx.author} (ID: {member_id}): {e}")
            await ctx.followup.send("❌ Error ", ephemeral=True)

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
        guild_id = ctx.guild.id
        member_id = ctx.author.id
        key = (guild_id, member_id)
        if key not in self.guild_members:
            msg = get_user_message(ctx, GUILD_MEMBERS["weapons"], "not_registered")
            await ctx.followup.send(msg, ephemeral=True)
            return

        arme1_code = weapon1.strip().upper()
        arme2_code = weapon2.strip().upper()
        if arme1_code == arme2_code:
            msg = get_user_message(ctx, GUILD_MEMBERS["weapons"], "not_valid_same")
            await ctx.followup.send(msg, ephemeral=True)
            return

        valid_weapons = self.get_valid_weapons(guild_id)
        if arme1_code not in valid_weapons or arme2_code not in valid_weapons:
            msg = get_user_message(ctx, GUILD_MEMBERS["weapons"], "not_valid")
            await ctx.followup.send(msg, ephemeral=True)
            return

        armes_normalized = sorted([arme1_code, arme2_code])
        player_class = self.determine_class(armes_normalized, guild_id)
        armes_str = "/".join(armes_normalized)
        query = "UPDATE guild_members SET armes = ?, classe = ? WHERE guild_id = ? AND member_id = ?"
        await self.bot.run_db_query(query, (armes_str, player_class, guild_id, member_id), commit=True)
        self.guild_members[key]["armes"] = armes_str
        self.guild_members[key]["classe"] = player_class

        msg = get_user_message(ctx, GUILD_MEMBERS["weapons"], "updated", pseudo=ctx.author.display_name, armes_str=armes_str)
        await ctx.followup.send(msg, ephemeral=True)

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

        if not (url.startswith("https://questlog.gg/") or url.startswith("https://maxroll.gg/")):
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

        query = "UPDATE guild_members SET build = ? WHERE guild_id = ? AND member_id = ?"
        await self.bot.run_db_query(query, (url, guild_id, member_id), commit=True)
        self.guild_members[key]["build"] = url
        msg = get_user_message(ctx, GUILD_MEMBERS["build"], "updated", pseudo=ctx.author.display_name)
        await ctx.followup.send(msg, ephemeral=True)

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
        guild_id = ctx.guild.id
        member_id = ctx.author.id
        key = (guild_id, member_id)
        if key not in self.guild_members:
            msg = get_user_message(ctx, GUILD_MEMBERS["build"], "not_registered")
            await ctx.followup.send(msg, ephemeral=True)
            return
        new_pseudo = new_name.strip()
        query = "UPDATE guild_members SET pseudo = ? WHERE guild_id = ? AND member_id = ?"
        await self.bot.run_db_query(query, (new_pseudo, guild_id, member_id), commit=True)
        self.guild_members[key]["pseudo"] = new_pseudo
        try:
            await ctx.author.edit(nick=new_pseudo)
        except discord.Forbidden:
            logging.warning(f"⚠️ Impossible de mettre à jour le pseudo de {ctx.author.display_name}.")
        msg = get_user_message(ctx, GUILD_MEMBERS["pseudo"], "updated", pseudo=new_pseudo)
        await ctx.followup.send(msg, ephemeral=True)

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
                    logging.debug(f"[GuildMembers] Pseudo mis à jour pour {member.display_name} (ID: {member.id}).")
            else:
                user_setup = self.user_setup_members.get(key, {})
                if user_setup:
                    lang = user_setup.get("locale") or locale
                    gs_value = user_setup.get("gs")
                    logging.debug(f"[GuildMembers] Valeurs récupérées depuis user_setup pour {member.display_name}: lang={lang}, gs={gs_value}")

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
                    logging.debug(f"[GuildMembers] Pas d'info user_setup pour {member.display_name}. Valeurs par défaut: lang={lang}, gs={gs_value}")

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
                logging.debug(f"[GuildMembers] Nouveau membre ajouté : {member.display_name} (ID: {member.id}).")

        await self.load_guild_members()
        await self.update_recruitment_message(ctx)
        await self.update_members_message(ctx)

        msg = get_user_message(ctx, GUILD_MEMBERS["maj_roster"], "updated")
        await ctx.followup.send(msg, ephemeral=True)

    async def update_recruitment_message(self, ctx):
        if hasattr(ctx, "guild"):
            guild_obj = ctx.guild
        else:
            guild_obj = ctx
        guild_id = guild_obj.id
        guild_config = self.forum_channels.get(guild_id)
        locale = guild_config.get("guild_lang", "en-US")
        if not guild_config:
            logging.error(f"❌ Aucune configuration trouvée pour la guilde {guild_id}.")
            return

        channel_id = guild_config.get("external_recruitment_channel")
        message_id = guild_config.get("external_recruitment_message")
        channel = self.bot.get_channel(channel_id)
        if not channel:
            logging.error("❌ Impossible de récupérer le canal de recrutement.")
            return

        members_in_roster = [v for (g, _), v in self.guild_members.items() if g == guild_id]
        total_members = len(members_in_roster)
        effectif_max = guild_config.get("max_members")

        ideal_staff = {
            "Tank": 12,
            "Healer": 12,
            "Flanker": 12,
            "Ranged DPS": 17,
            "Melee DPS": 17
        }

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

        # Construction des détails pour chaque rôle disponible
        positions_details = ""
        for cls_key, ideal_number in ideal_staff.items():
            class_name = GUILD_MEMBERS["class"][cls_key][locale]
            current_count = class_counts.get(cls_key, 0)
            available = max(0, ideal_number - current_count)
            positions_details += f"- **{class_name}** : {available} \n"

        # Assemblage de la description complète
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
            logging.error(f"❌ Aucune configuration trouvée pour la guilde {guild_id}.")
            return

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
            logging.error("❌ Impossible de récupérer le canal du roster.")
            return

        members_in_roster = [v for (g, _), v in self.guild_members.items() if g == guild_id]
        sorted_members = sorted(members_in_roster, key=lambda x: x.get("pseudo", "").lower())

        tank_count = sum(1 for m in sorted_members if m.get("classe", "").lower() == "tank")
        dps_melee_count = sum(1 for m in sorted_members if m.get("classe", "").lower() == "melee dps")
        dps_distant_count = sum(1 for m in sorted_members if m.get("classe", "").lower() == "ranged dps")
        heal_count = sum(1 for m in sorted_members if m.get("classe", "").lower() == "healer")
        flank_count = sum(1 for m in sorted_members if m.get("classe", "").lower() == "flanker")

        pseudo_width = 20
        lang_width = 6
        gs_width = 8
        build_width = 7
        armes_width = 9
        classe_width = 14
        dkp_width = 10
        insc_width = 8
        pres_width = 8

        header = (
            f"{'Pseudo'.ljust(pseudo_width)}│"
            f"{'Langue'.center(lang_width)}│"
            f"{'GS'.center(gs_width)}│"
            f"{'Build'.center(build_width)}│"
            f"{'Armes'.center(armes_width)}│"
            f"{'Classe'.center(classe_width)}│"
            f"{'DKP'.center(dkp_width)}│"
            f"{'%Insc'.center(insc_width)}│"
            f"{'%Prés'.center(pres_width)}"
        )
        separator = "─" * len(header)

        rows = []
        for m in sorted_members:
            pseudo = m.get("pseudo", "")[:pseudo_width].ljust(pseudo_width)
            # Récupération et formatage de la langue
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
            # Assemblage de la ligne incluant la langue
            rows.append(f"{pseudo}│{lang_text}│{gs}│{build_flag}│{armes_str}│{classe_str}│{dkp}│{inscriptions}│{presences}")

        if not rows:
            logging.warning("⚠️ Aucun membre trouvé dans le roster.")
            return

        now_str = datetime.now().strftime("%d/%m/%Y à %H:%M")
        role_stats = (
            f"Tank: {tank_count}\n"
            f"DPS Mélée: {dps_melee_count}\n"
            f"DPS Distance: {dps_distant_count}\n"
            f"Healer: {heal_count}\n"
            f"Flanker: {flank_count}"
        )
        update_footer = f"\n**Nombre de membres** : {len(rows)}\n{role_stats}\n\n*Mis à jour le {now_str}*"
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
            # Boucle sur les 5 messages
            for i in range(5):
                message = await channel.fetch_message(message_ids[i])
                if i < len(message_contents):
                    await message.edit(content=message_contents[i])
                else:
                    await message.edit(content=".")
        except discord.NotFound:
            logging.warning("⚠️ Un ou plusieurs messages du roster sont introuvables.")
        logging.info("✅ Mise à jour du message des membres effectuée.")

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
        guild_id = ctx.guild.id
        matching = [m for (g, _), m in self.guild_members.items() if g == guild_id and m.get("pseudo", "").lower().startswith(pseudo.lower())]

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

        # Parcourir les membres enregistrés dans le cache de guild_members pour la guilde
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
                    logging.error(f"[GuildMembers] Erreur en envoyant un MP à {member.display_name} (ID: {member_id}): {e}")
                    failures += 1
            else:
                failures += 1

        msg = get_user_message(ctx, GUILD_MEMBERS["notify_profile"], "success", successes=successes, failures=failures)
        await ctx.followup.send(msg,ephemeral=True)

    async def run_maj_roster(self, guild_id: int) -> None:
        # Récupérer les guild_config et rôles pour la guilde
        roles_config = self.roles.get(guild_id)
        if not roles_config:
            logging.error(f"[GuildMembers] Aucun rôle configuré pour la guilde {guild_id}.")
            return

        members_role_id = roles_config.get("members")
        absent_role_id = roles_config.get("absent_members")
        if not members_role_id:
            logging.error(f"[GuildMembers] Rôle 'membres' non configuré pour la guilde {guild_id}.")
            return

        # Récupérer la guilde depuis le bot
        guild = self.bot.get_guild(guild_id)
        if not guild:
            logging.error(f"[GuildMembers] La guilde {guild_id} n'est pas trouvée sur Discord.")
            return

        # Filtrer uniquement les membres possédant le rôle 'membres' ou 'membres absents'
        actual_members = {
            m.id: m for m in guild.members
            if not m.bot and (members_role_id in [r.id for r in m.roles] or absent_role_id in [r.id for r in m.roles])
        }

        # Supprimer de la BDD et du cache les membres absents
        keys_to_remove = []
        for (g, user_id), data in self.guild_members.items():
            if g == guild_id and user_id not in actual_members:
                delete_query = "DELETE FROM guild_members WHERE guild_id = ? AND member_id = ?"
                await self.bot.run_db_query(delete_query, (guild_id, user_id), commit=True)
                keys_to_remove.append((g, user_id))
        for key in keys_to_remove:
            del self.guild_members[key]

        # Pour chaque membre actuel, synchroniser les informations dans guild_members
        for member in actual_members.values():
            key = (guild_id, member.id)
            if key in self.guild_members:
                # Membre déjà enregistré : mettre à jour uniquement le pseudo s'il a changé
                record = self.guild_members[key]
                if record.get("pseudo") != member.display_name:
                    record["pseudo"] = member.display_name
                    update_query = "UPDATE guild_members SET pseudo = ? WHERE guild_id = ? AND member_id = ?"
                    await self.bot.run_db_query(update_query, (member.display_name, guild_id, member.id), commit=True)
                    logging.debug(f"[GuildMembers] Pseudo mis à jour pour {member.display_name} (ID: {member.id}).")
            else:
                # Nouveau membre : récupérer les infos depuis user_setup si disponibles, sinon valeurs par défaut
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
                logging.debug(f"[GuildMembers] Nouveau membre ajouté : {member.display_name} (ID: {member.id}).")

        # Mettre à jour les messages d'affichage
        await self.load_guild_members()
        await self.update_recruitment_message(guild)
        await self.update_members_message(guild)
        logging.info(f"[GuildMembers] Synchronisation de maj_roster effectuée pour la guilde {guild_id}.")

    @commands.Cog.listener()
    async def on_ready(self):
        # Mettre en cache les infos BDD au chargement
        asyncio.create_task(self.load_forum_channels())
        asyncio.create_task(self.load_roles())
        asyncio.create_task(self.load_weapons())
        asyncio.create_task(self.load_weapons_combinations())
        asyncio.create_task(self.load_user_setup_members())
        asyncio.create_task(self.load_guild_members())
        logging.debug("[GuildMembers] Tâche de récupérations des infos dans le cache lancée depuis on_ready")

def setup(bot: discord.Bot):
    bot.add_cog(GuildMembers(bot))
