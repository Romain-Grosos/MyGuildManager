"""
Profile Setup Cog - Manages member profile creation and role assignment workflow.
"""

import asyncio
import logging
import re
from datetime import datetime
from typing import Dict, Tuple, Any, Optional

import discord
import pytz
from discord.ext import commands

from core.translation import translations as global_translations
from db import DBQueryError

MAX_PLAYTIME_LEN = 64
SUPPORTED_LOCALES = global_translations.get("global", {}).get("supported_locales", ["en-US", "fr", "es-ES", "de", "it"])
LANGUAGE_NAMES = global_translations.get("global", {}).get("language_names", {})
WELCOME_MP = global_translations.get("welcome_mp", {})
PROFILE_SETUP_DATA = global_translations.get("profile_setup", {})

class ProfileSetup(commands.Cog):
    """Cog for managing member profile creation and role assignment workflow."""
    
    def __init__(self, bot: discord.Bot) -> None:
        """
        Initialize the ProfileSetup cog.
        
        Args:
            bot: Discord bot instance
        """
        self.bot = bot
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.session_locks: Dict[str, asyncio.Lock] = {}

    async def load_session(self, guild_id: int, user_id: int) -> Dict[str, Any]:
        """
        Load or create a user session for profile setup.
        
        Args:
            guild_id: Discord guild ID
            user_id: Discord user ID
            
        Returns:
            Dictionary containing user session data
        """
        key = f"{guild_id}_{user_id}"
        if key not in self.sessions:
            self.sessions[key] = {}
        if key not in self.session_locks:
            self.session_locks[key] = asyncio.Lock()
        return self.sessions[key]
    
    async def get_guild_lang(self, guild_id: int) -> str:
        """
        Get guild language from cache.
        
        Args:
            guild_id: Discord guild ID
            
        Returns:
            Guild language code (default: en-US)
        """
        guild_lang = await self.bot.cache.get_guild_data(guild_id, 'guild_lang')
        return guild_lang or "en-US"
    
    async def get_guild_settings(self, guild_id: int) -> Dict[str, Any]:
        """
        Get guild settings from cache.
        
        Args:
            guild_id: Discord guild ID
            
        Returns:
            Dictionary containing guild settings
        """
        settings = await self.bot.cache.get_guild_data(guild_id, 'guild_settings')
        return settings or {}
    
    async def get_guild_roles(self, guild_id: int) -> Dict[str, Any]:
        """
        Get guild roles from cache.
        
        Args:
            guild_id: Discord guild ID
            
        Returns:
            Dictionary containing guild role IDs
        """
        roles = await self.bot.cache.get_guild_data(guild_id, 'roles')
        return roles or {}
    
    async def get_guild_channels(self, guild_id: int) -> Dict[str, Any]:
        """
        Get guild channels from cache.
        
        Args:
            guild_id: Discord guild ID
            
        Returns:
            Dictionary containing guild channel IDs
        """
        channels = await self.bot.cache.get_guild_data(guild_id, 'channels')
        return channels or {}
    
    async def get_welcome_message_for_user(self, guild_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get welcome message for a specific user from cache.
        
        Args:
            guild_id: Discord guild ID
            user_id: Discord user ID
            
        Returns:
            Dictionary with welcome message info or None if not found
        """
        return await self.bot.cache.get_user_data(guild_id, user_id, 'welcome_message')
    
    async def get_pending_validations(self) -> Dict[str, Dict[str, Any]]:
        """
        Get pending validations from cache.
        
        Returns:
            Dictionary containing pending diplomat validations
        """
        validations = await self.bot.cache.get('temporary', 'pending_validations')
        return validations or {}

    def _sanitize_llm_input(self, text: str) -> str:
        """Sanitize text input for LLM queries to prevent prompt injection attacks.
        
        Args:
            text: Raw text input from user
            
        Returns:
            str: Sanitized text safe for LLM prompts
        """
        if not isinstance(text, str):
            return ""

        dangerous_patterns = [
            r'```.*?```',
            r'`[^`]*`',
            r'\n\s*[Rr]esponse:',
            r'\n\s*[Ii]nstruct(ion)?s?:',
            r'\n\s*[Tt]ask:',
            r'\n\s*[Ss]ystem:',
            r'\n\s*[Aa]ssistant:',
            r'\n\s*[Uu]ser:',
            r'<\|.*?\|>',
            r'\[INST\].*?\[/INST\]',
            r'###.*?###',
        ]
        
        sanitized = text
        for pattern in dangerous_patterns:
            sanitized = re.sub(pattern, '', sanitized, flags=re.IGNORECASE | re.DOTALL)

        sanitized = re.sub(r'\n+', ' ', sanitized)
        sanitized = re.sub(r'\s+', ' ', sanitized)

        sanitized = re.sub(r'[<>"\'`\\]', '', sanitized)

        max_length = 100
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length].strip()
            logging.debug(f"[ProfileSetup] Truncated LLM input to {max_length} characters")

        sanitized = sanitized.strip()
        if not sanitized:
            logging.warning("[ProfileSetup] Input became empty after LLM sanitization")
            return "Unknown"
        
        return sanitized

    def _validate_llm_response(self, response: str, original_input: str, valid_options: list) -> str:
        """Validate LLM response to prevent malicious or unexpected outputs.
        
        Args:
            response: Raw response from LLM
            original_input: The original user input
            valid_options: List of valid response options
            
        Returns:
            str: Validated response or original input if validation fails
        """
        if not isinstance(response, str):
            logging.warning("[ProfileSetup] LLM response is not a string")
            return original_input

        cleaned_response = response.strip().strip('"').strip("'")

        if len(cleaned_response) > 200:
            logging.warning(f"[ProfileSetup] LLM response too long ({len(cleaned_response)} chars), rejecting")
            return original_input

        dangerous_patterns = [
            r'```.*?```',
            r'<script',
            r'javascript:',
            r'data:',
            r'<.*?>',
            r'\n\s*[Ii]nstruct',
            r'\n\s*[Ss]ystem',
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, cleaned_response, re.IGNORECASE | re.DOTALL):
                logging.warning(f"[ProfileSetup] LLM response contains dangerous pattern, rejecting")
                return original_input

        if cleaned_response == original_input:
            return cleaned_response
        
        if cleaned_response in valid_options:
            return cleaned_response

        cleaned_lower = cleaned_response.lower()
        for option in valid_options:
            if option.lower() == cleaned_lower:
                return option

        logging.warning(f"[ProfileSetup] LLM response '{cleaned_response}' not in valid options, using original")
        return original_input


    async def _load_pending_validations(self) -> None:
        """
        Load pending diplomat validations into cache.
        
        Retrieves all pending diplomat validations from database and stores
        them in cache for restoration after bot restart.
        """
        logging.debug("[ProfileSetup] Loading pending validations from database")
        query = """
            SELECT guild_id, member_id, guild_name, channel_id, message_id, created_at 
            FROM pending_diplomat_validations 
            WHERE status = 'pending'
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            pending_validations = {}
            for row in rows:
                guild_id, member_id, guild_name, channel_id, message_id, created_at = row
                key = f"{guild_id}_{member_id}_{guild_name}"
                pending_validations[key] = {
                    "guild_id": guild_id,
                    "member_id": member_id,
                    "guild_name": guild_name,
                    "channel_id": channel_id,
                    "message_id": message_id,
                    "created_at": created_at
                }
            await self.bot.cache.set('temporary', pending_validations, 'pending_validations')
            logging.debug(f"[ProfileSetup] Pending validations loaded: {len(pending_validations)} entries")
        except Exception as e:
            logging.error(f"[ProfileSetup] Error loading pending validations: {e}", exc_info=True)


    async def restore_pending_validation_views(self) -> None:
        """
        Restore pending validation views after bot restart.
        
        Re-attaches Discord UI views to pending validation messages
        so buttons remain functional after bot restarts.
        """
        logging.debug("[ProfileSetup] Restoring pending validation views")
        
        await asyncio.sleep(2)

        await self._load_pending_validations()
        
        pending_validations = await self.get_pending_validations()
        for key, validation_data in pending_validations.items():
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
                
                guild_lang = await self.get_guild_lang(guild_id)
                view = self.DiplomatValidationView(member, channel, guild_lang, guild_name, self.bot)
                view.original_message = message
                
                self.bot.add_view(view, message_id=message_id)
                
                logging.info(f"[ProfileSetup] Restored validation view for {member.display_name} in guild '{guild_name}'")
                
            except Exception as e:
                logging.error(f"[ProfileSetup] Error restoring validation view for key {key}: {e}")
    async def save_pending_validation(self, guild_id: int, member_id: int, guild_name: str, 
                                    channel_id: int, message_id: int) -> None:
        """
        Save pending validation to database and cache.
        
        Args:
            guild_id: Discord guild ID
            member_id: Discord member ID requiring validation
            guild_name: Name of the guild being validated for
            channel_id: Discord channel ID where validation message is
            message_id: Discord message ID of the validation message
        """
        query = """
            INSERT INTO pending_diplomat_validations 
            (guild_id, member_id, guild_name, channel_id, message_id, status)
            VALUES (%s, %s, %s, %s, %s, 'pending')
        """
        try:
            await self.bot.run_db_query(query, (guild_id, member_id, guild_name, channel_id, message_id), commit=True)
            
            key = f"{guild_id}_{member_id}_{guild_name}"
            pending_validations = await self.get_pending_validations()
            pending_validations[key] = {
                "guild_id": guild_id,
                "member_id": member_id,
                "guild_name": guild_name,
                "channel_id": channel_id,
                "message_id": message_id,
                "created_at": "now"
            }
            await self.bot.cache.set('temporary', pending_validations, 'pending_validations')
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
        """
        Remove pending validation from database and cache.
        
        Args:
            guild_id: Discord guild ID
            member_id: Discord member ID to remove validation for
            guild_name: Name of the guild validation was for
        """
        query = """
            UPDATE pending_diplomat_validations 
            SET status = 'completed', completed_at = NOW()
            WHERE guild_id = %s AND member_id = %s AND guild_name = %s AND status = 'pending'
        """
        try:
            await self.bot.run_db_query(query, (guild_id, member_id, guild_name), commit=True)
            
            key = f"{guild_id}_{member_id}_{guild_name}"
            pending_validations = await self.get_pending_validations()
            if key in pending_validations:
                del pending_validations[key]
                await self.bot.cache.set('temporary', pending_validations, 'pending_validations')
                
            logging.debug(f"[ProfileSetup] Removed pending validation for {member_id} in guild '{guild_name}'")
        except Exception as e:
            logging.error(f"[ProfileSetup] Error removing pending validation: {e}")

    async def validate_guild_name_with_llm(self, guild_name: str, category_channel) -> str:
        """
        Validate guild name with LLM to detect similar existing guilds.
        
        Args:
            guild_name: Guild name to validate
            category_channel: Discord category channel containing diplomat channels
            
        Returns:
            Validated guild name (may be corrected if similar guild found)
        """
        try:
            existing_guild_names = []
            for channel in category_channel.channels:
                if isinstance(channel, discord.TextChannel) and channel.name.startswith("diplomat-"):
                    channel_guild_name = channel.name.replace("diplomat-", "").replace("-", " ").title()
                    existing_guild_names.append(channel_guild_name)
            
            if not existing_guild_names:
                return guild_name
            
            llm_cog = self.bot.get_cog("LLMInteraction")
            if not llm_cog:
                logging.warning("[ProfileSetup] LLMInteraction cog not found for guild name validation")
                return guild_name
            
            if not hasattr(llm_cog, 'safe_ai_query'):
                logging.warning("[ProfileSetup] LLMInteraction cog missing safe_ai_query method")
                return guild_name

            sanitized_guild_name = self._sanitize_llm_input(guild_name)
            sanitized_existing_names = [self._sanitize_llm_input(name) for name in existing_guild_names]

            if len(sanitized_existing_names) > 20:
                sanitized_existing_names = sanitized_existing_names[:20]
                logging.warning(f"[ProfileSetup] Truncated existing guild names list for LLM validation (guild: {category_channel.guild.id})")

            prompt = f"""Task: Compare guild names for similarity detection.\n
            Input guild name: "{sanitized_guild_name}"\n
            Existing guild names: {', '.join(f'"{name}"' for name in sanitized_existing_names)}\n
            Instructions:\n
            1. If the input guild name is very similar to any existing guild name (typos, abbreviations), return the most similar existing guild name.\n
            2. If the input guild name is clearly different and unique, return the input guild name unchanged.\n
            3. Return only the guild name, no additional text or explanations.\n
            Examples:\n
            - Input "Guild War" vs existing "Guild Wars" -> return "Guild Wars"\n
            - Input "MGM" vs existing "MGM Guild" -> return "MGM Guild"\n
            - Input "DarK Knight" vs existing "Dark Knights" -> return "Dark Knights"\n
            Response:"""
            
            try:
                response = await llm_cog.safe_ai_query(prompt)
                if not response:
                    logging.warning("[ProfileSetup] LLM returned empty response, using original guild name")
                    return guild_name

                validated_name = self._validate_llm_response(response, guild_name, existing_guild_names)
                
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
        """Initialize profile setup data on bot ready."""
        
        async def safe_restore_pending_validation_views():
            try:
                await self.restore_pending_validation_views()
            except Exception as e:
                logging.error(f"[ProfileSetup] Error restoring pending validation views: {e}", exc_info=True)
        
        asyncio.create_task(self.bot.cache_loader.wait_for_initial_load())
        asyncio.create_task(safe_restore_pending_validation_views())
        logging.debug("[Profile_Setup] Waiting for initial cache load")

    async def finalize_profile(self, guild_id: int, user_id: int) -> None:
        """
        Finalize user profile setup and assign roles.
        
        Args:
            guild_id: Discord guild ID
            user_id: Discord user ID to finalize profile for
        """
        guild_lang = await self.get_guild_lang(guild_id)
        session = await self.load_session(guild_id, user_id)

        def _values_from_session(s: Dict[str, Any]) -> Tuple[Any, ...]:
            """Internal method: Values from session."""
            return (
                guild_id,
                user_id,
                s.get("nickname"),
                s.get("locale"),
                s.get("motif"),
                s.get("friend_pseudo"),
                s.get("weapons"),
                s.get("guild_name"),
                s.get("guild_acronym"),
                s.get("gs"),
                s.get("playtime"),
                s.get("game_mode"),
                s.get("nickname"),
                s.get("locale"),
                s.get("motif"),
                s.get("friend_pseudo"),
                s.get("weapons"),
                s.get("guild_name"),
                s.get("guild_acronym"),
                s.get("gs"),
                s.get("playtime"),
                s.get("game_mode"),
            )

        query = """
            INSERT INTO user_setup
                (guild_id, user_id, nickname, locale, motif, friend_pseudo, weapons, guild_name, guild_acronym, gs, playtime, game_mode)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                nickname = %s, locale = %s, motif = %s, friend_pseudo = %s, weapons = %s, guild_name = %s, guild_acronym = %s, gs = %s, playtime = %s, game_mode = %s
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

        locale = session.get("locale")

        try:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                logging.error(f"[ProfileSetup] Guild {guild_id} not found.")
                return

            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
            motif = session.get("motif")
            logging.debug(f"[ProfileSetup] Motif for user {user_id}: {motif}")
            role_id = None
            roles_config = await self.get_guild_roles(guild_id)
            if motif == "diplomat":
                role_id = roles_config.get("diplomats")
            elif motif == "friends":
                role_id = roles_config.get("friends")
            elif motif == "application":
                role_id = roles_config.get("applicant")

            config_ok_role_id = roles_config.get("config_ok")
            if config_ok_role_id:
                config_ok_role = guild.get_role(config_ok_role_id)
                if config_ok_role:
                    await member.add_roles(config_ok_role)
            
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
            nickname = session.get("nickname", "")
            new_nickname = nickname
            if motif == "application":
                post_acronym = PROFILE_SETUP_DATA["acronym"].get(
                    session.get("locale", "en-US"),
                    PROFILE_SETUP_DATA["acronym"].get("en-US"),
                )
                new_nickname = f"{post_acronym} {nickname}"
            elif motif in ["diplomat", "allies"]:
                guild_acronym = session.get("guild_acronym", "")
                new_nickname = f"[{guild_acronym}] {nickname}"
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

        channels_data = await self.get_guild_channels(guild_id)
        channels = {
            "member": channels_data.get("forum_members_channel"),
            "application": channels_data.get("forum_recruitment_channel"),
            "diplomat": channels_data.get("forum_diplomats_channel"),
            "allies": channels_data.get("forum_allies_channel"),
            "friends": channels_data.get("forum_friends_channel"),
        }
        channel_id = channels.get(str(motif)) if motif else None
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

            if motif == "member":
                embed_color = discord.Color.blue()
            elif motif == "application":
                embed_color = discord.Color.purple()
            elif motif == "diplomat":
                embed_color = discord.Color.red()
            elif motif == "allies":
                embed_color = discord.Color.green()
            elif motif == "friends":
                embed_color = discord.Color.gold()
            else:
                embed_color = discord.Color.blue()
            
            logging.debug(f"[ProfileSetup] Embed color for motif '{motif}': {embed_color}")
            
            embed = discord.Embed(
                title=PROFILE_SETUP_DATA["notification"]["title"].get(
                    locale, PROFILE_SETUP_DATA["notification"]["title"].get("en-US")
                ),
                color=embed_color,
            )
            embed.add_field(
                name=PROFILE_SETUP_DATA["notification"]["fields"]["user"].get(
                    locale, PROFILE_SETUP_DATA["notification"]["fields"]["user"].get("en-US")
                ),
                value=f"<@{user_id}>",
                inline=False,
            )
            embed.add_field(
                name=PROFILE_SETUP_DATA["notification"]["fields"]["discord_name"].get(
                    locale,
                    PROFILE_SETUP_DATA["notification"]["fields"]["discord_name"].get("en-US"),
                ),
                value=f"`{session.get('nickname', 'Unknown')}`",
                inline=False,
            )
            embed.set_footer(
                text=PROFILE_SETUP_DATA["footer"].get(
                    locale, PROFILE_SETUP_DATA["footer"].get("en-US")
                )
            )

            if motif == "member":
                weapons = session.get("weapons", "N/A")
                gs = session.get("gs", "N/A")
                embed.add_field(
                    name=PROFILE_SETUP_DATA["notification"]["fields"]["weapons"].get(
                        locale,
                        PROFILE_SETUP_DATA["notification"]["fields"]["weapons"].get("en-US"),
                    ),
                    value=f"`{weapons}`",
                    inline=True,
                )
                embed.add_field(
                    name=PROFILE_SETUP_DATA["notification"]["fields"]["gs"].get(
                        locale, PROFILE_SETUP_DATA["notification"]["fields"]["gs"].get("en-US")
                    ),
                    value=f"`{gs}`",
                    inline=True,
                )
            elif motif == "application":
                weapons = session.get("weapons", "N/A")
                gs = session.get("gs", "N/A")
                playtime = session.get("playtime", "N/A")
                game_mode = session.get("game_mode", "N/A")
                embed.add_field(
                    name=PROFILE_SETUP_DATA["notification"]["fields"]["weapons"].get(
                        locale,
                        PROFILE_SETUP_DATA["notification"]["fields"]["weapons"].get("en-US"),
                    ),
                    value=f"`{weapons}`",
                    inline=True,
                )
                embed.add_field(
                    name=PROFILE_SETUP_DATA["notification"]["fields"]["gs"].get(
                        locale, PROFILE_SETUP_DATA["notification"]["fields"]["gs"].get("en-US")
                    ),
                    value=f"`{gs}`",
                    inline=True,
                )
                embed.add_field(
                    name=PROFILE_SETUP_DATA["notification"]["fields"]["playtime"].get(
                        locale,
                        PROFILE_SETUP_DATA["notification"]["fields"]["playtime"].get("en-US"),
                    ),
                    value=f"`{playtime}`",
                    inline=False,
                )
                embed.add_field(
                    name=PROFILE_SETUP_DATA["notification"]["fields"]["game_mode"].get(
                        locale,
                        PROFILE_SETUP_DATA["notification"]["fields"]["game_mode"].get("en-US"),
                    ),
                    value=f"`{game_mode}`",
                    inline=False,
                )
                application_embed = embed.copy()
            elif motif == "diplomat":
                guild_name = session.get("guild_name", "N/A")
                guild_acronym = session.get("guild_acronym", "N/A")
                embed.add_field(
                    name=PROFILE_SETUP_DATA["notification"]["fields"]["guild"].get(
                        locale, PROFILE_SETUP_DATA["notification"]["fields"]["guild"].get("en-US")
                    ),
                    value=f"`{guild_name}` ({guild_acronym})",
                    inline=False,
                )
            elif motif == "allies":
                guild_name = session.get("guild_name", "N/A")
                guild_acronym = session.get("guild_acronym", "N/A")
                embed.add_field(
                    name=PROFILE_SETUP_DATA["notification"]["fields"]["allied_guild"].get(
                        locale,
                        PROFILE_SETUP_DATA["notification"]["fields"]["allied_guild"].get("en-US"),
                    ),
                    value=f"`{guild_name}` ({guild_acronym})",
                    inline=False,
                )
            elif motif == "friends":
                friend_pseudo = session.get("friend_pseudo", "N/A")
                embed.add_field(
                    name=PROFILE_SETUP_DATA["notification"]["fields"]["friend"].get(
                        locale,
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

        welcome_message = await self.get_welcome_message_for_user(guild_id, user_id)
        if welcome_message:
            info = welcome_message
            try:
                channel = await self.bot.fetch_channel(info["channel"])
                message = await channel.fetch_message(info["message"])
                if not message.embeds:
                    logging.error(
                        f"[ProfileSetup] ❌ No embed found in welcome message for {session.get('nickname', 'Unknown')}."
                    )
                    return
                embed = message.embeds[0]
                colors = {
                    "member": discord.Color.blue(),
                    "application": discord.Color.purple(),
                    "diplomat": discord.Color.red(),
                    "allies": discord.Color.green(),
                    "friends": discord.Color.gold(),
                }
                motif_value = session.get("motif")
                embed.color = colors.get(str(motif_value) if motif_value else "", discord.Color.default())
                tz_france = pytz.timezone("Europe/Paris")
                now = datetime.now(pytz.utc).astimezone(tz_france).strftime("%d/%m/%Y à %Hh%M")
                pending_text = PROFILE_SETUP_DATA["pending"].get(
                    guild_lang, PROFILE_SETUP_DATA["pending"].get("en-US")
                )
                if motif == "member":
                    template = PROFILE_SETUP_DATA["accepted_member"].get(
                        guild_lang, PROFILE_SETUP_DATA["accepted_member"].get("en-US")
                    )
                    new_text = template.format(new_nickname=new_nickname, gs=gs, now=now)
                elif motif == "application":
                    template = PROFILE_SETUP_DATA["accepted_application"].get(
                        guild_lang, PROFILE_SETUP_DATA["accepted_application"].get("en-US")
                    )
                    new_text = template.format(new_nickname=new_nickname, gs=gs, now=now)
                elif motif == "diplomat":
                    guild_name = session.get("guild_name", "Unknown")
                    template = PROFILE_SETUP_DATA["accepted_diplomat"].get(
                        guild_lang, PROFILE_SETUP_DATA["accepted_diplomat"].get("en-US")
                    )
                    new_text = template.format(new_nickname=new_nickname, guild_name=guild_name, now=now)
                elif motif == "allies":
                    guild_name = session.get("guild_name", "Unknown")
                    template = PROFILE_SETUP_DATA["accepted_allies"].get(
                        guild_lang, PROFILE_SETUP_DATA["accepted_allies"].get("en-US")
                    )
                    new_text = template.format(new_nickname=new_nickname, guild_name=guild_name, now=now)
                elif motif == "friends":
                    friend_pseudo = session.get("friend_pseudo", "Unknown")
                    template = PROFILE_SETUP_DATA["accepted_friends"].get(
                        guild_lang, PROFILE_SETUP_DATA["accepted_friends"].get("en-US")
                    )
                    new_text = template.format(new_nickname=new_nickname, friend_pseudo=friend_pseudo, now=now)
                embed.description = embed.description.replace(pending_text, new_text)
                await message.edit(embed=embed)
                logging.debug(
                    f"[ProfileSetup] Welcome message updated for {session.get('nickname', 'Unknown')} with motif {motif}."
                )
            except Exception as e:
                logging.error(f"[ProfileSetup] ❌ Error updating welcome message: {e}", exc_info=True)
        else:
            logging.debug(f"[ProfileSetup] No welcome message cached for user {user_id} in guild {guild_id}.")

        if motif == "application":
            channels_data = await self.get_guild_channels(guild_id)
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
                    roles_config = await self.get_guild_roles(guild_id)
                    applicant_role_id = roles_config.get("applicant")
                    if applicant_role_id:
                        applicant_role = guild.get_role(applicant_role_id)
                        if applicant_role:
                            overwrites[applicant_role] = discord.PermissionOverwrite(view_channel=False)
                    overwrites[member] = discord.PermissionOverwrite(
                        view_channel=True, send_messages=True, read_message_history=True
                    )
                    for role_name in ["guild_master", "officer", "guardian"]:
                        role_id = roles_config.get(role_name)
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
                            embed=application_embed,
                            allowed_mentions=discord.AllowedMentions(everyone=True)
                        )
                        logging.info(
                            f"[ProfileSetup] Recruitment channel created: {new_channel.name} (ID: {new_channel.id}) for user {member.id}"
                        )
                    except Exception as e:
                        logging.error(
                            f"[ProfileSetup] Error creating individual channel for {member.display_name}: {e}"
                        )

        elif motif == "diplomat":
            channels_data = await self.get_guild_channels(guild_id)
            diplomats_category_id = channels_data.get("category_diplomat")
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
                        
                        roles_config = await self.get_guild_roles(guild_id)
                        diplomat_role_id = roles_config.get("diplomats")
                        existing_members = [
                            m for m in existing_channel.members 
                            if m != guild.me and any(
                                role.id == diplomat_role_id 
                                for role in m.roles
                            )
                        ]
                        
                        if existing_members:
                            logging.warning(
                                f"[ProfileSetup] Anti-espionage: Channel for '{guild_name}' already has diplomat {existing_members[0].display_name}. "
                                f"New diplomat {member.display_name} needs manual validation."
                            )
                            
                            guild_lang = await self.get_guild_lang(guild_id)
                            alert_text = PROFILE_SETUP_DATA["anti_espionage"]["alert_message"].get(
                                guild_lang, PROFILE_SETUP_DATA["anti_espionage"]["alert_message"].get("en-US")
                            ).format(
                                new_diplomat=member.display_name,
                                guild_name=guild_name,
                                existing_diplomat=existing_members[0].mention
                            )
                            
                            diplomat_embed = embed.copy()
                            
                            view = self.DiplomatValidationView(member, existing_channel, guild_lang, guild_name, self.bot)
                            message = await existing_channel.send(
                                f"@everyone\n\n{alert_text}",
                                embed=diplomat_embed,
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
                            
                            diplomat_embed = embed.copy()
                            await existing_channel.send(
                                embed=diplomat_embed,
                                allowed_mentions=discord.AllowedMentions(everyone=False)
                            )
                            
                            logging.info(
                                f"[ProfileSetup] Diplomat {member.display_name} added to existing channel for guild '{guild_name}'"
                            )
                    else:
                        channel_name = f"diplomat-{normalized_guild_name}"
                        overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
                        
                        diplomat_role_id = roles_config.get("diplomats")
                        if diplomat_role_id:
                            diplomat_role = guild.get_role(diplomat_role_id)
                            if diplomat_role:
                                overwrites[diplomat_role] = discord.PermissionOverwrite(view_channel=False)
                        
                        overwrites[member] = discord.PermissionOverwrite(
                            view_channel=True, send_messages=True, read_message_history=True
                        )
                        
                        for role_name in ["guild_master", "officer", "guardian"]:
                            role_id = roles_config.get(role_name)
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
                            
                            diplomat_embed = embed.copy()
                            await new_channel.send(
                                embed=diplomat_embed,
                                allowed_mentions=discord.AllowedMentions(everyone=False)
                            )
                            
                            logging.info(
                                f"[ProfileSetup] Diplomat channel created: {new_channel.name} (ID: {new_channel.id}) for guild '{guild_name}'"
                            )
                        except Exception as e:
                            logging.error(
                                f"[ProfileSetup] Error creating diplomat channel for guild '{guild_name}': {e}"
                            )

        await self.bot.cache.invalidate_category('user_data')

    class LangButton(discord.ui.Button):
        """Button for language selection."""
        
        def __init__(self, locale: str):
            """
            Initialize language button.
            
            Args:
                locale: Language locale code
            """
            label = LANGUAGE_NAMES.get(locale, locale)
            super().__init__(label=label, style=discord.ButtonStyle.primary, custom_id=f"lang_{locale}")
            self.locale = locale

        async def callback(self, interaction: discord.Interaction):
            """
            Handle language selection.
            
            Args:
                interaction: Discord interaction from button click
            """
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
        """View for language selection."""
        
        def __init__(self, cog: "ProfileSetup", guild_id: int):
            """
            Initialize language selection view.
            
            Args:
                cog: ProfileSetup cog instance
                guild_id: Discord guild ID
            """
            super().__init__(timeout=180)
            self.cog = cog
            self.guild_id = guild_id
            for locale in SUPPORTED_LOCALES:
                self.add_item(ProfileSetup.LangButton(locale))

    class MotifSelect(discord.ui.Select):
        """Select menu for choosing profile motif."""
        
        def __init__(self, locale: str, guild_id: int):
            """
            Initialize motif selection.
            
            Args:
                locale: Language locale code
                guild_id: Discord guild ID
            """
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
            """
            Handle motif selection.
            
            Args:
                interaction: Discord interaction from select menu
            """
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
        """View for motif selection modal."""
        
        def __init__(self, cog: "ProfileSetup", locale: str, guild_id: int):
            """
            Initialize motif modal view.
            
            Args:
                cog: ProfileSetup cog instance
                locale: Language locale code
                guild_id: Discord guild ID
            """
            super().__init__(timeout=180)
            self.cog = cog
            self.locale = locale
            self.guild_id = guild_id
            self.add_item(ProfileSetup.MotifSelect(locale, guild_id))

    class QuestionsSelect(discord.ui.Modal):
        """Modal for collecting profile information based on motif."""
        
        def __init__(self, locale: str, guild_id: int, motif: str):
            """
            Initialize questions modal for profile setup.
            
            Args:
                locale: Language locale code
                guild_id: Discord guild ID
                motif: Profile motif (member, application, diplomat, etc.)
            """
            title = PROFILE_SETUP_DATA["questions_title"].get(locale, PROFILE_SETUP_DATA["questions_title"].get("en-US"))
            super().__init__(title=title)
            self.locale = locale
            self.guild_id = guild_id
            self.motif = motif
            logging.debug(
                f"[ProfileSetup] Initializing QuestionsSelect modal for guild_id={guild_id}, motif={motif}, locale={locale}"
            )

            self.nickname = discord.ui.InputText(
                label=PROFILE_SETUP_DATA["nickname_select"].get(locale, PROFILE_SETUP_DATA["nickname_select"].get("en-US")),
                min_length=3,
                max_length=16,
                required=True,
            )
            self.add_item(self.nickname)

            if motif in ["diplomat", "allies"]:
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

            if motif == "friends":
                self.friend_pseudo = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["friend_pseudo"].get(locale, PROFILE_SETUP_DATA["friend_pseudo"].get("en-US")),
                    min_length=3,
                    max_length=16,
                    required=True,
                )
                self.add_item(self.friend_pseudo)

            if motif in ["application", "member"]:
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

            if motif == "application":
                self.game_mode = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["game_mode_select"].get(locale, PROFILE_SETUP_DATA["game_mode_select"].get("en-US")),
                    required=True,
                    placeholder="PvE / PvP / PvE + PvP",
                )
                self.add_item(self.game_mode)

                self.playtime = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["playtime_select"].get(locale, PROFILE_SETUP_DATA["playtime_select"].get("en-US")),
                    required=True,
                    placeholder="**h / week",
                )
                self.add_item(self.playtime)

        async def callback(self, interaction: discord.Interaction):
            """
            Handle profile information submission.
            
            Args:
                interaction: Discord interaction from modal submission
            """
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
                session["nickname"] = self.nickname.value
                if hasattr(self, "guild_name"):
                    session["guild_name"] = self.guild_name.value
                    session["guild_acronym"] = self.guild_acronym.value
                if hasattr(self, "friend_pseudo"):
                    session["friend_pseudo"] = self.friend_pseudo.value
                if hasattr(self, "weapons"):
                    weapons_input = self.weapons.value
                    llm_cog = interaction.client.get_cog("LLMInteraction")
                    try:
                        if llm_cog:
                            weapons_clean = await llm_cog.normalize_weapons(weapons_input)
                            if not weapons_clean:
                                weapons_clean = weapons_input
                        else:
                            weapons_clean = weapons_input
                    except Exception as e:
                        logging.warning(f"[ProfileSetup] LLM weapons normalization failed: {e}")
                        weapons_clean = weapons_input
                    session["weapons"] = weapons_clean[:32]
                    session["gs"] = self.gs.value
                if hasattr(self, "game_mode"):
                    raw_playtime = self.playtime.value.strip()
                    session["game_mode"] = self.game_mode.value
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
        """Button to open profile questions modal."""
        
        def __init__(self, cog: "ProfileSetup", locale: str, guild_id: int, motif: str):
            """
            Initialize questions select button.
            
            Args:
                cog: ProfileSetup cog instance
                locale: Language locale code
                guild_id: Discord guild ID
                motif: Profile motif type
            """
            label = PROFILE_SETUP_DATA["comp_profile"].get(locale, PROFILE_SETUP_DATA["comp_profile"].get("en-US"))
            super().__init__(label=label, style=discord.ButtonStyle.primary, custom_id="questions_select_button")
            self.cog = cog
            self.locale = locale
            self.guild_id = guild_id
            self.motif = motif

        async def callback(self, interaction: discord.Interaction):
            """
            Handle button click to show profile modal.
            
            Args:
                interaction: Discord interaction from button click
            """
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
        """View containing the profile questions button."""
        
        def __init__(self, cog: "ProfileSetup", locale: str, guild_id: int, motif: str):
            """
            Initialize questions select view.
            
            Args:
                cog: ProfileSetup cog instance
                locale: Language locale code
                guild_id: Discord guild ID
                motif: Profile motif type
            """
            super().__init__(timeout=180)
            self.cog = cog
            self.locale = locale
            self.guild_id = guild_id
            self.motif = motif
            logging.debug(f"[ProfileSetup] Initializing QuestionsSelectView for guild_id={guild_id}, locale={locale}, motif={motif}")
            self.add_item(ProfileSetup.QuestionsSelectButton(cog, locale, guild_id, motif))

    class DiplomatValidationButton(discord.ui.Button):
        """Button for validating diplomat access to channels."""
        
        def __init__(self, member: discord.Member, channel: discord.TextChannel, guild_lang: str, guild_name: str = "Unknown"):
            """
            Initialize diplomat validation button.
            
            Args:
                member: Discord member requiring validation
                channel: Discord text channel for validation
                guild_lang: Guild language code
                guild_name: Name of the guild being validated for
            """
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
            """
            Handle diplomat validation button callback.
            
            Args:
                interaction: Discord interaction from button press
            """
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
                
                validated_by_template = PROFILE_SETUP_DATA["anti_espionage"]["validated_by"].get(
                    self.guild_lang, PROFILE_SETUP_DATA["anti_espionage"]["validated_by"].get("en-US")
                )
                validation_by_text = f"\n👤 {validated_by_template.format(user=interaction.user.mention)}"
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
        """View for diplomat validation buttons."""
        
        def __init__(self, member: discord.Member, channel: discord.TextChannel, guild_lang: str, guild_name: str = "Unknown", bot=None):
            """
            Initialize diplomat validation view.
            
            Args:
                member: Discord member to validate
                channel: Text channel for validation
                guild_lang: Guild language for translations
                guild_name: Name of the guild (default: Unknown)
                bot: Discord bot instance (optional)
            """
            super().__init__(timeout=86400)
            self.member = member
            self.channel = channel
            self.guild_lang = guild_lang
            self.guild_name = guild_name
            self.original_message = None
            self.bot = bot
            self.add_item(ProfileSetup.DiplomatValidationButton(member, channel, guild_lang, guild_name))
        
        async def on_timeout(self):
            """
            Handle view timeout after 24 hours.
            
            Disables all buttons and updates database to mark validation as expired.
            """
            for item in self.children:
                item.disabled = True
            
            message_text = PROFILE_SETUP_DATA["anti_espionage"]["validation_timeout"].get(
                self.guild_lang, PROFILE_SETUP_DATA["anti_espionage"]["validation_timeout"].get("en-US")
            )
            
            try:
                if self.bot:
                    cog = self.bot.get_cog("ProfileSetup")
                    if cog:
                        query = """
                            UPDATE pending_diplomat_validations 
                            SET status = 'expired', completed_at = NOW()
                            WHERE guild_id = %s AND member_id = %s AND guild_name = %s AND status = 'pending'
                        """
                        await self.bot.run_db_query(query, (self.member.guild.id, self.member.id, self.guild_name), commit=True)
                        
                        pending_validations = await cog.get_pending_validations()
                        key = f"{self.member.guild.id}_{self.member.id}_{self.guild_name}"
                        if key in pending_validations:
                            del pending_validations[key]
                            await self.bot.cache.set('temporary', pending_validations, 'pending_validations')
                
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
    """
    Setup function to add the ProfileSetup cog to the bot.
    
    Args:
        bot: Discord bot instance
    """
    bot.add_cog(ProfileSetup(bot))

