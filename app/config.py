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
import re
import tempfile
from typing import Optional, Any, Union, Mapping
from types import MappingProxyType
from contextvars import ContextVar

from dotenv import load_dotenv
from .core.logger import ComponentLogger

correlation_id_context: ContextVar[Optional[str]] = ContextVar(
    "correlation_id", default=None
)

_logger = ComponentLogger("config")

class ConfigError(Exception):
    """Custom exception for configuration-related errors."""
    pass

env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(env_path)

# #################################################################################### #
#                            Validation Ranges and Logging
# #################################################################################### #
def parse_bool(value: str, default: bool = False) -> bool:
    """Parse boolean value from string with consistent normalization.

    Args:
        value: String value to parse
        default: Default value if empty or None

    Returns:
        Parsed boolean value
    """
    if not value:
        return default
    return value.strip().lower() in ("true", "1", "yes", "on", "y")

VALIDATION_RANGES = {
    "MAX_MEMORY_MB": (50, 2048),
    "MAX_CPU_PERCENT": (10, 95),
    "MAX_RECONNECT_ATTEMPTS": (1, 10),
    "RATE_LIMIT_PER_MINUTE": (10, 1000),
    "DB_POOL_SIZE": (1, 50),
    "DB_TIMEOUT": (5, 30),
    "DB_CIRCUIT_BREAKER_THRESHOLD": (3, 20),
    "MAX_TRANSLATION_FILE_SIZE": (1024, 50 * 1024 * 1024),
    "DB_PORT": (1, 65535),
}

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

def validate_int_env_var(
    var_name: str,
    value: Optional[str],
    default: Optional[int] = None,
    auto_clamp: bool = False,
) -> int:
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
            raise ConfigError(
                f"Missing required integer environment variable: {var_name}"
            )
        return default
    try:
        parsed_value = int(value)

        if auto_clamp and var_name in VALIDATION_RANGES:
            min_val, max_val = VALIDATION_RANGES[var_name]
            if parsed_value < min_val:
                _logger.warning("config_value_clamped",
                    variable=var_name,
                    original=parsed_value,
                    clamped=min_val,
                    reason="below_minimum",
                    range_min=min_val,
                    range_max=max_val,
                )
                return min_val
            elif parsed_value > max_val:
                _logger.warning("config_value_clamped",
                    variable=var_name,
                    original=parsed_value,
                    clamped=max_val,
                    reason="above_maximum",
                    range_min=min_val,
                    range_max=max_val,
                )
                return max_val

        return parsed_value
    except ValueError:
        raise ConfigError(f"Invalid integer value for {var_name}: {value}")

def validate_file_exists(file_path: str, var_name: str) -> Union[int, bool]:
    """Validate that a file exists and is readable.

    Returns:
        File size in bytes if file exists and is readable, False otherwise.
    """
    if not os.path.isfile(file_path):
        _logger.error("file_not_found", variable=var_name, file_path=file_path)
        return False

    try:
        file_size = os.path.getsize(file_path)
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read(1)
        safe_path = file_path if not any(secret in file_path.lower() for secret in ["password", "token", "key", "secret"]) else "[REDACTED_PATH]"
        _logger.debug("file_validated",
            variable=var_name,
            file_path=safe_path,
            size_bytes=file_size,
        )
        return file_size
    except (IOError, OSError) as e:
        safe_path = file_path if not any(secret in file_path.lower() for secret in ["password", "token", "key", "secret"]) else "[REDACTED_PATH]"
        _logger.error("file_read_error",
            variable=var_name,
            file_path=safe_path,
            error_type=type(e).__name__,
            error_msg=str(e),
        )
        return False

def validate_ranges(var_name: str, value: int) -> None:
    """Validate value against defined ranges and log warnings."""
    if var_name in VALIDATION_RANGES:
        min_val, max_val = VALIDATION_RANGES[var_name]
        if not (min_val <= value <= max_val):
            _logger.warning("config_value_out_of_range",
                variable=var_name,
                value=value,
                min_recommended=min_val,
                max_recommended=max_val,
            )

# #################################################################################### #
#                            Configuration Loading Function
# #################################################################################### #
def load_config() -> Mapping[str, Any]:
    """
    Load and validate all configuration from environment variables.

    Returns:
        Dict containing all validated configuration values

    Raises:
        ConfigError: If critical configuration is invalid or missing
    """
    config = {}
    auto_clamp = parse_bool(os.getenv("CONFIG_AUTO_CLAMP", "False"))

    try:
        # #################################################################################### #
        #                            Debug and Logging Configuration
        # #################################################################################### #
        config["DEBUG"] = parse_bool(os.getenv("DEBUG", "False"))
        config["PRODUCTION"] = parse_bool(os.getenv("PRODUCTION", "False"))

        LOG_DIR = "logs"
        log_fallback = False
        try:
            if not os.path.exists(LOG_DIR):
                os.makedirs(LOG_DIR, mode=0o750)
            config["LOG_FILE"] = os.path.join(LOG_DIR, "discord-bot.log")
            with open(config["LOG_FILE"], "a") as f:
                pass
        except (OSError, IOError) as e:
            _logger.warning("log_dir_fallback", original_dir=LOG_DIR, error=str(e))
            try:
                fallback_log = os.path.join(tempfile.gettempdir(), "discord-bot.log")
                with open(fallback_log, "a") as f:
                    pass
                config["LOG_FILE"] = fallback_log
                log_fallback = True
                safe_fallback = fallback_log if not any(secret in fallback_log.lower() for secret in ["password", "token", "key", "secret"]) else "[REDACTED_PATH]"
                _logger.info("log_file_fallback_success", fallback_path=safe_fallback
                )
            except (OSError, IOError) as fallback_error:
                raise ConfigError(
                    f"Cannot create log file in any location: {fallback_error}"
                )

        # #################################################################################### #
        #                            Discord Bot Configuration
        # #################################################################################### #
        bot_token = os.getenv("BOT_TOKEN")
        discord_token = os.getenv("DISCORD_TOKEN")

        if bot_token and discord_token:
            _logger.warning("multiple_token_sources",
                message="Both BOT_TOKEN and DISCORD_TOKEN are defined. Using BOT_TOKEN.",
            )
            config["TOKEN"] = bot_token
            _logger.info("token_source_selected", source="BOT_TOKEN")
        elif bot_token:
            config["TOKEN"] = bot_token
            _logger.info("token_source_detected", source="BOT_TOKEN")
        elif discord_token:
            config["TOKEN"] = discord_token
            _logger.info("token_source_detected", source="DISCORD_TOKEN")
        else:
            raise ConfigError(
                "Missing required environment variable: BOT_TOKEN or DISCORD_TOKEN"
            )

        if len(config["TOKEN"]) < 50:
            raise ConfigError("Invalid Discord token format - token too short")

        # #################################################################################### #
        #                            Database Configuration
        # #################################################################################### #
        config["DB_USER"] = validate_env_var("DB_USER", os.getenv("DB_USER"))
        db_password = validate_env_var(
            "DB_PASSWORD", os.getenv("DB_PASSWORD") or os.getenv("DB_PASS")
        )

        db_host = os.getenv("DB_HOST", "localhost")
        if db_host == "localhost" and not os.getenv("DB_HOST"):
            _logger.info("db_host_fallback",
                fallback_value="localhost",
                reason="env_var_not_set",
            )
        config["DB_HOST"] = db_host

        config["DB_PORT"] = validate_int_env_var(
            "DB_PORT", os.getenv("DB_PORT"), default=3306, auto_clamp=auto_clamp
        )
        validate_ranges("DB_PORT", config["DB_PORT"])

        config["DB_NAME"] = validate_env_var("DB_NAME", os.getenv("DB_NAME"))
        if len(config["DB_NAME"]) > 64:
            raise ConfigError(
                f"DB_NAME too long: {len(config['DB_NAME'])} characters (max 64)"
            )
        if not re.match(r"^[A-Za-z0-9_]+$", config["DB_NAME"]):
            raise ConfigError(
                f"DB_NAME contains invalid characters. Only alphanumeric and underscore allowed: {config['DB_NAME']}"
            )

        # #################################################################################### #
        #                            Performance and Resource Limits
        # #################################################################################### #
        config["MAX_MEMORY_MB"] = validate_int_env_var(
            "MAX_MEMORY_MB",
            os.getenv("MAX_MEMORY_MB"),
            default=1024,
            auto_clamp=auto_clamp,
        )
        validate_ranges("MAX_MEMORY_MB", config["MAX_MEMORY_MB"])

        config["MAX_CPU_PERCENT"] = validate_int_env_var(
            "MAX_CPU_PERCENT",
            os.getenv("MAX_CPU_PERCENT"),
            default=90,
            auto_clamp=auto_clamp,
        )
        validate_ranges("MAX_CPU_PERCENT", config["MAX_CPU_PERCENT"])

        config["MAX_RECONNECT_ATTEMPTS"] = validate_int_env_var(
            "MAX_RECONNECT_ATTEMPTS",
            os.getenv("MAX_RECONNECT_ATTEMPTS"),
            default=5,
            auto_clamp=auto_clamp,
        )
        validate_ranges("MAX_RECONNECT_ATTEMPTS", config["MAX_RECONNECT_ATTEMPTS"])

        config["RATE_LIMIT_PER_MINUTE"] = validate_int_env_var(
            "RATE_LIMIT_PER_MINUTE",
            os.getenv("RATE_LIMIT_PER_MINUTE"),
            default=100,
            auto_clamp=auto_clamp,
        )
        validate_ranges("RATE_LIMIT_PER_MINUTE", config["RATE_LIMIT_PER_MINUTE"])

        # #################################################################################### #
        #                            Database Connection Pool Settings
        # #################################################################################### #
        config["DB_POOL_SIZE"] = validate_int_env_var(
            "DB_POOL_SIZE", os.getenv("DB_POOL_SIZE"), default=25, auto_clamp=auto_clamp
        )
        validate_ranges("DB_POOL_SIZE", config["DB_POOL_SIZE"])

        config["DB_TIMEOUT"] = validate_int_env_var(
            "DB_TIMEOUT", os.getenv("DB_TIMEOUT"), default=15, auto_clamp=auto_clamp
        )
        validate_ranges("DB_TIMEOUT", config["DB_TIMEOUT"])

        config["DB_CIRCUIT_BREAKER_THRESHOLD"] = validate_int_env_var(
            "DB_CIRCUIT_BREAKER_THRESHOLD",
            os.getenv("DB_CIRCUIT_BREAKER_THRESHOLD"),
            default=5,
            auto_clamp=auto_clamp,
        )
        validate_ranges(
            "DB_CIRCUIT_BREAKER_THRESHOLD", config["DB_CIRCUIT_BREAKER_THRESHOLD"]
        )

        # #################################################################################### #
        #                            Translation System Configuration
        # #################################################################################### #
        config["MAX_TRANSLATION_FILE_SIZE"] = validate_int_env_var(
            "MAX_TRANSLATION_FILE_SIZE",
            os.getenv("MAX_TRANSLATION_FILE_SIZE"),
            default=5 * 1024 * 1024,
            auto_clamp=auto_clamp,
        )
        validate_ranges(
            "MAX_TRANSLATION_FILE_SIZE", config["MAX_TRANSLATION_FILE_SIZE"]
        )

        default_translation_path = os.path.join(
            os.path.dirname(__file__), "config", "translation.json"
        )
        translation_file = (
            validate_env_var(
                "TRANSLATION_FILE", os.getenv("TRANSLATION_FILE"), required=False
            )
            or default_translation_path
        )

        if not translation_file.endswith(".json"):
            safe_path = translation_file if not any(secret in translation_file.lower() for secret in ["password", "token", "key", "secret"]) else "[REDACTED_PATH]"
            _logger.warning("translation_file_extension",
                file_path=safe_path,
                expected=".json",
            )

        file_size_or_false = validate_file_exists(translation_file, "TRANSLATION_FILE")
        if file_size_or_false:
            abs_translation_file = os.path.abspath(translation_file)
            if file_size_or_false > config["MAX_TRANSLATION_FILE_SIZE"]:
                raise ConfigError(
                    f"Translation file too large: {file_size_or_false} bytes (max {config['MAX_TRANSLATION_FILE_SIZE']} bytes)"
                )
            config["TRANSLATION_FILE"] = abs_translation_file
        else:
            raise ConfigError(
                f"Translation file not found or not readable: {translation_file}"
            )

        _logger.info("config_loaded_successfully",
            total_vars=len(config),
            auto_clamp_enabled=auto_clamp,
            log_fallback_used=log_fallback,
        )

        config["get_db_password"] = lambda: db_password

        return MappingProxyType(config)

    except ConfigError:
        raise
    except Exception as e:
        raise ConfigError(f"Unexpected error during configuration loading: {e}")

# #################################################################################### #
#                            Global Configuration (Optional Immediate Load)
# #################################################################################### #
_config_cache: Optional[Mapping[str, Any]] = None

def _assign_module_vars():
    """Assign values to module-level variables for backwards compatibility."""
    global TOKEN, DEBUG, PRODUCTION, LOG_FILE, DB_USER, DB_HOST, DB_PORT, DB_NAME
    global MAX_MEMORY_MB, MAX_CPU_PERCENT, MAX_RECONNECT_ATTEMPTS, RATE_LIMIT_PER_MINUTE
    global DB_POOL_SIZE, DB_TIMEOUT, DB_CIRCUIT_BREAKER_THRESHOLD, TRANSLATION_FILE, MAX_TRANSLATION_FILE_SIZE

    config = _get_config_direct()
    TOKEN = config["TOKEN"]
    DEBUG = config["DEBUG"]
    PRODUCTION = config["PRODUCTION"]
    LOG_FILE = config["LOG_FILE"]
    DB_USER = config["DB_USER"]
    DB_HOST = config["DB_HOST"]
    DB_PORT = config["DB_PORT"]
    DB_NAME = config["DB_NAME"]
    MAX_MEMORY_MB = config["MAX_MEMORY_MB"]
    MAX_CPU_PERCENT = config["MAX_CPU_PERCENT"]
    MAX_RECONNECT_ATTEMPTS = config["MAX_RECONNECT_ATTEMPTS"]
    RATE_LIMIT_PER_MINUTE = config["RATE_LIMIT_PER_MINUTE"]
    DB_POOL_SIZE = config["DB_POOL_SIZE"]
    DB_TIMEOUT = config["DB_TIMEOUT"]
    DB_CIRCUIT_BREAKER_THRESHOLD = config["DB_CIRCUIT_BREAKER_THRESHOLD"]
    TRANSLATION_FILE = config["TRANSLATION_FILE"]
    MAX_TRANSLATION_FILE_SIZE = config["MAX_TRANSLATION_FILE_SIZE"]

def _get_config_direct() -> Mapping[str, Any]:
    """Get cached configuration directly without triggering assignment."""
    global _config_cache
    if _config_cache is None:
        _config_cache = load_config()
    return _config_cache

def _get_config() -> Mapping[str, Any]:
    """Get cached configuration, loading it if necessary."""
    return _get_config_direct()

def get_token() -> str:
    """Get Discord bot token."""
    return _get_config()["TOKEN"]

def get_debug() -> bool:
    """Get debug mode setting."""
    return _get_config()["DEBUG"]

def get_production() -> bool:
    """Get production mode setting."""
    return _get_config()["PRODUCTION"]

def get_log_file() -> str:
    """Get log file path."""
    return _get_config()["LOG_FILE"]

def get_db_user() -> str:
    """Get database user."""
    return _get_config()["DB_USER"]

def get_db_host() -> str:
    """Get database host."""
    return _get_config()["DB_HOST"]

def get_db_port() -> int:
    """Get database port."""
    return _get_config()["DB_PORT"]

def get_db_name() -> str:
    """Get database name."""
    return _get_config()["DB_NAME"]

def get_db_password() -> str:
    """Securely get database password without storing it globally."""
    return _get_config()["get_db_password"]()

def get_max_memory_mb() -> int:
    """Get maximum memory limit in MB."""
    return _get_config()["MAX_MEMORY_MB"]

def get_max_cpu_percent() -> int:
    """Get maximum CPU usage percentage."""
    return _get_config()["MAX_CPU_PERCENT"]

def get_max_reconnect_attempts() -> int:
    """Get maximum reconnection attempts."""
    return _get_config()["MAX_RECONNECT_ATTEMPTS"]

def get_rate_limit_per_minute() -> int:
    """Get rate limit per minute."""
    return _get_config()["RATE_LIMIT_PER_MINUTE"]

def get_db_pool_size() -> int:
    """Get database connection pool size."""
    return _get_config()["DB_POOL_SIZE"]

def get_db_timeout() -> int:
    """Get database timeout in seconds."""
    return _get_config()["DB_TIMEOUT"]

def get_db_circuit_breaker_threshold() -> int:
    """Get database circuit breaker threshold."""
    return _get_config()["DB_CIRCUIT_BREAKER_THRESHOLD"]

def get_translation_file() -> str:
    """Get translation file path."""
    return _get_config()["TRANSLATION_FILE"]

def get_max_translation_file_size() -> int:
    """Get maximum translation file size in bytes."""
    return _get_config()["MAX_TRANSLATION_FILE_SIZE"]

TOKEN: str = None  # type: ignore
DEBUG: bool = None  # type: ignore
PRODUCTION: bool = None  # type: ignore
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

# #################################################################################### #
#                            Immediate Validation (Optional)
# #################################################################################### #
config_immediate_load = parse_bool(
    os.getenv("CONFIG_IMMEDIATE_LOAD", "True"), default=True
)

if config_immediate_load and not ("pytest" in sys.modules or "unittest" in sys.modules):
    try:
        _config_cache = load_config()
        _assign_module_vars()
        _logger.info("config_module_initialized", immediate_load=True)
    except ConfigError as e:
        _logger.critical("config_initialization_failed", error_msg=str(e))
        sys.exit(1)
    except Exception as e:
        _logger.critical("config_unexpected_error",
            error_type=type(e).__name__,
            error_msg=str(e),
        )
        sys.exit(1)
else:
    _logger.debug("config_module_initialized",
        immediate_load=False,
        reason="test_context",
    )

# #################################################################################### #
#                            Public API Export
# #################################################################################### #
__all__ = [
    "load_config",
    "ConfigError",
    "get_token",
    "get_debug",
    "get_production",
    "get_log_file",
    "get_db_user",
    "get_db_host",
    "get_db_port",
    "get_db_name",
    "get_db_password",
    "get_max_memory_mb",
    "get_max_cpu_percent",
    "get_max_reconnect_attempts",
    "get_rate_limit_per_minute",
    "get_db_pool_size",
    "get_db_timeout",
    "get_db_circuit_breaker_threshold",
    "get_translation_file",
    "get_max_translation_file_size",
    "TOKEN",
    "DEBUG",
    "PRODUCTION",
    "LOG_FILE",
    "DB_USER",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "MAX_MEMORY_MB",
    "MAX_CPU_PERCENT",
    "MAX_RECONNECT_ATTEMPTS",
    "RATE_LIMIT_PER_MINUTE",
    "DB_POOL_SIZE",
    "DB_TIMEOUT",
    "DB_CIRCUIT_BREAKER_THRESHOLD",
    "TRANSLATION_FILE",
    "MAX_TRANSLATION_FILE_SIZE",
    "parse_bool",
    "correlation_id_context",
]
