import discord
import logging
import pytz
from datetime import datetime
from typing import Dict, Tuple, Any
from discord.ext import commands
from typing import Dict, Any
from translation import translations as global_translations
import asyncio

SUPPORTED_LOCALES = global_translations.get("supported_locales", {})
LANGUAGE_NAMES = global_translations.get("language_names", {})
WELCOME_MP = global_translations.get("welcome_mp", {})
PROFILE_SETUP_DATA = global_translations.get("profile_setup", {})

class ProfileSetup(commands.Cog):
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.roles: Dict[int, int] = {}
        self.forum_channels: Dict[int, int] = {}
        self.welcome_messages: Dict[Tuple[int, int], Dict[str, int]] = {}

    async def load_session(self, guild_id: int, user_id: int) -> Dict[str, Any]:
        key = f"{guild_id}_{user_id}"
        if key not in self.sessions:
            self.sessions[key] = {}
        return self.sessions[key]
    
    async def load_roles(self) -> None:
        """Charge depuis la BDD les rôles 'diplomats', 'friends', 'applicant', 'config_ok', 'guild_master', 'officer' et 'guardian' pour chaque guilde."""
        logging.debug("[ProfileSetup] Chargement des rôles depuis la BDD")
        query = """
            SELECT guild_id, diplomats, friends, applicant, config_ok, guild_master, officer, guardian
            FROM guild_roles 
            WHERE diplomats IS NOT NULL 
            AND friends IS NOT NULL 
            AND applicant IS NOT NULL
            AND guild_master IS NOT NULL
            AND officer IS NOT NULL
            AND guardian IS NOT NULL
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.roles = {}
            for row in rows:
                guild_id, diplomats_role_id, friends_role_id, applicant_role_id, config_ok_id, guild_master_role_id, officer_role_id, guardian_role_id = row
                self.roles[guild_id] = {
                    "diplomats": diplomats_role_id,
                    "friends": friends_role_id,
                    "applicant": applicant_role_id,
                    "config_ok": config_ok_id,
                    "guild_master": guild_master_role_id,
                    "officer": officer_role_id,
                    "guardian": guardian_role_id
                }
            logging.debug(f"[ProfileSetup] Rôles chargés : {self.roles}")
        except Exception as e:
            logging.error(f"[ProfileSetup] Erreur lors du chargement des rôles : {e}")

    async def load_forum_channels(self) -> None:
        """Charge depuis la BDD les IDs des channels de forum, la catégorie de recrutement externe et la langue de chaque guilde."""
        logging.debug("[ProfileSetup] Chargement des channels de forum depuis la BDD")
        query = """
            SELECT gc.guild_id,
                gc.forum_allies_channel,
                gc.forum_friends_channel,
                gc.forum_diplomats_channel,
                gc.forum_recruitment_channel,
                gc.external_recruitment_cat,
                gc.forum_members_channel,
                gc.notifications_channel,
                gs.guild_lang
            FROM guild_channels gc
            JOIN guild_settings gs ON gc.guild_id = gs.guild_id;
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.forum_channels = {}
            for row in rows:
                guild_id, allies, friends, diplomats, recruitment, external_recruitment_cat, members, notifications, guild_lang = row
                self.forum_channels[guild_id] = {
                    "forum_allies_channel": allies,
                    "forum_friends_channel": friends,
                    "forum_diplomats_channel": diplomats,
                    "forum_recruitment_channel": recruitment,
                    "external_recruitment_cat": external_recruitment_cat,
                    "forum_members_channel": members,
                    "notifications_channel": notifications,
                    "guild_lang": guild_lang
                }
            logging.debug(f"[ProfileSetup] Channels chargés : {self.forum_channels}")
        except Exception as e:
            logging.error(f"[ProfileSetup] Erreur lors du chargement des channels de forum : {e}")

    async def load_welcome_messages_cache(self) -> None:
        """Charge depuis la BDD les informations des messages de bienvenue pour chaque membre."""
        logging.debug("[ProfileSetup] Chargement des welcome messages depuis la BDD")
        query = "SELECT guild_id, member_id, channel_id, message_id FROM welcome_messages"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            for row in rows:
                guild_id, member_id, channel_id, message_id = row
                key = f"{guild_id}_{member_id}"
                self.welcome_messages[key] = {"channel": channel_id, "message": message_id}
            logging.debug(f"[ProfileSetup] Welcome messages chargés : {self.welcome_messages}")
        except Exception as e:
            logging.error(f"[ProfileSetup] Erreur lors du chargement des welcome messages : {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        # Mettre en cache les infos BDD au chargement
        asyncio.create_task(self.load_roles())
        asyncio.create_task(self.load_forum_channels())
        asyncio.create_task(self.load_welcome_messages_cache())
        logging.debug("[ProfileSetup] Tâche de récupérations des infos dans le cache lancée depuis on_ready")

    async def finalize_profile(self, guild_id: int, user_id: int) -> None:
        guild_lang = self.forum_channels.get(guild_id, {}).get("guild_lang", "en-US")
        session = await self.load_session(guild_id, user_id)
        key = f"{guild_id}_{user_id}"

        query = """
        INSERT INTO user_setup 
            (guild_id, user_id, pseudo, locale, motif, friend_pseudo, weapons, guild_name, guild_acronym, gs, playtime, gametype)
        VALUES 
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON DUPLICATE KEY UPDATE 
            pseudo = ?, locale = ?, motif = ?, friend_pseudo = ?, weapons = ?, guild_name = ?, guild_acronym = ?, gs = ?, playtime = ?, gametype = ?
        """
        values = (
            guild_id,
            user_id,
            session.get("pseudo"),
            session.get("locale"),
            session.get("motif"),
            session.get("friend_pseudo", None),
            session.get("weapons", None),
            session.get("guild_name", None),
            session.get("guild_acronym", None),
            session.get("gs", None),
            session.get("playtime", None),
            session.get("gametype", None),
            # ON DUPLICATE KEY UPDATE values:
            session.get("pseudo"),
            session.get("locale"),
            session.get("motif"),
            session.get("friend_pseudo", None),
            session.get("weapons", None),
            session.get("guild_name", None),
            session.get("guild_acronym", None),
            session.get("gs", None),
            session.get("playtime", None),
            session.get("gametype", None)
        )
        await self.bot.run_db_query(query, values, commit=True)
        logging.debug(f"[ProfileSetup] Session saved for key {key}: {self.sessions.get(key)}")

        self.locale = session.get("locale")

        # Ajout des rôles selon le motif
        try:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                logging.error(f"[ProfileSetup] Guild {guild_id} not found.")
                return

            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
            motif = session.get("motif")
            role_id = None
            if motif == "diplomate":
                role_id = self.roles.get(guild_id, {}).get("diplomats")
            elif motif == "amis":
                role_id = self.roles.get(guild_id, {}).get("friends")
            elif motif == "postulation":
                role_id = self.roles.get(guild_id, {}).get("applicant")

            await member.add_roles(guild.get_role(self.roles.get(guild.id, {}).get("config_ok")))
            
            if role_id:
                role = guild.get_role(role_id)
                if role:
                    await member.add_roles(role)
                    logging.debug(f"[ProfileSetup] Added role {role.name} to user {user_id} for motif {motif}.")
                else:
                    logging.error(f"[ProfileSetup] Role with ID {role_id} not found in guild {guild_id}.")
            else:
                logging.debug(f"[ProfileSetup] No role assigned for motif {motif} in guild {guild_id}.")
        except Exception as e:
            logging.error("[ProfileSetup] Error while assigning role in finalize_profile", exc_info=True)

        # Modification du pseudo sur Discord selon le motif
        try:
            pseudo = session.get("pseudo", "")
            new_nickname = pseudo

            if motif == "postulation":
                post_acronym = PROFILE_SETUP_DATA["acronym"].get(session.get("locale", "en-US"), PROFILE_SETUP_DATA["acronym"].get("en-US"))
                new_nickname = f"{post_acronym} {pseudo}"
            elif motif in ["diplomate", "allies"]:
                guild_acronym = session.get("guild_acronym", "")
                new_nickname = f"[{guild_acronym}] {pseudo}"

            await member.edit(nick=new_nickname)
            logging.debug(f"[ProfileSetup] Nickname updated for {member.name} to '{new_nickname}'")
        except discord.Forbidden:
            logging.error(f"[ProfileSetup] ⚠️ Impossible de modifier le pseudo de {member.name} (permissions insuffisantes).")
        except Exception as e:
            logging.error(f"[ProfileSetup] Error updating nickname for {member.name}: {e}", exc_info=True)

        # Notifications dans les channels forums, utilisant 'session' pour récupérer les données.
        channels_data = self.forum_channels.get(guild_id, {})
        channels = {
            "membre": channels_data.get("forum_members_channel"),
            "postulation": channels_data.get("forum_recruitment_channel"),
            "diplomate": channels_data.get("forum_diplomats_channel"),
            "allies": channels_data.get("forum_allies_channel"),
            "amis": channels_data.get("forum_friends_channel")
        }
        channel_id = channels.get(motif)
        if not channel_id:
            logging.error(f"[ProfileSetup] ❌ Motif inconnu ({motif}) pour l'utilisateur {user_id}, aucune notification envoyée.")
            return

        try:
            channel = await self.bot.fetch_channel(channel_id)
            if not channel:
                logging.error(f"[ProfileSetup] ❌ Impossible de récupérer le channel {channel_id} pour l'utilisateur {user_id}.")
                return

            embed = discord.Embed(title=PROFILE_SETUP_DATA["notification"]["title"].get(self.locale, PROFILE_SETUP_DATA["notification"]["title"].get("en-US")), color=discord.Color.blue())
            embed.add_field(name=PROFILE_SETUP_DATA["notification"]["fields"]["user"].get(self.locale, PROFILE_SETUP_DATA["notification"]["fields"]["user"].get("en-US")), value=f"<@{user_id}>", inline=False)
            embed.add_field(name=PROFILE_SETUP_DATA["notification"]["fields"]["discord_name"].get(self.locale, PROFILE_SETUP_DATA["notification"]["fields"]["discord_name"].get("en-US")), value=f"`{session.get('pseudo', 'Inconnu')}`", inline=False)
            embed.set_footer(text=PROFILE_SETUP_DATA["footer"].get(self.locale, PROFILE_SETUP_DATA["footer"].get("en-US")))

            if motif == "membre":
                embed.color = discord.Color.gold()
                weapons = session.get("weapons", "N/A")
                gs = session.get("gs", "N/A")
                embed.add_field(name=PROFILE_SETUP_DATA["notification"]["fields"]["weapons"].get(self.locale, PROFILE_SETUP_DATA["notification"]["fields"]["weapons"].get("en-US")), value=f"`{weapons}`", inline=True)
                embed.add_field(name=PROFILE_SETUP_DATA["notification"]["fields"]["gs"].get(self.locale, PROFILE_SETUP_DATA["notification"]["fields"]["gs"].get("en-US")), value=f"`{gs}`", inline=True)
            elif motif == "postulation":
                embed.color = discord.Color.purple()
                weapons = session.get("weapons", "N/A")
                gs = session.get("gs", "N/A")
                playtime = session.get("playtime", "N/A")
                gametype = session.get("gametype", "N/A")
                embed.add_field(name=PROFILE_SETUP_DATA["notification"]["fields"]["weapons"].get(self.locale, PROFILE_SETUP_DATA["notification"]["fields"]["weapons"].get("en-US")), value=f"`{weapons}`", inline=True)
                embed.add_field(name=PROFILE_SETUP_DATA["notification"]["fields"]["gs"].get(self.locale, PROFILE_SETUP_DATA["notification"]["fields"]["gs"].get("en-US")), value=f"`{gs}`", inline=True)
                embed.add_field(name=PROFILE_SETUP_DATA["notification"]["fields"]["playtime"].get(self.locale, PROFILE_SETUP_DATA["notification"]["fields"]["playtime"].get("en-US")), value=f"`{playtime}`", inline=False)
                embed.add_field(name=PROFILE_SETUP_DATA["notification"]["fields"]["gametype"].get(self.locale, PROFILE_SETUP_DATA["notification"]["fields"]["gametype"].get("en-US")), value=f"`{gametype}`", inline=False)
            elif motif == "diplomate":
                embed.color = discord.Color.dark_blue()
                guild_name = session.get("guild_name", "N/A")
                guild_acronym = session.get("guild_acronym", "N/A")
                embed.add_field(name=PROFILE_SETUP_DATA["notification"]["fields"]["guild"].get(self.locale, PROFILE_SETUP_DATA["notification"]["fields"]["guild"].get("en-US")), value=f"`{guild_name}` ({guild_acronym})", inline=False)
            elif motif == "allies":
                embed.color = discord.Color.green()
                guild_name = session.get("guild_name", "N/A")
                guild_acronym = session.get("guild_acronym", "N/A")
                embed.add_field(name=PROFILE_SETUP_DATA["notification"]["fields"]["allied_guild"].get(self.locale, PROFILE_SETUP_DATA["notification"]["fields"]["allied_guild"].get("en-US")), value=f"`{guild_name}` ({guild_acronym})", inline=False)
            elif motif == "amis":
                embed.color = discord.Color.blue()
                friend_pseudo = session.get("friend_pseudo", "N/A")
                embed.add_field(name=PROFILE_SETUP_DATA["notification"]["fields"]["friend"].get(self.locale, PROFILE_SETUP_DATA["notification"]["fields"]["friend"].get("en-US")), value=f"`{friend_pseudo}`", inline=False)

            await channel.send(embed=embed)
            logging.debug(f"[ProfileSetup] 📢 Notification envoyée dans {channel.name} pour l'utilisateur {user_id}.")
        except Exception as e:
            logging.error(f"[ProfileSetup] ❌ Impossible d'envoyer la notification pour l'utilisateur {user_id} : {e}", exc_info=True)

        # Mise à jour du welcome message à l'aide du cache et de la session

        if key in self.welcome_messages:
            info = self.welcome_messages[key]
            try:
                channel = await self.bot.fetch_channel(info["channel"])
                message = await channel.fetch_message(info["message"])

                if not message.embeds:
                    logging.error(f"[ProfileSetup] ❌ Aucun embed trouvé dans le message pour {session.get('pseudo', 'Inconnu')}.")
                    return
                embed = message.embeds[0]
                colors = {
                    "membre": discord.Color.gold(),
                    "postulation": discord.Color.purple(),
                    "diplomate": discord.Color.dark_blue(),
                    "allies": discord.Color.green(),
                    "amis": discord.Color.blue()
                }
                embed.color = colors.get(session.get("motif"), discord.Color.default())
                TZ_FRANCE = pytz.timezone("Europe/Paris")
                now = datetime.now(pytz.utc).astimezone(TZ_FRANCE).strftime("%d/%m/%Y à %Hh%M")
                pending_text = PROFILE_SETUP_DATA["pending"].get(guild_lang, PROFILE_SETUP_DATA["pending"].get("en-US"))
                motif = session.get("motif")
                if motif == "membre":
                    template = PROFILE_SETUP_DATA["accepted_membre"].get(guild_lang, PROFILE_SETUP_DATA["accepted_membre"].get("en-US"))
                    new_text = template.format(new_nickname=new_nickname, gs=gs, now=now)
                elif motif == "postulation":
                    template = PROFILE_SETUP_DATA["accepted_postulation"].get(guild_lang, PROFILE_SETUP_DATA["accepted_postulation"].get("en-US"))
                    new_text = template.format(new_nickname=new_nickname, gs=gs, now=now)
                elif motif == "diplomate":
                    guild_name = session.get("guild_name", "Inconnue")
                    template = PROFILE_SETUP_DATA["accepted_diplomate"].get(guild_lang, PROFILE_SETUP_DATA["accepted_diplomate"].get("en-US"))
                    new_text = template.format(new_nickname=new_nickname, guild_name=guild_name, now=now)
                elif motif == "allies":
                    guild_name = session.get("guild_name", "Inconnue")
                    template = PROFILE_SETUP_DATA["accepted_allies"].get(guild_lang, PROFILE_SETUP_DATA["accepted_allies"].get("en-US"))
                    new_text = template.format(new_nickname=new_nickname, guild_name=guild_name, now=now)
                elif motif == "amis":
                    friend_pseudo = session.get("friend_pseudo", "Inconnu")
                    template = PROFILE_SETUP_DATA["accepted_amis"].get(guild_lang, PROFILE_SETUP_DATA["accepted_amis"].get("en-US"))
                    new_text = template.format(new_nickname=new_nickname, friend_pseudo=friend_pseudo, now=now)
                embed.description = embed.description.replace(pending_text, new_text)
                await message.edit(embed=embed)
                logging.debug(f"[ProfileSetup] 📢 Welcome message mis à jour pour {session.get('pseudo', 'Inconnu')} avec motif {motif}.")
            except Exception as e:
                logging.error(f"[ProfileSetup] ❌ Erreur lors de la mise à jour du welcome message : {e}", exc_info=True)
        else:
            logging.debug(f"[ProfileSetup] Pas de welcome message en cache pour la clé {key}.")

        # Création d'un channel "ticket" lors des postulations
        if motif == "postulation":
            channels_data = self.forum_channels.get(guild_id, {})
            recruitment_category_id = channels_data.get("external_recruitment_cat")
            if not recruitment_category_id:
                logging.error("L'ID de la catégorie recrutement externe est manquant. Veuillez le fournir pour créer les channels individuels.")
            else:
                recruitment_category = guild.get_channel(recruitment_category_id)
                if recruitment_category is None:
                    logging.error(f"La catégorie de recrutement (ID: {recruitment_category_id}) n'a pas été trouvée dans la guilde {guild.id}.")
                else:
                    channel_name = f"{member.display_name}".replace(" ", "-").lower()
                    overwrites = {
                        guild.default_role: discord.PermissionOverwrite(view_channel=False)
                    }
                    applicant_role_id = self.roles.get(guild_id, {}).get("applicant")
                    if applicant_role_id:
                        applicant_role = guild.get_role(applicant_role_id)
                        if applicant_role:
                            overwrites[applicant_role] = discord.PermissionOverwrite(view_channel=False)
                    overwrites[member] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

                    for role_name in ["guild_master", "officer", "guardian"]:
                        role_id = self.roles.get(guild_id, {}).get(role_name)
                        if role_id:
                            role_obj = guild.get_role(role_id)
                            if role_obj:
                                overwrites[role_obj] = discord.PermissionOverwrite(
                                    view_channel=True,
                                    send_messages=True,
                                    read_message_history=True,
                                    manage_channels=True
                                )
                    
                    try:
                        new_channel = await guild.create_text_channel(
                            name=channel_name,
                            category=recruitment_category,
                            topic=f"Channel individuel pour la postulation de {member.display_name}",
                            overwrites=overwrites
                        )
                        logging.info(f"Channel de postulation créé : {new_channel.name} (ID: {new_channel.id}) pour l'utilisateur {member.id}")
                    except Exception as e:
                        logging.error(f"Erreur lors de la création du channel individuel pour {member.display_name} : {e}")

        guildmembers_cog = self.bot.get_cog("GuildMembers")
        if guildmembers_cog:
            await guildmembers_cog.load_user_setup_members()

    # ---------------------------------------------------------
    # UI Components for language selection
    # ---------------------------------------------------------
    class LangButton(discord.ui.Button):
        def __init__(self, locale: str):
            label = LANGUAGE_NAMES.get(locale, locale)
            super().__init__(label=label, style=discord.ButtonStyle.primary, custom_id=f"lang_{locale}")
            self.locale = locale

        async def callback(self, interaction: discord.Interaction):
            cog: ProfileSetup = self.view.cog
            guild_id = self.view.guild_id
            user_id = interaction.user.id
            session = await cog.load_session(guild_id, user_id)
            session["locale"] = self.locale
            lang_msg = PROFILE_SETUP_DATA["language_saved"].get(self.locale, PROFILE_SETUP_DATA["language_saved"].get("en-US"))
            await interaction.response.send_message(lang_msg, ephemeral=True)
            await interaction.user.send(view=ProfileSetup.MotifModalView(cog, self.locale, guild_id))

    class LangSelectView(discord.ui.View):
        def __init__(self, cog: "ProfileSetup", guild_id: int):
            super().__init__(timeout=180)
            self.cog = cog
            self.guild_id = guild_id
            for locale in SUPPORTED_LOCALES:
                self.add_item(ProfileSetup.LangButton(locale))

    # ---------------------------------------------------------
    # UI Components for motif selection
    # ---------------------------------------------------------
    class MotifSelect(discord.ui.Select):
        def __init__(self, locale: str, guild_id: int):
            self.locale = locale
            self.guild_id = guild_id
            options = []
            for item in PROFILE_SETUP_DATA["motif_select_options"]:
                label = item["label"].get(locale, item["label"].get("en-US"))
                value = item["value"]
                description = item["description"].get(locale, item["description"].get("en-US"))
                options.append(discord.SelectOption(label=label, value=value, description=description))
            placeholder = PROFILE_SETUP_DATA["motif_select"].get(locale, PROFILE_SETUP_DATA["motif_select"].get("en-US"))
            super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

        async def callback(self, interaction: discord.Interaction):
            try:
                cog: ProfileSetup = self.view.cog
                guild_id = self.guild_id
                user_id = interaction.user.id
                logging.debug(f"[ProfileSetup] MotifSelect callback invoked for guild_id={guild_id}, user_id={user_id}")
                session = await cog.load_session(guild_id, user_id)
                session["motif"] = self.values[0]
                message  = PROFILE_SETUP_DATA["motif_saved"].get(self.locale, PROFILE_SETUP_DATA["motif_saved"].get("en-US"))
                await interaction.response.send_message(message, ephemeral=True)
                await interaction.user.send(view=ProfileSetup.QuestionsSelectView(cog, self.locale, guild_id, self.values[0]))
            except Exception as e:
                logging.error("[ProfileSetup] Erreur dans le callback de MotifSelect", exc_info=True)

    class MotifModalView(discord.ui.View):
        def __init__(self, cog: "ProfileSetup", locale: str, guild_id: int):
            super().__init__(timeout=180)
            self.cog = cog
            self.locale = locale
            self.guild_id = guild_id
            self.add_item(ProfileSetup.MotifSelect(locale, guild_id))

    # ---------------------------------------------------------
    # UI Components for profile questions
    # ---------------------------------------------------------
    class QuestionsSelect(discord.ui.Modal):
        def __init__(self, locale: str, guild_id: int, motif: str):
            title = PROFILE_SETUP_DATA["questions_title"].get(locale, PROFILE_SETUP_DATA["questions_title"].get("en-US"))
            super().__init__(title=title)
            self.locale = locale
            self.guild_id = guild_id
            self.motif = motif
            logging.debug(f"[ProfileSetup] Initializing QuestionsSelect modal for guild_id={guild_id}, motif={motif}, locale={locale}")

            self.pseudo = discord.ui.InputText(
                label=PROFILE_SETUP_DATA["pseudo_select"].get(locale, PROFILE_SETUP_DATA["pseudo_select"].get("en-US")),
                min_length=3,
                max_length=16,
                required=True
            )
            self.add_item(self.pseudo)

            if motif in ["diplomate", "allies"]:
                self.guild_name = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["guild_select"].get(locale, PROFILE_SETUP_DATA["guild_select"].get("en-US")),
                    min_length=3,
                    max_length=16,
                    required=True
                )
                self.add_item(self.guild_name)

                self.guild_acronym = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["guild_acronym"].get(locale, PROFILE_SETUP_DATA["guild_acronym"].get("en-US")),
                    min_length=3,
                    max_length=3,
                    required=True
                )
                self.add_item(self.guild_acronym)

            if motif == "amis":
                self.friend_pseudo = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["friend_pseudo"].get(locale, PROFILE_SETUP_DATA["friend_pseudo"].get("en-US")),
                    min_length=3,
                    max_length=16,
                    required=True
                )
                self.add_item(self.friend_pseudo)

            if motif in ["postulation", "membre"]:
                self.weapons = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["weapons_select"].get(locale, PROFILE_SETUP_DATA["weapons_select"].get("en-US")),
                    required=True,
                    placeholder="SNS / GS / SP / DG / B / S / W / CB"
                )
                self.add_item(self.weapons)

                self.gs = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["gs"].get(locale, PROFILE_SETUP_DATA["gs"].get("en-US")),
                    required=True,
                    min_length=3,
                    max_length=4
                )
                self.add_item(self.gs)

            if motif == "postulation":
                self.gametype = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["gametype_select"].get(locale, PROFILE_SETUP_DATA["gametype_select"].get("en-US")),
                    required=True,
                    placeholder="PvE / PvP / PvE + PvP"
                )
                self.add_item(self.gametype)

                self.playtime = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["playtime_select"].get(locale, PROFILE_SETUP_DATA["playtime_select"].get("en-US")),
                    required=True,
                    placeholder="**h / week"
                )
                self.add_item(self.playtime)

        async def callback(self, interaction: discord.Interaction):
            try:
                logging.debug(f"[ProfileSetup] QuestionsSelect submitted by user {interaction.user.id} in guild {self.guild_id}.")

                cog: ProfileSetup = interaction.client.get_cog("ProfileSetup")
                if not cog:
                    logging.error("[ProfileSetup] Cog 'ProfileSetup' introuvable.")
                    await interaction.response.send_message("❌ Error.", ephemeral=True)
                    return

                guild_id = self.guild_id
                user_id = interaction.user.id

                session = await cog.load_session(guild_id, user_id)
                logging.debug(f"[ProfileSetup] Session before update: {session}")
                session["pseudo"] = self.pseudo.value

                if hasattr(self, "guild_name"):
                    session["guild_name"] = self.guild_name.value
                    session["guild_acronym"] = self.guild_acronym.value

                if hasattr(self, "friend_pseudo"):
                    session["friend_pseudo"] = self.friend_pseudo.value

                if hasattr(self, "weapons"):
                    session["weapons"] = self.weapons.value
                    session["gs"] = self.gs.value

                if hasattr(self, "gametype"):
                    session["gametype"] = self.gametype.value
                    session["playtime"] = self.playtime.value

                logging.debug(f"[ProfileSetup] Session after update: {session}")

                await interaction.response.defer(ephemeral=True)
                await cog.finalize_profile(guild_id, user_id)
                await interaction.followup.send(
                    PROFILE_SETUP_DATA["setup_complete"].get(self.locale, PROFILE_SETUP_DATA["setup_complete"].get("en-US")),
                    ephemeral=True
                )
                logging.debug("[ProfileSetup] QuestionsSelect modal submission processed successfully.")
            except Exception as e:
                logging.error("[ProfileSetup] Error in QuestionsSelect.on_submit", exc_info=True)
                try:
                    await interaction.response.send_message("❌ An error occurred during profile submission.", ephemeral=True)
                except Exception:
                    pass

    class QuestionsSelectButton(discord.ui.Button):
        def __init__(self, cog: "ProfileSetup", locale: str, guild_id: int, motif: str):
            label = PROFILE_SETUP_DATA["comp_profile"].get(locale, PROFILE_SETUP_DATA["comp_profile"].get("en-US"))
            super().__init__(label=label, style=discord.ButtonStyle.primary, custom_id="questions_select_button")
            self.cog = cog
            self.locale = locale
            self.guild_id = guild_id
            self.motif = motif

        async def callback(self, interaction: discord.Interaction):
            logging.debug(f"[ProfileSetup] QuestionsSelectButton clicked for user {interaction.user.id}")
            try:
                modal = ProfileSetup.QuestionsSelect(self.locale, self.guild_id, self.motif)
                if len(modal.children) > 5:
                    logging.error(f"[ProfileSetup] Modal contains {len(modal.children)} fields, exceeding Discord's limit of 5.")
                    await interaction.response.send_message("⚠️ Trop de champs dans le formulaire ! Contacte un admin.", ephemeral=True)
                    return
                await interaction.response.send_modal(modal)
                logging.debug("[ProfileSetup] Modal sent successfully.")
            except Exception as e:
                logging.error("[ProfileSetup] Failed to send modal.", exc_info=True)
                await interaction.response.send_message("❌ Une erreur est survenue lors de l'affichage du formulaire.", ephemeral=True)

    class QuestionsSelectView(discord.ui.View):
        def __init__(self, cog: "ProfileSetup", locale: str, guild_id: int, motif: str):
            super().__init__(timeout=180)
            self.cog = cog
            self.locale = locale
            self.guild_id = guild_id
            self.motif = motif
            logging.debug(f"[ProfileSetup] Initializing QuestionsSelectView for guild_id={guild_id}, locale={locale}, motif={motif}")
            self.add_item(ProfileSetup.QuestionsSelectButton(cog, locale, guild_id, motif))

def setup(bot: discord.Bot):
    bot.add_cog(ProfileSetup(bot))