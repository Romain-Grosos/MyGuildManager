import logging
import discord
from discord.ext import tasks, commands
from datetime import datetime
import pytz
import asyncio

# Définition du fuseau horaire pour Europe/Paris (UTC+1 ou UTC+2 selon l'heure d'été)
TIMEZONE = pytz.timezone("Europe/Paris")

class Cron(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        try:
            self.scheduled_tasks.start()
            logging.info("✅ [CRON] La tâche planifiée a bien été démarrée !")
        except Exception as e:
            logging.error(f"❌ [CRON] Erreur au démarrage du cron : {e}")

    @tasks.loop(minutes=1)
    async def scheduled_tasks(self):
        now = datetime.now(TIMEZONE).strftime("%H:%M")
        now_time = datetime.now(TIMEZONE)

        ############################################################################################
        # À 06:30, déclenche la suppression automatique des contrats
        ############################################################################################
        if now == "06:30":
            logging.info("⏰ [CRON] Suppression automatique des contrats.")
            contracts = self.bot.get_cog("Contract")
            if contracts:
                await contracts.contrat_delete_cron()
            else:
                logging.error("❌ [CRON] Contract cog not found.")

        ############################################################################################
        # À 5h00, 11h00, 17h00, 23h00, mets à jour la liste des membres de toutes les guildes
        ############################################################################################
        if now in {"05:00", "11:00", "17:00", "23:00"}:
            logging.info("⏰ [CRON] Lancement de maj_roster pour toutes les guildes.")
            guild_members_cog = self.bot.get_cog("GuildMembers")
            if not guild_members_cog:
                logging.error("❌ [CRON] GuildMembers cog non trouvé.")
                return
            # Itérer sur les guildes présentes dans le cache forum_channels
            for guild_id in guild_members_cog.forum_channels.keys():
                try:
                    await guild_members_cog.run_maj_roster(guild_id)
                    logging.info(f"✅ [CRON] maj_roster exécuté pour la guilde {guild_id}.")
                except Exception as e:
                    logging.exception(f"❌ [CRON] Erreur lors de maj_roster pour la guilde {guild_id} : {e}")

        ############################################################################################
        # À 12h00, créée les évènements du lendemain pour les guildes premium
        ############################################################################################
        if now == "12:00":
            logging.info("⏰ [CRON] Création automatique des événements déclenchée")
            events_cog = self.bot.get_cog("GuildEvents")
            try:
                await events_cog.create_events_for_all_premium_guilds()
                logging.info(f"✅ [CRON] Événements créés pour les guildes premium.")
            except Exception as e:
                logging.exception(f"❌ [CRON] Erreur lors de la création d'événements automatiques pour les guildes premium : {e}")

        ############################################################################################
        # À 13:00, 18:00, rappel par MP des membres non inscrits aux évènements
        ############################################################################################
        if now in ["13:00", "18:00"]:
            logging.info("⏰ [CRON] Rappel automatique des inscriptions déclenché")
            events_cog = self.bot.get_cog("GuildEvents")
            if events_cog:
                try:
                    await events_cog.event_reminder_cron()
                    logging.info("✅ [CRON] Rappel automatique des inscriptions effectué pour toutes les guildes.")
                except Exception as e:
                    logging.exception(f"❌ [CRON] Erreur lors du rappel automatique des inscriptions : {e}")
            else:
                logging.error("❌ [CRON] GuildEvents cog non trouvé.")

        ############################################################################################
        # À 23:30, suppression automatique des événements terminés
        ############################################################################################
        if now == "23:30":
            logging.info("⏰ [CRON] Suppression automatique des événements terminés.")
            events_cog = self.bot.get_cog("GuildEvents")
            if not events_cog:
                logging.error("❌ [CRON] GuildEvents cog non trouvé.")
                return
            try:
                await events_cog.event_delete_cron()
                logging.info("✅ [CRON] Suppression des événements terminés effectuée pour toutes les guildes.")
            except Exception as e:
                logging.exception(f"❌ [CRON] Erreur lors de la suppression des événements terminés : {e}")

        ############################################################################################
        # Toutes les 5 minutes, vérification des évènements et passage au status "Closed"
        ############################################################################################
        if now_time.minute % 5 == 0:
            events_cog = self.bot.get_cog("GuildEvents")
            if events_cog:
                try:
                    logging.info("⏰ [CRON] Clôture automatique des événements confirmés.")
                    await events_cog.event_close_cron()
                except Exception as e:
                    logging.exception(f"❌ [CRON] Erreur lors de la clôture automatique des événements : {e}")
            else:
                logging.error("❌ [CRON] GuildEvents cog non trouvé.")

    @scheduled_tasks.before_loop
    async def before_scheduled_tasks(self):
        logging.debug("⌛ [CRON] Attente que le bot soit prêt...")
        await self.bot.wait_until_ready()
        logging.debug("✅ [CRON] Le bot est prêt, lancement du cron.")

def setup(bot: discord.Bot):
    bot.add_cog(Cron(bot))
