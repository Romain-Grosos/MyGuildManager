"""
Dynamic Voice Cog - Enterprise-grade temporary voice channel management.

This cog provides comprehensive dynamic voice channel functionality with:

Features:
    - Automatic temporary voice channel creation
    - Intelligent channel cleanup and lifecycle management
    - Cooldown protection to prevent spam
    - Safe channel naming with sanitization
    - Persistent channel tracking across bot restarts
    - Orphan channel cleanup at startup
    - Auto-pruning of empty channels

Enterprise Patterns:
    - Structured logging with ComponentLogger
    - Discord API resilience with retry logic
    - Permission verification before operations
    - Graceful error handling with user feedback
    - Database-backed persistence and cleanup
    - Memory management with automatic cleanup
"""

import asyncio
import re
import time
from typing import Dict, Optional, Set, Tuple, List

import discord
from discord.ext import commands

from app.core.logger import ComponentLogger
from app.core.reliability import discord_resilient
from app.core.translation import translations as global_translations

DYNAMIC_VOICE = global_translations.get("dynamic_voice", {})
COOLDOWN_SECONDS = 1  
CHANNEL_NAME_MAX_LENGTH = 100
DEFAULT_CHANNEL_NAME = "Private Channel"

_logger = ComponentLogger("dynamic_voice")

class DynamicVoice(commands.Cog):
    """Enterprise-grade cog for managing dynamic temporary voice channels."""

    def __init__(self, bot: discord.Bot) -> None:
        """
        Initialize the DynamicVoice cog with enterprise patterns.

        Args:
            bot: Discord bot instance
        """
        self.bot = bot
        self.user_cooldowns: Dict[int, float] = {}
        self.active_channels: Set[int] = set()
        
        _logger.debug("dynamic_voice_cog_initialized")

    def _check_channel_permissions(self, guild: discord.Guild, category: discord.CategoryChannel = None) -> Tuple[bool, List[str]]:
        """
        Check if bot has required permissions for channel operations.
        
        Args:
            guild: Discord guild to check permissions in
            category: Optional category to check permissions for
            
        Returns:
            Tuple of (has_permissions: bool, missing_permissions: list[str])
        """
        bot_member = guild.me
        if not bot_member:
            return False, ["Bot member not found in guild"]
        
        missing_permissions = []

        if not bot_member.guild_permissions.manage_channels:
            missing_permissions.append("manage_channels")
        if not bot_member.guild_permissions.move_members:
            missing_permissions.append("move_members")

        if category:
            category_perms = category.permissions_for(bot_member)
            if not category_perms.manage_channels:
                missing_permissions.append("manage_channels (in category)")
        
        has_permissions = len(missing_permissions) == 0
        
        if not has_permissions:
            _logger.warning("missing_permissions_for_dynamic_voice",
                guild_id=guild.id,
                missing_permissions=missing_permissions,
                category_id=category.id if category else None
            )
        
        return has_permissions, missing_permissions

    async def _verify_guild_setup(self, guild_id: int) -> bool:
        """
        Verify guild has proper dynamic voice setup and permissions.
        
        Args:
            guild_id: Discord guild ID
            
        Returns:
            True if setup is valid, False otherwise
        """
        try:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                _logger.warning("guild_not_found_for_setup_verification", guild_id=guild_id)
                return False

            monitored_channels = await self._get_monitored_channels(guild_id)
            if not monitored_channels:
                _logger.debug("no_monitored_channels_configured", guild_id=guild_id)
                return True

            all_permissions_ok = True
            for channel_id in monitored_channels:
                channel = guild.get_channel(channel_id)
                if not channel:
                    _logger.warning("monitored_channel_not_found", 
                        guild_id=guild_id, 
                        channel_id=channel_id
                    )
                    continue
                
                category = channel.category
                has_perms, missing_perms = self._check_channel_permissions(guild, category)
                
                if not has_perms:
                    _logger.error("insufficient_permissions_for_monitored_channel",
                        guild_id=guild_id,
                        channel_id=channel_id,
                        missing_permissions=missing_perms
                    )
                    all_permissions_ok = False
            
            return all_permissions_ok
            
        except Exception as e:
            _logger.error("error_verifying_guild_setup", guild_id=guild_id, error=str(e))
            return False

    async def diagnostic_permissions_check(self) -> dict:
        """
        Perform comprehensive permissions diagnostic across all guilds.
        
        Returns:
            Dictionary with permissions status for all guilds
        """
        diagnostic_results = {
            "timestamp": time.time(),
            "total_guilds": 0,
            "guilds_with_issues": 0,
            "guild_details": {}
        }
        
        try:
            for guild in self.bot.guilds:
                diagnostic_results["total_guilds"] += 1
                guild_id = guild.id

                monitored_channels = await self._get_monitored_channels(guild_id)
                
                guild_status = {
                    "guild_name": guild.name,
                    "monitored_channels_count": len(monitored_channels),
                    "has_permissions_issues": False,
                    "missing_permissions": [],
                    "channels_blocked": 0,
                    "channels_with_warnings": 0,
                    "monitored_channels_details": []
                }
                
                if monitored_channels:
                    for channel_id in monitored_channels:
                        channel = guild.get_channel(channel_id)
                        if not channel:
                            continue
                        
                        has_perms, missing_perms = self._check_channel_permissions(guild, channel.category)

                        missing_blocking = [p for p in missing_perms if "manage_channels" in p]
                        missing_non_blocking = [p for p in missing_perms if "manage_channels" not in p]
                        
                        channel_detail = {
                            "channel_id": channel_id,
                            "channel_name": channel.name,
                            "category_name": channel.category.name if channel.category else "No Category",
                            "has_permissions": has_perms,
                            "missing_permissions": missing_perms,
                            "missing_blocking": missing_blocking,
                            "missing_non_blocking": missing_non_blocking,
                            "functionality_blocked": len(missing_blocking) > 0
                        }
                        
                        guild_status["monitored_channels_details"].append(channel_detail)

                        if missing_blocking:
                            guild_status["channels_blocked"] += 1
                            guild_status["has_permissions_issues"] = True
                            guild_status["missing_permissions"].extend(missing_blocking)
                        elif missing_non_blocking:
                            guild_status["channels_with_warnings"] += 1
                
                if guild_status["has_permissions_issues"]:
                    diagnostic_results["guilds_with_issues"] += 1
                
                diagnostic_results["guild_details"][guild_id] = guild_status
                
            _logger.info("permissions_diagnostic_completed",
                total_guilds=diagnostic_results["total_guilds"],
                guilds_with_issues=diagnostic_results["guilds_with_issues"]
            )
            
        except Exception as e:
            _logger.error("permissions_diagnostic_failed", error=str(e))
        
        return diagnostic_results

    def sanitize_channel_name(self, name: str) -> str:
        """
        Sanitize channel name by removing invalid characters with enterprise validation.

        Args:
            name: Raw channel name to sanitize

        Returns:
            Sanitized channel name safe for Discord
        """
        if not name or not isinstance(name, str):
            _logger.debug("invalid_channel_name_input", name=repr(name))
            return DEFAULT_CHANNEL_NAME

        sanitized = re.sub(r"[^\w\s\-_]", "", name)[:CHANNEL_NAME_MAX_LENGTH]
        
        if not sanitized.strip():
            _logger.debug("empty_channel_name_after_sanitization", original=name)
            return DEFAULT_CHANNEL_NAME
            
        result = sanitized.strip()
        _logger.debug("channel_name_sanitized", original=name, sanitized=result)
        return result

    def get_safe_username(self, member: discord.Member) -> str:
        """
        Get safe username for logging purposes with enhanced safety.

        Args:
            member: Discord member object

        Returns:
            Safe username string for logging
        """
        if not member:
            return "UnknownUser"
            
        try:
            if hasattr(member, 'global_name') and member.global_name:
                return f"{member.global_name}#{member.discriminator or '0000'}"
            elif hasattr(member, 'display_name') and member.display_name:
                return f"{member.display_name}#{member.discriminator or '0000'}"
            else:
                return f"User#{member.id}"
        except Exception:
            return f"User#{member.id}"

    def is_user_on_cooldown(self, user_id: int) -> bool:
        """
        Check if user is on cooldown for voice channel operations.

        Args:
            user_id: Discord user ID

        Returns:
            True if user is on cooldown, False otherwise
        """
        current_time = time.time()
        last_action = self.user_cooldowns.get(user_id, 0)
        
        if current_time - last_action < COOLDOWN_SECONDS:
            remaining = COOLDOWN_SECONDS - (current_time - last_action)
            _logger.debug("user_on_cooldown", user_id=user_id, remaining_seconds=round(remaining, 2))
            return True
            
        return False

    def update_user_cooldown(self, user_id: int) -> None:
        """
        Update user cooldown timestamp.

        Args:
            user_id: Discord user ID
        """
        self.user_cooldowns[user_id] = time.time()
        _logger.debug("user_cooldown_updated", user_id=user_id)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Initialize dynamic voice data on bot ready with enterprise patterns."""
        try:
            if hasattr(self.bot, 'cache_loader'):
                asyncio.create_task(self.bot.cache_loader.wait_for_initial_load())
                _logger.debug("waiting_for_initial_cache_load")
            else:
                _logger.debug("no_cache_loader_attached")

            asyncio.create_task(self.load_persistent_channels())
            asyncio.create_task(self.sweep_orphan_channels(delay=5))
            _logger.info("dynamic_voice_initialization_started")
            
        except Exception as e:
            _logger.error(
                "dynamic_voice_initialization_failed",
                error=str(e),
                exc_info=True
            )

    async def load_persistent_channels(self) -> None:
        """
        Load persistent dynamic channels from database into cache with enterprise error handling.

        Retrieves all existing dynamic voice channels from database and stores
        them in cache for tracking and cleanup purposes.
        """
        _logger.debug("loading_persistent_channels_from_db")
        
        try:
            query = "SELECT channel_id FROM dynamic_voice_channels"
            rows = await self.bot.run_db_query(query, fetch_all=True)
            
            if not rows:
                _logger.info("no_persistent_channels_found")
                await self.bot.cache.set("temporary", [], "dynamic_voice_channels")
                return

            dynamic_channels = set()
            for row in rows:
                if row and len(row) > 0:
                    channel_id = row[0]
                    if isinstance(channel_id, int) and channel_id > 0:
                        dynamic_channels.add(channel_id)
                        self.active_channels.add(channel_id)
                        
            await self.bot.cache.set("temporary", list(dynamic_channels), "dynamic_voice_channels")
            
            _logger.info(
                "persistent_channels_loaded_successfully",
                channel_count=len(dynamic_channels),
                channels=list(dynamic_channels)
            )
            
        except Exception as e:
            _logger.error(
                "failed_to_load_persistent_channels",
                error=str(e),
                exc_info=True
            )
            await self.bot.cache.set("temporary", [], "dynamic_voice_channels")

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """
        Handle voice state updates for dynamic channel creation and cleanup.

        Args:
            member: Discord member whose voice state changed
            before: Previous voice state
            after: New voice state
        """
        try:
            if not member or not member.guild:
                _logger.warning("invalid_voice_update_member")
                return
                
            guild = member.guild
            safe_name = self.get_safe_username(member)
            
            _logger.debug(
                "voice_state_update_received",
                user=safe_name,
                guild_id=guild.id,
                before_channel=before.channel.id if before.channel else None,
                after_channel=after.channel.id if after.channel else None
            )

            await self._cleanup_expired_cooldowns()

            monitored_channels = await self._get_monitored_channels(guild.id)
            if not monitored_channels:
                _logger.debug("no_monitored_channels", guild_id=guild.id)
                return

            if after.channel and after.channel.id in monitored_channels:
                await self._handle_channel_join(member, after.channel)

            if before.channel:
                await self._handle_channel_leave(member, before.channel, guild)
                
        except Exception as e:
            _logger.error(
                "voice_state_update_error",
                user=safe_name if 'safe_name' in locals() else "unknown",
                guild_id=member.guild.id if member and member.guild else None,
                error=str(e),
                exc_info=True
            )

    async def _cleanup_expired_cooldowns(self) -> None:
        """Periodically cleanup expired user cooldowns to prevent memory leaks."""
        current_time = time.time()
        if not hasattr(self, '_last_cleanup') or current_time - self._last_cleanup > 3600:
            self._last_cleanup = current_time
            expired_users = [
                user_id for user_id, timestamp in self.user_cooldowns.items()
                if current_time - timestamp > 3600
            ]
            for user_id in expired_users:
                del self.user_cooldowns[user_id]
            
            if expired_users:
                _logger.debug("expired_cooldowns_cleaned", count=len(expired_users))

    async def _get_monitored_channels(self, guild_id: int) -> Set[int]:
        """
        Get monitored channels for dynamic voice creation in a guild.
        
        Args:
            guild_id: Discord guild ID
            
        Returns:
            Set of channel IDs that are monitored for dynamic voice creation
        """
        try:
            channels_data = await self.bot.cache.get_guild_data(guild_id, "channels")
            if not channels_data:
                return set()
                
            create_room_channel = channels_data.get("create_room_channel")
            if not create_room_channel:
                return set()

            try:
                create_room_channel = int(create_room_channel)
            except (TypeError, ValueError):
                _logger.warning("invalid_create_room_channel_id", 
                    guild_id=guild_id, 
                    value=repr(create_room_channel),
                    recommendation="Check channel configuration"
                )
                return set()
                
            monitored_channels = {create_room_channel}
            _logger.debug("monitored_channels_retrieved", guild_id=guild_id, channels=list(monitored_channels))
            return monitored_channels
            
        except Exception as e:
            _logger.error("failed_to_get_monitored_channels", guild_id=guild_id, error=str(e))
            return set()

    async def _handle_channel_join(self, member: discord.Member, channel: discord.VoiceChannel) -> None:
        """
        Handle user joining a monitored channel - create temporary voice channel.
        
        Args:
            member: Discord member who joined
            channel: Voice channel that was joined
        """
        safe_name = self.get_safe_username(member)
        guild = member.guild
        
        _logger.debug(
            "user_joined_monitored_channel", 
            user=safe_name,
            guild_id=guild.id,
            channel_id=channel.id
        )

        has_perms, missing_perms = self._check_channel_permissions(guild, channel.category)
        missing_blocking = [p for p in missing_perms if "manage_channels" in p]
        if missing_blocking:
            _logger.warning("channel_creation_blocked_insufficient_permissions",
                user=safe_name,
                guild_id=guild.id,
                missing_permissions=missing_blocking,
                recommendation="Grant bot manage_channels permission"
            )
            return

        if missing_perms and not missing_blocking:
            _logger.info("channel_creation_missing_non_critical_permissions",
                user=safe_name,
                guild_id=guild.id,
                missing_permissions=missing_perms,
                note="Creation will proceed but some features may be limited"
            )

        if self.is_user_on_cooldown(member.id):
            _logger.debug("user_channel_creation_blocked_cooldown", user=safe_name)
            return

        await self._create_temporary_channel(member, channel)

    @discord_resilient(service_name="discord_api", max_retries=3)
    async def _create_temporary_channel(self, member: discord.Member, parent_channel: discord.VoiceChannel) -> Optional[discord.VoiceChannel]:
        """
        Create a temporary voice channel for the user with resilience.
        
        Args:
            member: Discord member requesting the channel
            parent_channel: Parent channel used as template
            
        Returns:
            Created voice channel or None on failure
        """
        try:
            guild = member.guild
            safe_name = self.get_safe_username(member)

            self.update_user_cooldown(member.id)

            guild_locale = await self.bot.cache.get_guild_data(guild.id, "guild_lang") or "en-US"
            channel_name_template = DYNAMIC_VOICE.get("channel_name", {}).get(guild_locale, "Channel of {username}")
            channel_name = self.sanitize_channel_name(channel_name_template.format(username=member.display_name))

            category = parent_channel.category
            if not category:
                _logger.warning("parent_channel_no_category",
                    user=safe_name,
                    guild_id=guild.id,
                    parent_channel_id=parent_channel.id,
                    parent_channel_name=parent_channel.name,
                    warning="Cannot create temporary channel without category - permissions may differ"
                )
                return None
            
            temp_channel = await guild.create_voice_channel(
                name=channel_name,
                category=category,
                reason=f"Dynamic voice channel created for {safe_name}"
            )
            
            if not guild.me.guild_permissions.move_members:
                _logger.warning("cannot_move_member_insufficient_permissions",
                    user=safe_name,
                    channel_id=temp_channel.id,
                    guild_id=guild.id,
                    warning="Channel created but user cannot be moved automatically"
                )
            else:
                try:
                    await member.move_to(temp_channel, reason="Moving to created dynamic channel")
                except discord.HTTPException as e:
                    _logger.warning("failed_to_move_member_after_creation",
                        user=safe_name,
                        guild_id=guild.id, 
                        channel_id=temp_channel.id, 
                        error=str(e),
                        note="Channel created successfully but move failed"
                    )

            self.active_channels.add(temp_channel.id)

            await self._store_channel_in_database(temp_channel.id, guild.id)

            asyncio.create_task(self._auto_prune_if_empty(temp_channel, guild))
            
            _logger.info(
                "temporary_channel_created_successfully",
                user=safe_name,
                guild_id=guild.id,
                channel_id=temp_channel.id,
                channel_name=channel_name
            )
            
            return temp_channel
            
        except discord.Forbidden:
            _logger.warning("insufficient_permissions_create_channel", guild_id=guild.id)
        except discord.HTTPException as e:
            _logger.error("discord_http_error_creating_channel", error=str(e), status_code=getattr(e, 'status', None))
        except Exception as e:
            _logger.error("unexpected_error_creating_channel", error=str(e), exc_info=True)
        
        return None

    async def _handle_channel_leave(self, member: discord.Member, channel: discord.VoiceChannel, guild: discord.Guild) -> None:
        """
        Handle user leaving a voice channel - cleanup if empty dynamic channel.
        
        Args:
            member: Discord member who left
            channel: Voice channel that was left  
            guild: Discord guild
        """
        if channel.id not in self.active_channels:
            return
            
        safe_name = self.get_safe_username(member)
        _logger.debug("user_left_dynamic_channel", user=safe_name, channel_id=channel.id)

        if len(channel.members) == 0:
            await self._cleanup_empty_channel(channel, guild)

    @discord_resilient(service_name="discord_api", max_retries=2)
    async def _cleanup_empty_channel(self, channel: discord.VoiceChannel, guild: discord.Guild) -> None:
        """
        Cleanup empty dynamic voice channel with resilience.
        
        Args:
            channel: Empty voice channel to cleanup
            guild: Discord guild
        """
        try:
            channel_id = channel.id

            has_perms, missing_perms = self._check_channel_permissions(guild, channel.category)
            missing_blocking = [p for p in missing_perms if "manage_channels" in p]
            if missing_blocking:
                _logger.error("channel_cleanup_blocked_insufficient_permissions",
                    channel_id=channel_id,
                    guild_id=guild.id,
                    missing_permissions=missing_blocking,
                    warning="Channel will remain orphaned until manage_channels permission is granted"
                )
                return

            await channel.delete(reason="Dynamic voice channel cleanup - empty")
            self.active_channels.discard(channel_id)
            await self._remove_channel_from_database(channel_id)
            _logger.info("dynamic_channel_cleaned_up", channel_id=channel_id, guild_id=guild.id)
            
        except discord.NotFound:
            _logger.debug("channel_already_deleted", channel_id=channel.id)
            self.active_channels.discard(channel.id)
            await self._remove_channel_from_database(channel.id)
        except discord.Forbidden:
            _logger.warning("insufficient_permissions_delete_channel", 
                channel_id=channel.id,
                guild_id=guild.id,
                warning="Channel remains on Discord but tracked in memory"
            )
        except Exception as e:
            _logger.error("error_cleaning_up_channel", 
                channel_id=channel.id, 
                error=str(e),
                warning="Channel may be in inconsistent state"
            )

    async def _store_channel_in_database(self, channel_id: int, guild_id: int) -> None:
        """Store dynamic channel in database for persistence with idempotent INSERT."""
        try:
            query = """
                INSERT INTO dynamic_voice_channels (channel_id, guild_id) 
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE guild_id = VALUES(guild_id)
            """
            await self.bot.run_db_query(query, (channel_id, guild_id), commit=True)
            _logger.debug("channel_stored_in_database", channel_id=channel_id, guild_id=guild_id)
        except Exception as e:
            _logger.error("failed_to_store_channel_in_database", channel_id=channel_id, error=str(e))

    async def _remove_channel_from_database(self, channel_id: int) -> None:
        """Remove dynamic channel from database."""
        try:
            query = "DELETE FROM dynamic_voice_channels WHERE channel_id = %s"
            await self.bot.run_db_query(query, (channel_id,), commit=True)
            _logger.debug("channel_removed_from_database", channel_id=channel_id)
        except Exception as e:
            _logger.error("failed_to_remove_channel_from_database", channel_id=channel_id, error=str(e))

    async def sweep_orphan_channels(self, delay: int = 0) -> None:
        """
        Clean up orphaned dynamic channels at startup - remove non-existent or empty channels.
        
        Args:
            delay: Delay in seconds before starting the sweep
        """
        try:
            if delay:
                await asyncio.sleep(delay)
            
            _logger.info("orphan_sweep_started")
            
            rows = await self.bot.run_db_query(
                "SELECT channel_id, guild_id FROM dynamic_voice_channels", 
                fetch_all=True
            ) or []
            
            cleaned_count = 0
            validated_count = 0
            
            for (channel_id, guild_id) in rows:
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    await self._remove_channel_from_database(channel_id)
                    self.active_channels.discard(channel_id)
                    cleaned_count += 1
                    _logger.debug("orphan_guild_removed", channel_id=channel_id, guild_id=guild_id)
                    continue
                
                ch = guild.get_channel(channel_id)
                if not ch:
                    await self._remove_channel_from_database(channel_id)
                    self.active_channels.discard(channel_id)
                    cleaned_count += 1
                    _logger.debug("orphan_channel_removed", channel_id=channel_id, guild_id=guild_id)
                    continue

                if isinstance(ch, discord.VoiceChannel) and len(ch.members) == 0:
                    await self._cleanup_empty_channel(ch, guild)
                    cleaned_count += 1
                    _logger.debug("empty_channel_cleaned", channel_id=channel_id)
                else:
                    self.active_channels.add(channel_id)
                    validated_count += 1
            
            _logger.info("orphan_sweep_completed", 
                cleaned_count=cleaned_count,
                validated_count=validated_count,
                total_processed=len(rows)
            )
            
        except Exception as e:
            _logger.error("orphan_sweep_failed", error=str(e))

    async def _auto_prune_if_empty(self, channel: discord.VoiceChannel, guild: discord.Guild, delay: int = 15):
        """
        Auto-prune channel if it remains empty after delay.
        
        Args:
            channel: Voice channel to monitor
            guild: Discord guild
            delay: Seconds to wait before checking if empty
        """
        try:
            await asyncio.sleep(delay)
            ch = guild.get_channel(channel.id)
            if ch and len(ch.members) == 0 and channel.id in self.active_channels:
                _logger.debug("auto_pruning_empty_channel", channel_id=channel.id)
                await self._cleanup_empty_channel(ch, guild)
        except Exception as e:
            _logger.debug("auto_prune_check_failed", channel_id=channel.id, error=str(e))

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        """
        Clean up tracking when a voice channel is deleted manually.
        
        Args:
            channel: Channel that was deleted
        """
        if not isinstance(channel, discord.VoiceChannel):
            return
            
        if channel.id not in self.active_channels:
            return
        
        try:
            _logger.info("tracked_voice_channel_deleted_manually", 
                channel_id=channel.id,
                channel_name=channel.name,
                guild_id=channel.guild.id if channel.guild else None
            )

            self.active_channels.discard(channel.id)

            await self._remove_channel_from_database(channel.id)
            
            _logger.debug("manual_deletion_cleanup_completed", channel_id=channel.id)
            
        except Exception as e:
            _logger.error("manual_deletion_cleanup_failed", 
                channel_id=channel.id,
                error=str(e)
            )

def setup(bot: discord.Bot) -> None:
    """
    Setup function to add the DynamicVoice cog to the bot.

    Args:
        bot: Discord bot instance
    """
    bot.add_cog(DynamicVoice(bot))
