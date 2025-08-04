"""
AutoRole Manager Cog - Manages automatic role assignment and welcome message handling.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, Tuple

import discord
import pytz
from discord.ext import commands

from ..core.reliability import discord_resilient
from ..core.translation import translations as global_translations

WELCOME_MP_DATA = global_translations.get("welcome_mp", {})

def update_welcome_embed(embed: discord.Embed, lang: str, translations: dict) -> discord.Embed:
    """
    Update welcome embed with acceptance timestamp and language-specific text.
    
    Args:
        embed: Discord embed to update
        lang: Language code for translations
        translations: Translation dictionary
        
    Returns:
        Updated Discord embed with acceptance timestamp
    """
    try:
        tz_france = pytz.timezone("Europe/Paris")
        now = datetime.now(pytz.utc).astimezone(tz_france).strftime("%d/%m/%Y at %Hh%M")
        pending_text = translations["welcome"]["pending"].get(lang)
        accepted_template = translations["welcome"]["accepted"].get(lang)
        if not pending_text or not accepted_template:
            logging.error(f"[AutoRole] Missing translation keys for language '{lang}'.")
            return embed
        new_text = accepted_template.format(date=now)
        if embed.description:
            embed.description = embed.description.replace(pending_text, new_text)
        else:
            embed.description = new_text
        embed.color = discord.Color.dark_grey()
    except Exception as e:
        logging.error(f"[AutoRole] Error updating welcome embed: {e}", exc_info=True)
    return embed

class AutoRole(commands.Cog):
    """Cog for managing automatic role assignment and welcome message handling."""
    
    def __init__(self, bot: discord.Bot) -> None:
        """
        Initialize the AutoRole cog.
        
        Args:
            bot: Discord bot instance
        """
        self.bot = bot
        self._profile_setup_cog = None
        self._recent_reactions: Dict[Tuple[int, int, int], float] = {}
        self._reaction_counts: Dict[Tuple[int, int, int], int] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        """Initialize autorole data on bot ready."""
        asyncio.create_task(self.load_autorole_data())
        logging.debug("[AutoRole] Cache loading tasks started from on_ready.")

    async def load_autorole_data(self) -> None:
        """Ensure all required data is loaded via centralized cache loader."""
        logging.debug("[AutoRole] Loading autorole data")

        await self.bot.cache_loader.ensure_category_loaded('guild_channels')
        await self.bot.cache_loader.ensure_category_loaded('guild_roles')
        await self.bot.cache_loader.ensure_category_loaded('guild_settings')
        await self.bot.cache_loader.ensure_category_loaded('welcome_messages')
        
        logging.debug("[AutoRole] Autorole data loading completed")

    def _check_rate_limit(self, guild_id: int, user_id: int, message_id: int) -> bool:
        """
        Check if user is rate limited for reactions on a specific message.
        
        Args:
            guild_id: Discord guild ID
            user_id: Discord user ID
            message_id: Discord message ID
            
        Returns:
            True if user can react, False if rate limited
        """
        key = (guild_id, user_id, message_id)
        current_time = time.time()
        
        self._reaction_counts[key] = self._reaction_counts.get(key, 0) + 1
        
        cutoff = current_time - 3600
        keys_to_remove = []
        for k, timestamp in self._recent_reactions.items():
            if timestamp <= cutoff:
                keys_to_remove.append(k)
        
        for k in keys_to_remove:
            self._recent_reactions.pop(k, None)
            self._reaction_counts.pop(k, None)
        
        if self._reaction_counts[key] <= 2:
            self._recent_reactions[key] = current_time
            return True
        
        if key in self._recent_reactions:
            if current_time - self._recent_reactions[key] < 5.0:
                return False
        
        self._recent_reactions[key] = current_time
        return True

    def _get_profile_setup_cog(self):
        """
        Get ProfileSetup cog instance with caching.
        
        Returns:
            ProfileSetup cog instance or None if not found
        """
        if self._profile_setup_cog is None:
            self._profile_setup_cog = self.bot.get_cog("ProfileSetup")
        return self._profile_setup_cog

    @commands.Cog.listener()
    @discord_resilient(service_name='discord_api', max_retries=2)
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        """
        Handle reaction addition for role assignment and welcome message updates.
        
        Args:
            payload: Discord raw reaction event payload
        """
        logging.debug(f"[AutoRole - on_raw_reaction_add] Processing reaction: user={payload.user_id}, message={payload.message_id}, emoji={payload.emoji}")
        
        if not payload.guild_id:
            logging.debug("[AutoRole - on_raw_reaction_add] No guild_id, skipping")
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            logging.debug(f"[AutoRole - on_raw_reaction_add] Guild {payload.guild_id} not found")
            return

        rules_info = await self.bot.cache.get_guild_data(guild.id, 'rules_message')
        if not rules_info or payload.message_id != rules_info.get("message"):
            logging.debug(f"[AutoRole - on_raw_reaction_add] Message {payload.message_id} is not rules message for guild {guild.id}")
            return

        if str(payload.emoji) != "✅":
            return

        if not self._check_rate_limit(guild.id, payload.user_id, payload.message_id):
            logging.debug(f"[AutoRole] Rate limited reaction from user {payload.user_id}")
            return

        role_id = await self.bot.cache.get_guild_data(guild.id, 'rules_ok_role')
        if not role_id:
            logging.warning(f"[AutoRole] No rules_ok role configured for guild {guild.id}")
            return
            
        role = guild.get_role(role_id)
        if not role:
            logging.warning(f"[AutoRole] Rules_ok role {role_id} not found in guild {guild.id}")
            return

        try:
            member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
        except Exception as e:
            logging.error(f"[AutoRole] Error fetching member with ID {payload.user_id}: {e}", exc_info=True)
            return

        if member and role and role not in member.roles:
            try:
                await member.add_roles(role)
                logging.debug(f"[AutoRole] Role added to {member.name} ({member.id}).")
            except Exception as e:
                logging.error(f"[AutoRole] Error adding role to {member.name}: {e}", exc_info=True)
                return

            welcome_info = await self.bot.cache.get_user_data(guild.id, member.id, 'welcome_message')
            if welcome_info:
                try:
                    channel = self.bot.get_channel(welcome_info["channel"])
                    if not channel:
                        channel = await self.bot.fetch_channel(welcome_info["channel"])
                    
                    if not channel:
                        logging.warning(f"[AutoRole] Channel {welcome_info['channel']} not found, removing from cache")
                        await self.bot.cache.delete('user_data', guild.id, member.id, 'welcome_message')
                        return
                    
                    try:
                        message = await channel.fetch_message(welcome_info["message"])
                    except discord.NotFound:
                        logging.warning(f"[AutoRole] Message {welcome_info['message']} not found, removing from cache")
                        await self.bot.cache.delete('user_data', guild.id, member.id, 'welcome_message')
                        return

                    if not message.embeds:
                        logging.warning(f"[AutoRole] No embeds found in welcome message for {member.name}")
                        return
                        
                    lang = await self.bot.cache.get_guild_data(guild.id, 'guild_lang') or "en-US"
                    embed = update_welcome_embed(message.embeds[0], lang, global_translations)
                    await message.edit(embed=embed)
                    logging.debug(f"[AutoRole] Welcome message updated for {member.name} (ID: {member.id}).")
                except discord.Forbidden:
                    logging.warning(f"[AutoRole] No permission to edit message for {member.name}")
                except Exception as e:
                    logging.error("[AutoRole] Error updating welcome message", exc_info=True)
            else:
                logging.debug(f"[AutoRole] No welcome message in cache for member {member.id} in guild {guild.id}.")

            try:
                user_setup = await self.bot.cache.get_user_data(guild.id, member.id, 'setup')
                if user_setup is not None:
                    logging.debug(f"[AutoRole] Profile already exists for {guild.id}_{member.id}; no DM sent for registration.")
                    return
            except Exception as e:
                logging.error(f"[AutoRole] Error checking user profile for {guild.id}_{member.id}: {e}", exc_info=True)
                return

            profile_setup_cog = self._get_profile_setup_cog()
            if profile_setup_cog is None:
                logging.error("[AutoRole] ProfileSetup cog not found!")
                return
            try:
                await member.send(view=profile_setup_cog.LangSelectView(profile_setup_cog, guild.id))
                logging.debug(f"[AutoRole] DM sent to {member.name} ({member.id}) to start the profile setup process for guild {guild.id}.")
            except discord.Forbidden:
                logging.warning(f"[AutoRole] Cannot send DM to {member.name} - DMs disabled for guild {guild.id}")
            except Exception as e:
                logging.error(f"[AutoRole] Error sending DM to {member.name}: {e} in guild {guild.id}.", exc_info=True)

    @commands.Cog.listener()
    @discord_resilient(service_name='discord_api', max_retries=2)
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        """
        Handle reaction removal and role management.
        
        Args:
            payload: Discord raw reaction event payload
        """
        if not payload.guild_id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        rules_info = await self.bot.cache.get_guild_data(guild.id, 'rules_message')
        if not rules_info or payload.message_id != rules_info.get("message"):
            return

        if str(payload.emoji) != "✅":
            return

        if not self._check_rate_limit(guild.id, payload.user_id, payload.message_id):
            logging.debug(f"[AutoRole] Rate limited reaction removal from user {payload.user_id}")
            return

        role_id = await self.bot.cache.get_guild_data(guild.id, 'rules_ok_role')
        if not role_id:
            logging.warning(f"[AutoRole] No rules_ok role configured for guild {guild.id}")
            return

        role = guild.get_role(role_id)
        if not role:
            logging.warning(f"[AutoRole] Rules_ok role {role_id} not found in guild {guild.id}")
            return

        try:
            member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
        except Exception as e:
            logging.error(f"[AutoRole] Error fetching member with ID {payload.user_id}: {e}", exc_info=True)
            return

        if member and role and role in member.roles:
            try:
                await member.remove_roles(role)
                logging.debug(f"[AutoRole] Role removed from {member.name} ({member.id}).")
            except Exception as e:
                logging.error(f"[AutoRole] Error removing role from {member.name}: {e}", exc_info=True)

def setup(bot: discord.Bot):
    """
    Setup function to add the AutoRole cog to the bot.
    
    Args:
        bot: Discord bot instance
    """
    bot.add_cog(AutoRole(bot))
