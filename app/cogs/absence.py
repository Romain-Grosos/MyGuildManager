"""
Absence Manager Cog - Manages member absence status and notifications.
"""

import asyncio
import logging

import discord
from discord.ext import commands

from ..core.translation import translations as global_translations

ABSENCE_TRANSLATIONS = global_translations.get("absence", {})

class AbsenceManager(commands.Cog):
    """Cog for managing member absence status and notifications."""
    
    def __init__(self, bot: commands.Bot) -> None:
        """
        Initialize the AbsenceManager cog.
        
        Args:
            bot: Discord bot instance
        """
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Initialize absence data on bot ready."""
        asyncio.create_task(self.load_absence_channels())
        logging.debug("[AbsenceManager] Load absence channels task started")

    async def _get_guild_roles(self, guild: discord.Guild) -> "tuple[discord.Role | None, discord.Role | None]":
        """
        Get member and absent roles for a guild from cache.
        
        Args:
            guild: Discord guild to get roles for
            
        Returns:
            Tuple of (member_role, absent_role) or (None, None) if not found
        """
        role_data = await self.bot.cache.get_guild_data(guild.id, 'roles')
        if not role_data:
            return None, None
        
        role_member = guild.get_role(role_data.get("members"))
        role_absent = guild.get_role(role_data.get("absent_members"))
        
        if role_member is None or role_absent is None:
            logging.warning("[AbsenceManager] Roles missing in guild %s", guild.id)
            return None, None
        return role_member, role_absent

    async def load_absence_channels(self) -> None:
        """Ensure all required data is loaded via centralized cache loader."""
        logging.debug("[AbsenceManager] Ensuring required data is loaded")
        
        await self.bot.cache_loader.ensure_category_loaded('guild_channels')
        await self.bot.cache_loader.ensure_category_loaded('guild_roles')
        await self.bot.cache_loader.ensure_category_loaded('guild_settings')
        await self.bot.cache_loader.ensure_category_loaded('absence_messages')
        
        logging.debug("[AbsenceManager] Required data loading completed")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Handle absence messages posted in absence channels."""
        if message.author.bot or message.webhook_id is not None:
            return

        guild = message.guild
        channels = await self.bot.cache.get_guild_data(guild.id, 'absence_channels')
        if not channels or message.channel.id != channels.get("abs_channel"):
            return

        member = guild.get_member(message.author.id)
        if not member:
            return

        role_member, role_absent = await self._get_guild_roles(guild)
        if not role_member or not role_absent:
            return

        if role_absent and role_member:
            if role_member in member.roles:
                try:
                    await member.remove_roles(role_member)
                except Exception as e:
                    logging.error(f"[AbsenceManager] Error removing member role from {member.name}: {e}")
            if role_absent not in member.roles:
                try:
                    await member.add_roles(role_absent)
                    logging.debug(f"[AbsenceManager] Absent Members role assigned to {member.name} in guild {guild.id}")

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
                        logging.error("[AbsenceManager] Error saving absence message: %s", e)

                    guild_lang = await self.bot.cache.get_guild_data(guild.id, 'guild_lang') or "en-US"
                    await self.notify_absence(member, "addition", channels.get("forum_members_channel"), guild_lang)
                except Exception as e:
                    logging.error(f"[AbsenceManager] Error adding absent role to {member.name}: {e}")

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        """Handle absence message deletion and role restoration."""
        cfg = await self.bot.cache.get_guild_data(payload.guild_id, 'absence_channels')
        if not cfg or payload.channel_id != cfg.get("abs_channel"):
            return

        try:
            row = await self.bot.run_db_query(
                "SELECT member_id FROM absence_messages "
                "WHERE guild_id = %s AND message_id = %s",
                (payload.guild_id, payload.message_id),
                fetch_one=True
            )
        except Exception as e:
            logging.error("[AbsenceManager] DB error fetching absence message: %s", e)
            return

        if not row:
            logging.debug("[AbsenceManager] Absence message not found in DB.")
            return

        member_id = row[0]
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            logging.warning("[AbsenceManager] Guild %s not found", payload.guild_id)
            return
            
        member = guild.get_member(member_id)
        if not member:
            logging.debug("[AbsenceManager] Member %s not found in guild %s", member_id, guild.id)
            return

        role_member, role_absent = await self._get_guild_roles(guild)
        if not role_member or not role_absent:
            return

        try:
            await self.bot.run_db_query(
                "DELETE FROM absence_messages WHERE guild_id = %s AND message_id = %s",
                (payload.guild_id, payload.message_id), commit=True
            )
        except Exception as e:
            logging.error("[AbsenceManager] Error deleting absence record: %s", e)
            return

        try:
            row = await self.bot.run_db_query(
                "SELECT COUNT(*) FROM absence_messages "
                "WHERE guild_id = %s AND member_id = %s",
                (payload.guild_id, member_id), fetch_one=True
            )
        except Exception as e:
            logging.error("[AbsenceManager] Error checking remaining absence messages: %s", e)
            return
        if row and row[0] > 0:
            logging.debug("[AbsenceManager] Other absence messages remain for %s, keeping 'absent' role.", member.name)
            return

        if role_absent in member.roles:
            try:
                await member.remove_roles(role_absent)
            except Exception as e:
                logging.error("[AbsenceManager] Error removing absent role: %s", e)
        if role_member and role_member not in member.roles:
            try:
                await member.add_roles(role_member)
                guild_lang = await self.bot.cache.get_guild_data(member.guild.id, 'guild_lang') or "en-US"
                await self.notify_absence( member, "removal", cfg["forum_members_channel"], guild_lang)
            except Exception as e:
                logging.error("[AbsenceManager] Error adding member role: %s", e)

    async def _set_absent(self,
                        guild: discord.Guild,
                        member: discord.Member,
                        channel: discord.TextChannel,
                        reason_message: str) -> None:
        """
        Set a member as absent with proper role management and database tracking.
        
        Args:
            guild: Discord guild where the member is located
            member: Discord member to mark as absent
            channel: Text channel to post absence message
            reason_message: Message to post in the absence channel
        """
        role_member, role_absent = await self._get_guild_roles(guild)
        if not role_member or not role_absent:
            return

        try:
            if role_member in member.roles:
                await member.remove_roles(role_member)
            if role_absent not in member.roles:
                await member.add_roles(role_absent)
        except Exception as e:
            logging.error("[AbsenceManager] Error switching roles: %s", e)
            return

        try:
            sent = await channel.send(reason_message)
        except Exception as e:
            logging.error("[AbsenceManager] Can't post absence message: %s", e)
            return

        try:
            await self.bot.run_db_query(
                "INSERT INTO absence_messages (guild_id, message_id, member_id) "
                "VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE created_at = NOW()",
                (guild.id, sent.id, member.id), commit=True
            )
        except Exception as e:
            logging.error("[AbsenceManager] Error saving absence entry: %s", e)

        cfg = await self.bot.cache.get_guild_data(guild.id, 'absence_channels')
        if not cfg:
            logging.error("[AbsenceManager] Guild config not found for guild %s", guild.id)
            return
        guild_lang = await self.bot.cache.get_guild_data(member.guild.id, 'guild_lang') or "en-US"
        await self.notify_absence(member, "addition",
                                cfg["forum_members_channel"],
                                guild_lang)

    @commands.slash_command(
        name=ABSENCE_TRANSLATIONS.get("command", {}).get("name", {}).get("en-US", "absence_add"),
        description=ABSENCE_TRANSLATIONS.get("command", {}).get("description", {}).get("en-US", "Mark a member as absent."),
        name_localizations=ABSENCE_TRANSLATIONS.get("command", {}).get("name", {}),
        description_localizations=ABSENCE_TRANSLATIONS.get("command", {}).get("description", {})
    )
    @commands.has_permissions(manage_guild=True)
    async def absence_add(
        self,
        ctx: discord.ApplicationContext,
        member: discord.Member,
        return_date: str | None = None
    ):
        """
        Command to manually mark a member as absent.
        
        Args:
            ctx: Discord application context
            member: Discord member to mark as absent
            return_date: Optional return date for the absence
        """
        await ctx.defer(ephemeral=True)

        loc = ctx.locale or "en-US"

        cfg = await self.bot.cache.get_guild_data(ctx.guild_id, 'absence_channels')
        if not cfg:
            msg = ABSENCE_TRANSLATIONS["error_chan"].get(loc,ABSENCE_TRANSLATIONS["error_chan"]["en-US"])
            await ctx.respond(msg, ephemeral=True)
            return

        abs_chan = ctx.guild.get_channel(cfg["abs_channel"])
        if abs_chan is None:
            msg = ABSENCE_TRANSLATIONS["error_chan"].get(loc,ABSENCE_TRANSLATIONS["error_chan"]["en-US"])
            await ctx.respond(msg, ephemeral=True)
            return
        
        lang = await self.bot.cache.get_guild_data(ctx.guild.id, 'guild_lang') or "en-US"

        reason_text = ABSENCE_TRANSLATIONS["away_ok"].get(lang, ABSENCE_TRANSLATIONS["away_ok"]["en-US"]).format(member=member.display_name)
        if return_date:
            back_text = ABSENCE_TRANSLATIONS["back_time"].get(lang, ABSENCE_TRANSLATIONS["back_time"]["en-US"]).format(return_date=return_date)
            reason_text = f"{reason_text} {back_text}"

        await self._set_absent(ctx.guild, member, abs_chan, reason_text)
        resp = ABSENCE_TRANSLATIONS["absence_ok"].get(loc,ABSENCE_TRANSLATIONS["absence_ok"]["en-US"]).format(member=member)
        await ctx.respond(resp, ephemeral=True)

    async def notify_absence(self, member: discord.Member, action: str, channel_id: int, guild_lang: str) -> None:
        """
        Send absence notification to the designated forum channel.
        
        Args:
            member: Discord member whose absence status changed
            action: Type of action ('addition' or 'removal')
            channel_id: ID of the notification channel
            guild_lang: Guild language for localized messages
        """
        channel = self.bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception as e:
                logging.error(f"[AbsenceManager] Error fetching notification channel: {e}")
                return

        if not channel:
            logging.error("[AbsenceManager] Failed to access the members notification channel.")
            return

        title = ABSENCE_TRANSLATIONS.get("title", {}).get(guild_lang, "Notification")
        member_label = ABSENCE_TRANSLATIONS.get("member_label", {}).get(guild_lang, "Member")
        status_label = ABSENCE_TRANSLATIONS.get("status_label", {}).get(guild_lang, "Status")
        absent_text = ABSENCE_TRANSLATIONS.get("absent", {}).get(guild_lang, "Absent")
        returned_text = ABSENCE_TRANSLATIONS.get("returned", {}).get(guild_lang, "Returned")

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
            logging.debug(f"[AbsenceManager] Notification sent for {member.name} ({status_text}).")
        except Exception as e:
            logging.error(f"[AbsenceManager] Error sending notification for {member.name}: {e}")

def setup(bot: discord.Bot):
    """
    Setup function to add the AbsenceManager cog to the bot.
    
    Args:
        bot: Discord bot instance
    """
    bot.add_cog(AbsenceManager(bot))
