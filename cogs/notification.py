import discord
import logging
from discord.ext import commands
from typing import Any
import asyncio

def create_embed(title: str, description: str, color: discord.Color, member: discord.Member) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    if member.avatar:
        embed.set_thumbnail(url=member.avatar.url)
    return embed

class Notification(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.notif_channels = {}

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
            self.notif_channels = {}
            for row in rows:
                guild_id, notif_channel_id, guild_lang = row
                self.notif_channels[guild_id] = {
                    "notif_channel": notif_channel_id,
                    "guild_lang": guild_lang
                }
            logging.debug(f"[NotificationManager] Notification information loaded: {self.notif_channels}")
        except Exception as e:
            logging.error(f"[NotificationManager] Error loading notification information: {e}")

    async def get_guild_lang(self, guild: discord.Guild) -> str:
        info = self.notif_channels.get(guild.id)
        if info and info.get("guild_lang"):
            return info["guild_lang"]
        return "en-US"

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild
        logging.debug(f"[NotificationManager] New member detected: {member.name} ({member.id}) in guild {guild.id}")
        try:
            info = self.notif_channels.get(guild.id)
            if info and info.get("notif_channel"):
                channel = await self.bot.fetch_channel(info["notif_channel"])
                guild_lang = await self.get_guild_lang(guild)
                notif_trans = self.bot.translations["notification"]["member_join"]
                title = notif_trans["title"][guild_lang]
                description = notif_trans["description"][guild_lang].format(
                    member_mention=member.mention,
                    member_name=member.name,
                    member_id=member.id
                )
                embed = create_embed(title, description, discord.Color.light_grey(), member)
                msg = await channel.send(embed=embed)
                insert_query = "INSERT INTO welcome_messages (guild_id, member_id, channel_id, message_id) VALUES (?, ?, ?, ?)"
                await self.bot.run_db_query(insert_query, (guild.id, member.id, channel.id, msg.id), commit=True)
                logging.debug(f"[NotificationManager] Welcome message saved for {member.name} (ID: {msg.id})")
                autorole_cog = self.bot.get_cog("AutoRole")
                if autorole_cog:
                    await autorole_cog.load_welcome_messages_cache()
                profilesetup_cog = self.bot.get_cog("ProfileSetup")
                if profilesetup_cog:
                    await profilesetup_cog.load_welcome_messages_cache()
            else:
                logging.warning(f"[NotificationManager] Notification channel not configured for guild {guild.id}.")
        except Exception as e:
            logging.error("[NotificationManager] Error in on_member_join", exc_info=True)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        guild = member.guild
        logging.debug(f"[NotificationManager] Departure detected: {member.name} ({member.id}) from guild {guild.id}")
        try:
            guild_lang = await self.get_guild_lang(guild)
            query = "SELECT channel_id, message_id FROM welcome_messages WHERE guild_id = ? AND member_id = ?"
            result = await self.bot.run_db_query(query, (guild.id, member.id), fetch_one=True)
            if result:
                channel_id, message_id = result
                channel = await self.bot.fetch_channel(channel_id)
                original_message = await channel.fetch_message(message_id)
                notif_trans = self.bot.translations["notification"]["member_leave"]
                title = notif_trans["title"][guild_lang]
                description = notif_trans["description"][guild_lang].format(
                    member_name=member.name,
                    member_id=member.id
                )
                embed = create_embed(title, description, discord.Color.red(), member)
                await original_message.reply(embed=embed, mention_author=False)
                logging.debug(f"[NotificationManager] Reply sent to welcome message for {member.name} (ID: {message_id}) in guild {guild.id}")
                delete_query = "DELETE FROM welcome_messages WHERE guild_id = ? AND member_id = ?"
                await self.bot.run_db_query(delete_query, (guild.id, member.id), commit=True)
                delete_query = "DELETE FROM user_setup WHERE guild_id = ? AND user_id = ?"
                await self.bot.run_db_query(delete_query, (guild.id, member.id), commit=True)
            else:
                info = self.notif_channels.get(guild.id)
                if info and info.get("notif_channel"):
                    channel = await self.bot.fetch_channel(info["notif_channel"])
                    notif_trans = self.bot.translations["notification"]["member_leave"]
                    title = notif_trans["title"][guild_lang]
                    description = notif_trans["description"][guild_lang].format(
                        member_name=member.name,
                        member_id=member.id
                    )
                    embed = create_embed(title, description, discord.Color.red(), member)
                    await channel.send(embed=embed)
        except Exception as e:
            logging.error("[NotificationManager] Error in on_member_remove", exc_info=True)

def setup(bot: discord.Bot):
    bot.add_cog(Notification(bot))
