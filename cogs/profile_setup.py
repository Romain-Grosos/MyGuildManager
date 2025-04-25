import discord
import logging
import pytz
from datetime import datetime
from typing import Dict, Tuple, Any
from discord.ext import commands
from typing import Dict, Any
from translation import translations as global_translations
import asyncio
from db import DBQueryError

MAX_PLAYTIME_LEN = 64
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
        logging.debug("[ProfileSetup] Loading roles from DB")
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
                (
                    guild_id,
                    diplomats_role_id,
                    friends_role_id,
                    applicant_role_id,
                    config_ok_id,
                    guild_master_role_id,
                    officer_role_id,
                    guardian_role_id,
                ) = row
                self.roles[guild_id] = {
                    "diplomats": diplomats_role_id,
                    "friends": friends_role_id,
                    "applicant": applicant_role_id,
                    "config_ok": config_ok_id,
                    "guild_master": guild_master_role_id,
                    "officer": officer_role_id,
                    "guardian": guardian_role_id,
                }
            logging.debug(f"[ProfileSetup] Roles loaded: {self.roles}")
        except Exception as e:
            logging.error(f"[ProfileSetup] Error while loading roles: {e}")

    async def load_forum_channels(self) -> None:
        logging.debug("[ProfileSetup] Loading forum channels from DB")
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
            JOIN guild_settings gs ON gc.guild_id = gs.guild_id
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.forum_channels = {}
            for row in rows:
                (
                    guild_id,
                    allies,
                    friends,
                    diplomats,
                    recruitment,
                    external_recruitment_cat,
                    members,
                    notifications,
                    guild_lang,
                ) = row
                self.forum_channels[guild_id] = {
                    "forum_allies_channel": allies,
                    "forum_friends_channel": friends,
                    "forum_diplomats_channel": diplomats,
                    "forum_recruitment_channel": recruitment,
                    "external_recruitment_cat": external_recruitment_cat,
                    "forum_members_channel": members,
                    "notifications_channel": notifications,
                    "guild_lang": guild_lang,
                }
            logging.debug(f"[ProfileSetup] Channels loaded: {self.forum_channels}")
        except Exception as e:
            logging.error(f"[ProfileSetup] Error while loading forum channels: {e}")

    async def load_welcome_messages_cache(self) -> None:
        logging.debug("[ProfileSetup] Loading welcome messages from DB")
        query = "SELECT guild_id, member_id, channel_id, message_id FROM welcome_messages"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.welcome_messages = {}
            for row in rows:
                guild_id, member_id, channel_id, message_id = row
                key = f"{guild_id}_{member_id}"
                self.welcome_messages[key] = {"channel": channel_id, "message": message_id}
            logging.debug(f"[ProfileSetup] Welcome messages loaded: {self.welcome_messages}")
        except Exception as e:
            logging.error(f"[ProfileSetup] Error while loading welcome messages: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        asyncio.create_task(self.load_roles())
        asyncio.create_task(self.load_forum_channels())
        asyncio.create_task(self.load_welcome_messages_cache())
        logging.debug("[ProfileSetup] Cache loading tasks started from on_ready")

    async def finalize_profile(self, guild_id: int, user_id: int) -> None:
        guild_lang = self.forum_channels.get(guild_id, {}).get("guild_lang", "en-US")
        session = await self.load_session(guild_id, user_id)
        key = f"{guild_id}_{user_id}"

        def _values_from_session(s: Dict[str, Any]) -> Tuple[Any, ...]:
            return (
                guild_id,
                user_id,
                s.get("pseudo"),
                s.get("locale"),
                s.get("motif"),
                s.get("friend_pseudo"),
                s.get("weapons"),
                s.get("guild_name"),
                s.get("guild_acronym"),
                s.get("gs"),
                s.get("playtime"),
                s.get("gametype"),
                s.get("pseudo"),
                s.get("locale"),
                s.get("motif"),
                s.get("friend_pseudo"),
                s.get("weapons"),
                s.get("guild_name"),
                s.get("guild_acronym"),
                s.get("gs"),
                s.get("playtime"),
                s.get("gametype"),
            )

        query = """
            INSERT INTO user_setup
                (guild_id, user_id, pseudo, locale, motif, friend_pseudo, weapons, guild_name, guild_acronym, gs, playtime, gametype)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON DUPLICATE KEY UPDATE
                pseudo = ?, locale = ?, motif = ?, friend_pseudo = ?, weapons = ?, guild_name = ?, guild_acronym = ?, gs = ?, playtime = ?, gametype = ?
        """

        try:
            await self.bot.run_db_query(query, _values_from_session(session), commit=True)
        except DBQueryError as exc:
            if "Data too long" in str(exc) and "playtime" in str(exc):
                truncated = (session.get("playtime") or "")[:MAX_PLAYTIME_LEN]
                session["playtime"] = truncated
                logging.warning(
                    "[ProfileSetup] Playtime truncated to fit DB column "
                    f"(user {user_id}, guild {guild_id})"
                )
                await self.bot.run_db_query(query, _values_from_session(session), commit=True)
            else:
                logging.error(f"[ProfileSetup] DB insertion failed: {exc}")
                raise
            
        logging.debug(f"[ProfileSetup] Session saved for key {key}: {self.sessions.get(key)}")

        self.locale = session.get("locale")

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
                    logging.debug(
                        f"[ProfileSetup] Added role {role.name} to user {user_id} for motif {motif}."
                    )
                else:
                    logging.error(
                        f"[ProfileSetup] Role with ID {role_id} not found in guild {guild_id}."
                    )
            else:
                logging.debug(
                    f"[ProfileSetup] No role assigned for motif {motif} in guild {guild_id}."
                )
        except Exception:
            logging.error("[ProfileSetup] Error while assigning role in finalize_profile", exc_info=True)

        try:
            pseudo = session.get("pseudo", "")
            new_nickname = pseudo
            if motif == "postulation":
                post_acronym = PROFILE_SETUP_DATA["acronym"].get(
                    session.get("locale", "en-US"),
                    PROFILE_SETUP_DATA["acronym"].get("en-US"),
                )
                new_nickname = f"{post_acronym} {pseudo}"
            elif motif in ["diplomate", "allies"]:
                guild_acronym = session.get("guild_acronym", "")
                new_nickname = f"[{guild_acronym}] {pseudo}"
            await member.edit(nick=new_nickname)
            logging.debug(f"[ProfileSetup] Nickname updated for {member.name} to '{new_nickname}'")
        except discord.Forbidden:
            logging.error(
                f"[ProfileSetup] ⚠️ Cannot modify nickname of {member.name} (missing permissions)."
            )
        except Exception as e:
            logging.error(
                f"[ProfileSetup] Error updating nickname for {member.name}: {e}", exc_info=True
            )

        channels_data = self.forum_channels.get(guild_id, {})
        channels = {
            "membre": channels_data.get("forum_members_channel"),
            "postulation": channels_data.get("forum_recruitment_channel"),
            "diplomate": channels_data.get("forum_diplomats_channel"),
            "allies": channels_data.get("forum_allies_channel"),
            "amis": channels_data.get("forum_friends_channel"),
        }
        channel_id = channels.get(motif)
        if not channel_id:
            logging.error(
                f"[ProfileSetup] ❌ Unknown motif ({motif}) for user {user_id}, notification skipped."
            )
            return

        try:
            channel = await self.bot.fetch_channel(channel_id)
            if not channel:
                logging.error(
                    f"[ProfileSetup] ❌ Unable to fetch channel {channel_id} for user {user_id}."
                )
                return

            embed = discord.Embed(
                title=PROFILE_SETUP_DATA["notification"]["title"].get(
                    self.locale, PROFILE_SETUP_DATA["notification"]["title"].get("en-US")
                ),
                color=discord.Color.blue(),
            )
            embed.add_field(
                name=PROFILE_SETUP_DATA["notification"]["fields"]["user"].get(
                    self.locale, PROFILE_SETUP_DATA["notification"]["fields"]["user"].get("en-US")
                ),
                value=f"<@{user_id}>",
                inline=False,
            )
            embed.add_field(
                name=PROFILE_SETUP_DATA["notification"]["fields"]["discord_name"].get(
                    self.locale,
                    PROFILE_SETUP_DATA["notification"]["fields"]["discord_name"].get("en-US"),
                ),
                value=f"`{session.get('pseudo', 'Unknown')}`",
                inline=False,
            )
            embed.set_footer(
                text=PROFILE_SETUP_DATA["footer"].get(
                    self.locale, PROFILE_SETUP_DATA["footer"].get("en-US")
                )
            )

            if motif == "membre":
                embed.color = discord.Color.gold()
                weapons = session.get("weapons", "N/A")
                gs = session.get("gs", "N/A")
                embed.add_field(
                    name=PROFILE_SETUP_DATA["notification"]["fields"]["weapons"].get(
                        self.locale,
                        PROFILE_SETUP_DATA["notification"]["fields"]["weapons"].get("en-US"),
                    ),
                    value=f"`{weapons}`",
                    inline=True,
                )
                embed.add_field(
                    name=PROFILE_SETUP_DATA["notification"]["fields"]["gs"].get(
                        self.locale, PROFILE_SETUP_DATA["notification"]["fields"]["gs"].get("en-US")
                    ),
                    value=f"`{gs}`",
                    inline=True,
                )
            elif motif == "postulation":
                embed.color = discord.Color.purple()
                weapons = session.get("weapons", "N/A")
                gs = session.get("gs", "N/A")
                playtime = session.get("playtime", "N/A")
                gametype = session.get("gametype", "N/A")
                embed.add_field(
                    name=PROFILE_SETUP_DATA["notification"]["fields"]["weapons"].get(
                        self.locale,
                        PROFILE_SETUP_DATA["notification"]["fields"]["weapons"].get("en-US"),
                    ),
                    value=f"`{weapons}`",
                    inline=True,
                )
                embed.add_field(
                    name=PROFILE_SETUP_DATA["notification"]["fields"]["gs"].get(
                        self.locale, PROFILE_SETUP_DATA["notification"]["fields"]["gs"].get("en-US")
                    ),
                    value=f"`{gs}`",
                    inline=True,
                )
                embed.add_field(
                    name=PROFILE_SETUP_DATA["notification"]["fields"]["playtime"].get(
                        self.locale,
                        PROFILE_SETUP_DATA["notification"]["fields"]["playtime"].get("en-US"),
                    ),
                    value=f"`{playtime}`",
                    inline=False,
                )
                embed.add_field(
                    name=PROFILE_SETUP_DATA["notification"]["fields"]["gametype"].get(
                        self.locale,
                        PROFILE_SETUP_DATA["notification"]["fields"]["gametype"].get("en-US"),
                    ),
                    value=f"`{gametype}`",
                    inline=False,
                )
                postulation_embed = embed.copy()
            elif motif == "diplomate":
                embed.color = discord.Color.dark_blue()
                guild_name = session.get("guild_name", "N/A")
                guild_acronym = session.get("guild_acronym", "N/A")
                embed.add_field(
                    name=PROFILE_SETUP_DATA["notification"]["fields"]["guild"].get(
                        self.locale, PROFILE_SETUP_DATA["notification"]["fields"]["guild"].get("en-US")
                    ),
                    value=f"`{guild_name}` ({guild_acronym})",
                    inline=False,
                )
            elif motif == "allies":
                embed.color = discord.Color.green()
                guild_name = session.get("guild_name", "N/A")
                guild_acronym = session.get("guild_acronym", "N/A")
                embed.add_field(
                    name=PROFILE_SETUP_DATA["notification"]["fields"]["allied_guild"].get(
                        self.locale,
                        PROFILE_SETUP_DATA["notification"]["fields"]["allied_guild"].get("en-US"),
                    ),
                    value=f"`{guild_name}` ({guild_acronym})",
                    inline=False,
                )
            elif motif == "amis":
                embed.color = discord.Color.blue()
                friend_pseudo = session.get("friend_pseudo", "N/A")
                embed.add_field(
                    name=PROFILE_SETUP_DATA["notification"]["fields"]["friend"].get(
                        self.locale,
                        PROFILE_SETUP_DATA["notification"]["fields"]["friend"].get("en-US"),
                    ),
                    value=f"`{friend_pseudo}`",
                    inline=False,
                )

            await channel.send(embed=embed)
            logging.debug(f"[ProfileSetup] Notification sent in {channel.name} for user {user_id}.")
        except Exception as e:
            logging.error(
                f"[ProfileSetup] ❌ Unable to send notification for user {user_id}: {e}",
                exc_info=True,
            )

        if key in self.welcome_messages:
            info = self.welcome_messages[key]
            try:
                channel = await self.bot.fetch_channel(info["channel"])
                message = await channel.fetch_message(info["message"])
                if not message.embeds:
                    logging.error(
                        f"[ProfileSetup] ❌ No embed found in welcome message for {session.get('pseudo', 'Unknown')}."
                    )
                    return
                embed = message.embeds[0]
                colors = {
                    "membre": discord.Color.gold(),
                    "postulation": discord.Color.purple(),
                    "diplomate": discord.Color.dark_blue(),
                    "allies": discord.Color.green(),
                    "amis": discord.Color.blue(),
                }
                embed.color = colors.get(session.get("motif"), discord.Color.default())
                tz_france = pytz.timezone("Europe/Paris")
                now = datetime.now(pytz.utc).astimezone(tz_france).strftime("%d/%m/%Y à %Hh%M")
                pending_text = PROFILE_SETUP_DATA["pending"].get(
                    guild_lang, PROFILE_SETUP_DATA["pending"].get("en-US")
                )
                if motif == "membre":
                    template = PROFILE_SETUP_DATA["accepted_membre"].get(
                        guild_lang, PROFILE_SETUP_DATA["accepted_membre"].get("en-US")
                    )
                    new_text = template.format(new_nickname=new_nickname, gs=gs, now=now)
                elif motif == "postulation":
                    template = PROFILE_SETUP_DATA["accepted_postulation"].get(
                        guild_lang, PROFILE_SETUP_DATA["accepted_postulation"].get("en-US")
                    )
                    new_text = template.format(new_nickname=new_nickname, gs=gs, now=now)
                elif motif == "diplomate":
                    guild_name = session.get("guild_name", "Unknown")
                    template = PROFILE_SETUP_DATA["accepted_diplomate"].get(
                        guild_lang, PROFILE_SETUP_DATA["accepted_diplomate"].get("en-US")
                    )
                    new_text = template.format(new_nickname=new_nickname, guild_name=guild_name, now=now)
                elif motif == "allies":
                    guild_name = session.get("guild_name", "Unknown")
                    template = PROFILE_SETUP_DATA["accepted_allies"].get(
                        guild_lang, PROFILE_SETUP_DATA["accepted_allies"].get("en-US")
                    )
                    new_text = template.format(new_nickname=new_nickname, guild_name=guild_name, now=now)
                elif motif == "amis":
                    friend_pseudo = session.get("friend_pseudo", "Unknown")
                    template = PROFILE_SETUP_DATA["accepted_amis"].get(
                        guild_lang, PROFILE_SETUP_DATA["accepted_amis"].get("en-US")
                    )
                    new_text = template.format(new_nickname=new_nickname, friend_pseudo=friend_pseudo, now=now)
                embed.description = embed.description.replace(pending_text, new_text)
                await message.edit(embed=embed)
                logging.debug(
                    f"[ProfileSetup] Welcome message updated for {session.get('pseudo', 'Unknown')} with motif {motif}."
                )
            except Exception as e:
                logging.error(f"[ProfileSetup] ❌ Error updating welcome message: {e}", exc_info=True)
        else:
            logging.debug(f"[ProfileSetup] No welcome message cached for key {key}.")

        if motif == "postulation":
            channels_data = self.forum_channels.get(guild_id, {})
            recruitment_category_id = channels_data.get("external_recruitment_cat")
            if not recruitment_category_id:
                logging.error(
                    "[ProfileSetup] Missing external recruitment category ID. Channel creation aborted."
                )
            else:
                recruitment_category = guild.get_channel(recruitment_category_id)
                if recruitment_category is None:
                    logging.error(
                        f"[ProfileSetup] Recruitment category ID {recruitment_category_id} not found in guild {guild.id}."
                    )
                else:
                    channel_name = f"{member.display_name}".replace(" ", "-").lower()
                    overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
                    applicant_role_id = self.roles.get(guild_id, {}).get("applicant")
                    if applicant_role_id:
                        applicant_role = guild.get_role(applicant_role_id)
                        if applicant_role:
                            overwrites[applicant_role] = discord.PermissionOverwrite(view_channel=False)
                    overwrites[member] = discord.PermissionOverwrite(
                        view_channel=True, send_messages=True, read_message_history=True
                    )
                    for role_name in ["guild_master", "officer", "guardian"]:
                        role_id = self.roles.get(guild_id, {}).get(role_name)
                        if role_id:
                            role_obj = guild.get_role(role_id)
                            if role_obj:
                                overwrites[role_obj] = discord.PermissionOverwrite(
                                    view_channel=True,
                                    send_messages=True,
                                    read_message_history=True,
                                    manage_channels=True,
                                )
                    try:
                        new_channel = await guild.create_text_channel(
                            name=channel_name,
                            category=recruitment_category,
                            topic=f"Individual application channel for {member.display_name}",
                            overwrites=overwrites,
                        )
                        await new_channel.send(
                            content="@everyone",
                            embed=postulation_embed,
                            allowed_mentions=discord.AllowedMentions(everyone=True)
                        )
                        logging.info(
                            f"[ProfileSetup] Recruitment channel created: {new_channel.name} (ID: {new_channel.id}) for user {member.id}"
                        )
                    except Exception as e:
                        logging.error(
                            f"[ProfileSetup] Error creating individual channel for {member.display_name}: {e}"
                        )

        guildmembers_cog = self.bot.get_cog("GuildMembers")
        if guildmembers_cog:
            await guildmembers_cog.load_user_setup_members()

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
            lang_msg = PROFILE_SETUP_DATA["language_saved"].get(
                self.locale, PROFILE_SETUP_DATA["language_saved"].get("en-US")
            )
            await interaction.response.send_message(lang_msg, ephemeral=True)
            await interaction.user.send(view=ProfileSetup.MotifModalView(cog, self.locale, guild_id))

    class LangSelectView(discord.ui.View):
        def __init__(self, cog: "ProfileSetup", guild_id: int):
            super().__init__(timeout=180)
            self.cog = cog
            self.guild_id = guild_id
            for locale in SUPPORTED_LOCALES:
                self.add_item(ProfileSetup.LangButton(locale))

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
            placeholder = PROFILE_SETUP_DATA["motif_select"].get(
                locale, PROFILE_SETUP_DATA["motif_select"].get("en-US")
            )
            super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

        async def callback(self, interaction: discord.Interaction):
            try:
                cog: ProfileSetup = self.view.cog
                guild_id = self.guild_id
                user_id = interaction.user.id
                logging.debug(f"[ProfileSetup] MotifSelect callback for guild_id={guild_id}, user_id={user_id}")
                session = await cog.load_session(guild_id, user_id)
                session["motif"] = self.values[0]
                message = PROFILE_SETUP_DATA["motif_saved"].get(
                    self.locale, PROFILE_SETUP_DATA["motif_saved"].get("en-US")
                )
                await interaction.response.send_message(message, ephemeral=True)
                await interaction.user.send(
                    view=ProfileSetup.QuestionsSelectView(cog, self.locale, guild_id, self.values[0])
                )
            except Exception:
                logging.error("[ProfileSetup] Error in MotifSelect callback", exc_info=True)

    class MotifModalView(discord.ui.View):
        def __init__(self, cog: "ProfileSetup", locale: str, guild_id: int):
            super().__init__(timeout=180)
            self.cog = cog
            self.locale = locale
            self.guild_id = guild_id
            self.add_item(ProfileSetup.MotifSelect(locale, guild_id))

    class QuestionsSelect(discord.ui.Modal):
        def __init__(self, locale: str, guild_id: int, motif: str):
            title = PROFILE_SETUP_DATA["questions_title"].get(locale, PROFILE_SETUP_DATA["questions_title"].get("en-US"))
            super().__init__(title=title)
            self.locale = locale
            self.guild_id = guild_id
            self.motif = motif
            logging.debug(
                f"[ProfileSetup] Initializing QuestionsSelect modal for guild_id={guild_id}, motif={motif}, locale={locale}"
            )

            self.pseudo = discord.ui.InputText(
                label=PROFILE_SETUP_DATA["pseudo_select"].get(locale, PROFILE_SETUP_DATA["pseudo_select"].get("en-US")),
                min_length=3,
                max_length=16,
                required=True,
            )
            self.add_item(self.pseudo)

            if motif in ["diplomate", "allies"]:
                self.guild_name = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["guild_select"].get(locale, PROFILE_SETUP_DATA["guild_select"].get("en-US")),
                    min_length=3,
                    max_length=16,
                    required=True,
                )
                self.add_item(self.guild_name)

                self.guild_acronym = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["guild_acronym"].get(locale, PROFILE_SETUP_DATA["guild_acronym"].get("en-US")),
                    min_length=3,
                    max_length=3,
                    required=True,
                )
                self.add_item(self.guild_acronym)

            if motif == "amis":
                self.friend_pseudo = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["friend_pseudo"].get(locale, PROFILE_SETUP_DATA["friend_pseudo"].get("en-US")),
                    min_length=3,
                    max_length=16,
                    required=True,
                )
                self.add_item(self.friend_pseudo)

            if motif in ["postulation", "membre"]:
                self.weapons = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["weapons_select"].get(locale, PROFILE_SETUP_DATA["weapons_select"].get("en-US")),
                    required=True,
                    placeholder="SNS / GS / SP / DG / B / S / W / CB",
                )
                self.add_item(self.weapons)

                self.gs = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["gs"].get(locale, PROFILE_SETUP_DATA["gs"].get("en-US")),
                    required=True,
                    min_length=3,
                    max_length=4,
                )
                self.add_item(self.gs)

            if motif == "postulation":
                self.gametype = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["gametype_select"].get(locale, PROFILE_SETUP_DATA["gametype_select"].get("en-US")),
                    required=True,
                    placeholder="PvE / PvP / PvE + PvP",
                )
                self.add_item(self.gametype)

                self.playtime = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["playtime_select"].get(locale, PROFILE_SETUP_DATA["playtime_select"].get("en-US")),
                    required=True,
                    placeholder="**h / week",
                )
                self.add_item(self.playtime)

        async def callback(self, interaction: discord.Interaction):
            try:
                logging.debug(f"[ProfileSetup] QuestionsSelect submitted by user {interaction.user.id} in guild {self.guild_id}.")
                cog: ProfileSetup = interaction.client.get_cog("ProfileSetup")
                if not cog:
                    logging.error("[ProfileSetup] Cog 'ProfileSetup' not found.")
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
                    weapons_input = self.weapons.value
                    llm_cog = interaction.client.get_cog("LLMInteraction")
                    try:
                        weapons_clean = (
                            await llm_cog.normalize_weapons(weapons_input) if llm_cog else weapons_input
                        )
                    except Exception:
                        weapons_clean = weapons_input
                    session["weapons"] = weapons_clean[:32]
                    session["gs"] = self.gs.value
                if hasattr(self, "gametype"):
                    raw_playtime = self.playtime.value.strip()
                    session["gametype"] = self.gametype.value
                    session["playtime"] = raw_playtime[:MAX_PLAYTIME_LEN]
                    if len(raw_playtime) > MAX_PLAYTIME_LEN:
                        logging.warning(
                            f"[ProfileSetup] Playtime truncated at modal input for user {user_id}"
                        )
                logging.debug(f"[ProfileSetup] Session after update: {session}")
                await interaction.response.defer(ephemeral=True)
                await cog.finalize_profile(guild_id, user_id)
                await interaction.followup.send(
                    PROFILE_SETUP_DATA["setup_complete"].get(self.locale, PROFILE_SETUP_DATA["setup_complete"].get("en-US")),
                    ephemeral=True,
                )
                logging.debug("[ProfileSetup] QuestionsSelect modal submission processed successfully.")
            except Exception:
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
                    logging.error(f"[ProfileSetup] Modal contains {len(modal.children)} fields, exceeding Discord limit of 5.")
                    await interaction.response.send_message("⚠️ Too many fields in the form! Contact an admin.", ephemeral=True)
                    return
                await interaction.response.send_modal(modal)
                logging.debug("[ProfileSetup] Modal sent successfully.")
            except Exception:
                logging.error("[ProfileSetup] Failed to send modal.", exc_info=True)
                await interaction.response.send_message("❌ Error while displaying the form.", ephemeral=True)

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
