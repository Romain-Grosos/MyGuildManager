"""
Guild Members Cog - Manages guild member profiles, roster updates, and member data.
"""

import asyncio
import logging
import re
import time
from datetime import datetime
from typing import Dict, List, Tuple, Any, Optional, Union
from urllib.parse import urlparse

import discord
from discord.ext import commands, tasks

from ..core.functions import get_user_message
from ..core.performance_profiler import profile_performance
from ..core.rate_limiter import admin_rate_limit
from ..core.translation import translations as global_translations
from ..db import run_db_transaction

GUILD_MEMBERS = global_translations.get("guild_members", {})
CONFIG_ROSTER_DATA = global_translations.get("commands", {}).get("config_roster", {})

class GuildMembers(commands.Cog):
    """Cog for managing guild member profiles, roster updates, and member data."""
    
    def __init__(self, bot: discord.Bot) -> None:
        """
        Initialize the GuildMembers cog.
        
        Args:
            bot: The Discord bot instance
            
        Returns:
            None
        """
        self.bot = bot
        
        self.allowed_build_domains = ['questlog.gg', 'maxroll.gg']
        self.max_username_length = 32
        self.max_gs_value = 9999
        self.min_gs_value = 500
    
    def _sanitize_string(self, text: str, max_length: int = 100) -> str:
        """
        Sanitize string input by removing dangerous characters.
        
        Args:
            text: The input string to sanitize
            max_length: Maximum length of the sanitized string (default: 100)
            
        Returns:
            Sanitized string with dangerous characters removed and length limited
        """
        if not isinstance(text, str):
            return ""
        sanitized = re.sub(r'[<>"\';\\\x00-\x1f\x7f]', '', text.strip())
        return sanitized[:max_length]
    
    def _validate_url(self, url: str) -> bool:
        """
        Validate build URL against allowed domains.
        
        Args:
            url: The URL string to validate
            
        Returns:
            True if URL is valid and from allowed domain, False otherwise
        """
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
    
    def _validate_integer(self, value: Any, min_val: Optional[int] = None, max_val: Optional[int] = None) -> Optional[int]:
        """
        Validate and convert value to integer within bounds.
        
        Args:
            value: The value to convert to integer
            min_val: Minimum allowed value (optional)
            max_val: Maximum allowed value (optional)
            
        Returns:
            Validated integer value or None if validation fails
        """
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
        """
        Validate and normalize weapon code.
        
        Args:
            weapon: The weapon code string to validate
            
        Returns:
            Normalized weapon code string or None if validation fails
        """
        if not isinstance(weapon, str):
            return None
        
        sanitized = self._sanitize_string(weapon.strip().upper(), 10)
        if not re.match(r'^[A-Z0-9_]{1,10}$', sanitized):
            return None
        return sanitized

    async def load_guild_members_data(self) -> None:
        """
        Ensure all required data is loaded via centralized cache loader.
        
        Args:
            None
            
        Returns:
            None
        """
        logging.debug("[GuildMembers] Loading guild members data")
        
        await self.bot.cache_loader.ensure_category_loaded('guild_settings')
        await self.bot.cache_loader.ensure_category_loaded('guild_channels')
        await self.bot.cache_loader.ensure_category_loaded('guild_roles')
        await self._load_weapons_data()
        await self._load_members_data()
        
        logging.debug("[GuildMembers] Guild members data loading completed")

    async def _load_weapons_data(self) -> None:
        """
        Load weapons and combinations data using centralized cache loaders.
        
        Args:
            None
            
        Returns:
            None
        """
        logging.debug("[GuildMembers] Loading weapons data via cache loaders")
        
        await self.bot.cache_loader.ensure_weapons_loaded()
        await self.bot.cache_loader.ensure_weapons_combinations_loaded()
        
        logging.debug("[GuildMembers] Weapons and combinations data loaded via cache loaders")

    async def _load_user_setup_members(self) -> None:
        """
        Load user setup members with specific motif filter.
        
        Args:
            None
            
        Returns:
            None
            
        Raises:
            Exception: When database query fails
        """
        user_setup_query = """
            SELECT guild_id, user_id, username, locale, gs, weapons
            FROM user_setup
            WHERE motif IN ('member', 'application')
        """
        try:
            rows = await self.bot.run_db_query(user_setup_query, fetch_all=True)
            user_setup_members = {}
            for row in rows:
                guild_id, user_id, username, locale, gs, weapons = row
                key = (int(guild_id), int(user_id))
                user_setup_members[key] = {
                    "username": username,
                    "locale": locale,
                    "gs": gs,
                    "weapons": weapons
                }
            await self.bot.cache.set('user_data', user_setup_members, 'user_setup_members')
            logging.debug(f"[GuildMembers] User setup members loaded: {len(user_setup_members)} entries")
        except Exception as e:
            logging.error(f"[GuildMembers] Error loading user setup members: {e}", exc_info=True)

    async def _load_members_data(self) -> None:
        """
        Load member-specific data into cache (legacy method for compatibility).
        
        Args:
            None
            
        Returns:
            None
        """
        await self._load_user_setup_members()
        await self.bot.cache_loader.ensure_guild_members_loaded()
        await self.bot.cache_loader.ensure_guild_ideal_staff_loaded()
        logging.debug("[GuildMembers] Guild members and ideal staff data loaded via cache loaders")

    async def get_weapons_combinations(self, game_id: int) -> List[Dict[str, str]]:
        """
        Get weapon combinations for a specific game from cache.
        
        Args:
            game_id: The ID of the game to get weapon combinations for
            
        Returns:
            List of weapon combination dictionaries for the specified game
        """
        combinations = await self.bot.cache.get('static_data', 'weapons_combinations')
        return combinations.get(game_id, []) if combinations else []

    async def get_guild_members(self) -> Dict[Tuple[int, int], Dict[str, Any]]:
        """
        Get all guild members from cache.
        
        Args:
            None
            
        Returns:
            Dictionary mapping (guild_id, member_id) tuples to member data dictionaries
        """
        guild_members = await self.bot.cache.get('roster_data', 'guild_members')
        if guild_members is None:
            logging.warning("[GuildMembers] guild_members cache returned None, ensuring cache is loaded...")
            try:
                await self.bot.cache_loader.ensure_guild_members_loaded()
                guild_members = await self.bot.cache.get('roster_data', 'guild_members')
                logging.debug(f"[GuildMembers] After cache reload: {type(guild_members)} - {guild_members is None}")
            except Exception as e:
                logging.error(f"[GuildMembers] Error reloading guild members cache: {e}")
        return guild_members or {}

    async def get_user_setup_members(self) -> Dict[Tuple[int, int], Dict[str, Any]]:
        """
        Get user setup members from cache.
        
        Args:
            None
            
        Returns:
            Dictionary mapping (guild_id, user_id) tuples to user setup data dictionaries
        """
        user_setup = await self.bot.cache.get('user_data', 'user_setup_members')
        return user_setup or {}

    async def get_ideal_staff(self, guild_id: int) -> Dict[str, int]:
        """
        Get ideal staff configuration for a guild from cache.
        
        Args:
            guild_id: The ID of the guild to get ideal staff configuration for
            
        Returns:
            Dictionary mapping class names to ideal count numbers
        """
        ideal_staff = await self.bot.cache.get('guild_data', 'ideal_staff')
        return ideal_staff.get(guild_id, {}) if ideal_staff else {}

    async def update_guild_member_cache(self, guild_id: int, member_id: int, field: str, value: Any) -> None:
        """
        Update a specific field for a guild member in cache.
        
        Args:
            guild_id: The ID of the guild
            member_id: The ID of the member
            field: The field name to update
            value: The new value for the field
            
        Returns:
            None
        """
        guild_members = await self.get_guild_members()
        key = (guild_id, member_id)
        if key in guild_members:
            guild_members[key][field] = value
            await self.bot.cache.set('roster_data', guild_members, 'guild_members')

    async def determine_class(self, weapons_list: list, guild_id: int) -> str:
        """
        Determine class based on weapon combination.
        
        Args:
            weapons_list: List of weapon codes
            guild_id: The ID of the guild to check weapon combinations for
            
        Returns:
            The determined class name or "NULL" if no match found
        """
        if not isinstance(weapons_list, list) or not weapons_list:
            return "NULL"
        
        await self.bot.cache_loader.ensure_category_loaded('guild_settings')
        game = await self.bot.cache.get_guild_data(guild_id, 'guild_game')
        if not game:
            return "NULL"
        
        game_id = self._validate_integer(game)
        if game_id is None:
            return "NULL"
        
        combinations = await self.get_weapons_combinations(game_id)
        sorted_weapons = sorted(weapons_list)
        for combo in combinations:
            if sorted([combo["weapon1"], combo["weapon2"]]) == sorted_weapons:
                return combo["role"]
        return "NULL"

    async def get_valid_weapons(self, guild_id: int) -> set:
        """
        Get valid weapons for a guild based on its game configuration.
        
        Args:
            guild_id: The ID of the guild
            
        Returns:
            Set of valid weapon codes for the guild's game
        """
        valid = set()
        if not isinstance(guild_id, int):
            return valid
            
        await self.bot.cache_loader.ensure_category_loaded('guild_settings')
        game = await self.bot.cache.get_guild_data(guild_id, 'guild_game')
        if not game:
            return valid
        
        game_id = self._validate_integer(game)
        if game_id is None:
            return valid
        
        combinations = await self.get_weapons_combinations(game_id)
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
        """
        Update member's gear score (GS) value.
        
        Args:
            ctx: Discord application context
            value: New GS value to set
            
        Returns:
            None
        """
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
        
        guild_members = await self.get_guild_members()
        logging.debug(f"[GuildMembers - GS] Guild members cache contains {len(guild_members)} entries")
        if key not in guild_members:
            logging.debug(f"[GuildMembers - GS] Profile not found in guild_members cache for key {key}, trying database fallback...")
            try:
                await self._load_user_setup_members()

                user_setup_members = await self.get_user_setup_members()
                logging.debug(f"[GuildMembers - GS] User setup cache contains {len(user_setup_members)} entries")
                if key in user_setup_members:
                    logging.info(f"[GuildMembers - GS] User found in user_setup, creating guild_members entry for {key}")
                    user_setup_data = user_setup_members[key]
                    guild_member_data = {
                        "username": user_setup_data.get("username", ctx.author.display_name),
                        "language": user_setup_data.get("locale", "en-US"),
                        "GS": user_setup_data.get("gs", 0),
                        "build": "",
                        "weapons": user_setup_data.get("weapons", ""),
                        "DKP": 0,
                        "nb_events": 0,
                        "registrations": 0,
                        "attendances": 0,
                        "class": "NULL"
                    }
                    current_cache = await self.bot.cache.get('roster_data', 'guild_members') or {}
                    current_cache[key] = guild_member_data
                    await self.bot.cache.set('roster_data', current_cache, 'guild_members')
                    guild_members[key] = guild_member_data
                    logging.info(f"[GuildMembers - GS] Created guild_members cache entry for {key}")
                else:
                    logging.debug(f"[GuildMembers - GS] Profile not found anywhere for key {key}")
                    msg = get_user_message(ctx, GUILD_MEMBERS["gs"], "not_registered")
                    await ctx.followup.send(msg, ephemeral=True)
                    return
            except Exception as e:
                logging.error(f"[GuildMembers - GS] Error in fallback logic: {e}")
                msg = get_user_message(ctx, GUILD_MEMBERS["gs"], "not_registered")
                await ctx.followup.send(msg, ephemeral=True)
                return

        try: 
            query = "UPDATE guild_members SET GS = %s WHERE guild_id = %s AND member_id = %s"
            await self.bot.run_db_query(query, (validated_value, guild_id, member_id), commit=True)
            await self.update_guild_member_cache(guild_id, member_id, "GS", validated_value)
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
        """
        Update member's weapon combination and determine class.
        
        Args:
            ctx: Discord application context
            weapon1: First weapon code
            weapon2: Second weapon code
            
        Returns:
            None
        """
        await ctx.defer(ephemeral=True)
        
        if not ctx.guild or not ctx.author:
            logging.error("[GuildMembers - Weapons] Invalid context: missing guild or author")
            await ctx.followup.send("❌ Invalid request context", ephemeral=True)
            return
        
        guild_id = ctx.guild.id
        member_id = ctx.author.id
        key = (guild_id, member_id)
        
        guild_members = await self.get_guild_members()
        logging.debug(f"[GuildMembers - Weapons] Guild members cache contains {len(guild_members)} entries")
        if key not in guild_members:
            logging.debug(f"[GuildMembers - Weapons] Profile not found in guild_members cache for key {key}, trying database fallback...")
            try:
                await self._load_user_setup_members()

                user_setup_members = await self.get_user_setup_members()
                logging.debug(f"[GuildMembers - Weapons] User setup cache contains {len(user_setup_members)} entries")
                if key in user_setup_members:
                    logging.info(f"[GuildMembers - Weapons] User found in user_setup, creating guild_members entry for {key}")
                    user_setup_data = user_setup_members[key]
                    guild_member_data = {
                        "username": user_setup_data.get("username", ctx.author.display_name),
                        "language": user_setup_data.get("locale", "en-US"),
                        "GS": user_setup_data.get("gs", 0),
                        "build": "",
                        "weapons": user_setup_data.get("weapons", ""),
                        "DKP": 0,
                        "nb_events": 0,
                        "registrations": 0,
                        "attendances": 0,
                        "class": "NULL"
                    }
                    current_cache = await self.bot.cache.get('roster_data', 'guild_members') or {}
                    current_cache[key] = guild_member_data
                    await self.bot.cache.set('roster_data', current_cache, 'guild_members')
                    guild_members[key] = guild_member_data
                    logging.info(f"[GuildMembers - Weapons] Created guild_members cache entry for {key}")
                else:
                    logging.debug(f"[GuildMembers - Weapons] Profile not found anywhere for key {key}")
                    msg = get_user_message(ctx, GUILD_MEMBERS["weapons"], "not_registered")
                    await ctx.followup.send(msg, ephemeral=True)
                    return
            except Exception as e:
                logging.error(f"[GuildMembers - Weapons] Error in fallback logic: {e}")
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

        valid_weapons = await self.get_valid_weapons(guild_id)
        if weapon1_code not in valid_weapons or weapon2_code not in valid_weapons:
            msg = get_user_message(ctx, GUILD_MEMBERS["weapons"], "not_valid")
            await ctx.followup.send(msg, ephemeral=True)
            return

        try:
            weapons_normalized = sorted([weapon1_code, weapon2_code])
            player_class = await self.determine_class(weapons_normalized, guild_id)
            weapons_str = "/".join(weapons_normalized)
            
            query = "UPDATE guild_members SET weapons = %s, `class` = %s WHERE guild_id = %s AND member_id = %s"
            await self.bot.run_db_query(query, (weapons_str, player_class, guild_id, member_id), commit=True)
            
            await self.update_guild_member_cache(guild_id, member_id, "weapons", weapons_str)
            await self.update_guild_member_cache(guild_id, member_id, "class", player_class)

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
        """
        Update member's build URL.
        
        Args:
            ctx: Discord application context
            url: Build URL to set
            
        Returns:
            None
        """
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
        
        guild_members = await self.get_guild_members()
        if key not in guild_members:
            logging.debug(f"[GuildMembers - Build] Profile not found in guild_members cache for key {key}, trying database fallback...")
            try:
                user_setup_members = await self.get_user_setup_members()
                if key in user_setup_members:
                    logging.info(f"[GuildMembers - Build] User found in user_setup, creating guild_members entry for {key}")
                    user_setup_data = user_setup_members[key]
                    guild_member_data = {
                        "username": user_setup_data.get("username", ctx.author.display_name),
                        "language": user_setup_data.get("locale", "en-US"),
                        "GS": user_setup_data.get("gs", 0),
                        "build": "",
                        "weapons": user_setup_data.get("weapons", ""),
                        "DKP": 0,
                        "nb_events": 0,
                        "registrations": 0,
                        "attendances": 0,
                        "class": "NULL"
                    }
                    current_cache = await self.bot.cache.get('roster_data', 'guild_members') or {}
                    current_cache[key] = guild_member_data
                    await self.bot.cache.set('roster_data', current_cache, 'guild_members')
                    guild_members[key] = guild_member_data
                    logging.info(f"[GuildMembers - Build] Created guild_members cache entry for {key}")
                else:
                    logging.debug(f"[GuildMembers - Build] Profile not found anywhere for key {key}")
                    msg = get_user_message(ctx, GUILD_MEMBERS["build"], "not_registered")
                    await ctx.followup.send(msg, ephemeral=True)
                    return
            except Exception as e:
                logging.error(f"[GuildMembers - Build] Error in fallback logic: {e}")
                msg = get_user_message(ctx, GUILD_MEMBERS["build"], "not_registered")
                await ctx.followup.send(msg, ephemeral=True)
                return

        try:
            sanitized_url = self._sanitize_string(url.strip(), 500)
            query = "UPDATE guild_members SET build = %s WHERE guild_id = %s AND member_id = %s"
            await self.bot.run_db_query(query, (sanitized_url, guild_id, member_id), commit=True)
            await self.update_guild_member_cache(guild_id, member_id, "build", sanitized_url)
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
        """
        Update member's username and Discord nickname.
        
        Args:
            ctx: Discord application context
            new_name: New username to set
            
        Returns:
            None
        """
        await ctx.defer(ephemeral=True)
        
        if not ctx.guild or not ctx.author:
            logging.error("[GuildMembers - Username] Invalid context: missing guild or author")
            await ctx.followup.send("❌ Invalid request context", ephemeral=True)
            return
        
        guild_id = ctx.guild.id
        member_id = ctx.author.id
        key = (guild_id, member_id)
        
        guild_members = await self.get_guild_members()
        if key not in guild_members:
            logging.debug(f"[GuildMembers - Username] Profile not found in guild_members cache for key {key}, trying database fallback...")
            try:
                user_setup_members = await self.get_user_setup_members()
                if key in user_setup_members:
                    logging.info(f"[GuildMembers - Username] User found in user_setup, creating guild_members entry for {key}")
                    user_setup_data = user_setup_members[key]
                    guild_member_data = {
                        "username": user_setup_data.get("username", ctx.author.display_name),
                        "language": user_setup_data.get("locale", "en-US"),
                        "GS": user_setup_data.get("gs", 0),
                        "build": "",
                        "weapons": user_setup_data.get("weapons", ""),
                        "DKP": 0,
                        "nb_events": 0,
                        "registrations": 0,
                        "attendances": 0,
                        "class": "NULL"
                    }
                    current_cache = await self.bot.cache.get('roster_data', 'guild_members') or {}
                    current_cache[key] = guild_member_data
                    await self.bot.cache.set('roster_data', current_cache, 'guild_members')
                    guild_members[key] = guild_member_data
                    logging.info(f"[GuildMembers - Username] Created guild_members cache entry for {key}")
                else:
                    logging.debug(f"[GuildMembers - Username] Profile not found anywhere for key {key}")
                    msg = get_user_message(ctx, GUILD_MEMBERS["username"], "not_registered")
                    await ctx.followup.send(msg, ephemeral=True)
                    return
            except Exception as e:
                logging.error(f"[GuildMembers - Username] Error in fallback logic: {e}")
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
            await self.update_guild_member_cache(guild_id, member_id, "username", new_username)
            
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
        """
        Optimized roster update command - reduces DB queries by 90%.
        
        Args:
            ctx: Discord application context
            
        Returns:
            None
        """
        start_time = time.time()
        
        await ctx.defer(ephemeral=True)
        guild_id = ctx.guild.id
        
        await self.bot.cache_loader.ensure_category_loaded('guild_roles')
        await self.bot.cache_loader.ensure_category_loaded('guild_settings')
        await self.bot.cache_loader.reload_category('guild_channels')
        
        roles_config = await self.bot.cache.get_guild_data(guild_id, 'roles')
        locale = await self.bot.cache.get_guild_data(guild_id, 'guild_lang') or "en-US"
        
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
            if not m.bot and (members_role_id in [role.id for role in m.roles] or 
                             (absent_role_id and absent_role_id in [role.id for role in m.roles]))
        }

        try:
            guild_members_db = await self._get_guild_members_bulk(guild_id)
            user_setup_db = await self._get_user_setup_bulk(guild_id)
        except Exception as e:
            logging.error(f"[GuildMembers] Error loading member data for guild {guild_id}: {e}", exc_info=True)
            msg = get_user_message(ctx, GUILD_MEMBERS["maj_roster"], "database_error")
            if not msg:
                msg = "Database error occurred. Please try again later."
            await ctx.followup.send(msg, ephemeral=True)
            return

        to_delete, to_update, to_insert = await self._calculate_roster_changes(
            guild_id, actual_members, guild_members_db, user_setup_db, locale
        )

        deleted, updated, inserted = await self._apply_roster_changes_bulk(
            guild_id, to_delete, to_update, to_insert
        )

        await self._load_user_setup_members()
        await self.bot.cache_loader.reload_category('guild_members')

        try:
            await asyncio.gather(
                self.update_recruitment_message(ctx),
                self.update_members_message(ctx),
                return_exceptions=True
            )
        except Exception as e:
            logging.warning(f"[GuildMembers] Message update failed: {e}")

        execution_time = (time.time() - start_time) * 1000
        msg = f"✅ Roster updated in {execution_time:.0f}ms - {deleted} deleted, {updated} modified, {inserted} added"
        await ctx.followup.send(msg, ephemeral=True)
        
        logging.info(f"[GuildMembers] Optimized maj_roster completed in {execution_time:.0f}ms: -{deleted} +{inserted} ~{updated}")

    @profile_performance(threshold_ms=50.0)
    async def _get_guild_members_bulk(self, guild_id: int) -> dict:
        """
        Retrieves all guild members with performance optimization.
        
        Args:
            guild_id: The ID of the guild to retrieve members for
            
        Returns:
            Dictionary mapping member IDs to member data dictionaries
        """
        if hasattr(self.bot, 'cache') and hasattr(self.bot.cache, 'get_bulk_guild_members'):
            return await self.bot.cache.get_bulk_guild_members(guild_id)

        query = """
        SELECT member_id, username, language, GS, build, weapons, DKP, 
               nb_events, registrations, attendances, `class`
        FROM guild_members 
        WHERE guild_id = %s
        """
        
        rows = await self.bot.run_db_query(query, (guild_id,), fetch_all=True)
        members_db = {}
        
        if rows:
            for row in rows:
                member_id, username, language, gs, build, weapons, dkp, nb_events, registrations, attendances, class_type = row
                members_db[member_id] = {
                    'username': username,
                    'language': language,
                    'GS': gs,
                    'build': build,
                    'weapons': weapons,
                    'DKP': dkp,
                    'nb_events': nb_events,
                    'registrations': registrations,
                    'attendances': attendances,
                    'class': class_type
                }
        
        return members_db

    async def _get_user_setup_bulk(self, guild_id: int) -> dict:
        """
        Retrieves consolidated member data from guild_members, with fallback to user_setup for missing members.
        
        Args:
            guild_id: The ID of the guild to retrieve setup data for
            
        Returns:
            Dictionary mapping member IDs to consolidated setup data dictionaries
        """
        query = """
        SELECT COALESCE(gm.member_id, us.user_id) as member_id,
               COALESCE(us.locale, gm.language) as locale,
               COALESCE(gm.GS, us.gs) as gs,
               COALESCE(gm.weapons, us.weapons) as weapons,
               gm.build,
               gm.class
        FROM user_setup us
        LEFT JOIN guild_members gm ON us.guild_id = gm.guild_id AND us.user_id = gm.member_id
        WHERE us.guild_id = %s
        
        UNION
        
        SELECT gm.member_id,
               gm.language as locale,
               gm.GS as gs,
               gm.weapons,
               gm.build,
               gm.class
        FROM guild_members gm
        WHERE gm.guild_id = %s 
        AND gm.member_id NOT IN (SELECT user_id FROM user_setup WHERE guild_id = %s)
        """
        
        rows = await self.bot.run_db_query(query, (guild_id, guild_id, guild_id), fetch_all=True)
        setup_db = {}
        
        if rows:
            for row in rows:
                member_id, locale, gs, weapons, build, class_type = row
                setup_db[member_id] = {
                    'locale': locale,
                    'gs': gs,
                    'weapons': weapons,
                    'build': build,
                    'class': class_type
                }
        
        return setup_db

    async def _calculate_roster_changes(self, guild_id: int, actual_members: dict, 
                                       guild_members_db: dict, user_setup_db: dict, locale: str):
        """
        Calculates all necessary changes without DB queries.
        
        Args:
            guild_id: The ID of the guild
            actual_members: Dictionary of current Discord members
            guild_members_db: Dictionary of members from database
            user_setup_db: Dictionary of user setup data from database
            locale: Guild's locale for language defaults
            
        Returns:
            Tuple of (to_delete, to_update, to_insert) lists
        """
        to_delete = []
        to_update = []
        to_insert = []

        for member_id in guild_members_db.keys():
            if member_id not in actual_members:
                to_delete.append(member_id)

        for member_id, discord_member in actual_members.items():
            if member_id in guild_members_db:
                db_member = guild_members_db[member_id]
                if db_member.get('username') != discord_member.display_name:
                    to_update.append((member_id, 'username', discord_member.display_name))
            else:
                user_setup = user_setup_db.get(member_id, {})
                
                weapons_normalized, computed_class = await self._process_weapons_optimized(
                    user_setup.get('weapons'), guild_id
                )
                
                language = user_setup.get('locale', locale)
                if language and '-' in language:
                    language = language.split('-')[0]
                
                gs_value = user_setup.get('gs') or 0
                if gs_value in (None, "", "NULL"):
                    gs_value = 0

                member_data = {
                    'member_id': member_id,
                    'username': discord_member.display_name,
                    'language': language,
                    'GS': gs_value,
                    'build': user_setup.get('build', ''),
                    'weapons': weapons_normalized,
                    'DKP': 0,
                    'nb_events': 0,
                    'registrations': 0,
                    'attendances': 0,
                    'class': computed_class
                }
                to_insert.append(member_data)

        return to_delete, to_update, to_insert

    async def _process_weapons_optimized(self, weapons_raw: str, guild_id: int):
        """
        Optimized weapon processing with validation.
        
        Args:
            weapons_raw: Raw weapon string from database
            guild_id: The ID of the guild for weapon validation
            
        Returns:
            Tuple of (normalized_weapons_string, computed_class)
        """
        if not weapons_raw or not isinstance(weapons_raw, str):
            return "NULL", "NULL"
        
        weapons_raw = weapons_raw.strip()
        if not weapons_raw:
            return "NULL", "NULL"
        
        if "/" not in weapons_raw:
            if "," in weapons_raw:
                weapons_raw = weapons_raw.replace(",", "/")
            else:
                return "NULL", "NULL"
        
        weapons_list = [w.strip().upper() for w in weapons_raw.split("/") if w.strip()]
        
        if len(weapons_list) != 2:
            return "NULL", "NULL"
        
        valid_weapons = await self.get_valid_weapons(guild_id)
        if weapons_list[0] not in valid_weapons or weapons_list[1] not in valid_weapons:
            return "NULL", "NULL"
        
        weapons_normalized = "/".join(sorted(weapons_list))
        computed_class = await self.determine_class(sorted(weapons_list), guild_id)
        
        return weapons_normalized, computed_class

    @profile_performance(threshold_ms=100.0)
    async def _apply_roster_changes_bulk(self, guild_id: int, to_delete: list, to_update: list, to_insert: list):
        """
        Applies all changes using a secure transaction with automatic rollback.
        
        Args:
            guild_id: The ID of the guild
            to_delete: List of member IDs to delete
            to_update: List of update tuples (member_id, field, value)
            to_insert: List of member data dictionaries to insert
            
        Returns:
            Tuple of (deleted_count, updated_count, inserted_count)
            
        Raises:
            ValueError: When invalid data is provided
            Exception: When database transaction fails
        """
        deleted_count = 0
        updated_count = 0
        inserted_count = 0

        transaction_queries = []
        
        try:
            total_operations = len(to_delete) + len(to_update) + len(to_insert)
            if total_operations > 1000:
                logging.warning(f"[GuildMembers] Large batch operation detected: {total_operations} operations for guild {guild_id}")

            if to_delete:
                if not all(isinstance(mid, int) and mid > 0 for mid in to_delete):
                    raise ValueError("Invalid member ID format in deletion list")
                    
                if len(to_delete) == 1:
                    delete_query = "DELETE FROM guild_members WHERE guild_id = %s AND member_id = %s"
                    transaction_queries.append((delete_query, (guild_id, to_delete[0])))
                else:
                    placeholders = ','.join(['%s'] * len(to_delete))
                    delete_query = f"DELETE FROM guild_members WHERE guild_id = %s AND member_id IN ({placeholders})"
                    params = [guild_id] + to_delete
                    transaction_queries.append((delete_query, tuple(params)))
                deleted_count = len(to_delete)

            if to_update:
                for member_id, field, value in to_update:
                    allowed_fields = {'username', 'language', 'GS', 'build', 'weapons', 'DKP', 'nb_events', 'registrations', 'attendances', 'class'}
                    if field not in allowed_fields:
                        raise ValueError(f"Invalid field name for update: {field}")

                    if not isinstance(member_id, int) or member_id <= 0:
                        raise ValueError(f"Invalid member ID format in update: {member_id}")
                        
                    update_query = f"UPDATE guild_members SET {field} = %s WHERE guild_id = %s AND member_id = %s"
                    transaction_queries.append((update_query, (value, guild_id, member_id)))
                updated_count = len(to_update)

            if to_insert:
                insert_query = """
                    INSERT INTO guild_members 
                    (guild_id, member_id, username, language, GS, build, weapons, DKP, nb_events, registrations, attendances, `class`)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                    username = VALUES(username),
                    language = VALUES(language),
                    GS = VALUES(GS),
                    build = VALUES(build),
                    weapons = VALUES(weapons),
                    DKP = VALUES(DKP),
                    nb_events = VALUES(nb_events),
                    registrations = VALUES(registrations),
                    attendances = VALUES(attendances),
                    `class` = VALUES(`class`)
                """
                for member_data in to_insert:
                    required_fields = ['member_id', 'username', 'language', 'GS', 'build', 'weapons', 'DKP', 'nb_events', 'registrations', 'attendances', 'class']
                    if not all(field in member_data for field in required_fields):
                        raise ValueError("Missing required fields in member data")

                    if not isinstance(member_data['member_id'], int) or member_data['member_id'] <= 0:
                        raise ValueError(f"Invalid member ID format in insert: {member_data['member_id']}")
                        
                    params = (
                        guild_id,
                        member_data['member_id'],
                        member_data['username'],
                        member_data['language'],
                        member_data['GS'],
                        member_data['build'],
                        member_data['weapons'],
                        member_data['DKP'],
                        member_data['nb_events'],
                        member_data['registrations'],
                        member_data['attendances'],
                        member_data['class']
                    )
                    transaction_queries.append((insert_query, params))
                inserted_count = len(to_insert)

            if transaction_queries:
                success = await run_db_transaction(transaction_queries)
                if not success:
                    raise Exception("Database transaction failed")
                    
                logging.info(f"[GuildMembers] Roster transaction completed successfully for guild {guild_id}: {deleted_count} deleted, {updated_count} updated, {inserted_count} inserted")
            else:
                logging.debug(f"[GuildMembers] No roster changes needed for guild {guild_id}")

        except Exception as e:
            logging.error(f"[GuildMembers] Roster transaction failed for guild {guild_id}: {e}", exc_info=True)
            return 0, 0, 0

        return deleted_count, updated_count, inserted_count


    async def update_recruitment_message(self, ctx):
        """
        Update recruitment message with current roster statistics.
        
        Args:
            ctx: Discord context (can be ApplicationContext or Guild object)
            
        Returns:
            None
        """
        if hasattr(ctx, "guild"):
            guild_obj = ctx.guild
        else:
            guild_obj = ctx
        guild_id = guild_obj.id
        await self.bot.cache_loader.ensure_category_loaded('guild_settings')
        await self.bot.cache_loader.ensure_category_loaded('guild_channels')
        
        locale = await self.bot.cache.get_guild_data(guild_id, 'guild_lang') or "en-US"
        channel_id = await self.bot.cache.get_guild_data(guild_id, 'external_recruitment_channel')
        message_id = await self.bot.cache.get_guild_data(guild_id, 'external_recruitment_message')
        
        if not channel_id:
            logging.error(f"[GuildMembers] No recruitment channel configured for guild {guild_id}")
            return
        channel = self.bot.get_channel(channel_id)
        if not channel:
            logging.error("[GuildMembers] Unable to retrieve recruitment channel")
            return

        guild_members = await self.get_guild_members()
        members_in_roster = [v for (g, _), v in guild_members.items() if g == guild_id]
        total_members = len(members_in_roster)
        logging.info(f"[GuildMembers] Recruitment message - Guild members cache contains {len(guild_members)} total entries, {len(members_in_roster)} for guild {guild_id}")
        
        if not members_in_roster:
            logging.warning(f"[GuildMembers] No members found in roster for recruitment message in guild {guild_id}, checking database directly...")
            try:
                guild_members_db = await self._get_guild_members_bulk(guild_id)
                logging.info(f"[GuildMembers] Database query for recruitment returned {len(guild_members_db)} members for guild {guild_id}")
                if guild_members_db:
                    current_cache = await self.bot.cache.get('roster_data', 'guild_members') or {}
                    for member_id, data in guild_members_db.items():
                        key = (guild_id, member_id)
                        current_cache[key] = data
                    await self.bot.cache.set('roster_data', current_cache, 'guild_members')
                    members_in_roster = list(guild_members_db.values())
                    total_members = len(members_in_roster)
                    logging.info(f"[GuildMembers] Updated global cache for recruitment and found {total_members} members")
            except Exception as e:
                logging.error(f"[GuildMembers] Error loading members for recruitment message: {e}", exc_info=True)

        game_id = await self.bot.cache.get_guild_data(guild_id, 'guild_game')
        roster_size_max = None
        if game_id:
            await self.bot.cache_loader.ensure_games_list_loaded()
            games_data = await self.bot.cache.get_static_data('games_list')
            if games_data and game_id in games_data:
                roster_size_max = games_data[game_id].get('max_members')

        ideal_staff = await self.get_ideal_staff(guild_id)
        if not ideal_staff:
            ideal_staff = {
                "Tank": 20,
                "Healer": 20,
                "Flanker": 10,
                "Ranged DPS": 10,
                "Melee DPS": 10
            }

        class_counts = { key: 0 for key in ideal_staff.keys() }
        for m in members_in_roster:
            cls = m.get("class", "NULL")
            if cls in ideal_staff:
                class_counts[cls] += 1

        remaining_slots = max(0, (roster_size_max or 0) - total_members)

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
            await self.bot.cache.set_guild_data(guild_id, 'external_recruitment_message', new_message.id)
            query = "UPDATE guild_settings SET external_recruitment_message = %s WHERE guild_id = %s"
            await self.bot.run_db_query(query, (new_message.id, guild_id), commit=True)

    async def update_members_message(self, ctx):
        """
        Update members message with detailed roster table.
        
        Args:
            ctx: Discord context (can be ApplicationContext or Guild object)
            
        Returns:
            None
        """
        if hasattr(ctx, "guild"):
            guild_obj = ctx.guild
        else:
            guild_obj = ctx
        guild_id = guild_obj.id
        await self.bot.cache_loader.ensure_category_loaded('guild_settings')
        await self.bot.cache_loader.ensure_category_loaded('guild_channels')
        
        locale = await self.bot.cache.get_guild_data(guild_id, 'guild_lang') or "en-US"
        channel_id = await self.bot.cache.get_guild_data(guild_id, 'members_channel')
        
        message_ids = []
        for i in range(1, 6):
            msg_id = await self.bot.cache.get_guild_data(guild_id, f'members_m{i}')
            message_ids.append(msg_id)

        logging.info(f"[GuildMembers] Channel ID: {channel_id}, Message IDs: {message_ids}")

        channel = self.bot.get_channel(channel_id)
        if not channel:
            logging.error(f"[GuildMembers] Unable to retrieve roster channel with ID {channel_id}")
            return

        guild_members = await self.get_guild_members()
        members_in_roster = [v for (g, _), v in guild_members.items() if g == guild_id]
        logging.info(f"[GuildMembers] Guild members cache contains {len(guild_members)} total entries, {len(members_in_roster)} for guild {guild_id}")
        
        if not members_in_roster:
            logging.warning(f"[GuildMembers] No members found in roster for guild {guild_id}, checking database directly...")
            try:
                guild_members_db = await self._get_guild_members_bulk(guild_id)
                logging.info(f"[GuildMembers] Database query returned {len(guild_members_db)} members for guild {guild_id}")
                if guild_members_db:
                    current_cache = await self.bot.cache.get('roster_data', 'guild_members') or {}
                    for member_id, data in guild_members_db.items():
                        key = (guild_id, member_id)
                        current_cache[key] = data
                    await self.bot.cache.set('roster_data', current_cache, 'guild_members')
                    members_in_roster = list(guild_members_db.values())
                    logging.info(f"[GuildMembers] Updated global cache and found {len(members_in_roster)} members")
            except Exception as e:
                logging.error(f"[GuildMembers] Error loading members from database: {e}", exc_info=True)
                
        if not members_in_roster:
            logging.warning("[GuildMembers] No members found in roster")
            return
            
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
            build_value = m.get("build")
            build_flag = "Y" if build_value and build_value not in ("NULL", None, "", "None") else " "
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
            logging.info(f"[GuildMembers] Starting message updates for {len(message_contents)} message contents")
            for i in range(5):
                try:
                    message_id = message_ids[i]
                    if not message_id:
                        logging.warning(f"[GuildMembers] Message ID {i+1}/5 is None, skipping")
                        continue
                        
                    logging.debug(f"[GuildMembers] Fetching message {i+1}/5 with ID {message_id}")
                    message = await channel.fetch_message(message_id)
                    new_content = message_contents[i] if i < len(message_contents) else "."

                    logging.debug(f"[GuildMembers] Message {i+1}/5 content length: old={len(message.content)}, new={len(new_content)}")
                    if message.content != new_content:
                        logging.info(f"[GuildMembers] Updating message {i+1}/5 (content changed)")
                        await message.edit(content=new_content)
                        logging.info(f"[GuildMembers] Message {i+1}/5 updated successfully")
                        if i < 4:
                            await asyncio.sleep(0.25)
                    else:
                        logging.debug(f"[GuildMembers] Message {i+1}/5 content unchanged, skipping update")
                except discord.NotFound:
                    logging.warning(f"[GuildMembers] Roster message {i+1}/5 not found (ID: {message_ids[i]})")
                except Exception as e:
                    logging.error(f"[GuildMembers] Error updating roster message {i+1}/5: {e}", exc_info=True)
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
        """
        Show another member's build URL in private message.
        
        Args:
            ctx: Discord application context
            username: Username to search for
            
        Returns:
            None
        """
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

        await self.bot.cache_loader.ensure_guild_members_loaded()
        guild_members = await self.get_guild_members()
        matching = [m for (g, _), m in guild_members.items() 
                   if g == guild_id and m.get("username", "").lower().startswith(sanitized_username.lower())]

        if not matching:
            msg = get_user_message(ctx, GUILD_MEMBERS["show_build"], "not_found", username=username)
            await ctx.followup.send(msg, ephemeral=True)
            return

        member_data = matching[0]
        build_url = member_data.get("build")
        if not build_url or build_url in ("NULL", None, "", "None"):
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
        """
        Send notifications to members with incomplete profiles.
        
        Args:
            ctx: Discord application context
            
        Returns:
            None
        """
        await ctx.defer(ephemeral=True)
        guild = ctx.guild
        guild_id = guild.id

        await self.bot.cache_loader.ensure_guild_members_loaded()
        
        incomplete_members = []
        guild_members = await self.get_guild_members()
        logging.debug(f"[GuildMembers] notify_incomplete_profiles: Found {len(guild_members)} total members in cache")
        
        guild_member_count = 0
        for (g, member_id), data in guild_members.items():
            if g == guild_id:
                guild_member_count += 1
                gs = data.get("GS", 0)
                weapons = data.get("weapons", "NULL")
                logging.debug(f"[GuildMembers] Member {member_id}: GS={gs}, weapons={weapons}")
                if gs in (0, "0", 0.0, None) or weapons in ("NULL", None, ""):
                    incomplete_members.append(member_id)
                    logging.debug(f"[GuildMembers] Member {member_id} has incomplete profile")
        
        logging.debug(f"[GuildMembers] notify_incomplete_profiles: Found {guild_member_count} members for guild {guild_id}")
        logging.debug(f"[GuildMembers] notify_incomplete_profiles: Found {len(incomplete_members)} incomplete members")

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
    @admin_rate_limit(cooldown_seconds=300)
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
        """
        Configure ideal roster sizes by class for the guild.
        
        Args:
            ctx: Discord application context
            tank: Ideal number of Tank class members
            healer: Ideal number of Healer class members
            flanker: Ideal number of Flanker class members
            ranged_dps: Ideal number of Ranged DPS class members
            melee_dps: Ideal number of Melee DPS class members
            
        Returns:
            None
        """
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

            await self.bot.cache_loader.reload_category('guild_ideal_staff')
            
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
        """
        Change member's preferred language.
        
        Args:
            ctx: Discord application context
            language: New language code to set
            
        Returns:
            None
        """
        await ctx.defer(ephemeral=True)
        
        if not ctx.guild or not ctx.author:
            logging.error("[GuildMembers - ChangeLanguage] Invalid context: missing guild or author")
            return
        
        guild_id = ctx.guild.id
        member_id = ctx.author.id

        key = (guild_id, member_id)
        guild_members = await self.get_guild_members()
        if key not in guild_members:
            logging.debug(f"[GuildMembers - ChangeLanguage] Profile not found in guild_members cache for key {key}, trying database fallback...")
            try:
                user_setup_members = await self.get_user_setup_members()
                if key in user_setup_members:
                    logging.info(f"[GuildMembers - ChangeLanguage] User found in user_setup, creating guild_members entry for {key}")
                    user_setup_data = user_setup_members[key]
                    guild_member_data = {
                        "username": user_setup_data.get("username", ctx.author.display_name),
                        "language": user_setup_data.get("locale", "en-US"),
                        "GS": user_setup_data.get("gs", 0),
                        "build": "",
                        "weapons": user_setup_data.get("weapons", ""),
                        "DKP": 0,
                        "nb_events": 0,
                        "registrations": 0,
                        "attendances": 0,
                        "class": "NULL"
                    }
                    current_cache = await self.bot.cache.get('roster_data', 'guild_members') or {}
                    current_cache[key] = guild_member_data
                    await self.bot.cache.set('roster_data', current_cache, 'guild_members')
                    guild_members[key] = guild_member_data
                    logging.info(f"[GuildMembers - ChangeLanguage] Created guild_members cache entry for {key}")
                else:
                    logging.debug(f"[GuildMembers - ChangeLanguage] Profile not found anywhere for key {key}")
                    not_registered_msg = get_user_message(ctx, GUILD_MEMBERS["change_language"], "messages.not_registered")
                    await ctx.followup.send(not_registered_msg, ephemeral=True)
                    return
            except Exception as e:
                logging.error(f"[GuildMembers - ChangeLanguage] Error in fallback logic: {e}")
                not_registered_msg = get_user_message(ctx, GUILD_MEMBERS["change_language"], "messages.not_registered")
                await ctx.followup.send(not_registered_msg, ephemeral=True)
                return
        
        try:
            short_language = language[:2] if len(language) >= 2 else language
            
            query = "UPDATE guild_members SET language = %s WHERE guild_id = %s AND member_id = %s"
            await self.bot.run_db_query(query, (short_language, guild_id, member_id), commit=True)
            
            await self.update_guild_member_cache(guild_id, member_id, "language", short_language)
            
            language_name = global_translations.get("language_names", {}).get(language, language)
            
            success_msg = get_user_message(ctx, GUILD_MEMBERS["change_language"], "messages.success", language_name=language_name)
            await ctx.followup.send(success_msg, ephemeral=True)
            
            logging.debug(f"[GuildMembers - ChangeLanguage] Language updated for user {member_id} in guild {guild_id}: {language}")
            
        except Exception as e:
            logging.exception(f"[GuildMembers - ChangeLanguage] Error updating language for user {member_id} in guild {guild_id}: {e}")
            error_msg = get_user_message(ctx, GUILD_MEMBERS["change_language"], "messages.error", error=str(e))
            await ctx.followup.send(error_msg, ephemeral=True)

    async def run_maj_roster(self, guild_id: int) -> None:
        """
        Run roster update for a specific guild.
        
        Args:
            guild_id: The ID of the guild to update roster for
            
        Returns:
            None
        """
        await self.bot.cache_loader.ensure_category_loaded('guild_roles')
        roles_config = await self.bot.cache.get_guild_data(guild_id, 'roles')
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

        guild_members = await self.get_guild_members()
        to_delete = []
        for (g, user_id), data in guild_members.items():
            if g == guild_id and user_id not in actual_members:
                delete_query = "DELETE FROM guild_members WHERE guild_id = %s AND member_id = %s"
                await self.bot.run_db_query(delete_query, (guild_id, user_id), commit=True)
                to_delete.append(user_id)

        user_setup_members = await self.get_user_setup_members()
        for member in actual_members.values():
            key = (guild_id, member.id)
            if key in guild_members:
                record = guild_members[key]
                if record.get("username") != member.display_name:
                    update_query = "UPDATE guild_members SET username = %s WHERE guild_id = %s AND member_id = %s"
                    await self.bot.run_db_query(update_query, (member.display_name, guild_id, member.id), commit=True)
                    logging.debug(f"[GuildMembers] Username updated for {member.display_name} (ID: {member.id})")
            else:
                key_setup = (guild_id, member.id)
                user_setup = user_setup_members.get(key_setup, {})
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
                    ON DUPLICATE KEY UPDATE
                    username = VALUES(username),
                    language = VALUES(language),
                    GS = VALUES(GS),
                    build = VALUES(build),
                    weapons = VALUES(weapons),
                    DKP = VALUES(DKP),
                    nb_events = VALUES(nb_events),
                    registrations = VALUES(registrations),
                    attendances = VALUES(attendances),
                    `class` = VALUES(`class`)
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
                logging.debug(f"[GuildMembers] New member added: {member.display_name} (ID: {member.id})")

        try:
            await self._load_members_data()
            await self.update_recruitment_message(guild)
            await self.update_members_message(guild)
            logging.info(f"[GuildMembers] Roster synchronization completed for guild {guild_id}")
        except Exception as e:
            logging.exception(f"[GuildMembers] Error during roster synchronization for guild {guild_id}: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        """
        Initialize guild members data on bot ready.
        
        Args:
            None
            
        Returns:
            None
        """
        try:
            asyncio.create_task(self.load_guild_members_data())
            logging.debug("[GuildMembers] Database info caching tasks launched from on_ready")
        except Exception as e:
            logging.exception(f"[GuildMembers] Error during on_ready initialization: {e}")
    
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """
        Sync member nickname changes to PTB guild.
        
        Args:
            before: Member state before the update
            after: Member state after the update
            
        Returns:
            None
        """
        try:
            if before.display_name == after.display_name:
                return

            guild_ptb_cog = self.bot.get_cog("GuildPTB")
            if not guild_ptb_cog:
                return
            
            main_guild_id = after.guild.id
            
            ptb_settings = await guild_ptb_cog.get_guild_ptb_settings(main_guild_id)
            if not ptb_settings:
                return
            
            ptb_guild_id = ptb_settings.get("ptb_guild_id")
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
    """
    Setup function for the cog.
    
    Args:
        bot: The Discord bot instance
        
    Returns:
        None
    """
    bot.add_cog(GuildMembers(bot))

