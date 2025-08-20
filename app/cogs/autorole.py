"""
AutoRole Manager Cog - Enterprise-grade automatic role assignment and welcome message handling.

This cog provides comprehensive autorole management with:

Features:
    - Automatic role assignment on rules acceptance
    - Welcome message tracking and updates
    - Rate limiting for reaction abuse prevention
    - Profile setup integration with DM notifications
    - Real-time role management with validation

Enterprise Patterns:
    - Discord API resilience with retry logic and 5xx handling
    - Cache ready gates for cold start protection
    - Centralized permission error handling with user feedback
    - Structured logging with ComponentLogger
    - Full localization support via JSON translation system
    - Race condition protection with proper validation
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Dict, Tuple

import discord
from discord.ext import commands

from core.logger import ComponentLogger
from core.reliability import discord_resilient
from core.translation import translations as global_translations

_logger = ComponentLogger("autorole")
AUTOROLE_NAMESPACE = "autorole_system"
AUTOROLE_TRANSLATIONS = global_translations.get(AUTOROLE_NAMESPACE, {})

def _validate_translation_keys():
    """Validate required translation keys at module load time."""
    required_keys = [
        "welcome.pending",
        "welcome.accepted"
    ]
    
    missing_keys = []
    translations = AUTOROLE_TRANSLATIONS
    
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
            namespace=AUTOROLE_NAMESPACE,
            missing_keys=missing_keys
        )

_validate_translation_keys()


def update_welcome_embed(
    embed: discord.Embed, lang: str, autorole_translations: dict
) -> discord.Embed:
    """
    Update welcome embed with acceptance timestamp and language-specific text.

    Args:
        embed: Discord embed to update
        lang: Language code for translations
        autorole_translations: AutoRole translation dictionary

    Returns:
        Updated Discord embed with acceptance timestamp
    """
    try:
        epoch = int(datetime.now(timezone.utc).timestamp())
        discord_timestamp = f"<t:{epoch}:F>"
        
        pending_text = (
            autorole_translations.get("welcome", {}).get("pending", {}).get(lang)
        )
        accepted_template = (
            autorole_translations.get("welcome", {}).get("accepted", {}).get(lang)
        )
        if not pending_text or not accepted_template:
            _logger.error(
                "missing_welcome_translation_keys",
                lang=lang,
                missing_pending=not pending_text,
                missing_accepted=not accepted_template
            )
            return embed
        new_text = accepted_template.format(date=discord_timestamp)
        if embed.description:
            if pending_text in embed.description:
                embed.description = embed.description.replace(pending_text, new_text)
            else:
                embed.description = new_text
        else:
            embed.description = new_text
        embed.color = discord.Color.dark_grey()
    except Exception as e:
        _logger.error(
            "error_updating_welcome_embed",
            lang=lang,
            error=str(e),
            exc_info=True
        )
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

    def _has_cache(self) -> bool:
        """Check if bot has cache system available."""
        if not hasattr(self.bot, "cache") or self.bot.cache is None:
            _logger.debug("no_cache_attached")
            return False
        return True

    @commands.Cog.listener()
    async def on_ready(self):
        """Wait for initial cache load to complete."""
        if hasattr(self.bot, "cache_loader"):
            asyncio.create_task(self.bot.cache_loader.wait_for_initial_load())
            _logger.debug("waiting_for_initial_cache_load")
        else:
            _logger.debug("no_cache_loader_attached")

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
        current_time = time.time()
        cutoff = current_time - 3600

        for k, ts in list(self._recent_reactions.items()):
            if ts <= cutoff:
                self._recent_reactions.pop(k, None)
                self._reaction_counts.pop(k, None)

        if len(self._recent_reactions) > 10000:
            sorted_items = sorted(self._recent_reactions.items(), key=lambda x: x[1], reverse=True)
            keys_to_keep = {item[0] for item in sorted_items[:5000]}

            keys_to_remove = set(self._recent_reactions.keys()) - keys_to_keep
            for k in keys_to_remove:
                self._recent_reactions.pop(k, None)
                self._reaction_counts.pop(k, None)
            
            _logger.debug(
                "rate_limit_dict_purged",
                removed_count=len(keys_to_remove),
                remaining_count=len(self._recent_reactions)
            )

        key = (guild_id, user_id, message_id)
        self._reaction_counts[key] = self._reaction_counts.get(key, 0) + 1

        if self._reaction_counts[key] <= 2:
            self._recent_reactions[key] = current_time
            return True

        if key in self._recent_reactions:
            if current_time - self._recent_reactions[key] < 5.0:
                _logger.debug(
                    "reaction_rate_limited",
                    guild_id=guild_id,
                    user_id=user_id,
                    message_id=message_id,
                    reaction_count=self._reaction_counts[key]
                )
                return False

        self._recent_reactions[key] = current_time
        return True

    async def _ensure_cache_ready(self, event_type: str = "unknown") -> bool:
        """
        Ensure cache is ready before processing events.

        Args:
            event_type: Type of event for logging context

        Returns:
            True if cache is ready or no cache loader (dev/test mode), False if not ready
        """
        try:
            if not hasattr(self.bot, "cache_loader"):
                _logger.debug("no_cache_loader_attached")
                return True
            is_ready = await self.bot.cache_loader.is_initial_load_complete()
            if not is_ready:
                _logger.debug("cache_not_ready_skipping_event", event_type=event_type)
            return is_ready
        except Exception as e:
            _logger.error("error_checking_cache_ready", event_type=event_type, error=str(e), exc_info=True)
            return False

    async def _handle_permission_error(
        self,
        operation: str,
        channel_or_member,
        guild_id: int | None = None
    ) -> None:
        """
        Handle permission errors with appropriate logging.

        Args:
            operation: Operation that failed
            channel_or_member: Discord object that caused the permission error
            guild_id: Guild ID for logging context
        """
        _logger.warning(
            "permission_error",
            operation=operation,
            target_id=getattr(channel_or_member, 'id', None),
            guild_id=guild_id or getattr(channel_or_member, 'guild_id', None)
        )

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
    @discord_resilient(service_name="discord_api", max_retries=2)
    async def on_raw_reaction_add(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        """
        Handle reaction addition for role assignment and welcome message updates.

        Args:
            payload: Discord raw reaction event payload
        """
        if not await self._ensure_cache_ready("on_raw_reaction_add"):
            return

        if not self._has_cache():
            return

        if payload.user_id == self.bot.user.id:
            return

        _logger.debug(
            "processing_reaction_add",
            user_id=payload.user_id,
            message_id=payload.message_id,
            emoji=str(payload.emoji)
        )

        if not payload.guild_id:
            _logger.debug("no_guild_id_skipping")
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            _logger.debug(
                "guild_not_found",
                guild_id=payload.guild_id
            )
            return

        rules_info = await self.bot.cache.get_guild_data(guild.id, "rules_message")
        if not rules_info or payload.message_id != rules_info.get("message"):
            _logger.debug(
                "message_not_rules_message",
                message_id=payload.message_id,
                guild_id=guild.id
            )
            return

        if str(payload.emoji) != "✅":
            return

        if not self._check_rate_limit(guild.id, payload.user_id, payload.message_id):
            return

        role_id = await self.bot.cache.get_guild_data(guild.id, "rules_ok_role")
        if not role_id:
            _logger.warning(
                "no_rules_ok_role_configured",
                guild_id=guild.id
            )
            return

        role = guild.get_role(role_id)
        if not role:
            _logger.warning(
                "rules_ok_role_not_found",
                role_id=role_id,
                guild_id=guild.id
            )
            return

        try:
            member = guild.get_member(payload.user_id) or await guild.fetch_member(
                payload.user_id
            )
        except discord.NotFound:
            _logger.debug(
                "member_no_longer_exists",
                user_id=payload.user_id,
                guild_id=guild.id
            )
            return
        except Exception as e:
            _logger.error(
                "error_fetching_member",
                user_id=payload.user_id,
                guild_id=guild.id,
                error=str(e),
                exc_info=True
            )
            return

        if member and member.bot:
            _logger.debug(
                "ignoring_bot_reaction",
                user_id=payload.user_id,
                guild_id=guild.id
            )
            return

        if member and role and role not in member.roles:
            me = guild.me
            if not me.guild_permissions.manage_roles or role >= me.top_role or role.managed:
                _logger.warning(
                    "insufficient_role_hierarchy",
                    guild_id=guild.id,
                    bot_top=getattr(me.top_role, "id", None),
                    target_role=role.id,
                    role_managed=role.managed
                )
                return

            try:
                await member.add_roles(role, reason="Autorole: rules accepted")
                _logger.debug(
                    "role_added_to_member",
                    member_name=member.name,
                    member_id=member.id,
                    role_id=role.id
                )
            except discord.Forbidden:
                await self._handle_permission_error(
                    "add_rules_ok_role",
                    member,
                    guild_id=guild.id
                )
                return
            except Exception as e:
                _logger.error(
                    "error_adding_role_to_member",
                    member_name=member.name,
                    member_id=member.id,
                    role_id=role.id,
                    error=str(e),
                    exc_info=True
                )
                return

            welcome_info = await self.bot.cache.get_user_data(
                guild.id, member.id, "welcome_message"
            )
            if welcome_info:
                try:
                    channel = self.bot.get_channel(welcome_info["channel"])
                    if not channel:
                        channel = await self.bot.fetch_channel(welcome_info["channel"])

                    if not channel:
                        _logger.warning(
                            "welcome_channel_not_found",
                            channel_id=welcome_info['channel'],
                            member_id=member.id,
                            guild_id=guild.id
                        )
                        await self.bot.cache.delete(
                            "user_data", guild.id, member.id, "welcome_message"
                        )
                        return

                    try:
                        message = await channel.fetch_message(welcome_info["message"])
                    except discord.NotFound:
                        _logger.warning(
                            "welcome_message_not_found",
                            message_id=welcome_info['message'],
                            member_id=member.id,
                            guild_id=guild.id
                        )
                        await self.bot.cache.delete(
                            "user_data", guild.id, member.id, "welcome_message"
                        )
                        return

                    if not message.embeds:
                        _logger.warning(
                            "no_embeds_in_welcome_message",
                            member_name=member.name,
                            member_id=member.id,
                            message_id=welcome_info['message']
                        )
                        return

                    lang = (
                        await self.bot.cache.get_guild_data(guild.id, "guild_lang")
                        or "en-US"
                    )
                    embed = update_welcome_embed(
                        message.embeds[0], lang, AUTOROLE_TRANSLATIONS
                    )

                    for attempt in range(2):
                        try:
                            await message.edit(embed=embed)
                            break
                        except discord.HTTPException as e:
                            if e.status >= 500 and attempt == 0:
                                await asyncio.sleep(1.5)
                                continue
                            raise
                    
                    _logger.debug(
                        "welcome_message_updated",
                        member_name=member.name,
                        member_id=member.id,
                        message_id=welcome_info['message']
                    )
                except discord.Forbidden:
                    await self._handle_permission_error(
                        "edit_welcome_message",
                        channel,
                        guild_id=guild.id
                    )
                except Exception as e:
                    _logger.error(
                        "error_updating_welcome_message",
                        member_name=member.name,
                        member_id=member.id,
                        message_id=welcome_info['message'],
                        error=str(e),
                        exc_info=True
                    )
            else:
                _logger.debug(
                    "no_welcome_message_in_cache",
                    member_id=member.id,
                    guild_id=guild.id
                )

            try:
                if hasattr(self.bot, "cache_loader"):
                    await self.bot.cache_loader.ensure_category_loaded("user_data")
                user_setup = await self.bot.cache.get_user_data(
                    guild.id, member.id, "setup"
                )

                if user_setup is not None:
                    _logger.debug(
                        "profile_already_exists",
                        member_id=member.id,
                        guild_id=guild.id
                    )
                    return

                _logger.debug(
                    "no_profile_found_sending_dm",
                    member_id=member.id,
                    guild_id=guild.id
                )
            except Exception as e:
                _logger.error(
                    "error_checking_user_profile",
                    member_id=member.id,
                    guild_id=guild.id,
                    error=str(e),
                    exc_info=True
                )
                return

            profile_setup_cog = self._get_profile_setup_cog()
            if profile_setup_cog is None:
                _logger.error(
                    "profile_setup_cog_not_found",
                    guild_id=guild.id
                )
                return
            try:
                await member.send(
                    view=profile_setup_cog.LangSelectView(profile_setup_cog, guild.id)
                )
                _logger.debug(
                    "profile_setup_dm_sent",
                    member_name=member.name,
                    member_id=member.id,
                    guild_id=guild.id
                )
            except discord.Forbidden:
                _logger.warning(
                    "cannot_send_dm_to_member",
                    member_name=member.name,
                    member_id=member.id,
                    guild_id=guild.id
                )
            except Exception as e:
                _logger.error(
                    "error_sending_dm_to_member",
                    member_name=member.name,
                    member_id=member.id,
                    guild_id=guild.id,
                    error=str(e),
                    exc_info=True
                )

    @commands.Cog.listener()
    @discord_resilient(service_name="discord_api", max_retries=2)
    async def on_raw_reaction_remove(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        """
        Handle reaction removal and role management.

        Args:
            payload: Discord raw reaction event payload
        """
        if not await self._ensure_cache_ready("on_raw_reaction_remove"):
            return

        if not self._has_cache():
            return

        if payload.user_id == self.bot.user.id:
            return

        if not payload.guild_id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        rules_info = await self.bot.cache.get_guild_data(guild.id, "rules_message")
        if not rules_info or payload.message_id != rules_info.get("message"):
            return

        if str(payload.emoji) != "✅":
            return

        if not self._check_rate_limit(guild.id, payload.user_id, payload.message_id):
            return

        role_id = await self.bot.cache.get_guild_data(guild.id, "rules_ok_role")
        if not role_id:
            _logger.warning(
                "no_rules_ok_role_configured",
                guild_id=guild.id
            )
            return

        role = guild.get_role(role_id)
        if not role:
            _logger.warning(
                "rules_ok_role_not_found",
                role_id=role_id,
                guild_id=guild.id
            )
            return

        try:
            member = guild.get_member(payload.user_id) or await guild.fetch_member(
                payload.user_id
            )
        except discord.NotFound:
            _logger.debug(
                "member_no_longer_exists_removal",
                user_id=payload.user_id,
                guild_id=guild.id
            )
            return
        except Exception as e:
            _logger.error(
                "error_fetching_member_removal",
                user_id=payload.user_id,
                guild_id=guild.id,
                error=str(e),
                exc_info=True
            )
            return

        if member and member.bot:
            _logger.debug(
                "ignoring_bot_reaction_removal",
                user_id=payload.user_id,
                guild_id=guild.id
            )
            return

        if member and role and role in member.roles:
            me = guild.me
            if not me.guild_permissions.manage_roles or role >= me.top_role or role.managed:
                _logger.warning(
                    "insufficient_role_hierarchy",
                    guild_id=guild.id,
                    bot_top=getattr(me.top_role, "id", None),
                    target_role=role.id,
                    role_managed=role.managed
                )
                return

            try:
                await member.remove_roles(role, reason="Autorole: rules reaction removed")
                _logger.debug(
                    "role_removed_from_member",
                    member_name=member.name,
                    member_id=member.id,
                    role_id=role.id
                )
            except discord.Forbidden:
                await self._handle_permission_error(
                    "remove_rules_ok_role",
                    member,
                    guild_id=guild.id
                )
            except Exception as e:
                _logger.error(
                    "error_removing_role_from_member",
                    member_name=member.name,
                    member_id=member.id,
                    role_id=role.id,
                    error=str(e),
                    exc_info=True
                )


def setup(bot: discord.Bot):
    """
    Setup function to add the AutoRole cog to the bot.

    Args:
        bot: Discord bot instance
    """
    bot.add_cog(AutoRole(bot))
