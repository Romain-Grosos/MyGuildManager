import discord
import logging
from discord.ext import commands
import asyncio

class AbsenceManager(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.abs_channels = {}

    @commands.Cog.listener()
    async def on_ready(self):
        asyncio.create_task(self.load_absence_channels())
        logging.debug("[AbsenceManager] 'load_absence_channels' task started from cog load.")

    async def load_absence_channels(self) -> None:
        logging.debug("[AbsenceManager] Loading absence channels from the database.")
        query = """
            SELECT gc.guild_id, gc.abs_channel, gc.forum_members_channel, gs.guild_lang
            FROM guild_channels gc
            JOIN guild_settings gs ON gc.guild_id = gs.guild_id;
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            if rows:
                for row in rows:
                    guild_id, abs_channel_id, forum_members_channel_id, guild_lang = row
                    self.abs_channels[guild_id] = {
                        "abs_channel": abs_channel_id,
                        "forum_members_channel": forum_members_channel_id,
                        "guild_lang": guild_lang
                    }
                logging.debug(f"[AbsenceManager] Absence channels loaded: {self.abs_channels}")
            else:
                logging.warning("[AbsenceManager] No absence channels found in the database.")
        except Exception as e:
            logging.error(f"[AbsenceManager] Error loading absence channels: {e}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.webhook_id is not None:
            return

        guild = message.guild
        channels = self.abs_channels.get(guild.id)
        if not channels or message.channel.id != channels.get("abs_channel"):
            return

        member = guild.get_member(message.author.id)
        if not member:
            return

        query = "SELECT members, absent_members FROM guild_roles WHERE guild_id = ?"
        result = await self.bot.run_db_query(query, (guild.id,), fetch_one=True)
        role_member = role_absent = None
        if result:
            role_member_id, role_absent_id = result
            role_member = guild.get_role(role_member_id)
            role_absent = guild.get_role(role_absent_id)
        else:
            logging.warning(f"[AbsenceManager] No roles found for guild {guild.id}.")

        if role_absent and role_member:
            if role_member in member.roles:
                try:
                    await member.remove_roles(role_member)
                except Exception as e:
                    logging.error(f"[AbsenceManager] Error removing member role from {member.name}: {e}")
            if role_absent not in member.roles:
                try:
                    await member.add_roles(role_absent)
                    logging.debug(f"[AbsenceManager] ✅ 'Absent Members' role assigned to {member.name} in guild {guild.id}.")
                    await self.notify_absence(member, "addition", channels.get("forum_members_channel"), channels.get("guild_lang"))
                except Exception as e:
                    logging.error(f"[AbsenceManager] Error adding absent role to {member.name}: {e}")

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.author.bot or message.webhook_id is not None:
            return

        guild = message.guild
        channels = self.abs_channels.get(guild.id)
        if not channels or message.channel.id != channels.get("abs_channel"):
            return

        member = guild.get_member(message.author.id)
        if not member:
            return

        query = "SELECT members, absent_members FROM guild_roles WHERE guild_id = ?"
        result = await self.bot.run_db_query(query, (guild.id,), fetch_one=True)
        role_member = role_absent = None
        if result:
            role_member_id, role_absent_id = result
            role_member = guild.get_role(role_member_id)
            role_absent = guild.get_role(role_absent_id)
        else:
            logging.warning(f"[AbsenceManager] No roles found for guild {guild.id}.")

        if role_absent and role_member:
            if role_absent in member.roles:
                try:
                    await member.remove_roles(role_absent)
                except Exception as e:
                    logging.error(f"[AbsenceManager] Error removing absent role from {member.name}: {e}")
            if role_member not in member.roles:
                try:
                    await member.add_roles(role_member)
                    logging.debug(f"[AbsenceManager] ✅ 'Members' role restored for {member.name} in guild {guild.id}.")
                    await self.notify_absence(member, "removal", channels.get("forum_members_channel"), channels.get("guild_lang"))
                except Exception as e:
                    logging.error(f"[AbsenceManager] Error adding member role to {member.name}: {e}")

    async def notify_absence(self, member: discord.Member, action: str, channel_id: int, guild_lang: str) -> None:
        try:
            channel = await self.bot.fetch_channel(channel_id)
        except Exception as e:
            logging.error(f"[AbsenceManager] ❌ Error fetching notification channel: {e}")
            return

        if not channel:
            logging.error("[AbsenceManager] ❌ Failed to access the members notification channel.")
            return

        absence_translations = self.bot.translations.get("absence", {})
        title = absence_translations.get("title", {}).get(guild_lang, "Notification")
        member_label = absence_translations.get("member_label", {}).get(guild_lang, "Member")
        status_label = absence_translations.get("status_label", {}).get(guild_lang, "Status")
        absent_text = absence_translations.get("absent", {}).get(guild_lang, "Absent")
        returned_text = absence_translations.get("returned", {}).get(guild_lang, "Returned")

        status_text = absent_text if action == "addition" else returned_text

        embed = discord.Embed(
            title=title,
            color=discord.Color.orange() if action == "addition" else discord.Color.green()
        )
        embed.add_field(
            name=member_label,
            value=f"{member.mention} ({member.name})",
            inline=True
        )
        embed.add_field(
            name=status_label,
            value=status_text,
            inline=True
        )
        try:
            await channel.send(embed=embed)
            logging.debug(f"[AbsenceManager] ✅ Notification sent for {member.name} ({status_text}).")
        except Exception as e:
            logging.error(f"[AbsenceManager] ❌ Error sending notification for {member.name}: {e}")

def setup(bot: discord.Bot):
    bot.add_cog(AbsenceManager(bot))