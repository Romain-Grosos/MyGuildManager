"""
Absence Manager Cog - Manages member absence status and notifications.
"""

import asyncio
import logging

import discord
from discord.ext import commands

from core.translation import translations as global_translations
from core.functions import get_user_message, get_guild_message

ABSENCE_TRANSLATIONS = global_translations.get("absence_system", {}).get("messages", {})
logging.debug(f"[AbsenceManager] Loaded ABSENCE_TRANSLATIONS keys: {list(ABSENCE_TRANSLATIONS.keys())}")
if "title" in ABSENCE_TRANSLATIONS:
    logging.debug(f"[AbsenceManager] Title translation keys: {list(ABSENCE_TRANSLATIONS['title'].keys())}")
else:
    logging.error(f"[AbsenceManager] No 'title' key in ABSENCE_TRANSLATIONS!")
    logging.debug(f"[AbsenceManager] Full absence_system structure: {list(global_translations.get('absence_system', {}).keys())}")

class AbsenceManager(commands.Cog):
    """Cog for managing member absence status and notifications."""
    
    def __init__(self, bot: commands.Bot) -> None:
        """
        Initialize the AbsenceManager cog.
        
        Args:
            bot: Discord bot instance
        """
        self.bot = bot

        self._register_absence_commands()
    
    def _register_absence_commands(self):
        """Register absence commands with the centralized absence group."""
        if hasattr(self.bot, 'absence_group'):
            self.bot.absence_group.command(
                name=ABSENCE_TRANSLATIONS.get("absence_add", {}).get("name", {}).get("en-US", "absence_add"),
                description=ABSENCE_TRANSLATIONS.get("absence_add", {}).get("description", {}).get("en-US", "Mark a member as absent."),
                name_localizations=ABSENCE_TRANSLATIONS.get("absence_add", {}).get("name", {}),
                description_localizations=ABSENCE_TRANSLATIONS.get("absence_add", {}).get("description", {})
            )(self.absence_add)

            self.bot.absence_group.command(
                name=ABSENCE_TRANSLATIONS.get("return", {}).get("name", {}).get("en-US", "return"),
                description=ABSENCE_TRANSLATIONS.get("return", {}).get("description", {}).get("en-US", "Signal your return from absence."),
                name_localizations=ABSENCE_TRANSLATIONS.get("return", {}).get("name", {}),
                description_localizations=ABSENCE_TRANSLATIONS.get("return", {}).get("description", {})
            )(self.absence_remove)

    @commands.Cog.listener()
    async def on_ready(self):
        """Wait for centralized cache load to complete."""
        asyncio.create_task(self.bot.cache_loader.wait_for_initial_load())
        logging.debug("[AbsenceManager] Waiting for initial cache load")

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
                await self.notify_absence(member, "removal", cfg["forum_members_channel"], guild_lang)
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

        cfg = await self.bot.cache.get_guild_data(ctx.guild_id, 'absence_channels')
        if not cfg:
            msg = await get_user_message(ctx, global_translations.get("absence_system", {}), "error_chan")
            await ctx.respond(msg, ephemeral=True)
            return

        abs_chan = ctx.guild.get_channel(cfg["abs_channel"])
        if abs_chan is None:
            msg = await get_user_message(ctx, global_translations.get("absence_system", {}), "error_chan")
            await ctx.respond(msg, ephemeral=True)
            return
        
        guild_lang = await self.bot.cache.get_guild_data(ctx.guild.id, 'guild_lang') or "en-US"
        logging.debug(f"[AbsenceManager] Guild lang: {guild_lang}, Available translations: {list(ABSENCE_TRANSLATIONS.get('away_ok', {}).keys())}")
        reason_text = ABSENCE_TRANSLATIONS.get("away_ok", {}).get(guild_lang, ABSENCE_TRANSLATIONS.get("away_ok", {}).get("en-US", "**{member}** is now marked as away.")).format(member=member.display_name)
        logging.debug(f"[AbsenceManager] reason_text: {reason_text}")
        if return_date:
            back_text = ABSENCE_TRANSLATIONS.get("back_time", {}).get(guild_lang, ABSENCE_TRANSLATIONS.get("back_time", {}).get("en-US", "Expected return: {return_date}")).format(return_date=return_date)
            reason_text = f"{reason_text} {back_text}"

        await self._set_absent(ctx.guild, member, abs_chan, reason_text)
        resp = await get_user_message(ctx, global_translations.get("absence_system", {}), "messages.absence_ok", member_mention=member.mention)
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

        guild_lang = await self.bot.cache.get_guild_data(member.guild.id, 'guild_lang') or "en-US"
        logging.debug(f"[AbsenceManager] Embed guild_lang: {guild_lang}, Available title translations: {list(ABSENCE_TRANSLATIONS.get('title', {}).keys())}")
        title = ABSENCE_TRANSLATIONS.get("title", {}).get(guild_lang, ABSENCE_TRANSLATIONS.get("title", {}).get("en-US", "📢 Member status update"))
        logging.debug(f"[AbsenceManager] Retrieved title: {title}")
        member_label = ABSENCE_TRANSLATIONS.get("member_label", {}).get(guild_lang, ABSENCE_TRANSLATIONS.get("member_label", {}).get("en-US", "Member"))
        status_label = ABSENCE_TRANSLATIONS.get("status_label", {}).get(guild_lang, ABSENCE_TRANSLATIONS.get("status_label", {}).get("en-US", "Status"))
        absent_text = ABSENCE_TRANSLATIONS.get("absent", {}).get(guild_lang, ABSENCE_TRANSLATIONS.get("absent", {}).get("en-US", "🚨 Absent"))
        returned_text = ABSENCE_TRANSLATIONS.get("returned", {}).get(guild_lang, ABSENCE_TRANSLATIONS.get("returned", {}).get("en-US", "✅ Returned"))

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

    async def absence_remove(self, ctx: discord.ApplicationContext):
        """
        Allow members to signal their return from absence.
        
        This command removes the absent role from the member and restores
        their normal member role, then sends a notification.
        
        Args:
            ctx: Discord application context
        """
        await ctx.defer(ephemeral=True)
        
        guild = ctx.guild
        member = ctx.author
        
        try:
            role_member, role_absent = await self._get_guild_roles(guild)
            if not role_member or not role_absent:
                error_msg = await get_user_message(ctx, global_translations.get("absence_system", {}), "error.roles_not_configured")
                await ctx.followup.send(error_msg, ephemeral=True)
                return

            if role_absent not in member.roles:
                error_msg = await get_user_message(ctx, global_translations.get("absence_system", {}), "error.not_absent")
                await ctx.followup.send(error_msg, ephemeral=True)
                return

            try:
                await member.remove_roles(role_absent)
                logging.debug(f"[AbsenceManager] Removed absent role from {member.name}")
                
                if role_member not in member.roles:
                    await member.add_roles(role_member)
                    logging.debug(f"[AbsenceManager] Added member role to {member.name}")

                try:
                    select_query = "SELECT message_id FROM absence_messages WHERE guild_id = %s AND member_id = %s"
                    message_ids = await self.bot.run_db_query(select_query, (guild.id, member.id), fetch_all=True)

                    if message_ids:
                        channels_data = await self.bot.cache.get_guild_data(guild.id, 'absence_channels')
                        if channels_data and channels_data.get('abs_channel'):
                            abs_channel = self.bot.get_channel(channels_data['abs_channel'])
                            if abs_channel:
                                for row in message_ids:
                                    message_id = row[0]
                                    try:
                                        message = await abs_channel.fetch_message(message_id)
                                        await message.delete()
                                        logging.debug(f"[AbsenceManager] Deleted absence message {message_id}")
                                    except discord.NotFound:
                                        logging.debug(f"[AbsenceManager] Absence message {message_id} already deleted")
                                    except Exception as msg_error:
                                        logging.error(f"[AbsenceManager] Error deleting message {message_id}: {msg_error}")

                    delete_query = "DELETE FROM absence_messages WHERE guild_id = %s AND member_id = %s"
                    await self.bot.run_db_query(delete_query, (guild.id, member.id), commit=True)
                    logging.debug(f"[AbsenceManager] Removed absence record for {member.name}")
                except Exception as db_error:
                    logging.error(f"[AbsenceManager] Error removing absence record: {db_error}")

                channels_data = await self.bot.cache.get_guild_data(guild.id, 'absence_channels')
                
                if channels_data and channels_data.get('forum_members_channel'):
                    guild_lang = await self.bot.cache.get_guild_data(guild.id, 'guild_lang') or "en-US"
                    
                    await self.notify_absence(member, "removal", 
                                            channels_data['forum_members_channel'], 
                                            guild_lang)
                
                success_msg = await get_user_message(ctx, global_translations.get("absence_system", {}), "success.returned")
                await ctx.followup.send(success_msg, ephemeral=True)
                
            except discord.Forbidden:
                error_msg = await get_user_message(ctx, global_translations.get("absence_system", {}), "error.no_permission")
                await ctx.followup.send(error_msg, ephemeral=True)
            except Exception as role_error:
                logging.error(f"[AbsenceManager] Error managing roles for {member.name}: {role_error}")
                error_msg = await get_user_message(ctx, global_translations.get("absence_system", {}), "error.role_management")
                await ctx.followup.send(error_msg, ephemeral=True)
                
        except Exception as e:
            logging.error(f"[AbsenceManager] Error in absence_remove for {member.name}: {e}")
            error_msg = await get_user_message(ctx, global_translations.get("absence_system", {}), "error.general")
            await ctx.followup.send(error_msg, ephemeral=True)

def setup(bot: discord.Bot):
    """
    Setup function to add the AbsenceManager cog to the bot.
    
    Args:
        bot: Discord bot instance
    """
    bot.add_cog(AbsenceManager(bot))
