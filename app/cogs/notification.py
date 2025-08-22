"""
Notification Manager Cog - Manages member join/leave notifications and welcome message handling.
"""

import asyncio
import time

import discord
from discord.ext import commands
from discord.utils import escape_markdown, escape_mentions

from core.logger import ComponentLogger
from core.reliability import discord_resilient
from core.translation import translations as global_translations

NOTIFICATION_DATA = global_translations.get("notification", {})

_logger = ComponentLogger("notification")


def create_embed(
    title: str, description: str, color: discord.Color, member: discord.Member
) -> discord.Embed:
    """
    Create a Discord embed with member information.

    Args:
        title: Embed title
        description: Embed description text
        color: Discord color for the embed
        member: Discord member to extract avatar from

    Returns:
        Configured Discord embed with member avatar
    """
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_thumbnail(url=member.display_avatar.url)
    return embed


class Notification(commands.Cog):
    """Cog for managing member join/leave notifications and welcome message handling."""

    SEND_TIMEOUT = 10.0

    def __init__(self, bot: commands.Bot) -> None:
        """
        Initialize the Notification cog.

        Args:
            bot: Discord bot instance
        """
        self.bot = bot
        self.max_events_per_minute = 60
        self._guild_locks: dict[int, asyncio.Lock] = {}

    def sanitize_user_data(self, name: str) -> str:
        """
        Sanitize user data by escaping markdown and mentions.

        Args:
            name: Raw username to sanitize

        Returns:
            Sanitized username with markdown and mentions escaped
        """
        name = name[:100]
        return escape_mentions(escape_markdown(name))

    def _get_guild_lock(self, guild_id: int) -> asyncio.Lock:
        """
        Get or create a guild-specific lock for notification rate limiting.

        Args:
            guild_id: Discord guild ID

        Returns:
            asyncio.Lock for the guild
        """
        return self._guild_locks.setdefault(guild_id, asyncio.Lock())

    async def check_event_rate_limit(self, guild_id: int) -> bool:
        """
        Check if guild has exceeded the event rate limit.

        Args:
            guild_id: Discord guild ID to check

        Returns:
            True if guild can process events, False if rate limited
        """
        now = time.monotonic()
        key = f"member_events_{guild_id}"
        events: list[float] = await self.bot.cache.get("temporary", key) or []
        events = [t for t in events if now - t < 60]
        if len(events) >= self.max_events_per_minute:
            return False
        events.append(now)
        await self.bot.cache.set("temporary", events, key)
        return True

    @discord_resilient(service_name="ptb_kick", max_retries=1)
    async def _kick_ptb_member(
        self, 
        ptb_member: discord.Member, 
        reason: str,
        main_guild_id: int,
        ptb_guild_id: int
    ) -> bool:
        """
        Safely kick a member from PTB guild with resilient error handling.

        Args:
            ptb_member: Member to kick from PTB guild
            reason: Reason for the kick
            main_guild_id: ID of the main guild
            ptb_guild_id: ID of the PTB guild

        Returns:
            True if kick was successful, False otherwise
        """
        try:
            await ptb_member.kick(reason=reason)
            return True
        except discord.Forbidden:
            _logger.warning("ptb_kick_forbidden",
                user_id=ptb_member.id,
                ptb_guild_id=ptb_guild_id
            )
            return False
        except Exception as e:
            _logger.error("ptb_kick_failed",
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                user_id=ptb_member.id,
                ptb_guild_id=ptb_guild_id
            )
            return False

    async def is_ptb_guild(self, guild_id: int) -> bool:
        """
        Check if guild is a PTB (Public Test Branch) guild.

        Args:
            guild_id: Discord guild ID to check

        Returns:
            True if guild is a PTB guild, False otherwise
        """
        try:
            guild_ptb_cog = self.bot.get_cog("GuildPTB")
            if not guild_ptb_cog:
                return False

            ptb_settings = await guild_ptb_cog.get_ptb_settings()
            for main_guild_id, settings in ptb_settings.items():
                if settings.get("ptb_guild_id") == guild_id:
                    _logger.debug("guild_identified_as_ptb",
                        guild_id=guild_id,
                        main_guild_id=main_guild_id
                    )
                    return True
            return False
        except Exception as e:
            _logger.error("ptb_check_failed",
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                guild_id=guild_id
            )
            return False

    async def get_safe_channel(self, channel_id: int):
        """
        Safely retrieve a Discord channel by ID with error handling.

        Args:
            channel_id: Discord channel ID to retrieve

        Returns:
            Discord channel object or None if not accessible
        """
        try:
            channel = self.bot.get_channel(channel_id)
            if not channel:
                channel = await self.bot.fetch_channel(channel_id)
            return channel
        except discord.NotFound:
            _logger.error("channel_not_found", channel_id=channel_id)
            return None
        except discord.Forbidden:
            _logger.error("channel_access_denied", channel_id=channel_id)
            return None
        except Exception as e:
            _logger.error("channel_fetch_failed",
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                channel_id=channel_id
            )
            return None

    @discord_resilient(service_name="discord_api", max_retries=2)
    async def safe_send_notification(self, channel, embed):
        """
        Safely send a notification embed to a channel with timeout and error handling.

        Args:
            channel: Discord channel to send message to
            embed: Discord embed to send

        Returns:
            Discord message object or None if sending failed
        """
        try:
            return await asyncio.wait_for(
                channel.send(
                    embed=embed, 
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)
                ), 
                timeout=self.SEND_TIMEOUT
            )
        except asyncio.TimeoutError:
            _logger.error("notification_send_timeout")
            return None
        except discord.HTTPException as e:
            _logger.error("notification_http_error",
                error_type=type(e).__name__,
                error_msg=str(e)[:200]
            )
            return None
        except Exception as e:
            _logger.error("notification_unexpected_error",
                error_type=type(e).__name__,
                error_msg=str(e)[:200]
            )
            return None

    @commands.Cog.listener()
    async def on_ready(self):
        """Initialize notification data on bot ready."""
        asyncio.create_task(self.bot.cache_loader.wait_for_initial_load())
        _logger.debug("notification_data_loading_started")

    async def get_guild_lang(self, guild: discord.Guild) -> str:
        """
        Get guild language from centralized cache.

        Args:
            guild: Discord guild to get language for

        Returns:
            Guild language code (default: en-US)
        """
        guild_lang = await self.bot.cache.get_guild_data(guild.id, "guild_lang")
        return guild_lang or "en-US"

    @commands.Cog.listener()
    @discord_resilient(service_name="discord_api", max_retries=2)
    async def on_member_join(self, member: discord.Member) -> None:
        """
        Handle member join events with notification and welcome message creation.

        Args:
            member: Discord member who joined the guild
        """
        guild = member.guild
        _logger.debug("member_joined",
            user_id=member.id,
            guild_id=guild.id
        )

        is_ptb = await self.is_ptb_guild(guild.id)
        _logger.debug("ptb_check_result", guild_id=guild.id, is_ptb=is_ptb)
        if is_ptb:
            _logger.debug("skipping_ptb_guild", guild_id=guild.id)
            return

        lock = self._get_guild_lock(guild.id)
        async with lock:
            if not await self.check_event_rate_limit(guild.id):
                _logger.warning("rate_limit_exceeded",
                    guild_id=guild.id
                )
                return

        try:
            channels_data = await self.bot.cache.get_guild_data(
                guild.id, "channels"
            )
            _logger.debug("channels_data_loaded", guild_id=guild.id, has_data=bool(channels_data))
            notif_channel_id = (
                channels_data.get("notifications_channel")
                if channels_data
                else None
            )

            _logger.debug("notification_channel_configured",
                guild_id=guild.id,
                channel_id=notif_channel_id
            )
            if notif_channel_id:
                channel = await self.get_safe_channel(notif_channel_id)
                if not channel:
                    _logger.warning("notification_channel_inaccessible", guild_id=guild.id)
                    return

                guild_lang = await self.get_guild_lang(guild)
                notif_trans = NOTIFICATION_DATA.get("member_join", {})
                title = notif_trans.get("title", {}).get(
                    guild_lang,
                    notif_trans.get("title", {}).get("en-US", "🟢 New Member!"),
                )

                safe_name = self.sanitize_user_data(member.name)
                description_template = notif_trans.get("description", {}).get(
                    guild_lang,
                    notif_trans.get("description", {}).get(
                        "en-US",
                        "Welcome {member_mention}!\n**Discord Name:** {member_name}\n**Discord ID:** `{member_id}`\n📜 **Pending rules acceptance**\n🚀 Pending configuration...",
                    ),
                )
                description = description_template.format(
                    member_mention=member.mention,
                    member_name=safe_name,
                    member_id=member.id,
                )

                embed = create_embed(
                    title, description, discord.Color.light_grey(), member
                )
                msg = await self.safe_send_notification(channel, embed)

                if msg:
                    try:
                        insert_query = "INSERT INTO welcome_messages (guild_id, member_id, channel_id, message_id) VALUES (%s, %s, %s, %s)"
                        await self.bot.run_db_query(
                            insert_query,
                            (guild.id, member.id, channel.id, msg.id),
                            commit=True,
                        )

                        await self.bot.cache.set_user_data(
                            guild.id,
                            member.id,
                            "welcome_message",
                            {"channel": channel.id, "message": msg.id},
                        )
                        _logger.debug("welcome_message_saved",
                            user_id=member.id,
                            message_id=msg.id,
                            guild_id=guild.id
                        )
                    except Exception as e:
                        _logger.error("welcome_message_failed",
                            error_type=type(e).__name__,
                            error_msg=str(e)[:200],
                            user_id=member.id,
                            guild_id=guild.id
                        )
                else:
                    _logger.warning("welcome_message_not_sent",
                        user_id=member.id,
                        guild_id=guild.id
                    )
            else:
                _logger.warning("notification_channel_not_configured",
                    guild_id=guild.id
                )
        except Exception as e:
            _logger.error("join_notification_error",
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                user_id=member.id,
                guild_id=guild.id
            )

    @commands.Cog.listener()
    @discord_resilient(service_name="discord_api", max_retries=2)
    async def on_member_remove(self, member: discord.Member) -> None:
        """
        Handle member leave events with PTB auto-kick and leave notifications.

        Args:
            member: Discord member who left the guild
        """
        guild = member.guild
        _logger.debug("member_left",
            user_id=member.id,
            guild_id=guild.id
        )

        is_ptb = await self.is_ptb_guild(guild.id)
        _logger.debug("ptb_check_result", guild_id=guild.id, is_ptb=is_ptb)
        if is_ptb:
            _logger.debug("skipping_ptb_guild", guild_id=guild.id)
            return

        lock = self._get_guild_lock(guild.id)
        async with lock:
            if not await self.check_event_rate_limit(guild.id):
                _logger.warning("rate_limit_exceeded",
                    guild_id=guild.id
                )
                return

        try:
            guild_ptb_cog = self.bot.get_cog("GuildPTB")
            if guild_ptb_cog:
                ptb_guild_id = await self.bot.cache.get_guild_data(
                    guild.id, "guild_ptb"
                )
                if ptb_guild_id:
                    ptb_guild = self.bot.get_guild(ptb_guild_id)
                    if ptb_guild:
                        ptb_member = ptb_guild.get_member(member.id)
                        if ptb_member:
                            success = await self._kick_ptb_member(
                                ptb_member, 
                                f"Member left main Discord server ({guild.name})",
                                guild.id,
                                ptb_guild.id
                            )
                            if success:
                                _logger.info("ptb_auto_kick_success",
                                    user_id=member.id,
                                    ptb_guild_id=ptb_guild.id,
                                    main_guild_id=guild.id
                                )
        except Exception as e:
            _logger.error("leave_notification_error",
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                guild_id=guild.id
            )

        try:
            guild_lang = await self.get_guild_lang(guild)
            query = "SELECT channel_id, message_id FROM welcome_messages WHERE guild_id = %s AND member_id = %s"
            result = await self.bot.run_db_query(
                query, (guild.id, member.id), fetch_one=True
            )

            if result:
                channel_id, message_id = result
                channel = await self.get_safe_channel(channel_id)

                if channel:
                    try:
                        original_message = await asyncio.wait_for(
                            channel.fetch_message(message_id), timeout=self.SEND_TIMEOUT
                        )
                        notif_trans = NOTIFICATION_DATA.get("member_leave", {})
                        title = notif_trans.get("title", {}).get(
                            guild_lang,
                            notif_trans.get("title", {}).get("en-US", "🔴 Member Left"),
                        )

                        safe_name = self.sanitize_user_data(member.name)
                        description_template = notif_trans.get("description", {}).get(
                            guild_lang,
                            notif_trans.get("description", {}).get(
                                "en-US",
                                "**{member_name}** left the server\n**Discord ID:** `{member_id}`",
                            ),
                        )
                        description = description_template.format(
                            member_name=safe_name, member_id=member.id
                        )

                        embed = create_embed(
                            title, description, discord.Color.red(), member
                        )
                        await asyncio.wait_for(
                            original_message.reply(
                                embed=embed,
                                mention_author=False,
                                allowed_mentions=discord.AllowedMentions.none()
                            ),
                            timeout=self.SEND_TIMEOUT,
                        )
                        _logger.debug("leave_reply_sent",
                            user_id=member.id,
                            message_id=message_id,
                            guild_id=guild.id
                        )
                    except (discord.NotFound, asyncio.TimeoutError) as e:
                        _logger.warning("leave_reply_not_found",
                            error_type=type(e).__name__,
                            user_id=member.id,
                            message_id=message_id
                        )
                    except Exception as e:
                        _logger.error("notification_send_failed",
                            error_type=type(e).__name__,
                            error_msg=str(e)[:200],
                            user_id=member.id,
                            message_id=message_id
                        )

                try:
                    await self.bot.run_db_query(
                        "DELETE FROM welcome_messages WHERE guild_id = %s AND member_id = %s",
                        (guild.id, member.id),
                        commit=True,
                    )
                    await self.bot.run_db_query(
                        "DELETE FROM user_setup WHERE guild_id = %s AND user_id = %s",
                        (guild.id, member.id),
                        commit=True,
                    )
                    await self.bot.run_db_query(
                        "DELETE FROM guild_members WHERE guild_id = %s AND member_id = %s",
                        (guild.id, member.id),
                        commit=True,
                    )
                    await self.bot.run_db_query(
                        "DELETE FROM pending_diplomat_validations WHERE guild_id = %s AND member_id = %s",
                        (guild.id, member.id),
                        commit=True,
                    )

                    # Cleanup wishlist items for the departed member
                    loot_wishlist_cog = self.bot.get_cog("LootWishlist")
                    if loot_wishlist_cog:
                        await loot_wishlist_cog.cleanup_member_wishlist(guild.id, member.id)

                    await self.bot.cache.delete(
                        "user_data", guild.id, member.id, "welcome_message"
                    )
                    await self.bot.cache.delete(
                        "user_data", guild.id, member.id, "setup"
                    )

                    pending_validations = await self.bot.cache.get(
                        "temporary", "pending_validations"
                    )
                    if pending_validations:
                        keys_to_remove = [
                            key
                            for key in pending_validations.keys()
                            if key.split("_")[0] == str(guild.id)
                            and key.split("_")[1] == str(member.id)
                        ]
                        for key in keys_to_remove:
                            del pending_validations[key]
                        await self.bot.cache.set(
                            "temporary", pending_validations, "pending_validations"
                        )

                    await self.bot.cache.invalidate_category("roster_data")
                    _logger.debug("roster_cache_invalidated",
                        user_id=member.id,
                        guild_id=guild.id
                    )
                    _logger.debug("diplomat_validations_cleaned",
                        user_id=member.id,
                        guild_id=guild.id
                    )
                except Exception as e:
                    _logger.error("db_cleanup_failed",
                        error_type=type(e).__name__,
                        error_msg=str(e)[:200],
                        user_id=member.id,
                        guild_id=guild.id
                    )
            else:
                channels_data = await self.bot.cache.get_guild_data(
                    guild.id, "channels"
                )
                notif_channel_id = (
                    channels_data.get("notifications_channel")
                    if channels_data
                    else None
                )

                _logger.debug("notification_channel_configured",
                    guild_id=guild.id,
                    channel_id=notif_channel_id
                )
                if notif_channel_id:
                    channel = await self.get_safe_channel(notif_channel_id)
                    if channel:
                        notif_trans = NOTIFICATION_DATA.get("member_leave", {})
                        title = notif_trans.get("title", {}).get(
                            guild_lang,
                            notif_trans.get("title", {}).get("en-US", "🔴 Member Left"),
                        )

                        safe_name = self.sanitize_user_data(member.name)
                        description_template = notif_trans.get("description", {}).get(
                            guild_lang,
                            notif_trans.get("description", {}).get(
                                "en-US",
                                "**{member_name}** left the server\n**Discord ID:** `{member_id}`",
                            ),
                        )
                        description = description_template.format(
                            member_name=safe_name, member_id=member.id
                        )

                        embed = create_embed(
                            title, description, discord.Color.red(), member
                        )
                        await self.safe_send_notification(channel, embed)

                try:
                    await self.bot.run_db_query(
                        "DELETE FROM pending_diplomat_validations WHERE guild_id = %s AND member_id = %s",
                        (guild.id, member.id),
                        commit=True,
                    )

                    pending_validations = await self.bot.cache.get(
                        "temporary", "pending_validations"
                    )
                    if pending_validations:
                        keys_to_remove = [
                            key
                            for key in pending_validations.keys()
                            if key.split("_")[0] == str(guild.id)
                            and key.split("_")[1] == str(member.id)
                        ]
                        for key in keys_to_remove:
                            del pending_validations[key]
                        await self.bot.cache.set(
                            "temporary", pending_validations, "pending_validations"
                        )

                    _logger.debug("diplomat_validations_cleaned_no_welcome",
                        user_id=member.id,
                        guild_id=guild.id
                    )
                except Exception as e:
                    _logger.error("diplomat_cleanup_failed",
                        error_type=type(e).__name__,
                        error_msg=str(e)[:200],
                        user_id=member.id,
                        guild_id=guild.id
                    )

            # Clean up user data from database to prevent future errors
            try:
                await self._cleanup_member_database_records(member)
                _logger.debug("database_cleanup_completed",
                    user_id=member.id,
                    guild_id=member.guild.id
                )
            except Exception as e:
                _logger.error("database_cleanup_error",
                    error_type=type(e).__name__,
                    error_msg=str(e)[:200],
                    user_id=member.id,
                    guild_id=member.guild.id
                )

        except Exception as e:
            _logger.error("leave_notification_error",
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                user_id=member.id,
                guild_id=member.guild.id
            )

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        """
        Clean up guild-specific resources when bot leaves a guild.

        Args:
            guild: Discord guild the bot left
        """
        # Clean up guild lock to prevent memory bloat
        if guild.id in self._guild_locks:
            del self._guild_locks[guild.id]
            _logger.debug("guild_lock_cleaned",
                guild_id=guild.id
            )

    async def _cleanup_member_database_records(
        self, member: discord.Member
    ) -> None:
        """
        Clean up database records for departed members to prevent future AutoRole errors.

        Args:
            member: Discord member who left
        """
        guild_id = member.guild.id
        user_id = member.id

        try:
            delete_queries = [
                (
                    "DELETE FROM guild_members WHERE guild_id = %s AND user_id = %s",
                    (guild_id, user_id),
                ),
                (
                    "DELETE FROM user_setup WHERE guild_id = %s AND user_id = %s",
                    (guild_id, user_id),
                ),
                (
                    "DELETE FROM static_groups_members WHERE guild_id = %s AND user_id = %s",
                    (guild_id, user_id),
                ),
                (
                    "DELETE FROM event_attendance WHERE guild_id = %s AND user_id = %s",
                    (guild_id, user_id),
                ),
            ]

            for query, params in delete_queries:
                await self.bot.run_db_query(query, params, commit=True)

            await self.bot.cache.invalidate_guild_member_data(guild_id, user_id)
            _logger.debug("setup_cleanup_complete",
                user_id=user_id,
                guild_id=guild_id
            )

        except Exception as e:
            _logger.error("member_cleanup_failed",
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                user_id=user_id,
                guild_id=guild_id
            )


def setup(bot: discord.Bot):
    """
    Setup function to add the Notification cog to the bot.

    Args:
        bot: Discord bot instance
    """
    bot.add_cog(Notification(bot))
