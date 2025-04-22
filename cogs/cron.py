import logging
import discord
from discord.ext import tasks, commands
from datetime import datetime
import pytz

TIMEZONE = pytz.timezone("Europe/Paris")

class Cron(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        try:
            self.scheduled_tasks.start()
            logging.info("✅ [CRON] Scheduled task started successfully!")
        except Exception as e:
            logging.error(f"❌ [CRON] Error while starting the cron: {e}")

    @tasks.loop(minutes=1)
    async def scheduled_tasks(self):
        now = datetime.now(TIMEZONE).strftime("%H:%M")
        now_time = datetime.now(TIMEZONE)

        if now == "06:30":
            logging.info("⏰ [CRON] Automatic deletion of contracts.")
            contracts = self.bot.get_cog("Contract")
            if contracts:
                try:
                    await contracts.contrat_delete_cron()
                    logging.info("✅ [CRON] Contracts deleted successfully.")
                except Exception as e:
                    logging.exception(f"❌ [CRON] Error during contract deletion: {e}")
            else:
                logging.error("❌ [CRON] Contract cog not found.")

        if now in {"05:00", "11:00", "17:00", "23:00"}:
            logging.info("⏰ [CRON] Launching roster update for all guilds.")
            guild_members_cog = self.bot.get_cog("GuildMembers")
            if not guild_members_cog:
                logging.error("❌ [CRON] GuildMembers cog not found.")
                return
            for guild_id in guild_members_cog.forum_channels.keys():
                try:
                    await guild_members_cog.run_maj_roster(guild_id)
                    logging.info(f"✅ [CRON] Roster update executed for guild {guild_id}.")
                except Exception as e:
                    logging.exception(f"❌ [CRON] Error during roster update for guild {guild_id}: {e}")

        if now == "12:00":
            logging.info("⏰ [CRON] Automatic event creation triggered.")
            events_cog = self.bot.get_cog("GuildEvents")
            if events_cog:
                try:
                    await events_cog.create_events_for_all_premium_guilds()
                    logging.info("✅ [CRON] Events created for premium guilds.")
                except Exception as e:
                    logging.exception(f"❌ [CRON] Error during automatic event creation for premium guilds: {e}")
            else:
                logging.error("❌ [CRON] GuildEvents cog not found.")

        if now in ["13:00", "18:00"]:
            logging.info("⏰ [CRON] Automatic registration reminder triggered.")
            events_cog = self.bot.get_cog("GuildEvents")
            if events_cog:
                try:
                    await events_cog.event_reminder_cron()
                    logging.info("✅ [CRON] Registration reminder executed for all guilds.")
                except Exception as e:
                    logging.exception(f"❌ [CRON] Error during automatic registration reminder: {e}")
            else:
                logging.error("❌ [CRON] GuildEvents cog not found.")

        if now in ["23:30", '04:30']:
            logging.info("⏰ [CRON] Automatic deletion of finished events.")
            events_cog = self.bot.get_cog("GuildEvents")
            if not events_cog:
                logging.error("❌ [CRON] GuildEvents cog not found.")
                return
            try:
                await events_cog.event_delete_cron()
                logging.info("✅ [CRON] Finished events deletion executed for all guilds.")
            except Exception as e:
                logging.exception(f"❌ [CRON] Error during finished events deletion: {e}")

        if now_time.minute % 5 == 0:
            events_cog = self.bot.get_cog("GuildEvents")
            if events_cog:
                try:
                    logging.info("⏰ [CRON] Automatic closure of confirmed events.")
                    await events_cog.event_close_cron()
                except Exception as e:
                    logging.exception(f"❌ [CRON] Error during automatic closure of events: {e}")
            else:
                logging.error("❌ [CRON] GuildEvents cog not found.")

    @scheduled_tasks.before_loop
    async def before_scheduled_tasks(self):
        logging.debug("⌛ [CRON] Waiting for bot to be ready...")
        await self.bot.wait_until_ready()
        logging.debug("✅ [CRON] Bot is ready, starting cron.")

def setup(bot: discord.Bot):
    bot.add_cog(Cron(bot))
