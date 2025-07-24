import discord
import logging
from discord.ext import commands
import asyncio
from translation import translations as global_translations

ABSENCE_TRANSLATIONS = global_translations.get("absence", {})
class AbsenceManager(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.abs_channels: dict[int, dict[str, int]] = {}
        self.role_ids: dict[int, dict[str, int]] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        asyncio.create_task(self.load_absence_channels())
        logging.debug("[AbsenceManager] 'load_absence_channels' task started from cog load.")

    def _get_guild_roles(self, guild: discord.Guild) -> tuple[discord.Role | None, discord.Role | None]:
        roles = self.role_ids.get(guild.id, {})
        role_member = guild.get_role(roles.get("member"))
        role_absent = guild.get_role(roles.get("absent"))
        if role_member is None or role_absent is None:
            logging.warning("[AbsenceManager] Roles missing in guild %s", guild.id)
            return None, None
        return role_member, role_absent

    async def load_absence_channels(self) -> None:
        logging.debug("[AbsenceManager] Loading absence channels from the database.")
        query = """
            SELECT gc.guild_id, gc.abs_channel, gc.forum_members_channel,
                gs.guild_lang, gr.members, gr.absent_members
            FROM guild_channels gc
            JOIN guild_settings gs ON gc.guild_id = gs.guild_id
            JOIN guild_roles    gr ON gc.guild_id = gr.guild_id;
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            if rows:
                for row in rows:
                    guild_id, abs_channel_id, forum_members_channel_id, guild_lang, role_member_id, role_absent_id = row
                    self.abs_channels[guild_id] = {
                        "abs_channel": abs_channel_id,
                        "forum_members_channel": forum_members_channel_id,
                        "guild_lang": guild_lang
                    }
                    self.role_ids[guild_id] = {"member": role_member_id, "absent": role_absent_id}
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

        role_member, role_absent = self._get_guild_roles(guild)
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
                    logging.debug(f"[AbsenceManager] ✅ 'Absent Members' role assigned to {member.name} in guild {guild.id}.")

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

                    await self.notify_absence(member, "addition", channels.get("forum_members_channel"), channels.get("guild_lang"))
                except Exception as e:
                    logging.error(f"[AbsenceManager] Error adding absent role to {member.name}: {e}")

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        cfg = self.abs_channels.get(payload.guild_id)
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

        role_member, role_absent = self._get_guild_roles(guild)
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
                await self.notify_absence( member, "removal", cfg["forum_members_channel"], cfg["guild_lang"])
            except Exception as e:
                logging.error("[AbsenceManager] Error adding member role: %s", e)

    async def _set_absent(self,
                        guild: discord.Guild,
                        member: discord.Member,
                        channel: discord.TextChannel,
                        reason_message: str) -> None:
        role_member, role_absent = self._get_guild_roles(guild)
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

        cfg = self.abs_channels.get(guild.id)
        if not cfg:
            logging.error("[AbsenceManager] Guild config not found for guild %s", guild.id)
            return
        await self.notify_absence(member, "addition",
                                cfg["forum_members_channel"],
                                cfg["guild_lang"])

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
        await ctx.defer(ephemeral=True)

        loc = ctx.locale or "en-US"

        cfg = self.abs_channels.get(ctx.guild_id)
        if not cfg:
            msg = ABSENCE_TRANSLATIONS["error_chan"].get(loc,ABSENCE_TRANSLATIONS["error_chan"]["en-US"])
            await ctx.respond(msg, ephemeral=True)
            return

        abs_chan = ctx.guild.get_channel(cfg["abs_channel"])
        if abs_chan is None:
            msg = ABSENCE_TRANSLATIONS["error_chan"].get(loc,ABSENCE_TRANSLATIONS["error_chan"]["en-US"])
            await ctx.respond(msg, ephemeral=True)
            return
        
        lang = cfg.get("guild_lang") or "en-US"

        reason_text = ABSENCE_TRANSLATIONS["away_ok"].get(lang, ABSENCE_TRANSLATIONS["away_ok"]["en-US"]).format(member=member.display_name)
        if return_date:
            back_text = ABSENCE_TRANSLATIONS["back_time"].get(lang, ABSENCE_TRANSLATIONS["back_time"]["en-US"]).format(return_date=return_date)
            reason_text = f"{reason_text} {back_text}"

        await self._set_absent(ctx.guild, member, abs_chan, reason_text)
        resp = ABSENCE_TRANSLATIONS["absence_ok"].get(loc,ABSENCE_TRANSLATIONS["absence_ok"]["en-US"]).format(member=member)
        await ctx.respond(resp, ephemeral=True)

    async def notify_absence(self, member: discord.Member, action: str, channel_id: int, guild_lang: str) -> None:
        channel = self.bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception as e:
                logging.error(f"[AbsenceManager] ❌ Error fetching notification channel: {e}")
                return

        if not channel:
            logging.error("[AbsenceManager] ❌ Failed to access the members notification channel.")
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
            logging.debug(f"[AbsenceManager] ✅ Notification sent for {member.name} ({status_text}).")
        except Exception as e:
            logging.error(f"[AbsenceManager] ❌ Error sending notification for {member.name}: {e}")

def setup(bot: discord.Bot):
    bot.add_cog(AbsenceManager(bot))