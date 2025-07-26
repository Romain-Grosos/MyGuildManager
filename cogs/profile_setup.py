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
        self.pending_validations: Dict[str, Dict[str, Any]] = {}
        self.session_locks: Dict[str, asyncio.Lock] = {}

    async def load_session(self, guild_id: int, user_id: int) -> Dict[str, Any]:
        key = f"{guild_id}_{user_id}"
        if key not in self.sessions:
            self.sessions[key] = {}
        if key not in self.session_locks:
            self.session_locks[key] = asyncio.Lock()
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
                   gc.category_diplo,
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
                    category_diplo,
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
                    "category_diplo": category_diplo,
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

    async def load_pending_validations_cache(self) -> None:
        logging.debug("[ProfileSetup] Loading pending validations from DB")
        query = """
            SELECT guild_id, member_id, guild_name, channel_id, message_id, created_at 
            FROM pending_diplomat_validations 
            WHERE status = 'pending'
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.pending_validations = {}
            for row in rows:
                guild_id, member_id, guild_name, channel_id, message_id, created_at = row
                key = f"{guild_id}_{member_id}_{guild_name}"
                self.pending_validations[key] = {
                    "guild_id": guild_id,
                    "member_id": member_id,
                    "guild_name": guild_name,
                    "channel_id": channel_id,
                    "message_id": message_id,
                    "created_at": created_at
                }
            logging.debug(f"[ProfileSetup] Pending validations loaded: {self.pending_validations}")
        except Exception as e:
            logging.error(f"[ProfileSetup] Error while loading pending validations: {e}")

    async def restore_pending_validation_views(self) -> None:
        logging.debug("[ProfileSetup] Restoring pending validation views")
        
        await asyncio.sleep(2)
        
        for key, validation_data in self.pending_validations.items():
            try:
                guild_id = validation_data["guild_id"]
                member_id = validation_data["member_id"]
                guild_name = validation_data["guild_name"]
                channel_id = validation_data["channel_id"]
                message_id = validation_data["message_id"]
                
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    logging.warning(f"[ProfileSetup] Guild {guild_id} not found for pending validation")
                    continue
                
                member = guild.get_member(member_id)
                if not member:
                    logging.warning(f"[ProfileSetup] Member {member_id} not found for pending validation")
                    continue
                
                channel = await self.bot.fetch_channel(channel_id)
                if not channel:
                    logging.warning(f"[ProfileSetup] Channel {channel_id} not found for pending validation")
                    continue
                
                try:
                    message = await channel.fetch_message(message_id)
                except discord.NotFound:
                    logging.warning(f"[ProfileSetup] Message {message_id} not found, removing from pending validations")
                    await self.remove_pending_validation(guild_id, member_id, guild_name)
                    continue
                
                guild_lang = self.forum_channels.get(guild_id, {}).get("guild_lang", "en-US")
                view = self.DiplomatValidationView(member, channel, guild_lang, guild_name)
                view.original_message = message
                
                self.bot.add_view(view, message_id=message_id)
                
                logging.info(f"[ProfileSetup] Restored validation view for {member.display_name} in guild '{guild_name}'")
                
            except Exception as e:
                logging.error(f"[ProfileSetup] Error restoring validation view for key {key}: {e}")

    async def save_pending_validation(self, guild_id: int, member_id: int, guild_name: str, 
                                    channel_id: int, message_id: int) -> None:
        query = """
            INSERT INTO pending_diplomat_validations 
            (guild_id, member_id, guild_name, channel_id, message_id, status)
            VALUES (%s, %s, %s, %s, %s, 'pending')
        """
        try:
            await self.bot.run_db_query(query, (guild_id, member_id, guild_name, channel_id, message_id), commit=True)
            
            key = f"{guild_id}_{member_id}_{guild_name}"
            self.pending_validations[key] = {
                "guild_id": guild_id,
                "member_id": member_id,
                "guild_name": guild_name,
                "channel_id": channel_id,
                "message_id": message_id,
                "created_at": "now"
            }
            logging.debug(f"[ProfileSetup] Saved pending validation for {member_id} in guild '{guild_name}'")
        except Exception as e:
            error_msg = str(e).lower()
            if "duplicate entry" in error_msg or "1062" in error_msg:
                logging.warning(f"[ProfileSetup] Pending validation already exists for {member_id} in guild '{guild_name}'")
            elif "foreign key constraint" in error_msg or "1452" in error_msg:
                logging.error(f"[ProfileSetup] Foreign key constraint failed for pending validation: {e}")
            else:
                logging.error(f"[ProfileSetup] Error saving pending validation: {e}")
            raise

    async def remove_pending_validation(self, guild_id: int, member_id: int, guild_name: str) -> None:
        query = """
            UPDATE pending_diplomat_validations 
            SET status = 'completed', completed_at = NOW()
            WHERE guild_id = %s AND member_id = %s AND guild_name = %s AND status = 'pending'
        """
        try:
            await self.bot.run_db_query(query, (guild_id, member_id, guild_name), commit=True)
            
            key = f"{guild_id}_{member_id}_{guild_name}"
            if key in self.pending_validations:
                del self.pending_validations[key]
                
            logging.debug(f"[ProfileSetup] Removed pending validation for {member_id} in guild '{guild_name}'")
        except Exception as e:
            logging.error(f"[ProfileSetup] Error removing pending validation: {e}")

    async def validate_guild_name_with_llm(self, guild_name: str, category_channel) -> str:
        try:
            existing_guild_names = []
            for channel in category_channel.channels:
                if isinstance(channel, discord.TextChannel) and channel.name.startswith("diplo-"):
                    channel_guild_name = channel.name.replace("diplo-", "").replace("-", " ").title()
                    existing_guild_names.append(channel_guild_name)
            
            if not existing_guild_names:
                return guild_name
            
            llm_cog = self.bot.get_cog("LLMInteraction")
            if not llm_cog:
                logging.warning("[ProfileSetup] LLMInteraction cog not found for guild name validation")
                return guild_name
            
            prompt = f"""Compare the guild name '{guild_name}' with these existing guild names: {', '.join(existing_guild_names)}.
            If '{guild_name}' is very similar to any existing guild name (likely typos, abbreviations), return the most similar already existing guild name.
            If '{guild_name}' is clearly different and unique, return '{guild_name}' unchanged.
            Examples:
            - Prompted "Guild War" vs existing "Guild Wars" -> return "Guild Wars"
            - Prompted "MGM" vs existing "MGM Guild" -> return "MGM Guild"
            - Prompted "DarK Kights" vs existing "Dark Knights" -> return "Dark Knights"
            Only return the guild name, nothing else."""
            
            try:
                response = await llm_cog.safe_ai_query(prompt)
                validated_name = response.strip().strip('"').strip("'")
                
                if validated_name in existing_guild_names:
                    logging.info(f"[ProfileSetup] LLM detected similar guild: '{guild_name}' -> '{validated_name}'")
                    return validated_name
                elif validated_name == guild_name:
                    return guild_name
                else:
                    logging.warning(f"[ProfileSetup] LLM returned unexpected result: '{validated_name}', using original: '{guild_name}'")
                    return guild_name
                    
            except Exception as e:
                logging.error(f"[ProfileSetup] Error calling LLM for guild name validation: {e}")
                return guild_name
                
        except Exception as e:
            logging.error(f"[ProfileSetup] Error in validate_guild_name_with_llm: {e}")
            return guild_name

    @commands.Cog.listener()
    async def on_ready(self):
        asyncio.create_task(self.load_roles())
        asyncio.create_task(self.load_forum_channels())
        asyncio.create_task(self.load_welcome_messages_cache())
        asyncio.create_task(self.load_pending_validations_cache())
        asyncio.create_task(self.restore_pending_validation_views())
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
                (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                pseudo = %s, locale = %s, motif = %s, friend_pseudo = %s, weapons = %s, guild_name = %s, guild_acronym = %s, gs = %s, playtime = %s, gametype = %s
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
            logging.debug(f"[ProfileSetup] Motif for user {user_id}: {motif}")
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

            if motif == "membre":
                embed_color = discord.Color.gold()
            elif motif == "postulation":
                embed_color = discord.Color.purple()
            elif motif == "diplomate":
                embed_color = discord.Color.dark_blue()
            elif motif == "allies":
                embed_color = discord.Color.green()
            elif motif == "amis":
                embed_color = discord.Color.blue()
            else:
                embed_color = discord.Color.blue()
            
            logging.debug(f"[ProfileSetup] Embed color for motif '{motif}': {embed_color}")
            
            embed = discord.Embed(
                title=PROFILE_SETUP_DATA["notification"]["title"].get(
                    self.locale, PROFILE_SETUP_DATA["notification"]["title"].get("en-US")
                ),
                color=embed_color,
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

        elif motif == "diplomate":
            channels_data = self.forum_channels.get(guild_id, {})
            diplomats_category_id = channels_data.get("category_diplo")
            if not diplomats_category_id:
                logging.error(
                    "[ProfileSetup] Missing diplomacy category ID. Diplomat channel creation aborted."
                )
            else:
                diplomats_category = guild.get_channel(diplomats_category_id)
                if diplomats_category is None:
                    logging.error(
                        f"[ProfileSetup] Diplomats category ID {diplomats_category_id} not found in guild {guild.id}."
                    )
                else:
                    guild_name = session.get("guild_name", "Unknown")
                    
                    validated_guild_name = await self.validate_guild_name_with_llm(guild_name, diplomats_category)
                    if validated_guild_name != guild_name:
                        logging.warning(
                            f"[ProfileSetup] Guild name similarity detected: '{guild_name}' -> '{validated_guild_name}'"
                        )
                        guild_name = validated_guild_name
                        session["guild_name"] = validated_guild_name
                    
                    normalized_guild_name = guild_name.replace(" ", "-").lower()
                    
                    existing_channels = [
                        ch for ch in diplomats_category.channels 
                        if isinstance(ch, discord.TextChannel) and normalized_guild_name in ch.name.lower()
                    ]
                    
                    if existing_channels:
                        existing_channel = existing_channels[0]
                        logging.info(
                            f"[ProfileSetup] Found existing diplomat channel for guild '{guild_name}': {existing_channel.name}"
                        )
                        
                        existing_members = [
                            m for m in existing_channel.members 
                            if m != guild.me and any(
                                role.id == self.roles.get(guild_id, {}).get("diplomats") 
                                for role in m.roles
                            )
                        ]
                        
                        if existing_members:
                            logging.warning(
                                f"[ProfileSetup] Anti-espionage: Channel for '{guild_name}' already has diplomat {existing_members[0].display_name}. "
                                f"New diplomat {member.display_name} needs manual validation."
                            )
                            
                            guild_lang = channels_data.get("guild_lang", "en-US")
                            alert_text = PROFILE_SETUP_DATA["anti_espionage"]["alert_message"].get(
                                guild_lang, PROFILE_SETUP_DATA["anti_espionage"]["alert_message"].get("en-US")
                            ).format(
                                new_diplomat=member.display_name,
                                guild_name=guild_name,
                                existing_diplomat=existing_members[0].mention
                            )
                            
                            diplomate_embed = embed.copy()
                            
                            view = self.DiplomatValidationView(member, existing_channel, guild_lang, guild_name)
                            message = await existing_channel.send(
                                f"@everyone\n\n{alert_text}",
                                embed=diplomate_embed,
                                view=view,
                                allowed_mentions=discord.AllowedMentions(everyone=True, users=True)
                            )
                            view.original_message = message
                            
                            await self.save_pending_validation(guild_id, member.id, guild_name, existing_channel.id, message.id)
                            
                            overwrites = existing_channel.overwrites.copy()
                            overwrites[member] = discord.PermissionOverwrite(view_channel=False)
                            
                            await existing_channel.edit(overwrites=overwrites)
                            
                            user_locale = session.get("locale", "en-US")
                            pending_message = PROFILE_SETUP_DATA["anti_espionage"]["pending_notification"].get(
                                user_locale, PROFILE_SETUP_DATA["anti_espionage"]["pending_notification"].get("en-US")
                            ).format(
                                diplomat_name=member.display_name,
                                guild_name=guild_name
                            )
                            
                            try:
                                await member.send(pending_message)
                                logging.info(f"[ProfileSetup] Pending notification sent to diplomat {member.display_name}")
                            except discord.Forbidden:
                                logging.warning(f"[ProfileSetup] Could not send pending notification to {member.display_name} - DMs disabled")
                            except Exception as e:
                                logging.error(f"[ProfileSetup] Error sending pending notification to {member.display_name}: {e}")
                            
                            logging.info(
                                f"[ProfileSetup] Diplomat {member.display_name} added to pending validation for guild '{guild_name}'"
                            )
                        else:
                            overwrites = existing_channel.overwrites
                            overwrites[member] = discord.PermissionOverwrite(
                                view_channel=True,
                                send_messages=True,
                                read_message_history=True
                            )
                            await existing_channel.edit(overwrites=overwrites)
                            
                            diplomate_embed = embed.copy()
                            await existing_channel.send(
                                embed=diplomate_embed,
                                allowed_mentions=discord.AllowedMentions(everyone=False)
                            )
                            
                            logging.info(
                                f"[ProfileSetup] Diplomat {member.display_name} added to existing channel for guild '{guild_name}'"
                            )
                    else:
                        channel_name = f"diplo-{normalized_guild_name}"
                        overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
                        
                        diplomat_role_id = self.roles.get(guild_id, {}).get("diplomats")
                        if diplomat_role_id:
                            diplomat_role = guild.get_role(diplomat_role_id)
                            if diplomat_role:
                                overwrites[diplomat_role] = discord.PermissionOverwrite(view_channel=False)
                        
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
                                category=diplomats_category,
                                topic=f"Diplomatic channel for guild {guild_name}",
                                overwrites=overwrites,
                            )
                            
                            diplomate_embed = embed.copy()
                            await new_channel.send(
                                embed=diplomate_embed,
                                allowed_mentions=discord.AllowedMentions(everyone=False)
                            )
                            
                            logging.info(
                                f"[ProfileSetup] Diplomat channel created: {new_channel.name} (ID: {new_channel.id}) for guild '{guild_name}'"
                            )
                        except Exception as e:
                            logging.error(
                                f"[ProfileSetup] Error creating diplomat channel for guild '{guild_name}': {e}"
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

    class DiplomatValidationButton(discord.ui.Button):
        def __init__(self, member: discord.Member, channel: discord.TextChannel, guild_lang: str, guild_name: str = "Unknown"):
            button_text = PROFILE_SETUP_DATA["anti_espionage"]["validation_button"].get(
                guild_lang, PROFILE_SETUP_DATA["anti_espionage"]["validation_button"].get("en-US")
            )
            custom_id = f"validate_diplomat_{member.guild.id}_{member.id}_{hash(guild_name) % 10000}"
            super().__init__(label=button_text, style=discord.ButtonStyle.success, custom_id=custom_id)
            self.member = member
            self.channel = channel
            self.guild_lang = guild_lang
            self.guild_name = guild_name

        async def callback(self, interaction: discord.Interaction):
            try:
                channel_perms = self.channel.permissions_for(interaction.user)
                can_manage = channel_perms.manage_channels or channel_perms.administrator
                has_channel_access = channel_perms.view_channel and channel_perms.send_messages
                
                if not (can_manage or has_channel_access):
                    permission_denied_text = PROFILE_SETUP_DATA["anti_espionage"]["permission_denied"].get(
                        self.guild_lang, PROFILE_SETUP_DATA["anti_espionage"]["permission_denied"].get("en-US")
                    )
                    await interaction.response.send_message(permission_denied_text, ephemeral=True)
                    return

                overwrites = self.channel.overwrites
                overwrites[self.member] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )
                
                await self.channel.edit(overwrites=overwrites)
                
                self.disabled = True
                for item in self.view.children:
                    item.disabled = True
                
                success_text = PROFILE_SETUP_DATA["anti_espionage"]["validation_success"].get(
                    self.guild_lang, PROFILE_SETUP_DATA["anti_espionage"]["validation_success"].get("en-US")
                ).format(diplomat_name=self.member.display_name)
                
                validation_by_text = f"\n👤 Validé par : {interaction.user.mention}"
                full_message = success_text + validation_by_text
                
                await interaction.response.send_message(full_message, view=None)
                
                try:
                    if self.view.original_message:
                        await self.view.original_message.edit(view=self.view)
                except discord.NotFound:
                    pass
                except Exception as e:
                    logging.error(f"[ProfileSetup] Error updating original message: {e}")
                
                try:
                    cog = interaction.client.get_cog("ProfileSetup")
                    if cog:
                        query = "SELECT locale FROM user_setup WHERE guild_id = %s AND user_id = %s"
                        result = await interaction.client.run_db_query(query, (interaction.guild.id, self.member.id), fetch_one=True)
                        user_locale = result[0] if result else "en-US"
                    else:
                        user_locale = "en-US"
                        
                    granted_message = PROFILE_SETUP_DATA["anti_espionage"]["access_granted_notification"].get(
                        user_locale, PROFILE_SETUP_DATA["anti_espionage"]["access_granted_notification"].get("en-US")
                    ).format(
                        diplomat_name=self.member.display_name,
                        guild_name=self.guild_name
                    )
                    
                    await self.member.send(granted_message)
                    logging.info(f"[ProfileSetup] Access granted notification sent to {self.member.display_name}")
                    
                except discord.Forbidden:
                    logging.warning(f"[ProfileSetup] Could not send access granted notification to {self.member.display_name} - DMs disabled")
                except Exception as e:
                    logging.error(f"[ProfileSetup] Error sending access granted notification to {self.member.display_name}: {e}")
                
                cog = interaction.client.get_cog("ProfileSetup")
                if cog:
                    await cog.remove_pending_validation(self.member.guild.id, self.member.id, self.guild_name)
                
                logging.info(f"[ProfileSetup] Diplomat {self.member.display_name} validated by {interaction.user.display_name}")
                
            except Exception as e:
                error_text = PROFILE_SETUP_DATA["anti_espionage"]["validation_error"].get(
                    self.guild_lang, PROFILE_SETUP_DATA["anti_espionage"]["validation_error"].get("en-US")
                ).format(diplomat_name=self.member.display_name)
                
                await interaction.response.send_message(error_text, ephemeral=True)
                logging.error(f"[ProfileSetup] Error validating diplomat {self.member.display_name}: {e}")

    class DiplomatValidationView(discord.ui.View):
        def __init__(self, member: discord.Member, channel: discord.TextChannel, guild_lang: str, guild_name: str = "Unknown"):
            super().__init__(timeout=86400)
            self.member = member
            self.channel = channel
            self.guild_lang = guild_lang
            self.guild_name = guild_name
            self.original_message = None
            self.add_item(ProfileSetup.DiplomatValidationButton(member, channel, guild_lang, guild_name))
        
        async def on_timeout(self):
            for item in self.children:
                item.disabled = True
            
            message_text = PROFILE_SETUP_DATA["anti_espionage"]["validation_timeout"].get(
                self.guild_lang, PROFILE_SETUP_DATA["anti_espionage"]["validation_timeout"].get("en-US")
            )
            
            try:
                from discord.ext import commands
                bot = commands.Bot.get_bot()
                if bot:
                    cog = bot.get_cog("ProfileSetup")
                    if cog:
                        query = """
                            UPDATE pending_diplomat_validations 
                            SET status = 'expired', completed_at = NOW()
                            WHERE guild_id = %s AND member_id = %s AND guild_name = %s AND status = 'pending'
                        """
                        await bot.run_db_query(query, (self.member.guild.id, self.member.id, self.guild_name), commit=True)
                        
                        key = f"{self.member.guild.id}_{self.member.id}_{self.guild_name}"
                        if key in cog.pending_validations:
                            del cog.pending_validations[key]
                
                if self.original_message:
                    try:
                        await self.original_message.edit(view=self)
                    except discord.NotFound:
                        pass
                
                await self.channel.send(message_text)
                logging.info(f"[ProfileSetup] Validation timeout for diplomat {self.member.display_name}")
            except Exception as e:
                logging.error(f"[ProfileSetup] Error handling timeout: {e}")

def setup(bot: discord.Bot):
    bot.add_cog(ProfileSetup(bot))
