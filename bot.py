import discord
import logging
from logging.handlers import TimedRotatingFileHandler
from discord.ext import commands
import config
from translation import translations
from db import run_db_query

# #################################################################################### #
#                               Logging Configuration
# #################################################################################### #
log_level: int = logging.DEBUG if config.DEBUG else logging.INFO
logging.root.handlers.clear()
logger = logging.getLogger()
logger.setLevel(log_level)

file_handler = TimedRotatingFileHandler(
    config.LOG_FILE, when="midnight", interval=1, backupCount=7, encoding="utf-8"
)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

logging.debug("[Bot] ✅ Logs initialisés avec rotation journalière.")

# #################################################################################### #
#                            Discord Bot Initialization
# #################################################################################### #
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True
intents.members = True

bot = discord.Bot(intents=intents)
bot.translations = translations
bot.run_db_query = run_db_query

# List of Cog Extensions to load
extensions = [
    "cogs.core",
    "cogs.llm",
    "cogs.guild_init",
    "cogs.notification",
    "cogs.autorole",
    "cogs.profile_setup",
    "cogs.guild_members",
    "cogs.absence",
    "cogs.dynamic_voice",
    "cogs.contract",
    "cogs.guild_events",
    "cogs.cron"
]

def load_extensions():
    for ext in extensions:
        try:
            bot.load_extension(ext)
            logging.debug(f"[Bot] ✅ Extension chargée : {ext}")
        except Exception as e:
            logging.error(f"[Bot] ❌ Échec de chargement de l'extension {ext}: {e}")

if __name__ == "__main__":
    load_extensions()
    try:
        bot.run(config.TOKEN)
    except KeyboardInterrupt:
        logging.info("[Bot] 🛑 Arrêt du bot demandée par l'utilisateur.")