import discord
import logging
from discord.ext import commands
from typing import Any
import asyncio
import time
import re

def create_embed(title: str, description: str, color: discord.Color, member: discord.Member) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    if member.avatar:
        embed.set_thumbnail(url=member.avatar.url)
    return embed

class Notification(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.notify_channels = {}
        self.member_events = {}
        self.max_events_per_minute = 10
        self.notification_locks = {}
    
    def get_safe_user_info(self, member):
        return f"User{member.id}"
    
    def sanitize_user_data(self, name: str) -> str:
        return re.sub(r'[@#`]', '', name[:100])
    
    def check_event_rate_limit(self, guild_id: int) -> bool:
        now = time.time()
        if guild_id not in self.member_events:
            self.member_events[guild_id] = []
        
        self.member_events[guild_id] = [t for t in self.member_events[guild_id] if now - t < 60]
        
        if len(self.member_events[guild_id]) >= self.max_events_per_minute:
            return False
        
        self.member_events[guild_id].append(now)
        return True
    
    async def get_safe_channel(self, channel_id: int):
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
    
    async def safe_send_notification(self, channel, embed):
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
        asyncio.create_task(self.load_notification_channels())
        logging.debug("[NotificationManager] load_notification_channels task started from on_ready")

    async def load_notification_channels(self) -> None:
        logging.debug("[NotificationManager] Loading notification information from DB")
        query = """
            SELECT gc.guild_id, gc.notifications_channel, gs.guild_lang
            FROM guild_channels gc
            JOIN guild_settings gs ON gc.guild_id = gs.guild_id;
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.notify_channels = {}
            for row in rows:
                guild_id, notif_channel_id, guild_lang = row
                self.notify_channels[guild_id] = {
                    "notif_channel": notif_channel_id,
                    "guild_lang": guild_lang
                }
            logging.debug(f"[NotificationManager] Notification information loaded: {self.notify_channels}")
        except Exception as e:
            logging.error(f"[NotificationManager] Error loading notification information: {e}")

    async def get_guild_lang(self, guild: discord.Guild) -> str:
        info = self.notify_channels.get(guild.id)
        if info and info.get("guild_lang"):
            return info["guild_lang"]
        return "en-US"

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild
        safe_user = self.get_safe_user_info(member)
        logging.debug(f"[NotificationManager] New member detected: {safe_user} in guild {guild.id}")
        
        if guild.id not in self.notification_locks:
            self.notification_locks[guild.id] = asyncio.Lock()
        
        async with self.notification_locks[guild.id]:
            if not self.check_event_rate_limit(guild.id):
                logging.warning(f"[NotificationManager] Rate limit exceeded for guild {guild.id}")
                return
            
            try:
                info = self.notify_channels.get(guild.id)
                if info and info.get("notif_channel"):
                    channel = await self.get_safe_channel(info["notif_channel"])
                    if not channel:
                        logging.warning(f"[NotificationManager] Unable to access notification channel for guild {guild.id}")
                        return
                    
                    guild_lang = await self.get_guild_lang(guild)
                    notif_trans = self.bot.translations["notification"]["member_join"]
                    title = notif_trans["title"][guild_lang]
                    
                    safe_name = self.sanitize_user_data(member.name)
                    description = notif_trans["description"][guild_lang].format(
                        member_mention=member.mention,
                        member_name=safe_name,
                        member_id=member.id
                    )
                    
                    embed = create_embed(title, description, discord.Color.light_grey(), member)
                    msg = await self.safe_send_notification(channel, embed)
                    
                    if msg:
                        try:
                            insert_query = "INSERT INTO welcome_messages (guild_id, member_id, channel_id, message_id) VALUES (?, ?, ?, ?)"
                            await self.bot.run_db_query(insert_query, (guild.id, member.id, channel.id, msg.id), commit=True)
                            logging.debug(f"[NotificationManager] Welcome message saved for {safe_user} (ID: {msg.id})")
                            
                            auto_role_cog = self.bot.get_cog("AutoRole")
                            if auto_role_cog:
                                await auto_role_cog.load_welcome_messages_cache()
                            profile_setup_cog = self.bot.get_cog("ProfileSetup")
                            if profile_setup_cog:
                                await profile_setup_cog.load_welcome_messages_cache()
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
        guild = member.guild
        safe_user = self.get_safe_user_info(member)
        logging.debug(f"[NotificationManager] Departure detected: {safe_user} from guild {guild.id}")
        
        if not self.check_event_rate_limit(guild.id):
            logging.warning(f"[NotificationManager] Rate limit exceeded for guild {guild.id}")
            return
        
        try:
            guild_lang = await self.get_guild_lang(guild)
            query = "SELECT channel_id, message_id FROM welcome_messages WHERE guild_id = ? AND member_id = ?"
            result = await self.bot.run_db_query(query, (guild.id, member.id), fetch_one=True)
            
            if result:
                channel_id, message_id = result
                channel = await self.get_safe_channel(channel_id)
                
                if channel:
                    try:
                        original_message = await asyncio.wait_for(
                            channel.fetch_message(message_id), timeout=10.0
                        )
                        notif_trans = self.bot.translations["notification"]["member_leave"]
                        title = notif_trans["title"][guild_lang]
                        
                        safe_name = self.sanitize_user_data(member.name)
                        description = notif_trans["description"][guild_lang].format(
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
                    delete_query = "DELETE FROM welcome_messages WHERE guild_id = ? AND member_id = ?"
                    await self.bot.run_db_query(delete_query, (guild.id, member.id), commit=True)
                    delete_query = "DELETE FROM user_setup WHERE guild_id = ? AND user_id = ?"
                    await self.bot.run_db_query(delete_query, (guild.id, member.id), commit=True)
                except Exception as e:
                    logging.error(f"[NotificationManager] Error cleaning up DB records for {safe_user}: {e}", exc_info=True)
            else:
                info = self.notify_channels.get(guild.id)
                if info and info.get("notif_channel"):
                    channel = await self.get_safe_channel(info["notif_channel"])
                    if channel:
                        notif_trans = self.bot.translations["notification"]["member_leave"]
                        title = notif_trans["title"][guild_lang]
                        
                        safe_name = self.sanitize_user_data(member.name)
                        description = notif_trans["description"][guild_lang].format(
                            member_name=safe_name,
                            member_id=member.id
                        )
                        
                        embed = create_embed(title, description, discord.Color.red(), member)
                        await self.safe_send_notification(channel, embed)
        except Exception as e:
            logging.error(f"[NotificationManager] Error in on_member_remove for {safe_user}: {e}", exc_info=True)

def setup(bot: discord.Bot):
    bot.add_cog(Notification(bot))
