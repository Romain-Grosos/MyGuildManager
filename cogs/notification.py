import discord
import logging
from discord.ext import commands
from typing import Any
import asyncio

def create_embed(title: str, description: str, color: discord.Color, member: discord.Member) -> discord.Embed:
    """Crée un embed standardisé pour les événements de membre."""
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
        # Charger les canaux de notification et la langue depuis la BDD au démarrage
        asyncio.create_task(self.load_notification_channels())
        logging.debug("[NotificationManager] Tâche load_absence_channels lancée depuis on_ready")

    async def load_notification_channels(self) -> None:
        """Charge depuis la BDD l'ID du canal notifications et la langue de chaque guilde."""
        logging.debug("[NotificationManager]  Chargement des informations de notifications depuis la BDD")
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
            logging.debug(f"[NotificationManager] Informations de notifications chargées : {self.notif_channels}")
        except Exception as e:
            logging.error(f"[NotificationManager] Erreur lors du chargement des informations de notifications : {e}")

    async def get_guild_lang(self, guild: discord.Guild) -> str:
        """Récupère la langue de la guilde à partir du cache, avec fallback vers 'en-US' si non définie."""
        info = self.notif_channels.get(guild.id)
        if info and info.get("guild_lang"):
            return info["guild_lang"]
        return "en-US"

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Gère l'arrivée d'un nouveau membre en envoyant un message dans le canal notifications et en l'enregistrant en BDD."""
        guild = member.guild
        logging.debug(f"[NotificationManager] 👤 Nouveau membre détecté : {member.name} ({member.id}) dans {guild.id}")
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
                # Insertion dans la BDD dans la table welcome_messages
                insert_query = "INSERT INTO welcome_messages (guild_id, member_id, channel_id, message_id) VALUES (?, ?, ?, ?)"
                await self.bot.run_db_query(insert_query, (guild.id, member.id, channel.id, msg.id), commit=True)
                logging.debug(f"[NotificationManager] 📌 Message de bienvenue enregistré pour {member.name} (ID: {msg.id})")

                autorole_cog = self.bot.get_cog("AutoRole")
                if autorole_cog:
                    await autorole_cog.load_welcome_messages_cache()

                profilesetup_cog = self.bot.get_cog("ProfileSetup")
                if profilesetup_cog:
                    await profilesetup_cog.load_welcome_messages_cache()
            else:
                logging.warning(f"[NotificationManager] Canal de notifications non configuré pour la guilde {guild.id}.")
        except Exception as e:
            logging.error("[NotificationManager] ❌ Erreur dans on_member_join", exc_info=True)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Gère le départ d'un membre et met à jour le message de bienvenue correspondant."""
        guild = member.guild
        logging.debug(f"[NotificationManager] 🚪 Départ détecté : {member.name} ({member.id}) de {guild.id}")
        try:
            guild_lang = await self.get_guild_lang(guild)
            # Rechercher l'enregistrement de bienvenue pour ce membre
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
                logging.debug(f"[NotificationManager] 📌 Réponse envoyée au message de bienvenue pour {member.name} (ID: {message_id}) dans {guild.id}")
                # Supprimer les enregistrements de BDD
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
            # Fin du traitement
        except Exception as e:
            logging.error("[NotificationManager] ❌ Erreur dans on_member_remove", exc_info=True)

def setup(bot: discord.Bot):
    bot.add_cog(Notification(bot))