import discord
import logging
from discord.ext import commands
from typing import Dict, Tuple, Any
import asyncio
import pytz
from datetime import datetime
from translation import translations as global_translations

WELCOME_MP_DATA = global_translations.get("welcome_mp", {})

def update_welcome_embed(embed: discord.Embed, lang: str, translations: dict) -> discord.Embed:
    """Met à jour l'embed pour indiquer que les règles ont été acceptées, en utilisant la localisation.
    Remplace la partie correspondant au texte 'pending' par le texte 'accepted' avec la date.
    """
    TZ_FRANCE = pytz.timezone("Europe/Paris")
    now = datetime.now(pytz.utc).astimezone(TZ_FRANCE).strftime("%d/%m/%Y à %Hh%M")
    pending_text = translations["welcome"]["pending"][lang]
    accepted_template = translations["welcome"]["accepted"][lang]
    new_text = accepted_template.format(date=now)
    embed.description = embed.description.replace(pending_text, new_text)
    embed.color = discord.Color.dark_grey()
    return embed

class AutoRole(commands.Cog):
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
        self.rules_messages: Dict[int, Dict[str, int]] = {}
        self.welcome_messages: Dict[Tuple[int, int], Dict[str, int]] = {}
        self.rules_ok_roles: Dict[int, int] = {}
        self.guild_langs: Dict[int, str] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        # Charger les canaux d'absences depuis la BDD au démarrage
        asyncio.create_task(self.load_rules_messages())
        asyncio.create_task(self.load_welcome_messages_cache())
        asyncio.create_task(self.load_rules_ok_roles())
        asyncio.create_task(self.load_guild_lang())
        logging.debug("[AutoRole] Tâche de récupérations des infos dans le cache lancée depuis on_ready")

    async def load_rules_messages(self) -> None:
        """Charge depuis la BDD les informations des messages de règles pour chaque guilde."""
        logging.debug("[AutoRole] Chargement des messages de règles depuis la BDD")
        query = "SELECT guild_id, rules_channel, rules_message FROM guild_channels WHERE rules_message IS NOT NULL"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            for row in rows:
                guild_id, channel_id, message_id = row
                self.rules_messages[guild_id] = {"channel": channel_id, "message": message_id}
            logging.debug(f"[AutoRole] Règles messages chargés : {self.rules_messages}")
        except Exception as e:
            logging.error(f"[AutoRole] Erreur lors du chargement des messages de règles : {e}")

    async def load_welcome_messages_cache(self) -> None:
        """Charge depuis la BDD les informations des messages de bienvenue pour chaque membre."""
        logging.debug("[AutoRole] Chargement des welcome messages depuis la BDD")
        query = "SELECT guild_id, member_id, channel_id, message_id FROM welcome_messages"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            for row in rows:
                guild_id, member_id, channel_id, message_id = row
                self.welcome_messages[(guild_id, member_id)] = {"channel": channel_id, "message": message_id}
            logging.debug(f"[AutoRole] Welcome messages chargés : {self.welcome_messages}")
        except Exception as e:
            logging.error(f"[AutoRole] Erreur lors du chargement des welcome messages : {e}")

    async def load_rules_ok_roles(self) -> None:
        """Charge depuis la BDD le rôle d'acceptation (rules_ok) pour chaque guilde."""
        logging.debug("[AutoRole] Chargement des rôles d'acceptation depuis la BDD")
        query = "SELECT guild_id, rules_ok FROM guild_roles WHERE rules_ok IS NOT NULL"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            for row in rows:
                guild_id, rules_ok_role_id = row
                self.rules_ok_roles[guild_id] = rules_ok_role_id
            logging.debug(f"[AutoRole] Rôles d'acceptation chargés : {self.rules_ok_roles}")
        except Exception as e:
            logging.error(f"[AutoRole] Erreur lors du chargement des rôles d'acceptation : {e}")

    async def load_guild_lang(self) -> None:
        """Charge depuis la BDD la langue de chaque guilde et la stocke dans le cache."""
        logging.debug("[AutoRole] Chargement des langues de guilde depuis la BDD")
        query = "SELECT guild_id, guild_lang FROM guild_settings"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            for row in rows:
                guild_id, lang = row
                self.guild_langs[guild_id] = lang
            logging.debug(f"[AutoRole] Langues de guilde chargées : {self.guild_langs}")
        except Exception as e:
            logging.error(f"[AutoRole] Erreur lors du chargement des langues de guilde : {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        """Ajoute le rôle d'autorole et met à jour le message de bienvenue si la réaction est ajoutée au message de règles."""
        # Vérifier que l'événement concerne une guilde
        if not payload.guild_id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        # Vérifier que le message correspond à l'un des messages de règles chargés
        rules_info = self.rules_messages.get(guild.id)
        if not rules_info or payload.message_id != rules_info.get("message"):
            return

        # Vérifier l'emoji (ici "✅")
        if str(payload.emoji) != "✅":
            return

        role_id = self.rules_ok_roles.get(guild.id)
        role = guild.get_role(role_id) if role_id else None

        member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
        if member and role and role not in member.roles:
            await member.add_roles(role)
            logging.debug(f"[AutoRole] ✅ Rôle ajouté à {member.name} ({member.id})")

            # Mettre à jour le welcome message s'il existe dans le cache
            key = (guild.id, member.id)
            if key in self.welcome_messages:
                info = self.welcome_messages[key]
                try:
                    channel = await self.bot.fetch_channel(info["channel"])
                    message = await channel.fetch_message(info["message"])
                    embed = update_welcome_embed(message.embeds[0], self.guild_langs.get(guild.id), self.bot.translations)
                    await message.edit(embed=embed)
                    logging.debug(f"[AutoRole] ✅ Welcome message mis à jour pour {member.name} (ID: {member.id})")
                except Exception as e:
                    logging.error("[AutoRole] ❌ Erreur lors de la mise à jour du welcome message", exc_info=True)
            else:
                logging.debug(f"[AutoRole] Pas de welcome message en cache pour la clé {key}.")

            # Vérifier dans la BDD si un profil existe déjà pour cet utilisateur
            query = "SELECT user_id FROM user_setup WHERE guild_id = ? AND user_id = ?"
            result = await self.bot.run_db_query(query, (guild.id, member.id), fetch_one=True)
            if result is not None:
                logging.debug(f"[AutoRole] Un profil existe déjà pour {guild.id}_{member.id}, aucun MP envoyé pour l'inscription.")
                return

            profile_setup_cog = self.bot.get_cog("ProfileSetup")
            if profile_setup_cog is None:
                logging.error("❌ ProfileSetup cog not found!")
                return
            try:
                await member.send(view=profile_setup_cog.LangSelectView(profile_setup_cog, guild.id))
                logging.debug(f"📩 MP envoyé à {member.name} ({member.id}) pour démarrer le processus de profil ({guild.id})")
            except discord.Forbidden:
                logging.error(f"⚠️ Impossible d'envoyer un MP à {member.name}. Vérifie ses paramètres ({guild.id})")
            except Exception as e:
                logging.error(f"❌ Erreur lors de l'envoi du MP à {member.name} : {e} dans  ({guild.id})", exc_info=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        """Retire le rôle lorsque la réaction est enlevée du message de règles."""
        if not payload.guild_id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        rules_info = self.rules_messages.get(guild.id)
        if not rules_info or payload.message_id != rules_info.get("message"):
            return

        if str(payload.emoji) != "✅":
            return

        role_id = self.rules_ok_roles.get(guild.id)
        role = guild.get_role(role_id) if role_id else None

        member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
        if member and role and role in member.roles:
            await member.remove_roles(role)
            logging.debug(f"[AutoRole] ✅ Rôle retiré à {member.name} ({member.id})")

def setup(bot: discord.Bot):
    bot.add_cog(AutoRole(bot))