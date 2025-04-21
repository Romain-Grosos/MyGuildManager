import discord
import logging
from logging.handlers import TimedRotatingFileHandler
import config
from translation import translations
from db import run_db_query
import asyncio
import signal
import sys
from typing import Final
import aiohttp

# #################################################################################### #
#                               Logging Configuration
# #################################################################################### #
log_level: int = logging.DEBUG if config.DEBUG else logging.INFO
logging.root.handlers.clear()
logging.getLogger().setLevel(log_level)

file_handler = TimedRotatingFileHandler(
    config.LOG_FILE, when="midnight", interval=1, backupCount=7, encoding="utf-8"
)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)
logging.getLogger().addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logging.getLogger().addHandler(console_handler)

def _global_exception_hook(exc_type, exc_value, exc_tb):
    logging.critical("UNCAUGHT EXCEPTION", exc_info=(exc_type, exc_value, exc_tb))

sys.excepthook = _global_exception_hook

logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
logging.captureWarnings(True)

logging.debug("[Bot] ✅ Log initialization with daily rotation.")

# #################################################################################### #
#                            Discord Bot Startup
# #################################################################################### #

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# #################################################################################### #
#                            Discord Bot Initialization
# #################################################################################### #
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True
intents.members = True

bot = discord.Bot(intents=intents, loop=loop)
bot.translations = translations
bot.run_db_query = run_db_query

EXTENSIONS: Final[list[str]] = [
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
    for ext in EXTENSIONS:
        try:
            bot.load_extension(ext)
            logging.debug(f"[Bot] ✅ Extension loaded : {ext}")
        except Exception as e:
            logging.exception(f"[Bot] ❌ Failed to load extension {ext}")

# #################################################################################### #
#                            Extra Event Hooks
# #################################################################################### #

@bot.event
async def on_disconnect() -> None:
    logging.warning("[Discord] Gateway disconnected")


@bot.event
async def on_resumed() -> None:
    logging.info("[Discord] Gateway resume OK")


@bot.event
async def on_ready() -> None:
    logging.info("[Discord] Connected as %s (%s)", bot.user, bot.user.id)

# #################################################################################### #
#                            Resilient runner
# #################################################################################### #

async def run_bot():
    load_extensions()
    while True:
        try:
            await bot.start(config.TOKEN)
        except aiohttp.ClientError:
            logging.exception("Network error — retrying in 15s")
            await bot.close()
            await asyncio.sleep(15)
        else:
            break

def _graceful_exit(signame):
    logging.warning("[Bot] Signal %s received — closing the bot", signame)
    coro = bot.close()
    asyncio.create_task(coro)

if __name__ == "__main__":
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _graceful_exit, sig.name)
        except NotImplementedError:
           signal.signal(sig, lambda *_: asyncio.create_task(_graceful_exit(sig.name)))

    try:
        loop.run_until_complete(run_bot())
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        logging.shutdown()
        loop.close()