"""
Absence Manager Cog - Enterprise-grade absence tracking and management.

This cog provides comprehensive absence management with:

Features:
    - Automatic role management (member ↔ absent roles)
    - Real-time message tracking with database persistence
    - Smart date parsing (ISO, relative, keywords)
    - Bulk deletion handling with role recalculation
    - Member cleanup on leave/kick
    - Notification system with embeds
    - Localized responses and templates

Enterprise Patterns:
    - Race condition protection with per-member locks
    - Discord API resilience with retry logic and 5xx handling
    - Cache ready gates for cold start protection
    - Centralized permission error handling with user feedback
    - Structured logging with ComponentLogger
    - Full localization support via JSON translation system

Usage:
    - Users post messages in configured absence channel
    - Staff can use /absence_add command for manual marking
    - Return dates support multiple formats: 2024-12-25, +3d, tomorrow
    - Automatic role restoration when messages are deleted
"""

import asyncio
import collections
from datetime import datetime, timedelta, timezone
import random
import re
from typing import Tuple, List

import discord
from discord.ext import commands

from core.logger import ComponentLogger
from core.translation import translations as global_translations
from core.reliability import discord_resilient

_logger = ComponentLogger("absence")
ABSENCE_NAMESPACE = "absence_system"
ABSENCE_TRANSLATIONS = global_translations.get(ABSENCE_NAMESPACE, {})

def _validate_translation_keys():
    """Validate required translation keys at module load time."""
    required_keys = [
        "messages.title",
        "messages.member_label",
        "messages.status_label", 
        "messages.absent",
        "messages.returned",
        "messages.away_ok",
        "messages.back_time",
        "messages.error_chan",
        "messages.absence_ok",
        "errors.permission_insufficient",
        "errors.permission_staff_feedback", 
        "errors.permission_user_feedback",
        "date_keywords.tomorrow",
        "date_keywords.week",
        "messages.return_date_fallback",
        "commands.absence_add.name",
        "commands.absence_add.description",
        "commands.absence_add.options.member.name",
        "commands.absence_add.options.member.description",
        "commands.absence_add.options.return_date.name",
        "commands.absence_add.options.return_date.description",
        "forum.updates_thread_name",
        "forum.updates_thread_content"
    ]
    
    missing_keys = []
    translations = ABSENCE_TRANSLATIONS
    
    for key in required_keys:
        current = translations
        key_parts = key.split(".")
        
        try:
            for part in key_parts:
                current = current[part]
        except (KeyError, TypeError):
            missing_keys.append(key)
    
    if missing_keys:
        _logger.warning(
            "missing_translation_keys",
            namespace=ABSENCE_NAMESPACE,
            missing_keys=missing_keys
        )

_validate_translation_keys()

class AbsenceManager(commands.Cog):
    """Cog for managing member absence status and notifications."""

    def __init__(self, bot: discord.Bot) -> None:
        """
        Initialize the AbsenceManager cog.

        Args:
            bot: Discord bot instance
        """
        self.bot = bot

        self._locks: dict[tuple[int, int], asyncio.Lock] = collections.defaultdict(asyncio.Lock)
        self._locks_last_used: dict[tuple[int, int], float] = {}
        self._lock_cleanup_interval = 3600

        self._register_absence_commands()
        
    def _cleanup_old_locks(self) -> None:
        """Clean up unused locks to prevent memory leaks."""
        try:
            import time
            current_time = time.time()
            cutoff_time = current_time - self._lock_cleanup_interval
            
            keys_to_remove = [
                key for key, last_used in self._locks_last_used.items()
                if last_used < cutoff_time
            ]
            
            for key in keys_to_remove:
                if key in self._locks:
                    del self._locks[key]
                if key in self._locks_last_used:
                    del self._locks_last_used[key]
                    
            if keys_to_remove:
                _logger.debug(
                    "locks_cleanup",
                    removed_count=len(keys_to_remove),
                    remaining_count=len(self._locks)
                )
        except Exception as e:
            _logger.debug(
                "locks_cleanup_error",
                error=str(e)
            )
    
    def _get_member_lock(self, guild_id: int, member_id: int) -> asyncio.Lock:
        """Get or create a lock for a specific guild/member pair with tracking."""
        import time
        key = (guild_id, member_id)
        self._locks_last_used[key] = time.time()

        if len(self._locks_last_used) % 100 == 0:
            self._cleanup_old_locks()
            
        return self._locks[key]
    
    async def _get_or_create_forum_updates_thread(self, forum_channel: discord.ForumChannel) -> discord.Thread | None:
        """Get or create 'Updates' thread in Forum channel for notifications."""
        try:
            guild_id = forum_channel.guild.id
            guild_lang = await self.bot.cache.get_guild_data(guild_id, "guild_lang") or "en-US"

            thread_names = set()
            try:
                updates_translations = ABSENCE_TRANSLATIONS.get("forum", {}).get("updates_thread_name", {})
                for lang_code, thread_name in updates_translations.items():
                    thread_names.add(thread_name.lower())
            except Exception:
                thread_names = {"updates", "mises à jour", "actualizaciones", "aggiornamenti", "aktualisierungen"}

            for t in getattr(forum_channel, "threads", []):
                if t.name.lower() in thread_names:
                    if not t.archived:
                        return t
                    try:
                        await t.edit(archived=False)
                        return t
                    except discord.Forbidden:
                        pass

            async for t in forum_channel.archived_threads(limit=100):
                if t.name.lower() in thread_names:
                    try:
                        if t.archived:
                            await t.edit(archived=False)
                        return t
                    except discord.Forbidden:
                        pass

            try:
                thread_name = await self._get_absence_template(guild_id, "forum.updates_thread_name")
                message_content = await self._get_absence_template(guild_id, "forum.updates_thread_content")
            except Exception:
                thread_name = "Updates"
                message_content = "🔔 **Absence Notifications** | Notifications d'absence"
            
            thread = await forum_channel.create_thread(
                name=thread_name,
                content=message_content,
                reason="Automatic thread for absence notifications"
            )
            try:
                await thread.edit(pinned=True, archived=False)
            except (discord.Forbidden, discord.HTTPException):
                pass
            
            _logger.debug(
                "forum_updates_thread_created",
                forum_channel_id=forum_channel.id,
                thread_id=thread.id
            )
            
            return thread
            
        except Exception as e:
            _logger.error(
                "error_forum_updates_thread",
                forum_channel_id=forum_channel.id,
                error=str(e),
                exc_info=True
            )
            return None
    
    async def _check_role_management_permissions(self, guild: discord.Guild) -> bool:
        """Check if bot has permissions to manage roles."""
        if not guild.me.guild_permissions.manage_roles:
            await self._handle_permission_error(
                "manage_roles_permission_missing",
                guild.me,
                guild_id=guild.id
            )
            return False
        return True
        
    async def _check_channel_permissions(self, channel: discord.abc.GuildChannel, require_embed: bool = False) -> bool:
        """Check if bot has permissions to send messages and optionally embeds in channel."""
        if not hasattr(channel, 'permissions_for'):
            return True
            
        perms = channel.permissions_for(channel.guild.me)
        if isinstance(channel, discord.Thread):
            if not perms.send_messages_in_threads:
                await self._handle_permission_error(
                    "send_messages_in_threads_permission_missing",
                    channel,
                    guild_id=channel.guild.id
                )
                return False
        else:
            if not perms.send_messages:
                await self._handle_permission_error(
                    "send_messages_permission_missing",
                    channel,
                    guild_id=channel.guild.id
                )
                return False
            
        if require_embed and not perms.embed_links:
            await self._handle_permission_error(
                "embed_links_permission_missing", 
                channel,
                guild_id=channel.guild.id
            )
            return False
            
        return True

    async def _ensure_cache_ready(self, event_type: str = "unknown") -> bool:
        """
        Ensure cache is ready before processing events.
        
        Args:
            event_type: Type of event for logging context
            
        Returns:
            True if cache is ready, False if not ready
        """
        try:
            if not hasattr(self.bot, 'cache_loader'):
                return False
                
            is_ready = await self.bot.cache_loader.is_initial_load_complete()
            if not is_ready:
                _logger.debug(
                    "cache_not_ready_skipping_event",
                    event_type=event_type
                )
            return is_ready
        except Exception as e:
            _logger.error(
                "error_checking_cache_ready",
                event_type=event_type,
                error=str(e),
                exc_info=True
            )
            return False

    async def _ensure_cache_ready_command(self, ctx: discord.ApplicationContext, command_name: str) -> bool:
        """
        Ensure cache is ready for command execution with user feedback.
        
        Args:
            ctx: Discord application context
            command_name: Name of the command for logging
            
        Returns:
            True if cache is ready and command can proceed
        """
        if not await self._ensure_cache_ready(command_name):
            try:
                await ctx.respond(
                    "⏳ Bot initializing, please retry in a few seconds.",
                    ephemeral=True
                )
            except Exception as e:
                _logger.error(
                    "error_responding_cache_not_ready",
                    command_name=command_name,
                    error=str(e),
                    exc_info=True
                )
            return False
        return True

    async def _get_absence_template(self, guild_id: int, key: str, **kwargs) -> str:
        """
        Get localized absence template string with consistent fallbacks.
        
        Args:
            guild_id: Guild ID for language context
            key: Translation key to retrieve
            **kwargs: Template variables for string formatting
            
        Returns:
            Formatted localized string with fallback
        """
        guild_lang = await self.bot.cache.get_guild_data(guild_id, "guild_lang") or "en-US"
        
        current = ABSENCE_TRANSLATIONS
        key_parts = key.split(".")
        
        try:
            for part in key_parts:
                current = current[part]
            
            template = current.get(guild_lang) or current.get("en-US")
            if template and kwargs:
                return template.format(**kwargs)
            return template or f"[Missing translation: {key}]"
            
        except (KeyError, TypeError, AttributeError):
            _logger.warning(
                "translation_key_not_found",
                key=key,
                guild_lang=guild_lang,
                namespace=ABSENCE_NAMESPACE
            )
            return f"[Missing translation: {key}]"
    
    async def _handle_permission_error(
        self, 
        operation: str, 
        channel_or_member, 
        ctx_or_author=None,
        guild_id: int | None = None
    ) -> None:
        """
        Handle permission errors with appropriate logging and user feedback.
        
        Args:
            operation: Operation that failed
            channel_or_member: Discord object that caused the permission error
            ctx_or_author: Context or author to send ephemeral message to
            guild_id: Guild ID for logging context
        """
        error_msg = await self._get_absence_template(
            guild_id or 0, "errors.permission_insufficient", operation=operation
        )
        
        _logger.warning(
            "permission_error",
            operation=operation,
            target_id=getattr(channel_or_member, 'id', None),
            guild_id=guild_id or getattr(channel_or_member, 'guild_id', None)
        )
        
        if ctx_or_author:
            try:
                if hasattr(ctx_or_author, 'followup'):
                    staff_msg = await self._get_absence_template(
                        guild_id or 0, "errors.permission_staff_feedback", error=error_msg
                    )
                    await ctx_or_author.followup.send(f"❌ {staff_msg}", ephemeral=True)
                elif hasattr(ctx_or_author, 'send'):
                    try:
                        user_msg = await self._get_absence_template(
                            guild_id or 0, "errors.permission_user_feedback", error=error_msg
                        )
                        await ctx_or_author.send(f"❌ {user_msg}")
                    except discord.Forbidden:
                        pass
            except Exception as e:
                _logger.error(
                    "error_sending_permission_feedback",
                    error=str(e),
                    exc_info=True
                )

    def _parse_return_date(self, date_str: str, guild_lang: str = "en-US") -> Tuple[datetime | None, str]:
        """
        Parse return date string into datetime and relative display format.
        
        Args:
            date_str: User input date string (formats: YYYY-MM-DD, +3d, +1w, keywords)
            guild_lang: Guild language for keyword matching
            
        Returns:
            Tuple of (parsed_datetime, relative_display_string)
        """
        if not date_str:
            return None, ""
            
        date_str = date_str.strip().lower()
        now = datetime.now(timezone.utc)
        
        try:
            if re.match(r'^\d{4}-\d{2}-\d{2}(\s\d{2}:\d{2})?$', date_str):
                if ' ' in date_str:
                    parsed = datetime.strptime(date_str, '%Y-%m-%d %H:%M')
                else:
                    parsed = datetime.strptime(date_str, '%Y-%m-%d')
                    parsed = parsed.replace(hour=12)
                epoch = int(parsed.replace(tzinfo=timezone.utc).timestamp())
                return parsed, f"<t:{epoch}:R>"
            
            relative_match = re.match(r'^\+(\d+)([dwm])$', date_str)
            if relative_match:
                amount, unit = int(relative_match.group(1)), relative_match.group(2)
                if unit == 'd':
                    parsed = now + timedelta(days=amount)
                elif unit == 'w':
                    parsed = now + timedelta(weeks=amount)
                elif unit == 'm':
                    parsed = now + timedelta(days=amount * 30)
                epoch = int(parsed.replace(tzinfo=timezone.utc).timestamp())
                return parsed, f"<t:{epoch}:R>"
            
            date_keywords = self._get_date_keywords(guild_lang)
            if date_str in date_keywords.get('tomorrow', []):
                parsed = now + timedelta(days=1)
                epoch = int(parsed.replace(tzinfo=timezone.utc).timestamp())
                return parsed, f"<t:{epoch}:R>"
            elif date_str in date_keywords.get('week', []):
                parsed = now + timedelta(weeks=1)
                epoch = int(parsed.replace(tzinfo=timezone.utc).timestamp())
                return parsed, f"<t:{epoch}:R>"
                
            if re.match(r'^\d{1,2}/\d{1,2}/\d{4}$', date_str):
                parsed = datetime.strptime(date_str, '%d/%m/%Y')
                parsed = parsed.replace(hour=12)
                epoch = int(parsed.replace(tzinfo=timezone.utc).timestamp())
                return parsed, f"<t:{epoch}:R>"
                
        except (ValueError, OverflowError) as e:
            _logger.warning(
                "invalid_return_date_format",
                date_str=date_str,
                error=str(e)
            )
        
        fallback_template = ABSENCE_TRANSLATIONS.get("messages", {}).get("return_date_fallback", {}).get("en-US", "Expected return: {date}")
        try:
            return None, fallback_template.format(date=date_str)
        except (KeyError, ValueError):
            return None, f"Expected return: {date_str}"
    
    def _get_date_keywords(self, guild_lang: str) -> dict:
        """
        Get localized date keywords from translation system.
        
        Args:
            guild_lang: Guild language code
            
        Returns:
            Dictionary mapping keyword types to language-specific lists
        """
        try:
            date_keywords = ABSENCE_TRANSLATIONS.get("date_keywords", {})
            
            keywords_for_lang = {
                "tomorrow": date_keywords.get("tomorrow", {}).get(guild_lang, ["tomorrow"]),
                "week": date_keywords.get("week", {}).get(guild_lang, ["week", "+1w"])
            }
            
            if isinstance(keywords_for_lang["tomorrow"], str):
                keywords_for_lang["tomorrow"] = [keywords_for_lang["tomorrow"]]
            if isinstance(keywords_for_lang["week"], str):
                keywords_for_lang["week"] = [keywords_for_lang["week"]]
                
            if "+1w" not in keywords_for_lang["week"]:
                keywords_for_lang["week"].append("+1w")
                
            return keywords_for_lang
            
        except Exception as e:
            _logger.warning(
                "error_loading_date_keywords",
                guild_lang=guild_lang,
                error=str(e)
            )
            return {"tomorrow": ["tomorrow"], "week": ["week", "+1w"]}
    
    async def _store_absence_with_return_date(
        self, 
        guild_id: int, 
        member_id: int, 
        message_id: int,
        return_date: datetime | None = None
    ) -> None:
        """
        Store absence record with optional return date for future exploitation.
        
        Args:
            guild_id: Discord guild ID
            member_id: Discord member ID
            message_id: Discord message ID containing absence
            return_date: Parsed return date for analytics/reminders
        """
        try:
            if return_date:
                await self.bot.run_db_query(
                    """INSERT INTO absence_messages 
                       (guild_id, message_id, member_id, return_date, created_at) 
                       VALUES (%s, %s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE 
                       return_date = VALUES(return_date)""",
                    [guild_id, message_id, member_id, return_date, datetime.now(timezone.utc)],
                    commit=True
                )
            else:
                await self.bot.run_db_query(
                    """INSERT INTO absence_messages 
                       (guild_id, message_id, member_id, created_at) 
                       VALUES (%s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE 
                       member_id = VALUES(member_id)""",
                    [guild_id, message_id, member_id, datetime.now(timezone.utc)],
                    commit=True
                )
                
            _logger.debug(
                "absence_stored_with_return_date" if return_date else "absence_stored",
                guild_id=guild_id,
                member_id=member_id,
                message_id=message_id,
                has_return_date=return_date is not None
            )
            
        except Exception as e:
            _logger.error(
                "error_storing_absence_record",
                guild_id=guild_id,
                member_id=member_id,
                message_id=message_id,
                error=str(e),
                exc_info=True
            )

    def _register_absence_commands(self):
        """Register absence commands with the centralized absence group."""
        if hasattr(self.bot, "absence_group"):
            cmd_data = ABSENCE_TRANSLATIONS.get("commands", {}).get("absence_add", {})

            options = cmd_data.get("options", {})
            if options:
                member_option = options.get("member", {})
                date_option = options.get("return_date", {})

                if member_option:
                    self.absence_add = discord.option(
                        name=member_option.get("name", {}).get("en-US", "member"),
                        description=member_option.get("description", {}).get("en-US", "Member to mark as absent"),
                        name_localizations=member_option.get("name", {}),
                        description_localizations=member_option.get("description", {}),
                        parameter_name="member",
                        input_type=discord.Member
                    )(self.absence_add)
                    
                if date_option:
                    self.absence_add = discord.option(
                        name=date_option.get("name", {}).get("en-US", "return_date"),
                        description=date_option.get("description", {}).get("en-US", "Return date (formats: YYYY-MM-DD, +3d, +1w, keywords)"),
                        name_localizations=date_option.get("name", {}),
                        description_localizations=date_option.get("description", {}),
                        parameter_name="return_date",
                        input_type=str,
                        required=False
                    )(self.absence_add)
            
            self.bot.absence_group.command(
                name=cmd_data.get("name", {}).get("en-US", "absence_add"),
                description=cmd_data.get("description", {}).get("en-US", "Mark a member as absent."),
                name_localizations=cmd_data.get("name", {}),
                description_localizations=cmd_data.get("description", {}),
            )(self.absence_add)

    @commands.Cog.listener()
    async def on_ready(self):
        """Wait for centralized cache load to complete."""
        if hasattr(self.bot, "cache_loader"):
            asyncio.create_task(self.bot.cache_loader.wait_for_initial_load())
            _logger.debug("waiting_for_initial_cache_load")
        else:
            _logger.debug("no_cache_loader_attached")

    async def _get_guild_roles(
        self, guild: discord.Guild
    ) -> Tuple[discord.Role | None, discord.Role | None]:
        """
        Get member and absent roles for a guild from cache.

        Args:
            guild: Discord guild to get roles for

        Returns:
            Tuple of (member_role, absent_role) or (None, None) if not found
        """
        role_data = await self.bot.cache.get_guild_data(guild.id, "roles")
        if not role_data:
            return None, None

        role_member = guild.get_role(role_data.get("members"))
        role_absent = guild.get_role(role_data.get("absent_members"))

        if role_member is None or role_absent is None:
            _logger.warning("guild_roles_missing", guild_id=guild.id)
            return None, None
        return role_member, role_absent

    async def _manage_member_role(
        self, member: discord.Member, role: discord.Role, action: str
    ) -> bool:
        """
        Robustly manage member role with Discord API exception handling.

        Args:
            member: Discord member to modify
            role: Discord role to add or remove
            action: Either "add" or "remove"

        Returns:
            True if role management succeeded, False otherwise
        """
        max_retries = 2
        for attempt in range(max_retries):
            try:
                if action == "add":
                    await member.add_roles(role, reason="Absence system: Member marked as absent")
                else:
                    await member.remove_roles(role, reason="Absence system: Member returned from absence")
                return True
                
            except discord.Forbidden:
                await self._handle_permission_error(
                    f"{action}_role_{role.name}",
                    member,
                    guild_id=member.guild.id
                )
                return False
                
            except discord.NotFound:
                _logger.warning(
                    "discord_not_found_role_management",
                    member_id=member.id,
                    role_id=role.id,
                    action=action
                )
                return False
                
            except discord.HTTPException as e:
                if e.status >= 500 and attempt < max_retries - 1:
                    wait_time = (1.5 ** attempt) + (random.random() * 0.3)
                    await asyncio.sleep(wait_time)
                    continue
                
                _logger.error(
                    "discord_http_error_role_management",
                    member_id=member.id,
                    role_id=role.id,
                    action=action,
                    status=e.status,
                    error=str(e),
                    exc_info=True
                )
                return False
                    
            except Exception as e:
                _logger.error(
                    "unexpected_error_role_management",
                    member_id=member.id,
                    role_id=role.id,
                    action=action,
                    error=str(e),
                    exc_info=True
                )
                return False
        
        return False

    async def _get_notification_channel(self, channel_id: int) -> discord.abc.Messageable | None:
        """
        Robustly get notification channel with type verification and fallbacks.

        Args:
            channel_id: Channel ID to fetch

        Returns:
            Messageable channel or None if not accessible
        """
        max_retries = 2
        for attempt in range(max_retries):
            try:
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    channel = await self.bot.fetch_channel(channel_id)
                
                if isinstance(channel, (discord.TextChannel, discord.Thread)):
                    return channel
                elif isinstance(channel, discord.ForumChannel):
                    updates_thread = await self._get_or_create_forum_updates_thread(channel)
                    if updates_thread:
                        return updates_thread
                    else:
                        _logger.warning(
                            "forum_channel_updates_thread_failed",
                            channel_id=channel_id,
                            channel_type=type(channel).__name__
                        )
                        return None
                else:
                    _logger.warning(
                        "unsupported_channel_type_notification",
                        channel_id=channel_id,
                        channel_type=type(channel).__name__
                    )
                    return None
                    
            except discord.Forbidden:
                import types
                target = channel if 'channel' in locals() and channel else types.SimpleNamespace(id=channel_id)
                gid = getattr(getattr(target, 'guild', None), 'id', None)
                await self._handle_permission_error("access_notification_channel", target, guild_id=gid)
                return None
                
            except discord.NotFound:
                _logger.error(
                    "discord_not_found_notification_channel",
                    channel_id=channel_id
                )
                return None
                
            except discord.HTTPException as e:
                if e.status >= 500 and attempt < max_retries - 1:
                    wait_time = (1.5 ** attempt) + (random.random() * 0.3)
                    await asyncio.sleep(wait_time)
                    continue
                
                _logger.error(
                    "discord_http_error_notification_channel",
                    channel_id=channel_id,
                    status=e.status,
                    error=str(e),
                    exc_info=True
                )
                return None
        
        return None

    async def _send_absence_message(
        self, channel: discord.TextChannel, message: str
    ) -> discord.Message | None:
        """
        Robustly send absence message with retry logic for server errors.

        Args:
            channel: Discord channel to send message to
            message: Message content to send

        Returns:
            Sent Discord message or None if failed
        """
        max_retries = 2
        for attempt in range(max_retries):
            try:
                return await channel.send(message)
                
            except discord.Forbidden:
                await self._handle_permission_error(
                    "send_absence_message",
                    channel,
                    guild_id=channel.guild.id if hasattr(channel, 'guild') else None
                )
                return None
                
            except discord.HTTPException as e:
                if e.status >= 500 and attempt < max_retries - 1:
                    wait_time = (1.5 ** attempt) + (random.random() * 0.3)
                    await asyncio.sleep(wait_time)
                    continue
                    
                _logger.error(
                    "discord_http_error_send_absence_message",
                    channel_id=channel.id,
                    status=e.status,
                    error=str(e),
                    exc_info=True
                )
                return None
                    
            except Exception as e:
                _logger.error(
                    "unexpected_error_send_absence_message",
                    channel_id=channel.id,
                    error=str(e),
                    exc_info=True
                )
                return None
        
        return None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Handle absence messages posted in absence channels."""
        if not await self._ensure_cache_ready("on_message"):
            return
            
        if message.author.bot or message.webhook_id is not None:
            return
            
        guild = message.guild
        if not guild:
            return

        channels = await self.bot.cache.get_guild_data(guild.id, "absence_channels")
        if not channels or message.channel.id != channels.get("abs_channel"):
            return

        member = guild.get_member(message.author.id)
        if not member:
            return

        async with self._get_member_lock(guild.id, member.id):
            role_member, role_absent = await self._get_guild_roles(guild)
            if not role_member or role_absent is None:
                return

            if role_absent in member.roles:
                _logger.debug(
                    "member_already_absent",
                    member_id=member.id,
                    guild_id=guild.id
                )
                return

            if role_member and role_member in member.roles:
                await self._manage_member_role(member, role_member, "remove")

            success = await self._manage_member_role(member, role_absent, "add")
            if not success:
                return

            try:
                insert = """
                    INSERT INTO absence_messages (guild_id, message_id, member_id)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE created_at = NOW()
                """
                await self.bot.run_db_query(
                    insert, (guild.id, message.id, member.id), commit=True
                )
            except Exception as e:
                await self._manage_member_role(member, role_absent, "remove")
                if role_member and role_member not in member.roles:
                    await self._manage_member_role(member, role_member, "add")
                    
                _logger.error(
                    "error_saving_absence_message_rollback_applied",
                    guild_id=guild.id,
                    message_id=message.id,
                    member_id=member.id,
                    error=str(e),
                    exc_info=True
                )
                return

            cfg = await self.bot.cache.get_guild_data(guild.id, "absence_channels")
            if not cfg:
                return

            guild_lang = (
                await self.bot.cache.get_guild_data(guild.id, "guild_lang")
                or "en-US"
            )
            await self.notify_absence(
                member,
                "addition",
                cfg["forum_members_channel"],
                guild_lang,
            )

    @commands.Cog.listener()
    @discord_resilient(service_name="discord_api", max_retries=2)
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        """Handle individual message deletion and role recalculation."""
        if not await self._ensure_cache_ready("on_raw_message_delete"):
            return
            
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        cfg = await self.bot.cache.get_guild_data(payload.guild_id, "absence_channels")
        if not cfg or payload.channel_id != cfg.get("abs_channel"):
            return

        try:
            affected_member = await self.bot.run_db_query(
                "SELECT member_id FROM absence_messages WHERE guild_id = %s AND message_id = %s",
                [payload.guild_id, payload.message_id],
                fetch_one=True,
            )
        except Exception as e:
            _logger.error("error_fetching_affected_member", error=str(e), exc_info=True)
            return

        if not affected_member:
            _logger.debug("no_affected_member_single_delete")
            return

        member_id = affected_member[0]

        try:
            await self.bot.run_db_query(
                "DELETE FROM absence_messages WHERE guild_id = %s AND message_id = %s",
                [payload.guild_id, payload.message_id],
                commit=True,
            )
        except Exception as e:
            _logger.error("error_deleting_absence_record", error=str(e), exc_info=True)
            return

        member = guild.get_member(member_id)
        if not member:
            _logger.debug(
                "member_not_found_for_role_removal",
                member_id=member_id,
                guild_id=payload.guild_id,
            )
            return

        async with self._get_member_lock(guild.id, member.id):
            role_member, role_absent = await self._get_guild_roles(guild)
            if not role_member or not role_absent:
                return

            try:
                count_row = await self.bot.run_db_query(
                    "SELECT COUNT(*) FROM absence_messages WHERE guild_id = %s AND member_id = %s",
                    [guild.id, member.id],
                    fetch_one=True
                )
                remaining = count_row and count_row[0] or 0

                if remaining > 0:
                    if role_member in member.roles:
                        await self._manage_member_role(member, role_member, "remove")
                    if role_absent not in member.roles:
                        await self._manage_member_role(member, role_absent, "add")
                else:
                    if role_absent in member.roles:
                        await self._manage_member_role(member, role_absent, "remove")
                    if role_member not in member.roles:
                        success = await self._manage_member_role(member, role_member, "add")
                        if success:
                            guild_lang = (
                                await self.bot.cache.get_guild_data(guild.id, "guild_lang")
                                or "en-US"
                            )
                            await self.notify_absence(
                                member, "removal", cfg["forum_members_channel"], guild_lang
                            )
            except Exception as e:
                _logger.error(
                    "error_checking_remaining_messages",
                    member_id=member.id,
                    guild_id=guild.id,
                    error=str(e),
                    exc_info=True
                )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """
        Handle member leaving/being kicked - cleanup absence data and roles.
        
        Args:
            member: Discord member who left the guild
        """
        if not await self._ensure_cache_ready("on_member_remove"):
            return
        
        try:
            removed_count = await self.bot.run_db_query(
                "DELETE FROM absence_messages WHERE guild_id = %s AND member_id = %s",
                [member.guild.id, member.id],
                commit=True
            )
            
            if removed_count and removed_count > 0:
                _logger.info(
                    "member_absence_cleanup",
                    member_id=member.id,
                    member_name=member.name,
                    guild_id=member.guild.id,
                    removed_records=removed_count
                )
            
        except Exception as e:
            _logger.error(
                "error_member_remove_cleanup",
                member_id=member.id,
                guild_id=member.guild.id,
                error=str(e),
                exc_info=True
            )

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
        """Handle bulk message deletion (purge) and recalculate absence roles."""
        self._cleanup_old_locks()
        
        if not await self._ensure_cache_ready("on_raw_bulk_message_delete"):
            return
            
        cfg = await self.bot.cache.get_guild_data(payload.guild_id, "absence_channels")
        if not cfg or payload.channel_id != cfg.get("abs_channel"):
            return

        if not payload.message_ids:
            return

        try:
            placeholders = ",".join(["%s"] * len(payload.message_ids))
            affected_members = await self.bot.run_db_query(
                f"SELECT DISTINCT member_id FROM absence_messages "
                f"WHERE guild_id = %s AND message_id IN ({placeholders})",
                [payload.guild_id] + list(payload.message_ids),
                fetch_all=True,
            )
        except Exception as e:
            _logger.error("error_fetching_affected_members", error=str(e), exc_info=True)
            return

        if not affected_members:
            _logger.debug("no_affected_members_bulk_delete")
            return

        try:
            placeholders = ",".join(["%s"] * len(payload.message_ids))
            await self.bot.run_db_query(
                f"DELETE FROM absence_messages WHERE guild_id = %s AND message_id IN ({placeholders})",
                [payload.guild_id] + list(payload.message_ids),
                commit=True
            )
        except Exception as e:
            _logger.error("error_bulk_deleting_absence_records", error=str(e), exc_info=True)
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        role_member, role_absent = await self._get_guild_roles(guild)
        returned_members = []
        
        if role_member and role_absent:
            for (mid,) in affected_members:
                m = guild.get_member(mid)
                if not m:
                    continue
                async with self._get_member_lock(guild.id, mid):
                    try:
                        row = await self.bot.run_db_query(
                            "SELECT COUNT(*) FROM absence_messages WHERE guild_id=%s AND member_id=%s",
                            [guild.id, mid],
                            fetch_one=True
                        )
                        remaining = row and row[0] or 0
                        if remaining == 0:
                            if role_absent in m.roles:
                                await self._manage_member_role(m, role_absent, "remove")
                            if role_member not in m.roles:
                                success = await self._manage_member_role(m, role_member, "add")
                                if success:
                                    returned_members.append(m)
                        else:
                            if role_member in m.roles:
                                await self._manage_member_role(m, role_member, "remove")
                            if role_absent not in m.roles:
                                await self._manage_member_role(m, role_absent, "add")
                    except Exception as e:
                        _logger.error(
                            "error_recalculating_role_bulk",
                            member_id=mid,
                            guild_id=guild.id,
                            error=str(e),
                            exc_info=True
                        )

        if returned_members:
            cfg = await self.bot.cache.get_guild_data(payload.guild_id, "absence_channels")
            if cfg:
                guild_lang = (
                    await self.bot.cache.get_guild_data(guild.id, "guild_lang")
                    or "en-US"
                )
                await self._notify_bulk_returns(returned_members, cfg["forum_members_channel"], guild_lang)

        _logger.info(
            "bulk_absence_cleanup",
            guild_id=payload.guild_id,
            affected_members_count=len(affected_members)
        )

    async def _set_absent(
        self,
        guild: discord.Guild,
        member: discord.Member,
        channel: discord.TextChannel,
        reason_message: str,
        guild_lang: str = "en-US",
        return_date: datetime | None = None,
    ) -> None:
        """
        Set a member as absent with proper role management and database tracking.

        Args:
            guild: Discord guild where the member is located
            member: Discord member to mark as absent
            channel: Text channel to post absence message
            reason_message: Message to post in the absence channel
            guild_lang: Guild language for notifications (avoid re-fetching)
            return_date: Optional parsed return date for advanced tracking
        """
        if not await self._check_role_management_permissions(guild):
            return
        if not await self._check_channel_permissions(channel, require_embed=False):
            return
            
        role_member, role_absent = await self._get_guild_roles(guild)
        if not role_member or not role_absent:
            return

        async with self._get_member_lock(guild.id, member.id):
            if role_absent and role_member:
                if role_member in member.roles:
                    await self._manage_member_role(member, role_member, "remove")
                
                if role_absent not in member.roles:
                    success = await self._manage_member_role(member, role_absent, "add")
                    if success:
                        _logger.debug(
                            "absent_role_assigned",
                            member_name=member.name,
                            guild_id=guild.id
                        )

                        try:
                            sent = await self._send_absence_message(channel, reason_message)
                            if not sent:
                                return

                            await self._store_absence_with_return_date(
                                guild.id, member.id, sent.id, return_date
                            )

                            cfg = await self.bot.cache.get_guild_data(guild.id, "absence_channels")
                            if not cfg:
                                _logger.error("guild_config_not_found", guild_id=guild.id)
                                return
                            await self.notify_absence(
                                member, "addition", cfg["forum_members_channel"], guild_lang
                            )

                        except Exception as e:
                            await self._manage_member_role(member, role_absent, "remove")
                            if role_member not in member.roles:
                                await self._manage_member_role(member, role_member, "add")
                                
                            _logger.error(
                                "unexpected_error_set_absent_rollback_applied",
                                member_name=member.name,
                                guild_id=guild.id,
                                error=str(e),
                                exc_info=True,
                            )

    async def absence_add(
        self,
        ctx: discord.ApplicationContext,
        member: discord.Member,
        return_date: str | None = None,
    ):
        """
        Command to manually mark a member as absent.

        Args:
            ctx: Discord application context
            member: Discord member to mark as absent
            return_date: Optional return date for the absence
        """
        if not await self._ensure_cache_ready_command(ctx, "absence_add"):
            return
            
        await ctx.defer(ephemeral=True)

        guild_lang = await self.bot.cache.get_guild_data(ctx.guild_id, "guild_lang") or "en-US"
        
        cfg = await self.bot.cache.get_guild_data(ctx.guild_id, "absence_channels")
        if not cfg:
            error_msg = await self._get_absence_template(ctx.guild_id, "messages.error_chan")
            await ctx.followup.send(error_msg, ephemeral=True)
            return

        abs_chan = ctx.guild.get_channel(cfg["abs_channel"])
        if abs_chan is None:
            error_msg = await self._get_absence_template(ctx.guild_id, "messages.error_chan")
            await ctx.followup.send(error_msg, ephemeral=True)
            return
            
        if not abs_chan.permissions_for(ctx.guild.me).send_messages:
            await self._handle_permission_error(
                "send_messages_absence_channel",
                abs_chan,
                ctx_or_author=ctx,
                guild_id=ctx.guild_id
            )
            return

        parsed_date, relative_display = self._parse_return_date(return_date or "", guild_lang)
        
        reason_text = await self._get_absence_template(
            ctx.guild_id, "messages.away_ok", member=member.display_name
        )
        
        if parsed_date:
            try:
                back_txt = await self._get_absence_template(ctx.guild_id, "messages.back_time", when=relative_display)
                reason_text = f"{reason_text} {back_txt}"
            except (KeyError, ValueError):
                reason_text = f"{reason_text} {relative_display}" if relative_display else reason_text
        else:
            reason_text = f"{reason_text} {relative_display}" if relative_display else reason_text

        await self._set_absent(ctx.guild, member, abs_chan, reason_text, guild_lang, parsed_date)
        
        success_msg = await self._get_absence_template(
            ctx.guild_id, 
            "messages.absence_ok", 
            member_mention=member.mention
        )
        await ctx.followup.send(success_msg, ephemeral=True)

    async def _notify_bulk_returns(
        self, returned_members: List[discord.Member], channel_id: int, guild_lang: str
    ) -> None:
        """
        Send batch notification for multiple members returning from absence.

        Args:
            returned_members: List of members who returned from absence
            channel_id: ID of the notification channel
            guild_lang: Guild language for localized messages
        """
        if not returned_members:
            return

        channel = await self._get_notification_channel(channel_id)
        if not channel:
            return
        
        if not await self._check_channel_permissions(channel, require_embed=True):
            return

        guild = returned_members[0].guild
        title = await self._get_absence_template(guild.id, "messages.title")
        returned_text = await self._get_absence_template(guild.id, "messages.returned")

        embed = discord.Embed(
            title=f"{title} - Bulk Return",
            color=discord.Color.green(),
            description=f"**{len(returned_members)} member(s) returned from absence**"
        )

        member_chunks = [returned_members[i:i+10] for i in range(0, len(returned_members), 10)]
        
        for i, chunk in enumerate(member_chunks):
            member_list = "\n".join([f"• {member.mention} ({member.name})" for member in chunk])
            field_name = f"Returned Members ({i+1}/{len(member_chunks)})" if len(member_chunks) > 1 else "Returned Members"
            embed.add_field(name=field_name, value=member_list, inline=False)

        max_retries = 2
        for attempt in range(max_retries):
            try:
                await channel.send(embed=embed)
                _logger.debug(
                    "bulk_notification_sent",
                    returned_count=len(returned_members),
                    guild_id=guild.id
                )
                return

            except discord.Forbidden:
                await self._handle_permission_error(
                    "send_bulk_notification_embed",
                    channel,
                    guild_id=guild.id
                )
                return

            except discord.HTTPException as e:
                if e.status >= 500 and attempt < max_retries - 1:
                    wait_time = (1.5 ** attempt) + (random.random() * 0.3)
                    await asyncio.sleep(wait_time)
                    continue

                _logger.error(
                    "discord_http_error_send_bulk_notification",
                    channel_id=channel.id,
                    returned_count=len(returned_members),
                    status=e.status,
                    error=str(e),
                    exc_info=True
                )
                return

            except Exception as e:
                _logger.error(
                    "unexpected_error_send_bulk_notification",
                    channel_id=channel.id,
                    returned_count=len(returned_members),
                    error=str(e),
                    exc_info=True
                )
                return

    async def notify_absence(
        self, member: discord.Member, action: str, channel_id: int, guild_lang: str
    ) -> None:
        """
        Send absence notification to the designated forum channel.

        Args:
            member: Discord member whose absence status changed
            action: Type of action ('addition' or 'removal')
            channel_id: ID of the notification channel
            guild_lang: Guild language for localized messages
        """
        channel = await self._get_notification_channel(channel_id)
        if not channel:
            return
        
        if not await self._check_channel_permissions(channel, require_embed=True):
            return

        title = await self._get_absence_template(member.guild.id, "messages.title")
        member_label = await self._get_absence_template(member.guild.id, "messages.member_label")
        status_label = await self._get_absence_template(member.guild.id, "messages.status_label")
        absent_text = await self._get_absence_template(member.guild.id, "messages.absent")
        returned_text = await self._get_absence_template(member.guild.id, "messages.returned")

        status_text = absent_text if action == "addition" else returned_text

        embed = discord.Embed(
            title=title,
            color=(
                discord.Color.orange()
                if action == "addition"
                else discord.Color.green()
            ),
        )
        embed.add_field(
            name=member_label, value=f"{member.mention} ({member.name})", inline=True
        )
        embed.add_field(name=status_label, value=status_text, inline=True)
        
        max_retries = 2
        for attempt in range(max_retries):
            try:
                await channel.send(embed=embed)
                _logger.debug(
                    "notification_sent",
                    member_name=member.name,
                    status_text=status_text
                )
                return
                
            except discord.Forbidden:
                await self._handle_permission_error(
                    "send_notification_embed",
                    channel,
                    guild_id=member.guild.id
                )
                return
                
            except discord.HTTPException as e:
                if e.status >= 500 and attempt < max_retries - 1:
                    wait_time = (1.5 ** attempt) + (random.random() * 0.3)
                    await asyncio.sleep(wait_time)
                    continue
                    
                _logger.error(
                    "discord_http_error_send_notification",
                    channel_id=channel.id,
                    member_name=member.name,
                    status=e.status,
                    error=str(e),
                    exc_info=True
                )
                return
                
            except Exception as e:
                _logger.error(
                    "unexpected_error_send_notification",
                    channel_id=channel.id,
                    member_name=member.name,
                    error=str(e),
                    exc_info=True
                )
                return

def setup(bot: discord.Bot):
    """
    Setup function to add the AbsenceManager cog to the bot.

    Args:
        bot: Discord bot instance
    """
    bot.add_cog(AbsenceManager(bot))
