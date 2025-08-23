"""
Core Management Cog - Enterprise-grade guild initialization, modification, and reset operations.

This cog provides critical guild management with:

Features:
    - Guild initialization with comprehensive validation
    - Settings modification with rollback capability
    - Safe reset operations with confirmation
    - Automatic command syncing on startup
    - PTB (Public Test Build) support

Enterprise Patterns:
    - Structured logging with ComponentLogger
    - Discord API resilience with retry logic
    - Rate limiting for admin operations
    - Atomic database operations with transactions
    - Graceful error handling with user feedback
    - Thread-safe command synchronization
"""

import asyncio
import re
from typing import Tuple

import discord
from discord.ext import commands

from app.core.functions import get_user_message
from app.core.logger import ComponentLogger
from app.core.rate_limiter import admin_rate_limit, start_cleanup_task
from app.core.reliability import discord_resilient
from app.core.translation import translations as global_translations
from app.db import run_db_transaction

_logger = ComponentLogger("core")
ADMIN_COMMANDS = global_translations.get("admin_commands", {})
NAME_RE = re.compile(r"^[\w\s\-\_\[\]\(\)'.&/]{1,50}$", re.UNICODE)
SERVER_RE = re.compile(r"^[\w\s\-\'.&/]{1,50}$", re.UNICODE)
GUILD_GAME_CHOICES_CFG = (global_translations.get("global", {})
                         .get("common_options", {})
                         .get("guild_game", {})
                         .get("choices", {}))
RESET_CONFIRMATION_META = (((ADMIN_COMMANDS.get("bot_reset") or {}).get("options") or {}).get("confirmation") or {})

class Core(commands.Cog):
    """Enterprise-grade cog for managing core guild operations and bot initialization."""

    def __init__(self, bot: discord.Bot) -> None:
        """
        Initialize the Core cog with enterprise patterns.

        Args:
            bot: Discord bot instance
        """
        self.bot = bot
        self._sync_lock = asyncio.Lock()
        if not hasattr(bot, "synced"):
            bot.synced = False

        self._register_admin_commands()

        asyncio.create_task(start_cleanup_task(bot))
        _logger.debug("core_cog_initialized")

    def _cmd_meta(self, block_key: str, fallback_name: str, fallback_desc: str):
        """
        Helper to safely extract command metadata with fallbacks.
        
        Args:
            block_key: Translation block key
            fallback_name: Fallback command name
            fallback_desc: Fallback command description
            
        Returns:
            Tuple of (name_en, desc_en, name_localizations, desc_localizations)
        """
        meta = ADMIN_COMMANDS.get(block_key) or {}
        names = meta.get("name") or {}
        descs = meta.get("description") or {}
        name_en = names.get("en-US", fallback_name)
        desc_en = descs.get("en-US", fallback_desc)
        return name_en, desc_en, names, descs

    def _register_admin_commands(self):
        """Register core commands with the centralized admin_bot group."""
        if hasattr(self.bot, "admin_group"):
            n, d, nl, dl = self._cmd_meta("bot_initialize", "bot_initialize", "Initialize the bot for this guild.")
            self.bot.admin_group.command(name=n, description=d,
                                         name_localizations=nl, description_localizations=dl)(self.app_initialize)

            n, d, nl, dl = self._cmd_meta("bot_modify", "bot_modify", "Modify guild settings.")
            self.bot.admin_group.command(name=n, description=d,
                                         name_localizations=nl, description_localizations=dl)(self.app_modify)

            n, d, nl, dl = self._cmd_meta("bot_reset", "bot_reset", "Reset and purge guild data.")
            self.bot.admin_group.command(name=n, description=d,
                                         name_localizations=nl, description_localizations=dl)(self.app_reset)
        else:
            _logger.debug("admin_group_not_attached_skipping_command_registration")

    def _validate_guild_name(self, guild_name: str) -> Tuple[bool, str]:
        """
        Validate guild name format and constraints.

        Args:
            guild_name: Guild name to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not guild_name or not NAME_RE.match(guild_name.strip()):
            return False, "Guild name contains invalid characters or length > 50"
        return True, ""

    def _validate_guild_server(self, guild_server: str) -> Tuple[bool, str]:
        """
        Validate guild server name format and constraints.

        Args:
            guild_server: Server name to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not guild_server or not SERVER_RE.match(guild_server.strip()):
            return False, "Guild server contains invalid characters or length > 50"
        return True, ""

    def _fit_nick(self, nick: str, limit: int = 32) -> str:
        """
        Fit nickname to Discord's limit, truncating with ellipsis if needed.
        
        Args:
            nick: Nickname to fit
            limit: Maximum length (default: 32 for Discord nicknames)
            
        Returns:
            Truncated nickname with ellipsis if needed
        """
        return nick if len(nick) <= limit else (nick[:limit-1] + "…")

    @discord_resilient(service_name="discord_api", max_retries=2)
    async def _safe_edit_nickname(self, guild: discord.Guild, nickname: str) -> bool:
        """
        Safely change bot nickname in guild with error handling and permission checks.

        Args:
            guild: Discord guild where to change nickname
            nickname: New nickname for the bot

        Returns:
            True if nickname was changed successfully, False otherwise
        """
        try:
            me = guild.me or await guild.fetch_member(self.bot.user.id)
            perms = guild.me.guild_permissions if guild.me else me.guild_permissions
            if not perms.manage_nicknames:
                _logger.warning("no_permission_change_nickname", guild_id=guild.id)
                return False
            await me.edit(nick=nickname)
            _logger.debug("bot_nickname_changed", guild_id=guild.id, new_nickname=nickname)
            return True
        except discord.Forbidden:
            _logger.warning("no_permission_change_nickname", guild_id=guild.id); return False
        except discord.HTTPException as e:
            _logger.error("http_error_changing_nickname", guild_id=guild.id, error=str(e), status_code=getattr(e, 'status', None)); return False
        except Exception as e:
            _logger.error("unexpected_error_changing_nickname", guild_id=guild.id, error=str(e), exc_info=True); return False

    @commands.Cog.listener()
    async def on_ready(self):
        """Handle bot ready event and sync commands."""
        async with self._sync_lock:
            if not self.bot.synced:
                try:
                    await self.bot.sync_commands()
                    self.bot.synced = True
                    _logger.info(
                        "slash_commands_synced",
                        command_count=len(self.bot.commands)
                    )
                except Exception as e:
                    _logger.error(
                        "failed_to_sync_commands",
                        error=str(e),
                        exc_info=True
                    )
        _logger.info(
            "bot_connected",
            bot_name=str(self.bot.user),
            bot_id=self.bot.user.id if self.bot.user else None
        )

        if hasattr(self.bot, "cache_loader"):
            asyncio.create_task(self.bot.cache_loader.wait_for_initial_load())
            _logger.debug("waiting_for_initial_cache_load")
        else:
            _logger.debug("no_cache_loader_attached")

    @commands.Cog.listener()
    async def on_app_command_error(
        self, ctx: discord.ApplicationContext, error: Exception
    ):
        """
        Handle global application command errors.

        Args:
            ctx: Discord application context
            error: Exception that occurred during command execution
        """

        _logger.error(
            "cog_error_handler_triggered",
            error_type=type(error).__name__,
            error=str(error),
            guild_id=ctx.guild.id if ctx.guild else None,
            command=ctx.command.name if hasattr(ctx, 'command') and ctx.command else None,
            exc_info=True
        )

        response = await get_user_message(
            ctx, global_translations.get("global", {}), "errors.unknown", error=error
        )
        try:
            if ctx.response.is_done():
                await ctx.followup.send(response, ephemeral=True)
            else:
                await ctx.respond(response, ephemeral=True)
        except Exception as e:
            _logger.error(
                "failed_to_send_error_message",
                send_error=str(e),
                original_error=str(error),
                exc_info=True
            )

    @admin_rate_limit(cooldown_seconds=60)
    async def app_initialize(
        self,
        ctx: discord.ApplicationContext,
        guild_name: str = discord.Option(
            description=global_translations.get("global", {})
            .get("common_options", {})
            .get("guild_name", {})
            .get("description", {})
            .get("en-US", "Guild name"),
            description_localizations=global_translations.get("global", {})
            .get("common_options", {})
            .get("guild_name", {})
            .get("description", {}),
        ),
        guild_lang: str = discord.Option(
            description=global_translations.get("global", {})
            .get("common_options", {})
            .get("guild_lang", {})
            .get("description", {})
            .get("en-US", "Language"),
            description_localizations=global_translations.get("global", {})
            .get("common_options", {})
            .get("guild_lang", {})
            .get("description", {}),
            choices=["en-US", "fr", "es-ES", "de", "it"],
        ),
        guild_game: int = discord.Option(
            description=global_translations.get("global", {})
            .get("common_options", {})
            .get("guild_game", {})
            .get("description", {})
            .get("en-US", "Game"),
            description_localizations=global_translations.get("global", {})
            .get("common_options", {})
            .get("guild_game", {})
            .get("description", {}),
            choices=[
                discord.OptionChoice(
                    name=(cdata.get("name") or {}).get("en-US", cname),
                    value=str(cdata["value"])
                )
                for cname, cdata in GUILD_GAME_CHOICES_CFG.items()
                if isinstance(cdata, dict) and "value" in cdata
            ],
        ),
        guild_server: str = discord.Option(
            description=global_translations.get("global", {})
            .get("common_options", {})
            .get("guild_server", {})
            .get("description", {})
            .get("en-US", "Server"),
            description_localizations=global_translations.get("global", {})
            .get("common_options", {})
            .get("guild_server", {})
            .get("description", {}),
        ),
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
        await ctx.defer(ephemeral=True)

        _logger.info(
            "app_initialize_started",
            guild_id=ctx.guild.id,
            guild_name=guild_name,
            guild_lang=guild_lang,
            guild_game=guild_game,
            guild_server=guild_server
        )

        try:
            _logger.debug(
                "validating_guild_name",
                guild_name=guild_name
            )
            valid_name, name_error = self._validate_guild_name(guild_name)
            _logger.debug(
                "guild_name_validation_result",
                valid=valid_name,
                error=name_error if name_error else None
            )
        except Exception as e:
            _logger.error(
                "critical_error_validating_guild_name",
                error=str(e),
                exc_info=True
            )
            raise
        if not valid_name:
            return await ctx.followup.send(f"Invalid guild name: {name_error}", ephemeral=True)

        valid_server, server_error = self._validate_guild_server(guild_server)
        if not valid_server:
            return await ctx.followup.send(f"Invalid guild server: {server_error}", ephemeral=True)

        guild_id = ctx.guild.id

        exists = await self.bot.run_db_query(
            "SELECT 1 FROM guild_settings WHERE guild_id = %s",
            (guild_id,), fetch_one=True
        )
        if exists:
            _logger.info("guild_already_exists", guild_id=guild_id)
            response = await get_user_message(ctx, ADMIN_COMMANDS.get("bot_initialize", {}), "messages.already_declared")
            return await ctx.followup.send(response, ephemeral=True)

        try:
            insert_query = """
                INSERT INTO guild_settings 
                (guild_id, guild_name, guild_lang, guild_game, guild_server, initialized, premium)
                VALUES (%s, %s, %s, %s, %s, TRUE, 0)
            """
            await self.bot.run_db_query(
                insert_query,
                (
                    guild_id,
                    guild_name.strip(),
                    guild_lang,
                    guild_game,
                    guild_server.strip(),
                ),
                commit=True,
            )
            _logger.info(
                "guild_initialized_in_database",
                guild_id=guild_id
            )

            try:
                await self.bot.cache.set_guild_data(
                    guild_id, "guild_name", guild_name.strip()
                )
                await self.bot.cache.set_guild_data(
                    guild_id, "guild_lang", guild_lang
                )
                await self.bot.cache.set_guild_data(
                    guild_id, "guild_game", guild_game
                )
                await self.bot.cache.set_guild_data(
                    guild_id, "guild_server", guild_server.strip()
                )
                await self.bot.cache.set_guild_data(guild_id, "premium", 0)

                await self.bot.cache.set_guild_data(
                    guild_id,
                    "settings",
                    {
                        "guild_name": guild_name.strip(),
                        "guild_lang": guild_lang,
                        "guild_game": guild_game,
                        "guild_server": guild_server.strip(),
                        "premium": 0,
                    },
                )

                _logger.debug(
                    "global_cache_updated",
                    guild_id=guild_id
                )

                await self.bot.cache.invalidate_configured_guilds_cache()
            except Exception as cache_error:
                _logger.error(
                    "error_updating_global_cache",
                    guild_id=guild_id,
                    error=str(cache_error),
                    exc_info=True
                )

            rename_templates = (getattr(self.bot, "translations", None) or global_translations)\
                .get("global", {})\
                .get("rename_templates", {})
            template = rename_templates.get(
                guild_lang,
                rename_templates.get("en-US", "{guild_name} - Management"),
            )
            new_nickname = self._fit_nick(template.format(guild_name=guild_name.strip()))
            nickname_success = await self._safe_edit_nickname(
                ctx.guild, new_nickname
            )

            if not nickname_success:
                _logger.warning(
                    "nickname_change_failed_but_init_succeeded",
                    guild_id=guild_id,
                    nickname=new_nickname
                )

            response = await get_user_message(
                ctx, ADMIN_COMMANDS.get("bot_initialize", {}), "messages.success"
            )

        except Exception as e:
            _logger.error(
                "error_during_guild_initialization",
                guild_id=guild_id,
                error=str(e),
                exc_info=True
            )
            response = await get_user_message(
                ctx,
                ADMIN_COMMANDS.get("bot_initialize", {}),
                "messages.error",
                error="Database error",
            )
        await ctx.followup.send(response, ephemeral=True)

    @admin_rate_limit(cooldown_seconds=60)
    async def app_modify(
        self,
        ctx: discord.ApplicationContext,
        guild_name: str = discord.Option(
            default=None,
            description=global_translations.get("global", {})
            .get("common_options", {})
            .get("guild_name", {})
            .get("description", {})
            .get("en-US", "Guild name"),
            description_localizations=global_translations.get("global", {})
            .get("common_options", {})
            .get("guild_name", {})
            .get("description", {}),
        ),
        guild_lang: str = discord.Option(
            default=None,
            description=global_translations.get("global", {})
            .get("common_options", {})
            .get("guild_lang", {})
            .get("description", {})
            .get("en-US", "Language"),
            description_localizations=global_translations.get("global", {})
            .get("common_options", {})
            .get("guild_lang", {})
            .get("description", {}),
            choices=["en-US", "fr", "es-ES", "de", "it"],
        ),
        guild_game: int = discord.Option(
            default=None,
            description=global_translations.get("global", {})
            .get("common_options", {})
            .get("guild_game", {})
            .get("description", {})
            .get("en-US", "Game"),
            description_localizations=global_translations.get("global", {})
            .get("common_options", {})
            .get("guild_game", {})
            .get("description", {}),
            choices=[
                discord.OptionChoice(
                    name=(cdata.get("name") or {}).get("en-US", cname),
                    value=str(cdata["value"])
                )
                for cname, cdata in GUILD_GAME_CHOICES_CFG.items()
                if isinstance(cdata, dict) and "value" in cdata
            ],
        ),
        guild_server: str = discord.Option(
            default=None,
            description=global_translations.get("global", {})
            .get("common_options", {})
            .get("guild_server", {})
            .get("description", {})
            .get("en-US", "Server"),
            description_localizations=global_translations.get("global", {})
            .get("common_options", {})
            .get("guild_server", {})
            .get("description", {}),
        ),
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
        await ctx.defer(ephemeral=True)
        
        if guild_name is not None:
            valid_name, name_error = self._validate_guild_name(guild_name)
            if not valid_name:
                return await ctx.followup.send(f"Invalid guild name: {name_error}", ephemeral=True)

        if guild_server is not None:
            valid_server, server_error = self._validate_guild_server(guild_server)
            if not valid_server:
                return await ctx.followup.send(
                    f"Invalid guild server: {server_error}", ephemeral=True
                )

        guild_id = ctx.guild.id

        try:
            current_guild_name = await self.bot.cache.get_guild_data(
                guild_id, "guild_name"
            )
            current_guild_lang = await self.bot.cache.get_guild_data(
                guild_id, "guild_lang"
            )
            current_guild_game = await self.bot.cache.get_guild_data(
                guild_id, "guild_game"
            )
            current_guild_server = await self.bot.cache.get_guild_data(
                guild_id, "guild_server"
            )

            if not current_guild_lang:
                response = await get_user_message(
                    ctx, ADMIN_COMMANDS.get("bot_modify", {}), "messages.need_init"
                )
                return await ctx.followup.send(response, ephemeral=True)

            new_guild_name = (
                guild_name.strip() if guild_name is not None else current_guild_name
            )
            new_guild_lang = (
                guild_lang if guild_lang is not None else current_guild_lang
            )
            new_guild_game = (
                guild_game if guild_game is not None else current_guild_game
            )
            new_guild_server = (
                guild_server.strip()
                if guild_server is not None
                else current_guild_server
            )

            update_query = """
                UPDATE guild_settings
                SET guild_name = %s, guild_lang = %s, guild_game = %s, guild_server = %s
                WHERE guild_id = %s
            """
            await self.bot.run_db_query(
                update_query,
                (
                    new_guild_name,
                    new_guild_lang,
                    new_guild_game,
                    new_guild_server,
                    guild_id,
                ),
                commit=True,
            )
            _logger.info(
                "guild_modified_in_database",
                guild_id=guild_id,
                changes={
                    "name": new_guild_name if guild_name else None,
                    "lang": new_guild_lang if guild_lang else None, 
                    "game": new_guild_game if guild_game else None,
                    "server": new_guild_server if guild_server else None
                }
            )

            try:
                await self.bot.cache.set_guild_data(
                    guild_id, "guild_name", new_guild_name
                )
                await self.bot.cache.set_guild_data(
                    guild_id, "guild_lang", new_guild_lang
                )
                await self.bot.cache.set_guild_data(
                    guild_id, "guild_game", new_guild_game
                )
                await self.bot.cache.set_guild_data(
                    guild_id, "guild_server", new_guild_server
                )

                await self.bot.cache.set_guild_data(
                    guild_id,
                    "settings",
                    {
                        "guild_name": new_guild_name,
                        "guild_lang": new_guild_lang,
                        "guild_game": new_guild_game,
                        "guild_server": new_guild_server,
                    },
                )

                _logger.debug(
                    "global_cache_updated_after_modification",
                    guild_id=guild_id
                )
            except Exception as cache_error:
                _logger.error(
                    "error_updating_cache_after_modification",
                    guild_id=guild_id,
                    error=str(cache_error),
                    exc_info=True
                )

            rename_templates = (getattr(self.bot, "translations", None) or global_translations)\
                .get("global", {})\
                .get("rename_templates", {})
            template = rename_templates.get(
                new_guild_lang,
                rename_templates.get("en-US", "{guild_name} - Management"),
            )
            new_nickname = self._fit_nick(template.format(guild_name=new_guild_name))
            nickname_success = await self._safe_edit_nickname(ctx.guild, new_nickname)

            if not nickname_success:
                _logger.warning(
                    "nickname_change_failed_after_modification",
                    guild_id=guild_id,
                    nickname=new_nickname
                )

            response = await get_user_message(
                ctx, ADMIN_COMMANDS.get("bot_modify", {}), "messages.success"
            )

        except Exception as e:
            _logger.error(
                "error_during_guild_modification",
                guild_id=guild_id,
                error=str(e),
                exc_info=True
            )
            response = await get_user_message(
                ctx,
                ADMIN_COMMANDS.get("bot_modify", {}),
                "messages.error",
                error="Database error",
            )
        await ctx.followup.send(response, ephemeral=True)

    @admin_rate_limit(cooldown_seconds=60)
    async def app_reset(
        self,
        ctx: discord.ApplicationContext,
        confirmation: str = discord.Option(
            description=(RESET_CONFIRMATION_META.get("description") or {}).get("en-US", "Type DELETE to confirm"),
            description_localizations=RESET_CONFIRMATION_META.get("description") or {},
            choices=["DELETE"]
        ),
    ):
        """
        Reset guild configuration and delete all associated data.

        Args:
            ctx: Discord application context
            confirmation: Confirmation string to validate reset intention
        """
        await ctx.defer(ephemeral=True)
        
        guild_id = ctx.guild.id

        try:
            existing_settings = await self.bot.cache.get_guild_data(
                guild_id, "guild_lang"
            )

            if not existing_settings:
                response = await get_user_message(
                    ctx, ADMIN_COMMANDS.get("bot_reset", {}), "messages.need_init"
                )
                return await ctx.followup.send(response, ephemeral=True)

            success = await self._delete_guild_data_atomic(guild_id)

            if success:
                try:
                    await self.bot.cache.delete("guild_data", guild_id, "guild_name")
                    await self.bot.cache.delete("guild_data", guild_id, "guild_lang")
                    await self.bot.cache.delete("guild_data", guild_id, "guild_game")
                    await self.bot.cache.delete("guild_data", guild_id, "guild_server")
                    await self.bot.cache.delete("guild_data", guild_id, "premium")
                    await self.bot.cache.delete("guild_data", guild_id, "settings")
                    await self.bot.cache.delete("guild_data", guild_id, "roles")
                    await self.bot.cache.delete("guild_data", guild_id, "channels")
                    await self.bot.cache.delete(
                        "guild_data", guild_id, "absence_channels"
                    )
                    await self.bot.cache.delete("guild_data", guild_id, "rules_message")
                    await self.bot.cache.delete(
                        "guild_data", guild_id, "events_channel"
                    )

                    _logger.debug(
                        "global_cache_cleared",
                        guild_id=guild_id
                    )
                except Exception as cache_error:
                    _logger.error(
                        "error_clearing_global_cache",
                        guild_id=guild_id,
                        error=str(cache_error),
                        exc_info=True
                    )

                await self._safe_edit_nickname(ctx.guild, "My Guild Manager")

                _logger.info(
                    "guild_data_deleted",
                    guild_id=guild_id
                )
                response = await get_user_message(
                    ctx, ADMIN_COMMANDS.get("bot_reset", {}), "messages.success"
                )
            else:
                response = await get_user_message(
                    ctx,
                    ADMIN_COMMANDS.get("bot_reset", {}),
                    "messages.error",
                    error="Database deletion failed",
                )

        except Exception as e:
            _logger.error(
                "error_during_guild_reset",
                guild_id=guild_id,
                error=str(e),
                exc_info=True
            )
            response = await get_user_message(
                ctx,
                ADMIN_COMMANDS.get("bot_reset", {}),
                "messages.error",
                error="Database error",
            )
        await ctx.followup.send(response, ephemeral=True)

    async def _delete_guild_data_atomic(self, guild_id: int) -> bool:
        """
        Atomically delete all guild data from database using a real transaction.

        Args:
            guild_id: Discord guild ID

        Returns:
            True if deletion succeeded, False otherwise
        """
        _logger.debug("deletion_function_entry", guild_id=guild_id, guild_id_type=type(guild_id).__name__)
        
        try:
            guild_id = int(guild_id)
            _logger.debug("deletion_starting", guild_id=guild_id, guild_id_type=type(guild_id).__name__)
            
            ptb_guild_query = "SELECT guild_id FROM guild_settings WHERE guild_ptb = %s"
            ptb_result = await self.bot.run_db_query(ptb_guild_query, (guild_id,), fetch_all=True)
            
            ptb_guilds_to_clear_cache = []
            ptb_cleanup_queries = []
            
            if ptb_result:
                for row in ptb_result:
                    main_guild_id = row[0]
                    _logger.info(
                        "clearing_ptb_reference",
                        main_guild_id=main_guild_id,
                        ptb_guild_id=guild_id
                    )
                    ptb_cleanup_queries.append((
                        "UPDATE guild_settings SET guild_ptb = NULL WHERE guild_id = %s",
                        (main_guild_id,)
                    ))
                    ptb_guilds_to_clear_cache.append(main_guild_id)

            delete_queries = [
                ("DELETE FROM welcome_messages WHERE guild_id = %s", (guild_id,)),
                ("DELETE FROM absence_messages WHERE guild_id = %s", (guild_id,)),
                ("DELETE FROM contracts WHERE guild_id = %s", (guild_id,)),
                ("DELETE FROM events_data WHERE guild_id = %s", (guild_id,)),
                ("DELETE FROM user_setup WHERE guild_id = %s", (guild_id,)),
                ("DELETE FROM guild_members WHERE guild_id = %s", (guild_id,)),
                (
                    "DELETE FROM guild_static_members WHERE group_id IN (SELECT id FROM guild_static_groups WHERE guild_id = %s)",
                    (guild_id,),
                ),
                ("DELETE FROM guild_static_groups WHERE guild_id = %s", (guild_id,)),
                (
                    "DELETE FROM pending_diplomat_validations WHERE guild_id = %s",
                    (guild_id,),
                ),
                ("DELETE FROM loot_wishlist_history WHERE guild_id = %s", (guild_id,)),
                ("DELETE FROM loot_wishlist WHERE guild_id = %s", (guild_id,)),
                ("DELETE FROM dynamic_voice_channels WHERE guild_id = %s", (guild_id,)),
                (
                    "DELETE FROM guild_ptb_settings WHERE guild_id = %s OR ptb_guild_id = %s",
                    (guild_id, guild_id),
                ),
                ("DELETE FROM guild_ideal_staff WHERE guild_id = %s", (guild_id,)),
                ("DELETE FROM guild_roles WHERE guild_id = %s", (guild_id,)),
                ("DELETE FROM guild_channels WHERE guild_id = %s", (guild_id,)),
                ("DELETE FROM guild_settings WHERE guild_id = %s", (guild_id,)),
            ]

            all_queries = ptb_cleanup_queries + delete_queries

            _logger.debug("transaction_prepared", 
                guild_id=guild_id, 
                total_queries=len(all_queries),
                sample_query=all_queries[0] if all_queries else None
            )

            success = await run_db_transaction(all_queries)
            
            if success:
                _logger.info(
                    "atomic_deletion_completed",
                    guild_id=guild_id,
                    total_queries_executed=len(all_queries)
                )

                for ptb_guild_id in ptb_guilds_to_clear_cache:
                    try:
                        await self.bot.cache.delete("guild_data", ptb_guild_id, "settings")
                        _logger.debug(
                            "ptb_cache_cleared",
                            ptb_guild_id=ptb_guild_id,
                            deleted_guild_id=guild_id
                        )
                    except Exception as cache_error:
                        _logger.warning(
                            "ptb_cache_clear_failed",
                            ptb_guild_id=ptb_guild_id,
                            deleted_guild_id=guild_id,
                            error=str(cache_error)
                        )
                
                return True
            else:
                _logger.error(
                    "atomic_deletion_failed",
                    guild_id=guild_id,
                    total_queries=len(all_queries)
                )
                return False

        except Exception as e:
            _logger.error(
                "critical_error_during_atomic_deletion",
                guild_id=guild_id,
                error=str(e),
                exc_info=True
            )
            return False

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """
        Handle bot removal from guild and cleanup data.

        Args:
            guild: Discord guild the bot was removed from
        """
        guild_id = guild.id
        _logger.info(
            "bot_removed_from_guild",
            guild_id=guild_id,
            guild_name=guild.name
        )

        success = await self._delete_guild_data_atomic(guild_id)

        if success:
            try:
                await self.bot.cache.delete("guild_data", guild_id, "guild_name")
                await self.bot.cache.delete("guild_data", guild_id, "guild_lang")
                await self.bot.cache.delete("guild_data", guild_id, "guild_game")
                await self.bot.cache.delete("guild_data", guild_id, "guild_server")
                await self.bot.cache.delete("guild_data", guild_id, "premium")
                await self.bot.cache.delete("guild_data", guild_id, "settings")
                await self.bot.cache.delete("guild_data", guild_id, "roles")
                await self.bot.cache.delete("guild_data", guild_id, "channels")
                await self.bot.cache.delete("guild_data", guild_id, "absence_channels")
                await self.bot.cache.delete("guild_data", guild_id, "rules_message")
                await self.bot.cache.delete("guild_data", guild_id, "events_channel")

                _logger.debug(
                    "cache_cleared_for_removed_guild",
                    guild_id=guild_id
                )
            except Exception as cache_error:
                _logger.error(
                    "error_clearing_cache_for_removed_guild",
                    guild_id=guild_id,
                    error=str(cache_error),
                    exc_info=True
                )

            _logger.info(
                "guild_data_successfully_deleted",
                guild_id=guild_id
            )

            await self.bot.cache.invalidate_configured_guilds_cache()
        else:
            _logger.error(
                "failed_to_delete_guild_data",
                guild_id=guild_id
            )

def setup(bot: discord.Bot) -> None:
    """
    Setup function to add the Core cog to the bot.

    Args:
        bot: Discord bot instance
    """
    bot.add_cog(Core(bot))
