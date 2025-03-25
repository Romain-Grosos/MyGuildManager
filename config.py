from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# DEBUG ?
DEBUG: bool = True

# Log Configuration
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)
LOG_FILE: str = os.path.join(LOG_DIR, "discord-bot.log")

# Discord configuration
TOKEN: str = os.getenv("DISCORD_TOKEN")

# MariaDB configuration
DB_USER: str = os.getenv("DB_USER")
DB_PASS: str = os.getenv("DB_PASS")
DB_HOST: str = os.getenv("DB_HOST", "localhost")
DB_PORT: int = int(os.getenv("DB_PORT", 3306))
DB_NAME: str = os.getenv("DB_NAME")