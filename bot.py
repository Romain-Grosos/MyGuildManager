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
import time
from discord.ext import commands
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logging.warning("[Bot] psutil not available - resource monitoring disabled")

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

def validate_token():
    token = config.TOKEN
    if not token or len(token) < 50:
        logging.critical("[Bot] Invalid or missing Discord token")
        sys.exit(1)
    masked_token = f"{token[:10]}...{token[-4:]}"
    logging.debug(f"[Bot] Using token: {masked_token}")
    return token

bot = discord.Bot(intents=intents, loop=loop)
bot.translations = translations
bot.run_db_query = run_db_query
bot.global_command_cooldown = set()
bot.max_commands_per_minute = 100

EXTENSIONS: Final[list[str]] = [
    "cogs.core",
    "cogs.llm",
    "cogs.guild_init",
    "cogs.notification",
    "cogs.profile_setup",
    "cogs.guild_members",
    "cogs.absence",
    "cogs.dynamic_voice",
    "cogs.contract",
    "cogs.guild_events",
    "cogs.guild_attendance",
    "cogs.autorole",
    "cogs.cron"
]

def load_extensions():
    failed_extensions = []
    for ext in EXTENSIONS:
        try:
            bot.load_extension(ext)
            logging.debug(f"[Bot] ✅ Extension loaded: {ext}")
        except Exception as e:
            failed_extensions.append(ext)
            logging.exception(f"[Bot] ❌ Failed to load extension {ext}")
    
    if failed_extensions:
        logging.warning(f"[Bot] {len(failed_extensions)} extensions failed to load: {failed_extensions}")
    
    if len(failed_extensions) >= len(EXTENSIONS) // 2:
        logging.critical("[Bot] Too many extensions failed. Shutting down.")
        sys.exit(1)

# #################################################################################### #
#                            Extra Event Hooks
# #################################################################################### #
@bot.event
async def on_disconnect() -> None:
    logging.warning("[Discord] Gateway disconnected")


@bot.event
async def on_resumed() -> None:
    logging.info("[Discord] Gateway resume OK")


@bot.before_invoke
async def global_rate_limit(ctx):
    now = time.time()
    bot.global_command_cooldown = {
        timestamp for timestamp in bot.global_command_cooldown 
        if now - timestamp < 60
    }
    
    if len(bot.global_command_cooldown) >= bot.max_commands_per_minute:
        logging.warning(f"[Bot] Global rate limit exceeded ({len(bot.global_command_cooldown)} commands/min)")
        raise commands.CommandOnCooldown(None, 60)
    
    bot.global_command_cooldown.add(now)

@bot.event
async def on_ready() -> None:
    logging.info("[Discord] Connected as %s (%s)", bot.user, bot.user.id)
    
    if PSUTIL_AVAILABLE:
        asyncio.create_task(monitor_resources())
        logging.debug("[Bot] Resource monitoring started")

# #################################################################################### #
#                            Resource Monitoring
# #################################################################################### #

async def monitor_resources():
    while True:
        try:
            if PSUTIL_AVAILABLE:
                process = psutil.Process()
                memory_mb = process.memory_info().rss / 1024 / 1024
                cpu_percent = process.cpu_percent()
                
                if memory_mb > config.MAX_MEMORY_MB:
                    logging.warning(f"[Bot] High memory usage: {memory_mb:.1f}MB (limit: {config.MAX_MEMORY_MB}MB)")
                if cpu_percent > config.MAX_CPU_PERCENT:
                    logging.warning(f"[Bot] High CPU usage: {cpu_percent:.1f}% (limit: {config.MAX_CPU_PERCENT}%)")
                    
                if int(time.time()) % 3600 == 0:
                    logging.info(f"[Bot] Resource usage - Memory: {memory_mb:.1f}MB, CPU: {cpu_percent:.1f}%")
                    
            await asyncio.sleep(300)
        except Exception as e:
            logging.error(f"[Bot] Resource monitoring error: {e}")
            await asyncio.sleep(300)

# #################################################################################### #
#                            Resilient runner
# #################################################################################### #

async def run_bot():
    load_extensions()
    max_retries = config.MAX_RECONNECT_ATTEMPTS
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            await bot.start(validate_token())
        except aiohttp.ClientError as e:
            retry_count += 1
            logging.exception(f"Network error (attempt {retry_count}/{max_retries}) — retrying in 15s")
            if retry_count >= max_retries:
                logging.critical("[Bot] Max retries reached. Shutting down.")
                break
            await bot.close()
            await asyncio.sleep(15)
        except Exception as e:
            logging.critical(f"[Bot] Critical error during startup: {e}", exc_info=True)
            break
        else:
            break

def _graceful_exit(sig_name):
    logging.warning("[Bot] Signal %s received — closing the bot", sig_name)
    coroutine = bot.close()
    asyncio.create_task(coroutine)

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