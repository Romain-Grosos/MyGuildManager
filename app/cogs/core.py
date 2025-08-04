"""
Core Management Cog - Handles guild initialization, modification, and reset operations.
"""

import asyncio
import logging
import re
from typing import Optional, Tuple

import discord
from discord.ext import commands

from core.functions import get_user_message
from core.rate_limiter import admin_rate_limit, start_cleanup_task
from core.reliability import discord_resilient
from core.translation import translations as global_translations

APP_INITIALIZE_DATA = global_translations.get("commands", {}).get("app_initialize", {})
APP_MODIFICATION_DATA = global_translations.get("commands", {}).get("app_modify", {})
APP_RESET_DATA = global_translations.get("commands", {}).get("app_reset", {})

class Core(commands.Cog):
    """Cog for managing core guild operations and bot initialization."""
    
    def __init__(self, bot: discord.Bot) -> None:
        """
        Initialize the Core cog.
        
        Args:
            bot: Discord bot instance
        """
        self.bot = bot
        self._sync_lock = asyncio.Lock()
        if not hasattr(bot, "synced"):
            bot.synced = False
    
    def _validate_guild_name(self, guild_name: str) -> Tuple[bool, str]:
        """
        Validate guild name format and constraints.
        
        Args:
            guild_name: Guild name to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not guild_name or len(guild_name.strip()) == 0:
            return False, "Guild name cannot be empty"
        if len(guild_name) > 50:
            return False, "Guild name too long (max 50 characters)"
        if not re.match(r'^[a-zA-Z0-9\s\-_\[\]\(\)]+$', guild_name):
            return False, "Guild name contains invalid characters"
        return True, ""
    
    def _validate_guild_server(self, guild_server: str) -> Tuple[bool, str]:
        """
        Validate guild server name format and constraints.
        
        Args:
            guild_server: Server name to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not guild_server or len(guild_server.strip()) == 0:
            return False, "Guild server cannot be empty"
        if len(guild_server) > 50:
            return False, "Guild server name too long (max 50 characters)"
        if not re.match(r'^[a-zA-Z0-9\s\-]+$', guild_server):
            return False, "Guild server contains invalid characters"
        return True, ""
    
    @discord_resilient(service_name='discord_api', max_retries=2)
    async def _safe_edit_nickname(self, guild: discord.Guild, nickname: str) -> bool:
        """
        Safely change bot nickname in guild with error handling.
        
        Args:
            guild: Discord guild where to change nickname
            nickname: New nickname for the bot
            
        Returns:
            True if nickname was changed successfully, False otherwise
        """
        try:
            await guild.me.edit(nick=nickname)
            logging.debug(f"[CoreManager] Bot nickname changed to '{nickname}' in guild {guild.id}")
            return True
        except discord.Forbidden:
            logging.warning(f"[CoreManager] No permission to change nickname in guild {guild.id}")
            return False
        except discord.HTTPException as e:
            logging.error(f"[CoreManager] HTTP error changing nickname in guild {guild.id}: {e}")
            return False
        except Exception as e:
            logging.error(f"[CoreManager] Unexpected error changing nickname in guild {guild.id}: {e}")
            return False

    @commands.Cog.listener()
    async def on_ready(self):
        """Handle bot ready event and sync commands."""
        async with self._sync_lock:
            if not self.bot.synced:
                try:
                    await self.bot.sync_commands()
                    self.bot.synced = True
                    logging.info("[CoreManager] Slash commands synced successfully.")
                except Exception as e:
                    logging.error(f"[CoreManager] Failed to sync slash commands: {e}")
        logging.info(f"[CoreManager] Bot is connected as {self.bot.user}")

        asyncio.create_task(self.load_core_data())
        logging.debug("[CoreManager] Cache loading tasks started in on_ready.")
    
    async def load_core_data(self) -> None:
        """Ensure all required data is loaded via centralized cache loader."""
        logging.debug("[CoreManager] Loading core data")
        
        await self.bot.cache_loader.ensure_category_loaded('guild_settings')
        
        logging.debug("[CoreManager] Core data loading completed")

    @commands.Cog.listener()
    async def on_app_command_error(self, ctx: discord.ApplicationContext, error: Exception):
        """
        Handle global application command errors.
        
        Args:
            ctx: Discord application context
            error: Exception that occurred during command execution
        """
        response = get_user_message(ctx, global_translations, "global_error", error=error)
        try:
            if ctx.response.is_done():
                await ctx.followup.send(response, ephemeral=True)
            else:
                await ctx.respond(response, ephemeral=True)
        except Exception as e:
            logging.error("[CoreManager] Failed to send global error message.", exc_info=True)
        logging.error(f"[CoreManager] Global error in command: {error}", exc_info=True)

    @discord.slash_command(
        name=APP_INITIALIZE_DATA["name"]["en-US"],
        description=APP_INITIALIZE_DATA["description"]["en-US"],
        name_localizations=APP_INITIALIZE_DATA["name"],
        description_localizations=APP_INITIALIZE_DATA["description"]
    )
    @commands.has_permissions(administrator=True)
    @admin_rate_limit(cooldown_seconds=300)
    async def app_initialize(
        self,
        ctx: discord.ApplicationContext,
        guild_name: str = discord.Option(
            description=APP_INITIALIZE_DATA["options"]["guild_name"]["description"]["en-US"],
            description_localizations=APP_INITIALIZE_DATA["options"]["guild_name"]["description"]
        ),
        guild_lang: str = discord.Option(
            description=APP_INITIALIZE_DATA["options"]["guild_lang"]["description"]["en-US"],
            description_localizations=APP_INITIALIZE_DATA["options"]["guild_lang"]["description"],
            choices=["en-US", "fr", "es-ES", "de", "it"]
        ),
        guild_game: int = discord.Option(
            description=APP_INITIALIZE_DATA["options"]["guild_game"]["description"]["en-US"],
            description_localizations=APP_INITIALIZE_DATA["options"]["guild_game"]["description"],
            choices=[
                discord.OptionChoice(choice_name, choice_value)
                for choice_name, choice_value in APP_INITIALIZE_DATA["options"]["guild_game"]["choices"].items()
            ]
        ),
        guild_server: str = discord.Option(
            description=APP_INITIALIZE_DATA["options"]["guild_server"]["description"]["en-US"],
            description_localizations=APP_INITIALIZE_DATA["options"]["guild_server"]["description"]
        )
    ):
        """
        Initialize a guild in the bot system with basic settings.
        
        Args:
            ctx: Discord application context
            guild_name: Name of the guild to initialize
            guild_lang: Language for the guild
            guild_game: Game ID for the guild
            guild_server: Server name for the guild
        """
        valid_name, name_error = self._validate_guild_name(guild_name)
        if not valid_name:
            await ctx.respond(f"Invalid guild name: {name_error}", ephemeral=True)
            return
        
        valid_server, server_error = self._validate_guild_server(guild_server)
        if not valid_server:
            await ctx.respond(f"Invalid guild server: {server_error}", ephemeral=True)
            return
        
        guild_id = ctx.guild.id
        guild_game_int = int(guild_game)
        
        try:
            await self.bot.cache_loader.ensure_category_loaded('guild_settings')
            existing_settings = await self.bot.cache.get_guild_data(guild_id, 'guild_lang')
            
            if existing_settings:
                logging.info(f"[CoreManager] Guild {guild_id} already exists in the database.")
                response = get_user_message(ctx, APP_INITIALIZE_DATA, "messages.already_declared")
            else:
                insert_query = """
                    INSERT INTO guild_settings 
                    (guild_id, guild_name, guild_lang, guild_game, guild_server, initialized, premium)
                    VALUES (%s, %s, %s, %s, %s, TRUE, 0)
                """
                await self.bot.run_db_query(insert_query, (guild_id, guild_name.strip(), guild_lang, guild_game_int, guild_server.strip()), commit=True)
                logging.info(f"[CoreManager] Guild {guild_id} successfully initialized in the database.")

                try:
                    await self.bot.cache.set_guild_data(guild_id, 'guild_name', guild_name.strip())
                    await self.bot.cache.set_guild_data(guild_id, 'guild_lang', guild_lang)
                    await self.bot.cache.set_guild_data(guild_id, 'guild_game', guild_game_int)
                    await self.bot.cache.set_guild_data(guild_id, 'guild_server', guild_server.strip())
                    await self.bot.cache.set_guild_data(guild_id, 'premium', 0)

                    await self.bot.cache.set_guild_data(guild_id, 'settings', {
                        'guild_name': guild_name.strip(),
                        'guild_lang': guild_lang,
                        'guild_game': guild_game_int,
                        'guild_server': guild_server.strip(),
                        'premium': 0
                    })
                    
                    logging.debug(f"[CoreManager] Global cache updated after guild {guild_id} initialization")
                except Exception as cache_error:
                    logging.error(f"[CoreManager] Error updating global cache: {cache_error}")

                rename_templates = APP_INITIALIZE_DATA.get("rename_templates", {})
                template = rename_templates.get(guild_lang, rename_templates.get("en-US", "MGM - {guild_name}"))
                new_nickname = template.format(guild_name=guild_name.strip())
                nickname_success = await self._safe_edit_nickname(ctx.guild, new_nickname)
                
                if not nickname_success:
                    logging.warning(f"[CoreManager] Could not change nickname for guild {guild_id}, but initialization succeeded")

                response = get_user_message(ctx, APP_INITIALIZE_DATA, "messages.success")

        except Exception as e:
            logging.error("[CoreManager] Error during guild initialization: %s", e, exc_info=True)
            response = get_user_message(ctx, APP_INITIALIZE_DATA, "messages.error", error="Database error")
        await ctx.respond(response, ephemeral=True)

    @discord.slash_command(
        name=APP_MODIFICATION_DATA["name"]["en-US"],
        description=APP_MODIFICATION_DATA["description"]["en-US"],
        name_localizations=APP_MODIFICATION_DATA["name"],
        description_localizations=APP_MODIFICATION_DATA["description"]
    )
    @commands.has_permissions(administrator=True)
    @admin_rate_limit(cooldown_seconds=300)
    async def app_modify(
        self,
        ctx: discord.ApplicationContext,
        guild_name: str = discord.Option(
            default=None,
            description=APP_MODIFICATION_DATA["options"]["guild_name"]["description"]["en-US"],
            description_localizations=APP_MODIFICATION_DATA["options"]["guild_name"]["description"]
        ),
        guild_lang: str = discord.Option(
            default=None,
            description=APP_MODIFICATION_DATA["options"]["guild_lang"]["description"]["en-US"],
            description_localizations=APP_MODIFICATION_DATA["options"]["guild_lang"]["description"],
            choices=["en-US", "fr", "es-ES", "de", "it"]
        ),
        guild_game: int = discord.Option(
            default=None,
            description=APP_MODIFICATION_DATA["options"]["guild_game"]["description"]["en-US"],
            description_localizations=APP_MODIFICATION_DATA["options"]["guild_game"]["description"],
            choices=[
                discord.OptionChoice(choice_name, choice_value)
                for choice_name, choice_value in APP_MODIFICATION_DATA["options"]["guild_game"]["choices"].items()
            ]
        ),
        guild_server: str = discord.Option(
            default=None,
            description=APP_MODIFICATION_DATA["options"]["guild_server"]["description"]["en-US"],
            description_localizations=APP_MODIFICATION_DATA["options"]["guild_server"]["description"]
        )
    ):
        """
        Modify existing guild settings and update caches.
        
        Args:
            ctx: Discord application context
            guild_name: New guild name (optional)
            guild_lang: New guild language (optional)
            guild_game: New game ID (optional)
            guild_server: New server name (optional)
        """
        if guild_name is not None:
            valid_name, name_error = self._validate_guild_name(guild_name)
            if not valid_name:
                await ctx.respond(f"Invalid guild name: {name_error}", ephemeral=True)
                return
        
        if guild_server is not None:
            valid_server, server_error = self._validate_guild_server(guild_server)
            if not valid_server:
                await ctx.respond(f"Invalid guild server: {server_error}", ephemeral=True)
                return
        
        guild_id = ctx.guild.id
        
        try:
            await self.bot.cache_loader.ensure_category_loaded('guild_settings')
            current_guild_name = await self.bot.cache.get_guild_data(guild_id, 'guild_name')
            current_guild_lang = await self.bot.cache.get_guild_data(guild_id, 'guild_lang')
            current_guild_game = await self.bot.cache.get_guild_data(guild_id, 'guild_game')
            current_guild_server = await self.bot.cache.get_guild_data(guild_id, 'guild_server')
            
            if not current_guild_lang:
                response = get_user_message(ctx, APP_MODIFICATION_DATA, "messages.need_init")
                return await ctx.respond(response, ephemeral=True)
            
            new_guild_name = guild_name.strip() if guild_name is not None else current_guild_name
            new_guild_lang = guild_lang if guild_lang is not None else current_guild_lang
            new_guild_game = int(guild_game) if guild_game is not None else current_guild_game
            new_guild_server = guild_server.strip() if guild_server is not None else current_guild_server

            update_query = """
                UPDATE guild_settings
                SET guild_name = %s, guild_lang = %s, guild_game = %s, guild_server = %s
                WHERE guild_id = %s
            """
            await self.bot.run_db_query(update_query, (new_guild_name, new_guild_lang, new_guild_game, new_guild_server, guild_id), commit=True)
            logging.info(f"[CoreManager] Guild {guild_id} successfully modified in the database.")

            try:
                await self.bot.cache.set_guild_data(guild_id, 'guild_name', new_guild_name)
                await self.bot.cache.set_guild_data(guild_id, 'guild_lang', new_guild_lang)
                await self.bot.cache.set_guild_data(guild_id, 'guild_game', new_guild_game)
                await self.bot.cache.set_guild_data(guild_id, 'guild_server', new_guild_server)

                await self.bot.cache.set_guild_data(guild_id, 'settings', {
                    'guild_name': new_guild_name,
                    'guild_lang': new_guild_lang,
                    'guild_game': new_guild_game,
                    'guild_server': new_guild_server
                })
                
                logging.debug(f"[CoreManager] Global cache updated after guild {guild_id} modification")
            except Exception as cache_error:
                logging.error(f"[CoreManager] Error updating global cache: {cache_error}")

            rename_templates = APP_MODIFICATION_DATA.get("rename_templates", APP_INITIALIZE_DATA.get("rename_templates", {}))
            template = rename_templates.get(new_guild_lang, rename_templates.get("en-US", "MGM - {guild_name}"))
            new_nickname = template.format(guild_name=new_guild_name)
            nickname_success = await self._safe_edit_nickname(ctx.guild, new_nickname)
            
            if not nickname_success:
                logging.warning(f"[CoreManager] Could not change nickname for guild {guild_id}, but modification succeeded")

            response = get_user_message(ctx, APP_MODIFICATION_DATA, "messages.success")
            
        except Exception as e:
            logging.error(f"[CoreManager] Error during guild modification: {e}", exc_info=True)
            response = get_user_message(ctx, APP_MODIFICATION_DATA, "messages.error", error="Database error")
        await ctx.respond(response, ephemeral=True)

    @discord.slash_command(
        name=APP_RESET_DATA["name"]["en-US"],
        description=APP_RESET_DATA["description"]["en-US"],
        name_localizations=APP_RESET_DATA["name"],
        description_localizations=APP_RESET_DATA["description"]
    )
    @commands.has_permissions(administrator=True)
    @admin_rate_limit(cooldown_seconds=600)
    async def app_reset(
        self,
        ctx: discord.ApplicationContext,
        confirmation: str = discord.Option(
            description=APP_RESET_DATA["options"]["confirmation"]["description"]["en-US"],
            description_localizations=APP_RESET_DATA["options"]["confirmation"]["description"]
        )
    ):
        """
        Reset guild configuration and delete all associated data.
        
        Args:
            ctx: Discord application context
            confirmation: Confirmation string to validate reset intention
        """
        guild_id = ctx.guild.id

        if confirmation != "DELETE":
            response = get_user_message(ctx, APP_RESET_DATA, "messages.bad_parameter")
            return await ctx.respond(response, ephemeral=True)

        try:
            await self.bot.cache_loader.ensure_category_loaded('guild_settings')
            existing_settings = await self.bot.cache.get_guild_data(guild_id, 'guild_lang')
            
            if not existing_settings:
                response = get_user_message(ctx, APP_RESET_DATA, "messages.need_init")
                return await ctx.respond(response, ephemeral=True)

            success = await self._delete_guild_data_atomic(guild_id)
            
            if success:
                try:
                    await self.bot.cache.delete('guild_data', guild_id, 'guild_name')
                    await self.bot.cache.delete('guild_data', guild_id, 'guild_lang')
                    await self.bot.cache.delete('guild_data', guild_id, 'guild_game')
                    await self.bot.cache.delete('guild_data', guild_id, 'guild_server')
                    await self.bot.cache.delete('guild_data', guild_id, 'premium')
                    await self.bot.cache.delete('guild_data', guild_id, 'settings')
                    await self.bot.cache.delete('guild_data', guild_id, 'roles')
                    await self.bot.cache.delete('guild_data', guild_id, 'channels')
                    await self.bot.cache.delete('guild_data', guild_id, 'absence_channels')
                    await self.bot.cache.delete('guild_data', guild_id, 'rules_message')
                    await self.bot.cache.delete('guild_data', guild_id, 'events_channel')
                    
                    logging.debug(f"[CoreManager] Global cache cleared for guild {guild_id}")
                except Exception as cache_error:
                    logging.error(f"[CoreManager] Error clearing global cache: {cache_error}")
                
                await self._safe_edit_nickname(ctx.guild, "My Guild Manager")
                
                logging.info(f"[CoreManager] Guild {guild_id} data has been deleted from the database.")
                response = get_user_message(ctx, APP_RESET_DATA, "messages.success")
            else:
                response = get_user_message(ctx, APP_RESET_DATA, "messages.error", error="Database deletion failed")
                
        except Exception as e:
            logging.error("[CoreManager] Error during guild reset: %s", e, exc_info=True)
            response = get_user_message(ctx, APP_RESET_DATA, "messages.error", error="Database error")
        await ctx.respond(response, ephemeral=True)

    async def _delete_guild_data_atomic(self, guild_id: int) -> bool:
        """
        Atomically delete all guild data from database.
        
        Args:
            guild_id: Discord guild ID
            
        Returns:
            True if deletion succeeded, False otherwise
        """
        try:
            delete_queries = [
                "DELETE FROM welcome_messages WHERE guild_id = %s",
                "DELETE FROM absence_messages WHERE guild_id = %s", 
                "DELETE FROM contracts WHERE guild_id = %s",
                "DELETE FROM events_data WHERE guild_id = %s",
                "DELETE FROM user_setup WHERE guild_id = %s",
                "DELETE FROM guild_members WHERE guild_id = %s",
                "DELETE FROM guild_roles WHERE guild_id = %s",
                "DELETE FROM guild_channels WHERE guild_id = %s",
                "DELETE FROM guild_settings WHERE guild_id = %s"
            ]
            
            for query in delete_queries:
                try:
                    await self.bot.run_db_query(query, (guild_id,), commit=True)
                except Exception as e:
                    logging.debug(f"[CoreManager] Non-critical deletion error for guild {guild_id}: {e}")
            
            return True
            
        except Exception as e:
            logging.error(f"[CoreManager] Critical error during atomic deletion for guild {guild_id}: {e}", exc_info=True)
            return False
    
    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """
        Handle bot removal from guild and cleanup data.
        
        Args:
            guild: Discord guild the bot was removed from
        """
        guild_id = guild.id
        logging.info(f"[CoreManager] Bot removed from guild {guild_id}. Deleting associated data from the database.")
        
        success = await self._delete_guild_data_atomic(guild_id)
        
        if success:
            try:
                await self.bot.cache.delete('guild_data', guild_id, 'guild_name')
                await self.bot.cache.delete('guild_data', guild_id, 'guild_lang')
                await self.bot.cache.delete('guild_data', guild_id, 'guild_game')
                await self.bot.cache.delete('guild_data', guild_id, 'guild_server')
                await self.bot.cache.delete('guild_data', guild_id, 'premium')
                await self.bot.cache.delete('guild_data', guild_id, 'settings')
                await self.bot.cache.delete('guild_data', guild_id, 'roles')
                await self.bot.cache.delete('guild_data', guild_id, 'channels')
                await self.bot.cache.delete('guild_data', guild_id, 'absence_channels')
                await self.bot.cache.delete('guild_data', guild_id, 'rules_message')
                await self.bot.cache.delete('guild_data', guild_id, 'events_channel')
                
                logging.debug(f"[CoreManager] Global cache cleared for removed guild {guild_id}")
            except Exception as cache_error:
                logging.error(f"[CoreManager] Error clearing global cache for removed guild: {cache_error}")
            
            logging.info(f"[CoreManager] Data for guild {guild_id} successfully deleted from the database.")
        else:
            logging.error(f"[CoreManager] Failed to completely delete data for guild {guild_id}")

def setup(bot: discord.Bot) -> None:
    """
    Setup function to add the Core cog to the bot.
    
    Args:
        bot: Discord bot instance
    """
    bot.add_cog(Core(bot))
