"""
Notification Manager Cog - Manages member join/leave notifications and welcome message handling.
"""

import asyncio
import logging
import re
import time
from typing import Any

import discord
from discord.ext import commands

from core.reliability import discord_resilient
from core.translation import translations as global_translations

NOTIFICATION_DATA = global_translations.get("notification", {})

def create_embed(title: str, description: str, color: discord.Color, member: discord.Member) -> discord.Embed:
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
    if member.avatar:
        embed.set_thumbnail(url=member.avatar.url)
    return embed

class Notification(commands.Cog):
    """Cog for managing member join/leave notifications and welcome message handling."""
    
    def __init__(self, bot: commands.Bot) -> None:
        """
        Initialize the Notification cog.
        
        Args:
            bot: Discord bot instance
        """
        self.bot = bot
        self.max_events_per_minute = 10
    
    def get_safe_user_info(self, member):
        """
        Get safe user information for logging purposes.
        
        Args:
            member: Discord member object
            
        Returns:
            Safe user identifier string for logs
        """
        return f"User{member.id}"
    
    def sanitize_user_data(self, name: str) -> str:
        """
        Sanitize user data by removing potentially harmful characters.
        
        Args:
            name: Raw username to sanitize
            
        Returns:
            Sanitized username with harmful characters removed
        """
        return re.sub(r'[@#`]', '', name[:100])
    
    async def check_event_rate_limit(self, guild_id: int) -> bool:
        """
        Check if guild has exceeded the event rate limit.
        
        Args:
            guild_id: Discord guild ID to check
            
        Returns:
            True if guild can process events, False if rate limited
        """
        now = time.time()
        member_events = await self.bot.cache.get('temporary', f'member_events_{guild_id}') or []

        member_events = [t for t in member_events if now - t < 60]
        
        if len(member_events) >= self.max_events_per_minute:
            return False
        
        member_events.append(now)
        await self.bot.cache.set('temporary', f'member_events_{guild_id}', member_events)
        return True
    
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
                    logging.debug(f"[NotificationManager] Guild {guild_id} identified as PTB for main guild {main_guild_id}")
                    return True
            return False
        except Exception as e:
            logging.error(f"[NotificationManager] Error checking if guild {guild_id} is PTB: {e}")
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
            logging.error(f"[NotificationManager] Channel {channel_id} not found")
            return None
        except discord.Forbidden:
            logging.error(f"[NotificationManager] No access to channel {channel_id}")
            return None
        except Exception as e:
            logging.error(f"[NotificationManager] Error fetching channel {channel_id}: {e}")
            return None
    
    @discord_resilient(service_name='discord_api', max_retries=2)
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
            return await asyncio.wait_for(channel.send(embed=embed), timeout=10.0)
        except asyncio.TimeoutError:
            logging.error("[NotificationManager] Notification send timeout")
            return None
        except discord.HTTPException as e:
            logging.error(f"[NotificationManager] HTTP error sending notification: {e}")
            return None
        except Exception as e:
            logging.error(f"[NotificationManager] Unexpected error sending notification: {e}")
            return None

    @commands.Cog.listener()
    async def on_ready(self):
        """Initialize notification data on bot ready."""
        asyncio.create_task(self.load_notification_data())
        logging.debug("[NotificationManager] Notification data loading tasks started in on_ready.")

    async def load_notification_data(self) -> None:
        """
        Ensure all required data is loaded via centralized cache loader.
        
        Loads guild settings and channels data needed for notification processing.
        """
        logging.debug("[NotificationManager] Loading notification data")
        
        await self.bot.cache_loader.ensure_category_loaded('guild_settings')
        await self.bot.cache_loader.ensure_category_loaded('guild_channels')
        
        logging.debug("[NotificationManager] Notification data loading completed")

    async def get_guild_lang(self, guild: discord.Guild) -> str:
        """
        Get guild language from centralized cache.
        
        Args:
            guild: Discord guild to get language for
            
        Returns:
            Guild language code (default: en-US)
        """
        await self.bot.cache_loader.ensure_category_loaded('guild_settings')
        
        guild_lang = await self.bot.cache.get_guild_data(guild.id, 'guild_lang')
        return guild_lang or "en-US"

    @commands.Cog.listener()
    @discord_resilient(service_name='discord_api', max_retries=2)
    async def on_member_join(self, member: discord.Member) -> None:
        """
        Handle member join events with notification and welcome message creation.
        
        Args:
            member: Discord member who joined the guild
        """
        guild = member.guild
        safe_user = self.get_safe_user_info(member)
        logging.debug(f"[NotificationManager] New member detected: {safe_user} in guild {guild.id}")

        is_ptb = await self.is_ptb_guild(guild.id)
        logging.debug(f"[NotificationManager] PTB check for guild {guild.id}: {is_ptb}")
        if is_ptb:
            logging.debug(f"[NotificationManager] Skipping PTB guild {guild.id} - handled by GuildPTB")
            return

        lock_key = f'notification_lock_{guild.id}'
        lock = await self.bot.cache.get('temporary', lock_key)
        if not lock:
            lock = asyncio.Lock()
            await self.bot.cache.set('temporary', lock_key, lock)
        
        async with lock:
            if not await self.check_event_rate_limit(guild.id):
                logging.warning(f"[NotificationManager] Rate limit exceeded for guild {guild.id}")
                return
            
            try:
                await self.bot.cache_loader.ensure_category_loaded('guild_channels')
                channels_data = await self.bot.cache.get_guild_data(guild.id, 'channels')
                logging.debug(f"[NotificationManager] Channels data for guild {guild.id}: {channels_data}")
                notif_channel_id = channels_data.get('notifications_channel') if channels_data else None
                
                logging.debug(f"[NotificationManager] Notification channel ID for guild {guild.id}: {notif_channel_id}")
                if notif_channel_id:
                    channel = await self.get_safe_channel(notif_channel_id)
                    if not channel:
                        logging.warning(f"[NotificationManager] Unable to access notification channel for guild {guild.id}")
                        return
                    
                    guild_lang = await self.get_guild_lang(guild)
                    notif_trans = NOTIFICATION_DATA.get("member_join", {})
                    title = notif_trans.get("title", {}).get(guild_lang, "Welcome!")
                    
                    safe_name = self.sanitize_user_data(member.name)
                    description = notif_trans.get("description", {}).get(guild_lang, "Member {member_mention} joined").format(
                        member_mention=member.mention,
                        member_name=safe_name,
                        member_id=member.id
                    )
                    
                    embed = create_embed(title, description, discord.Color.light_grey(), member)
                    msg = await self.safe_send_notification(channel, embed)
                    
                    if msg:
                        try:
                            insert_query = "INSERT INTO welcome_messages (guild_id, member_id, channel_id, message_id) VALUES (%s, %s, %s, %s)"
                            await self.bot.run_db_query(insert_query, (guild.id, member.id, channel.id, msg.id), commit=True)

                            await self.bot.cache.set_user_data(guild.id, member.id, 'welcome_message', {
                                "channel": channel.id,
                                "message": msg.id
                            })
                            logging.debug(f"[NotificationManager] Welcome message saved for {safe_user} (ID: {msg.id})")
                        except Exception as e:
                            logging.error(f"[NotificationManager] Error saving welcome message to DB: {e}", exc_info=True)
                    else:
                        logging.error(f"[NotificationManager] Failed to send welcome message for {safe_user}")
                else:
                    logging.warning(f"[NotificationManager] Notification channel not configured for guild {guild.id}.")
            except Exception as e:
                logging.error(f"[NotificationManager] Error in on_member_join for {safe_user}: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """
        Handle member leave events with PTB auto-kick and leave notifications.
        
        Args:
            member: Discord member who left the guild
        """
        guild = member.guild
        safe_user = self.get_safe_user_info(member)
        logging.debug(f"[NotificationManager] Departure detected: {safe_user} from guild {guild.id}")

        is_ptb = await self.is_ptb_guild(guild.id)
        logging.debug(f"[NotificationManager] PTB check for guild {guild.id}: {is_ptb}")
        if is_ptb:
            logging.debug(f"[NotificationManager] Skipping PTB guild {guild.id} - handled by GuildPTB")
            return
        
        if not await self.check_event_rate_limit(guild.id):
            logging.warning(f"[NotificationManager] Rate limit exceeded for guild {guild.id}")
            return

        try:
            guild_ptb_cog = self.bot.get_cog("GuildPTB")
            if guild_ptb_cog:
                ptb_guild_id = await self.bot.cache.get_guild_data(guild.id, 'guild_ptb')
                if ptb_guild_id:
                    ptb_guild = self.bot.get_guild(ptb_guild_id)
                    if ptb_guild:
                        ptb_member = ptb_guild.get_member(member.id)
                        if ptb_member:
                            try:
                                await ptb_member.kick(reason=f"Member left main Discord server ({guild.name})")
                                logging.info(f"[NotificationManager] Auto-kicked {safe_user} from PTB guild after leaving main server")
                            except discord.Forbidden:
                                logging.warning(f"[NotificationManager] Cannot kick {safe_user} from PTB guild - insufficient permissions")
                            except Exception as e:
                                logging.error(f"[NotificationManager] Error kicking {safe_user} from PTB guild: {e}")
        except Exception as e:
            logging.error(f"[NotificationManager] Error in PTB auto-kick logic: {e}", exc_info=True)
        
        try:
            guild_lang = await self.get_guild_lang(guild)
            query = "SELECT channel_id, message_id FROM welcome_messages WHERE guild_id = %s AND member_id = %s"
            result = await self.bot.run_db_query(query, (guild.id, member.id), fetch_one=True)
            
            if result:
                channel_id, message_id = result
                channel = await self.get_safe_channel(channel_id)
                
                if channel:
                    try:
                        original_message = await asyncio.wait_for(
                            channel.fetch_message(message_id), timeout=10.0
                        )
                        notif_trans = NOTIFICATION_DATA.get("member_leave", {})
                        title = notif_trans.get("title", {}).get(guild_lang, "Goodbye!")
                        
                        safe_name = self.sanitize_user_data(member.name)
                        description = notif_trans.get("description", {}).get(guild_lang, "Member {member_name} left").format(
                            member_name=safe_name,
                            member_id=member.id
                        )
                        
                        embed = create_embed(title, description, discord.Color.red(), member)
                        await asyncio.wait_for(
                            original_message.reply(embed=embed, mention_author=False),
                            timeout=10.0
                        )
                        logging.debug(f"[NotificationManager] Reply sent to welcome message for {safe_user} (ID: {message_id}) in guild {guild.id}")
                    except (discord.NotFound, asyncio.TimeoutError) as e:
                        logging.warning(f"[NotificationManager] Could not reply to welcome message for {safe_user}: {e}")
                    except Exception as e:
                        logging.error(f"[NotificationManager] Error replying to welcome message for {safe_user}: {e}", exc_info=True)
                
                try:
                    await self.bot.run_db_query(
                        "DELETE FROM welcome_messages WHERE guild_id = %s AND member_id = %s", 
                        (guild.id, member.id), commit=True
                    )
                    await self.bot.run_db_query(
                        "DELETE FROM user_setup WHERE guild_id = %s AND user_id = %s", 
                        (guild.id, member.id), commit=True
                    )
                    await self.bot.run_db_query(
                        "DELETE FROM guild_members WHERE guild_id = %s AND member_id = %s", 
                        (guild.id, member.id), commit=True
                    )
                    await self.bot.run_db_query(
                        "DELETE FROM pending_diplomat_validations WHERE guild_id = %s AND member_id = %s", 
                        (guild.id, member.id), commit=True
                    )

                    await self.bot.cache.delete('user_data', guild.id, member.id, 'welcome_message')
                    await self.bot.cache.delete('user_data', guild.id, member.id, 'setup')

                    pending_validations = await self.bot.cache.get('temporary', 'pending_validations')
                    if pending_validations:
                        keys_to_remove = [key for key in pending_validations.keys() 
                                         if key.split('_')[0] == str(guild.id) and key.split('_')[1] == str(member.id)]
                        for key in keys_to_remove:
                            del pending_validations[key]
                        await self.bot.cache.set('temporary', pending_validations, 'pending_validations')

                    await self.bot.cache.invalidate_category('roster_data')
                    logging.debug(f"[NotificationManager] Invalidated roster_data cache after removing member {safe_user}")
                    logging.debug(f"[NotificationManager] Cleaned up pending diplomat validations for {safe_user}")
                except Exception as e:
                    logging.error(f"[NotificationManager] Error cleaning up DB records for {safe_user}: {e}", exc_info=True)
            else:
                await self.bot.cache_loader.ensure_category_loaded('guild_channels')
                channels_data = await self.bot.cache.get_guild_data(guild.id, 'channels')
                notif_channel_id = channels_data.get('notifications_channel') if channels_data else None
                
                logging.debug(f"[NotificationManager] Notification channel ID for guild {guild.id}: {notif_channel_id}")
                if notif_channel_id:
                    channel = await self.get_safe_channel(notif_channel_id)
                    if channel:
                        notif_trans = NOTIFICATION_DATA.get("member_leave", {})
                        title = notif_trans.get("title", {}).get(guild_lang, "Goodbye!")
                        
                        safe_name = self.sanitize_user_data(member.name)
                        description = notif_trans.get("description", {}).get(guild_lang, "Member {member_name} left").format(
                            member_name=safe_name,
                            member_id=member.id
                        )
                        
                        embed = create_embed(title, description, discord.Color.red(), member)
                        await self.safe_send_notification(channel, embed)

                try:
                    await self.bot.run_db_query(
                        "DELETE FROM pending_diplomat_validations WHERE guild_id = %s AND member_id = %s", 
                        (guild.id, member.id), commit=True
                    )

                    pending_validations = await self.bot.cache.get('temporary', 'pending_validations')
                    if pending_validations:
                        keys_to_remove = [key for key in pending_validations.keys() 
                                         if key.split('_')[0] == str(guild.id) and key.split('_')[1] == str(member.id)]
                        for key in keys_to_remove:
                            del pending_validations[key]
                        await self.bot.cache.set('temporary', pending_validations, 'pending_validations')
                    
                    logging.debug(f"[NotificationManager] Cleaned up pending diplomat validations for {safe_user} (no welcome message case)")
                except Exception as e:
                    logging.error(f"[NotificationManager] Error cleaning up diplomat validations for {safe_user}: {e}", exc_info=True)
                    
        except Exception as e:
            logging.error(f"[NotificationManager] Error in on_member_remove for {safe_user}: {e}", exc_info=True)

def setup(bot: discord.Bot):
    """
    Setup function to add the Notification cog to the bot.
    
    Args:
        bot: Discord bot instance
    """
    bot.add_cog(Notification(bot))

