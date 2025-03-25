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
        # Charger les canaux d'absences depuis la BDD au démarrage
        asyncio.create_task(self.load_absence_channels())
        logging.debug("[AbsenceManager] Tâche load_absence_channels lancée depuis cog_load")

    async def load_absence_channels(self) -> None:
        """Charge depuis la BDD les ID des canaux d'absences pour chaque guilde."""
        logging.debug("[AbsenceManager] Chargement des canaux d'absences depuis la BDD")
        query = """
            SELECT gc.guild_id, gc.abs_channel, gc.forum_members_channel, gs.guild_lang
            FROM guild_channels gc
            JOIN guild_settings gs ON gc.guild_id = gs.guild_id;
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            for row in rows:
                guild_id, abs_channel_id, forum_members_channel_id, guild_lang = row
                self.abs_channels[guild_id] = {
                    "abs_channel": abs_channel_id,
                    "forum_members_channel": forum_members_channel_id,
                    "guild_lang": guild_lang
                }
            logging.debug(f"[AbsenceManager] Canaux d'absences chargés : {self.abs_channels}")
        except Exception as e:
            logging.error(f"[AbsenceManager] Erreur lors du chargement des canaux d'absences : {e}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Détecte un message dans le canal d'absences et change le rôle en conséquence."""
        # Ignorer les messages des bots et ceux provenant d'applications (webhooks)
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
        if result:
            role_membre_id, role_absent_id = result
            role_membre = guild.get_role(role_membre_id)
            role_absent = guild.get_role(role_absent_id)
        else:
            role_membre = role_absent = None

        if role_absent and role_membre:
            if role_membre in member.roles:
                await member.remove_roles(role_membre)
            if role_absent not in member.roles:
                await member.add_roles(role_absent)
                logging.debug(f"[AbsenceManager] ✅ Rôle 'Membres Absents' attribué à {member.name} dans {guild.id}.")
                await self.notify_absence(member, "ajout", channels.get("forum_members_channel"), channels.get("guild_lang"))

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        """Détecte la suppression d'un message d'absence et restaure le rôle 'Membres'."""
        # Ignorer les messages des bots et ceux provenant d'applications
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
        if result:
            role_membre_id, role_absent_id = result
            role_membre = guild.get_role(role_membre_id)
            role_absent = guild.get_role(role_absent_id)
        else:
            role_membre = role_absent = None

        if role_absent and role_membre:
            if role_absent in member.roles:
                await member.remove_roles(role_absent)
            if role_membre not in member.roles:
                await member.add_roles(role_membre)
                logging.debug(f"[AbsenceManager] ✅ Rôle 'Membres' restauré pour {member.name} dans {guild.id}.")
                await self.notify_absence(member, "suppression", channels.get("forum_members_channel"), channels.get("guild_lang"))

    async def notify_absence(self, member: discord.Member, action: str, channel_id: int, guild_lang: str) -> None:
        """Envoie une notification dans le canal des membres en cas d'absence ou de retour."""
        channel = await self.bot.fetch_channel(channel_id)
        if not channel:
            logging.error("[AbsenceManager] ❌ Impossible d'accéder au canal de notification des membres.")
            return

        # Extraire les textes depuis le JSON de traductions
        absence_translations = self.bot.translations.get("absence", {})
        title = absence_translations.get("title", {}).get(guild_lang)
        member_label = absence_translations.get("member_label", {}).get(guild_lang)
        status_label = absence_translations.get("status_label", {}).get(guild_lang)
        absent_text = absence_translations.get("absent", {}).get(guild_lang)
        returned_text = absence_translations.get("returned", {}).get(guild_lang)

        # Choix du texte selon l'action
        status_text = absent_text if action == "ajout" else returned_text

        embed = discord.Embed(
            title=title,
            color=discord.Color.orange() if action == "ajout" else discord.Color.green()
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
        await channel.send(embed=embed)
        logging.debug(f"[AbsenceManager] ✅ Notification envoyée pour {member.name} ({status_text}).")

def setup(bot: discord.Bot):
    bot.add_cog(AbsenceManager(bot))