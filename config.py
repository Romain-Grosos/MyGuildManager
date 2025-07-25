from dotenv import load_dotenv
import os
import sys

load_dotenv()

def validate_env_var(var_name: str, value: str, required: bool = True) -> str:
    if not value:
        if required:
            raise ValueError(f"Missing required environment variable: {var_name}")
        return ""
    return value

def validate_int_env_var(var_name: str, value: str, default: int = None) -> int:
    if not value:
        if default is None:
            raise ValueError(f"Missing required integer environment variable: {var_name}")
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"Invalid integer value for {var_name}: {value}")

DEBUG: bool = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")

LOG_DIR = "logs"
try:
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR, mode=0o750)
except OSError as e:
    print(f"CRITICAL: Cannot create log directory {LOG_DIR}: {e}", file=sys.stderr)
    sys.exit(1)

LOG_FILE: str = os.path.join(LOG_DIR, "discord-bot.log")

try:
    with open(LOG_FILE, 'a') as f:
        pass
except IOError as e:
    print(f"CRITICAL: Cannot write to log file {LOG_FILE}: {e}", file=sys.stderr)
    sys.exit(1)

try:
    TOKEN: str = validate_env_var("DISCORD_TOKEN", os.getenv("DISCORD_TOKEN"))
    if len(TOKEN) < 50:
        raise ValueError("Invalid Discord token format - token too short")
except ValueError as e:
    print(f"CRITICAL: {e}", file=sys.stderr)
    sys.exit(1)

try:
    DB_USER: str = validate_env_var("DB_USER", os.getenv("DB_USER"))
    DB_PASS: str = validate_env_var("DB_PASS", os.getenv("DB_PASS"))
    DB_HOST: str = validate_env_var("DB_HOST", os.getenv("DB_HOST", "localhost"), required=False) or "localhost"
    DB_PORT: int = validate_int_env_var("DB_PORT", os.getenv("DB_PORT"), default=3306)
    DB_NAME: str = validate_env_var("DB_NAME", os.getenv("DB_NAME"))
    
    if not (1 <= DB_PORT <= 65535):
        raise ValueError(f"Invalid DB_PORT: {DB_PORT} (must be between 1 and 65535)")
    
    if len(DB_NAME) > 64:
        raise ValueError(f"DB_NAME too long: {len(DB_NAME)} characters (max 64)")
        
except ValueError as e:
    print(f"CRITICAL: Database configuration error: {e}", file=sys.stderr)
    sys.exit(1)

MAX_MEMORY_MB = validate_int_env_var("MAX_MEMORY_MB", os.getenv("MAX_MEMORY_MB"), default=1024)
MAX_CPU_PERCENT = validate_int_env_var("MAX_CPU_PERCENT", os.getenv("MAX_CPU_PERCENT"), default=90)
MAX_RECONNECT_ATTEMPTS = validate_int_env_var("MAX_RECONNECT_ATTEMPTS", os.getenv("MAX_RECONNECT_ATTEMPTS"), default=5)
RATE_LIMIT_PER_MINUTE = validate_int_env_var("RATE_LIMIT_PER_MINUTE", os.getenv("RATE_LIMIT_PER_MINUTE"), default=100)

DB_POOL_SIZE = validate_int_env_var("DB_POOL_SIZE", os.getenv("DB_POOL_SIZE"), default=25)
DB_TIMEOUT = validate_int_env_var("DB_TIMEOUT", os.getenv("DB_TIMEOUT"), default=30)
DB_CIRCUIT_BREAKER_THRESHOLD = validate_int_env_var("DB_CIRCUIT_BREAKER_THRESHOLD", os.getenv("DB_CIRCUIT_BREAKER_THRESHOLD"), default=5)

if not (50 <= MAX_MEMORY_MB <= 2048):
    print(f"WARNING: MAX_MEMORY_MB ({MAX_MEMORY_MB}) outside recommended range 50-2048MB", file=sys.stderr)
if not (10 <= MAX_CPU_PERCENT <= 95):
    print(f"WARNING: MAX_CPU_PERCENT ({MAX_CPU_PERCENT}) outside recommended range 10-95%", file=sys.stderr)
if not (1 <= MAX_RECONNECT_ATTEMPTS <= 10):
    print(f"WARNING: MAX_RECONNECT_ATTEMPTS ({MAX_RECONNECT_ATTEMPTS}) outside recommended range 1-10", file=sys.stderr)
if not (10 <= RATE_LIMIT_PER_MINUTE <= 1000):
    print(f"WARNING: RATE_LIMIT_PER_MINUTE ({RATE_LIMIT_PER_MINUTE}) outside recommended range 10-1000", file=sys.stderr)

if not (1 <= DB_POOL_SIZE <= 50):
    print(f"WARNING: DB_POOL_SIZE ({DB_POOL_SIZE}) outside recommended range 1-50", file=sys.stderr)
if not (5 <= DB_TIMEOUT <= 120):
    print(f"WARNING: DB_TIMEOUT ({DB_TIMEOUT}) outside recommended range 5-120 seconds", file=sys.stderr)
if not (3 <= DB_CIRCUIT_BREAKER_THRESHOLD <= 20):
    print(f"WARNING: DB_CIRCUIT_BREAKER_THRESHOLD ({DB_CIRCUIT_BREAKER_THRESHOLD}) outside recommended range 3-20", file=sys.stderr)