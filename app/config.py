"""
Configuration Module - Enterprise-grade environment variable management.

Provides centralized configuration loading with:
- JSON structured logging with correlation tracking
- Comprehensive validation with auto-clamping
- Security-focused secrets management
- Test-friendly error handling
- Production hardening and observability
"""

import os
import sys
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from contextvars import ContextVar

from dotenv import load_dotenv

# Context variables for correlation tracking
correlation_id_context: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)

# Custom exception for configuration errors
class ConfigError(Exception):
    """Custom exception for configuration-related errors."""
    pass

env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)

# #################################################################################### #
#                            Validation Ranges and Logging
# #################################################################################### #

# Centralized validation ranges for DRY principle
VALIDATION_RANGES = {
    'MAX_MEMORY_MB': (50, 2048),
    'MAX_CPU_PERCENT': (10, 95),
    'MAX_RECONNECT_ATTEMPTS': (1, 10),
    'RATE_LIMIT_PER_MINUTE': (10, 1000),
    'DB_POOL_SIZE': (1, 50),
    'DB_TIMEOUT': (5, 120),
    'DB_CIRCUIT_BREAKER_THRESHOLD': (3, 20),
    'MAX_TRANSLATION_FILE_SIZE': (1024, 50 * 1024 * 1024),
    'DB_PORT': (1, 65535)
}

def _log_json(level: str, event: str, **fields) -> None:
    """Log structured JSON message with correlation ID and PII masking."""
    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "level": level.upper(),
        "event": event,
        "component": "config",
        "version": "1.0"
    }
    
    # Add correlation ID if available
    correlation_id = correlation_id_context.get(None)
    if correlation_id:
        log_entry["correlation_id"] = correlation_id
    
    # Add fields with PII masking in production
    is_production = os.environ.get('PRODUCTION', 'False').lower() == 'true'
    for key, value in fields.items():
        # Never log sensitive data
        if 'password' in key.lower() or 'token' in key.lower() or 'secret' in key.lower():
            log_entry[key] = "REDACTED"
        elif is_production and key in ('guild_id', 'user_id'):
            log_entry[key] = "REDACTED"
        else:
            log_entry[key] = value
    
    # Log as JSON string
    log_msg = json.dumps(log_entry)
    if level == "debug":
        logging.debug(log_msg)
    elif level == "info":
        logging.info(log_msg)
    elif level == "warning":
        logging.warning(log_msg)
    elif level == "error":
        logging.error(log_msg)
    elif level == "critical":
        logging.critical(log_msg)

# #################################################################################### #
#                            Environment Variable Validation
# #################################################################################### #
def validate_env_var(var_name: str, value: Optional[str], required: bool = True) -> str:
    """
    Validate and return environment variable value.
    
    Args:
        var_name: Name of the environment variable
        value: Raw value from environment (can be None)
        required: Whether the variable is required
        
    Returns:
        Validated environment variable value
        
    Raises:
        ConfigError: If required variable is missing
    """
    if not value:
        if required:
            raise ConfigError(f"Missing required environment variable: {var_name}")
        return ""
    return value

def validate_int_env_var(var_name: str, value: Optional[str], default: Optional[int] = None, auto_clamp: bool = False) -> int:
    """
    Validate and return integer environment variable value.
    
    Args:
        var_name: Name of the environment variable
        value: Raw value from environment (can be None)
        default: Default value if not provided
        auto_clamp: Whether to automatically clamp values to valid ranges
        
    Returns:
        Validated integer value
        
    Raises:
        ConfigError: If value is invalid or missing without default
    """
    if not value:
        if default is None:
            raise ConfigError(f"Missing required integer environment variable: {var_name}")
        return default
    try:
        parsed_value = int(value)
        
        # Apply auto-clamping if enabled and range is defined
        if auto_clamp and var_name in VALIDATION_RANGES:
            min_val, max_val = VALIDATION_RANGES[var_name]
            if parsed_value < min_val:
                _log_json("warning", "config_value_clamped", 
                         variable=var_name, original=parsed_value, clamped=min_val, 
                         reason="below_minimum")
                return min_val
            elif parsed_value > max_val:
                _log_json("warning", "config_value_clamped", 
                         variable=var_name, original=parsed_value, clamped=max_val, 
                         reason="above_maximum")
                return max_val
        
        return parsed_value
    except ValueError:
        raise ConfigError(f"Invalid integer value for {var_name}: {value}")

def validate_file_exists(file_path: str, var_name: str) -> bool:
    """Validate that a file exists and is readable."""
    if not os.path.isfile(file_path):
        _log_json("error", "file_not_found", variable=var_name, file_path=file_path)
        return False
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read(1)  # Try to read first byte
        _log_json("debug", "file_validated", variable=var_name, file_path=file_path)
        return True
    except (IOError, OSError) as e:
        _log_json("error", "file_read_error", variable=var_name, file_path=file_path, 
                 error_type=type(e).__name__, error_msg=str(e))
        return False

def validate_ranges(var_name: str, value: int) -> None:
    """Validate value against defined ranges and log warnings."""
    if var_name in VALIDATION_RANGES:
        min_val, max_val = VALIDATION_RANGES[var_name]
        if not (min_val <= value <= max_val):
            _log_json("warning", "config_value_out_of_range", 
                     variable=var_name, value=value, 
                     min_recommended=min_val, max_recommended=max_val)

# #################################################################################### #
#                            Configuration Loading Function
# #################################################################################### #

def load_config() -> Dict[str, Any]:
    """
    Load and validate all configuration from environment variables.
    
    Returns:
        Dict containing all validated configuration values
        
    Raises:
        ConfigError: If critical configuration is invalid or missing
    """
    config = {}
    auto_clamp = os.getenv('CONFIG_AUTO_CLAMP', 'False').lower() == 'true'
    
    try:
        # ==================================================================================== #
        #                            Debug and Logging Configuration
        # ==================================================================================== #
        config['DEBUG'] = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")
        
        LOG_DIR = "logs"
        try:
            if not os.path.exists(LOG_DIR):
                os.makedirs(LOG_DIR, mode=0o750)
        except OSError as e:
            raise ConfigError(f"Cannot create log directory {LOG_DIR}: {e}")
        
        config['LOG_FILE'] = os.path.join(LOG_DIR, "discord-bot.log")
        
        try:
            with open(config['LOG_FILE'], 'a') as f:
                pass
        except IOError as e:
            raise ConfigError(f"Cannot write to log file {config['LOG_FILE']}: {e}")
        
        # ==================================================================================== #
        #                            Discord Bot Configuration
        # ==================================================================================== #
        bot_token = os.getenv("BOT_TOKEN")
        discord_token = os.getenv("DISCORD_TOKEN")
        
        if bot_token:
            config['TOKEN'] = bot_token
            _log_json("debug", "token_source_detected", source="BOT_TOKEN")
        elif discord_token:
            config['TOKEN'] = discord_token
            _log_json("debug", "token_source_detected", source="DISCORD_TOKEN")
        else:
            raise ConfigError("Missing required environment variable: BOT_TOKEN or DISCORD_TOKEN")
        
        if len(config['TOKEN']) < 50:
            raise ConfigError("Invalid Discord token format - token too short")
        
        # ==================================================================================== #
        #                            Database Configuration  
        # ==================================================================================== #
        config['DB_USER'] = validate_env_var("DB_USER", os.getenv("DB_USER"))
        # DB_PASSWORD is never stored in config dict for security
        db_password = validate_env_var("DB_PASSWORD", os.getenv("DB_PASSWORD") or os.getenv("DB_PASS"))
        
        db_host = os.getenv("DB_HOST", "localhost")
        if db_host == "localhost" and not os.getenv("DB_HOST"):
            _log_json("info", "db_host_fallback", fallback_value="localhost", reason="env_var_not_set")
        config['DB_HOST'] = db_host
        
        config['DB_PORT'] = validate_int_env_var("DB_PORT", os.getenv("DB_PORT"), default=3306, auto_clamp=auto_clamp)
        validate_ranges('DB_PORT', config['DB_PORT'])
        
        config['DB_NAME'] = validate_env_var("DB_NAME", os.getenv("DB_NAME"))
        if len(config['DB_NAME']) > 64:
            raise ConfigError(f"DB_NAME too long: {len(config['DB_NAME'])} characters (max 64)")
        
        # ==================================================================================== #
        #                            Performance and Resource Limits
        # ==================================================================================== #
        config['MAX_MEMORY_MB'] = validate_int_env_var("MAX_MEMORY_MB", os.getenv("MAX_MEMORY_MB"), default=1024, auto_clamp=auto_clamp)
        validate_ranges('MAX_MEMORY_MB', config['MAX_MEMORY_MB'])
        
        config['MAX_CPU_PERCENT'] = validate_int_env_var("MAX_CPU_PERCENT", os.getenv("MAX_CPU_PERCENT"), default=90, auto_clamp=auto_clamp)
        validate_ranges('MAX_CPU_PERCENT', config['MAX_CPU_PERCENT'])
        
        config['MAX_RECONNECT_ATTEMPTS'] = validate_int_env_var("MAX_RECONNECT_ATTEMPTS", os.getenv("MAX_RECONNECT_ATTEMPTS"), default=5, auto_clamp=auto_clamp)
        validate_ranges('MAX_RECONNECT_ATTEMPTS', config['MAX_RECONNECT_ATTEMPTS'])
        
        config['RATE_LIMIT_PER_MINUTE'] = validate_int_env_var("RATE_LIMIT_PER_MINUTE", os.getenv("RATE_LIMIT_PER_MINUTE"), default=100, auto_clamp=auto_clamp)
        validate_ranges('RATE_LIMIT_PER_MINUTE', config['RATE_LIMIT_PER_MINUTE'])
        
        # ==================================================================================== #
        #                            Database Connection Pool Settings
        # ==================================================================================== #
        config['DB_POOL_SIZE'] = validate_int_env_var("DB_POOL_SIZE", os.getenv("DB_POOL_SIZE"), default=25, auto_clamp=auto_clamp)
        validate_ranges('DB_POOL_SIZE', config['DB_POOL_SIZE'])
        
        config['DB_TIMEOUT'] = validate_int_env_var("DB_TIMEOUT", os.getenv("DB_TIMEOUT"), default=30, auto_clamp=auto_clamp)
        validate_ranges('DB_TIMEOUT', config['DB_TIMEOUT'])
        
        config['DB_CIRCUIT_BREAKER_THRESHOLD'] = validate_int_env_var("DB_CIRCUIT_BREAKER_THRESHOLD", os.getenv("DB_CIRCUIT_BREAKER_THRESHOLD"), default=5, auto_clamp=auto_clamp)
        validate_ranges('DB_CIRCUIT_BREAKER_THRESHOLD', config['DB_CIRCUIT_BREAKER_THRESHOLD'])
        
        # ==================================================================================== #
        #                            Translation System Configuration
        # ==================================================================================== #
        default_translation_path = os.path.join(os.path.dirname(__file__), 'core', 'translation.json')
        translation_file = validate_env_var("TRANSLATION_FILE", os.getenv("TRANSLATION_FILE"), required=False) or default_translation_path
        
        # Verify file exists and is readable
        if not translation_file.endswith('.json'):
            _log_json("warning", "translation_file_extension", file_path=translation_file, expected=".json")
        
        if validate_file_exists(translation_file, "TRANSLATION_FILE"):
            config['TRANSLATION_FILE'] = translation_file
        else:
            raise ConfigError(f"Translation file not found or not readable: {translation_file}")
        
        config['MAX_TRANSLATION_FILE_SIZE'] = validate_int_env_var("MAX_TRANSLATION_FILE_SIZE", os.getenv("MAX_TRANSLATION_FILE_SIZE"), default=5 * 1024 * 1024, auto_clamp=auto_clamp)
        validate_ranges('MAX_TRANSLATION_FILE_SIZE', config['MAX_TRANSLATION_FILE_SIZE'])
        
        _log_json("info", "config_loaded_successfully", 
                 total_vars=len(config), 
                 auto_clamp_enabled=auto_clamp)
        
        # Return config with DB password getter function for security
        config['get_db_password'] = lambda: db_password
        
        return config
        
    except ConfigError:
        raise
    except Exception as e:
        raise ConfigError(f"Unexpected error during configuration loading: {e}")

# ==================================================================================== #
#                            Global Configuration (Optional Immediate Load)
# ==================================================================================== #

# Global variables for backwards compatibility (only loaded if accessed)
_config_cache: Optional[Dict[str, Any]] = None

# Backward compatibility assignment (happens after config is loaded)
def _assign_module_vars():
    """Assign values to module-level variables for backwards compatibility."""
    global TOKEN, DEBUG, LOG_FILE, DB_USER, DB_HOST, DB_PORT, DB_NAME
    global MAX_MEMORY_MB, MAX_CPU_PERCENT, MAX_RECONNECT_ATTEMPTS, RATE_LIMIT_PER_MINUTE
    global DB_POOL_SIZE, DB_TIMEOUT, DB_CIRCUIT_BREAKER_THRESHOLD, TRANSLATION_FILE, MAX_TRANSLATION_FILE_SIZE
    
    config = _get_config_direct()
    TOKEN = config['TOKEN']
    DEBUG = config['DEBUG']
    LOG_FILE = config['LOG_FILE']
    DB_USER = config['DB_USER']
    DB_HOST = config['DB_HOST']
    DB_PORT = config['DB_PORT']
    DB_NAME = config['DB_NAME']
    MAX_MEMORY_MB = config['MAX_MEMORY_MB']
    MAX_CPU_PERCENT = config['MAX_CPU_PERCENT']
    MAX_RECONNECT_ATTEMPTS = config['MAX_RECONNECT_ATTEMPTS']
    RATE_LIMIT_PER_MINUTE = config['RATE_LIMIT_PER_MINUTE']
    DB_POOL_SIZE = config['DB_POOL_SIZE']
    DB_TIMEOUT = config['DB_TIMEOUT']
    DB_CIRCUIT_BREAKER_THRESHOLD = config['DB_CIRCUIT_BREAKER_THRESHOLD']
    TRANSLATION_FILE = config['TRANSLATION_FILE']
    MAX_TRANSLATION_FILE_SIZE = config['MAX_TRANSLATION_FILE_SIZE']

def _get_config_direct() -> Dict[str, Any]:
    """Get cached configuration directly without triggering assignment."""
    global _config_cache
    if _config_cache is None:
        _config_cache = load_config()
    return _config_cache

def _get_config() -> Dict[str, Any]:
    """Get cached configuration, loading it if necessary."""
    return _get_config_direct()

# Lazy loading functions for backwards compatibility
def get_token() -> str:
    """Get Discord bot token."""
    return _get_config()['TOKEN']

def get_debug() -> bool:
    """Get debug mode setting."""
    return _get_config()['DEBUG']

def get_log_file() -> str:
    """Get log file path."""
    return _get_config()['LOG_FILE']

def get_db_user() -> str:
    """Get database user."""
    return _get_config()['DB_USER']

def get_db_host() -> str:
    """Get database host."""
    return _get_config()['DB_HOST']

def get_db_port() -> int:
    """Get database port."""
    return _get_config()['DB_PORT']

def get_db_name() -> str:
    """Get database name."""
    return _get_config()['DB_NAME']

def get_db_password() -> str:
    """Securely get database password without storing it globally."""
    return _get_config()['get_db_password']()

def get_max_memory_mb() -> int:
    """Get maximum memory limit in MB."""
    return _get_config()['MAX_MEMORY_MB']

def get_max_cpu_percent() -> int:
    """Get maximum CPU usage percentage."""
    return _get_config()['MAX_CPU_PERCENT']

def get_max_reconnect_attempts() -> int:
    """Get maximum reconnection attempts."""
    return _get_config()['MAX_RECONNECT_ATTEMPTS']

def get_rate_limit_per_minute() -> int:
    """Get rate limit per minute."""
    return _get_config()['RATE_LIMIT_PER_MINUTE']

def get_db_pool_size() -> int:
    """Get database connection pool size."""
    return _get_config()['DB_POOL_SIZE']

def get_db_timeout() -> int:
    """Get database timeout in seconds."""
    return _get_config()['DB_TIMEOUT']

def get_db_circuit_breaker_threshold() -> int:
    """Get database circuit breaker threshold."""
    return _get_config()['DB_CIRCUIT_BREAKER_THRESHOLD']

def get_translation_file() -> str:
    """Get translation file path."""
    return _get_config()['TRANSLATION_FILE']

def get_max_translation_file_size() -> int:
    """Get maximum translation file size in bytes."""
    return _get_config()['MAX_TRANSLATION_FILE_SIZE']

# Module-level variables for backwards compatibility (lazy loading)
# These will trigger config loading when accessed
TOKEN: str = None  # type: ignore
DEBUG: bool = None  # type: ignore
LOG_FILE: str = None  # type: ignore
DB_USER: str = None  # type: ignore
DB_HOST: str = None  # type: ignore
DB_PORT: int = None  # type: ignore
DB_NAME: str = None  # type: ignore
MAX_MEMORY_MB: int = None  # type: ignore
MAX_CPU_PERCENT: int = None  # type: ignore
MAX_RECONNECT_ATTEMPTS: int = None  # type: ignore
RATE_LIMIT_PER_MINUTE: int = None  # type: ignore
DB_POOL_SIZE: int = None  # type: ignore
DB_TIMEOUT: int = None  # type: ignore
DB_CIRCUIT_BREAKER_THRESHOLD: int = None  # type: ignore
TRANSLATION_FILE: str = None  # type: ignore
MAX_TRANSLATION_FILE_SIZE: int = None  # type: ignore


# ==================================================================================== #
#                            Immediate Validation (Optional)
# ==================================================================================== #

# Only perform immediate loading if not in test context
if not ('pytest' in sys.modules or 'unittest' in sys.modules):
    try:
        # Trigger configuration loading and validation
        _config_cache = load_config()
        _assign_module_vars()  # Assign to module-level variables
        _log_json("info", "config_module_initialized", immediate_load=True)
    except ConfigError as e:
        _log_json("critical", "config_initialization_failed", error_msg=str(e))
        sys.exit(1)
    except Exception as e:
        _log_json("critical", "config_unexpected_error", 
                 error_type=type(e).__name__, error_msg=str(e))
        sys.exit(1)
else:
    _log_json("debug", "config_module_initialized", immediate_load=False, reason="test_context")