"""
Enterprise-grade Translation System with Full Observability and Security.

This module provides a robust, thread-safe translation system with:
- Immutable mappings and secure file access
- Comprehensive validation and PII protection
- Full observability with metrics and structured logging
- Automatic reloading and fallback mechanisms
- Safe formatting with placeholder validation
"""

import hashlib
import json
import os
import re
import stat
import threading
import time
import unicodedata
from collections.abc import Mapping
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import TRANSLATION_FILE, MAX_TRANSLATION_FILE_SIZE
from .logger import ComponentLogger

# #################################################################################### #
#                                    Constants
# #################################################################################### #
_logger = ComponentLogger("translation")

LOCALE_PATTERN = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")
KEY_PATTERN = re.compile(r"^[a-z0-9_.-]{1,128}$")
PLACEHOLDER_PATTERN = re.compile(r"\{(\w+)\}")
PII_PATTERNS = [
    re.compile(r"\b\d{17,20}\b"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
]

MAX_LOCALES = 50
MAX_NAMESPACES = 100
MAX_KEYS_PER_LOCALE = 10000
MAX_VALUE_LENGTH = 4096
MAX_OBJECT_DEPTH = 4

FAST_LOAD_THRESHOLD_MS = 100
SLOW_LOAD_THRESHOLD_MS = 1000

FALLBACK_BUNDLE = {
    "en": {
        "core": {
            "error.generic": "An error occurred",
            "error.permission": "Permission denied",
            "error.not_found": "Not found",
            "error.invalid_input": "Invalid input",
            "error.rate_limit": "Rate limit exceeded",
            "bot.starting": "Bot is starting...",
            "bot.ready": "Bot is ready",
            "bot.shutdown": "Bot is shutting down",
        }
    }
}

# #################################################################################### #
#                                Custom Exceptions
# #################################################################################### #
class TranslationError(Exception):
    """Base exception for translation system errors."""

    pass

class TranslationsLoadError(TranslationError):
    """Critical error during translation loading."""

    pass

class TranslationsSchemaError(TranslationError):
    """Translation file schema validation error."""

    pass

class TranslationsIOError(TranslationError):
    """I/O error during translation operations."""

    pass

class TranslationsSecurityError(TranslationError):
    """Security violation in translation system."""

    pass

# #################################################################################### #
#                             Observability Infrastructure
# #################################################################################### #
correlation_id_context: ContextVar[Optional[str]] = ContextVar(
    "correlation_id", default=None
)

class MetricsCollector:
    """Collects and aggregates metrics with 15-minute windows."""

    def __init__(self):
        self.lock = threading.Lock()
        self.reset_window()

    def reset_window(self):
        """Reset metrics for new window."""
        self.window_start = time.time()
        self.load_timings = []
        self.reload_count = 0
        self.missing_key_counts = {}
        self.placeholder_mismatch_count = 0
        self.security_denied_count = 0
        self.entries_count = 0
        self.size_bytes = 0
        self.fallback_active = False

    def record_load(self, duration_seconds: float, status: str):
        """Record a load operation."""
        with self.lock:
            self._check_window()
            self.load_timings.append((duration_seconds, status))

    def record_reload(self):
        """Record a reload operation."""
        with self.lock:
            self._check_window()
            self.reload_count += 1

    def record_missing_key(self, locale: str, key: str):
        """Record a missing translation key."""
        with self.lock:
            self._check_window()
            locale_key = f"{locale}.{key}"
            self.missing_key_counts[locale_key] = (
                self.missing_key_counts.get(locale_key, 0) + 1
            )

    def record_placeholder_mismatch(self):
        """Record a placeholder mismatch."""
        with self.lock:
            self._check_window()
            self.placeholder_mismatch_count += 1

    def record_security_denied(self):
        """Record a security denial."""
        with self.lock:
            self._check_window()
            self.security_denied_count += 1

    def set_entries(self, count: int):
        """Set the current number of translation entries."""
        with self.lock:
            self.entries_count = count

    def set_size(self, bytes_count: int):
        """Set the current size of translations in bytes."""
        with self.lock:
            self.size_bytes = bytes_count

    def set_fallback(self, active: bool):
        """Set fallback status."""
        with self.lock:
            self.fallback_active = active

    def _check_window(self):
        """Check if we need to reset the window (15 minutes)."""
        if time.time() - self.window_start > 900:
            self.reset_window()

    def get_stats(self) -> Dict[str, Any]:
        """Get current metrics statistics."""
        with self.lock:
            self._check_window()

            if self.load_timings:
                load_times = [t[0] for t in self.load_timings]
                fast_loads = sum(
                    1 for t in load_times if t < FAST_LOAD_THRESHOLD_MS / 1000
                )
                slow_loads = sum(
                    1 for t in load_times if t > SLOW_LOAD_THRESHOLD_MS / 1000
                )
                p95_load = (
                    sorted(load_times)[int(len(load_times) * 0.95)]
                    if len(load_times) > 1
                    else load_times[0]
                )
            else:
                fast_loads = slow_loads = p95_load = 0

            return {
                "window_start": datetime.fromtimestamp(
                    self.window_start, tz=timezone.utc
                ).isoformat(),
                "load_count": len(self.load_timings),
                "fast_loads": fast_loads,
                "slow_loads": slow_loads,
                "p95_load_seconds": p95_load,
                "reload_count": self.reload_count,
                "missing_key_total": sum(self.missing_key_counts.values()),
                "unique_missing_keys": len(self.missing_key_counts),
                "placeholder_mismatch_total": self.placeholder_mismatch_count,
                "security_denied_total": self.security_denied_count,
                "entries_count": self.entries_count,
                "size_bytes": self.size_bytes,
                "fallback_active": self.fallback_active,
            }

metrics = MetricsCollector()

# #################################################################################### #
#                              Structured Logging
# #################################################################################### #
class JSONLogger:
    """Structured JSON logging with correlation IDs."""

    @staticmethod
    def log(level: str, event: str, **kwargs):
        """Log a structured event."""
        corr_id = correlation_id_context.get()

        log_entry = {
            "ver": "1.0",
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "component": "translations",
            "event": event,
        }

        if corr_id:
            log_entry["corr_id"] = corr_id[:8]

        log_entry.update(kwargs)

        log_msg = json.dumps(log_entry, separators=(",", ":"))

        event_name = log_entry.pop("event", "unknown")
        log_entry.pop("level", None)
        log_entry.pop("component", None)
        
        if level == "ERROR":
            _logger.error(event_name, **log_entry)
        elif level == "WARNING":
            _logger.warning(event_name, **log_entry)
        else:
            _logger.info(event_name, **log_entry)

logger = JSONLogger()

# #################################################################################### #
#                              Immutable Mapping Wrapper
# #################################################################################### #
class ImmutableTranslationMapping(Mapping):
    """Read-only wrapper for translation dictionaries."""

    def __init__(self, data: Dict[str, Any]):
        self._data = data
        self._hash = hash(json.dumps(data, sort_keys=True))

    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def __hash__(self):
        return self._hash

    def get_nested(self, locale: str, namespace: str, key: str, default=None):
        """Safely get a nested translation value."""
        try:
            return self._data[locale][namespace][key]
        except (KeyError, TypeError):
            return default

# #################################################################################### #
#                           Security and Validation
# #################################################################################### #
class SecurityValidator:
    """Handles all security and validation checks."""

    @staticmethod
    def validate_file_path(file_path: str) -> Path:
        """Validate and secure file path."""
        path = Path(file_path).resolve()

        app_home = Path(os.environ.get("APP_HOME", os.getcwd())).resolve()
        allowed_dirs = [
            app_home / "config",
            app_home / "app" / "config"
        ]

        if not any(path.is_relative_to(allowed_dir) for allowed_dir in allowed_dirs):
            metrics.record_security_denied()
            raise TranslationsSecurityError(f"Path outside allowed directories: {path}")

        if path.is_symlink():
            metrics.record_security_denied()
            raise TranslationsSecurityError(f"Symlinks not allowed: {path}")

        if path.exists():
            file_stat = path.stat()

            if file_stat.st_mode & stat.S_IWOTH:
                metrics.record_security_denied()
                raise TranslationsSecurityError(f"File is world-writable: {path}")

            if hasattr(os, "getuid") and file_stat.st_uid != os.getuid():
                metrics.record_security_denied()
                raise TranslationsSecurityError(f"File owned by different user: {path}")

        return path

    @staticmethod
    def validate_schema(data: Dict[str, Any]) -> None:
        """Validate translation data schema."""
        if not isinstance(data, dict):
            raise TranslationsSchemaError("Root must be a dictionary")

        def check_depth(obj, current_depth=0):
            if current_depth > MAX_OBJECT_DEPTH:
                raise TranslationsSchemaError(
                    f"Object depth exceeds {MAX_OBJECT_DEPTH}"
                )
            if isinstance(obj, dict):
                for value in obj.values():
                    check_depth(value, current_depth + 1)

        check_depth(data)

        total_keys = 0
        locales = set()
        all_placeholders = {}

        for locale, locale_data in data.items():
            if not LOCALE_PATTERN.match(locale):
                raise TranslationsSchemaError(f"Invalid locale format: {locale}")

            locales.add(locale)
            if len(locales) > MAX_LOCALES:
                raise TranslationsSchemaError(f"Too many locales (max {MAX_LOCALES})")

            if not isinstance(locale_data, dict):
                raise TranslationsSchemaError(
                    f"Locale '{locale}' must contain a dictionary"
                )

            locale_keys = 0

            for namespace, namespace_data in locale_data.items():
                if not isinstance(namespace_data, dict):
                    raise TranslationsSchemaError(
                        f"Namespace '{namespace}' must contain a dictionary"
                    )

                for key, value in namespace_data.items():
                    full_key = f"{namespace}.{key}"

                    if not KEY_PATTERN.match(key):
                        raise TranslationsSchemaError(f"Invalid key format: {key}")

                    if not isinstance(value, str):
                        raise TranslationsSchemaError(
                            f"Value for '{full_key}' must be a string"
                        )

                    if not value.strip():
                        raise TranslationsSchemaError(
                            f"Value for '{full_key}' cannot be empty"
                        )

                    if len(value) > MAX_VALUE_LENGTH:
                        raise TranslationsSchemaError(
                            f"Value for '{full_key}' exceeds max length"
                        )

                    normalized = unicodedata.normalize("NFC", value)
                    if normalized != value:
                        raise TranslationsSchemaError(
                            f"Value for '{full_key}' not in NFC form"
                        )

                    if value.startswith("\ufeff"):
                        raise TranslationsSchemaError(
                            f"BOM detected in value for '{full_key}'"
                        )

                    for char in value:
                        if unicodedata.category(char) == "Cc" and char not in "\t\n":
                            raise TranslationsSchemaError(
                                f"Control character in '{full_key}'"
                            )

                    placeholders = set(PLACEHOLDER_PATTERN.findall(value))
                    if full_key not in all_placeholders:
                        all_placeholders[full_key] = {}
                    all_placeholders[full_key][locale] = placeholders

                    for pii_pattern in PII_PATTERNS:
                        if pii_pattern.search(value):
                            raise TranslationsSecurityError(
                                f"PII detected in '{full_key}'"
                            )

                    locale_keys += 1
                    total_keys += 1

            if locale_keys > MAX_KEYS_PER_LOCALE:
                raise TranslationsSchemaError(f"Too many keys in locale '{locale}'")

        for key, locale_placeholders in all_placeholders.items():
            if len(locale_placeholders) > 1:
                placeholder_sets = list(locale_placeholders.values())
                if not all(p == placeholder_sets[0] for p in placeholder_sets):
                    metrics.record_placeholder_mismatch()
                    raise TranslationsSchemaError(
                        f"Placeholder mismatch for '{key}' across locales"
                    )

# #################################################################################### #
#                            Translation Manager
# #################################################################################### #
class TranslationManager:
    """Thread-safe translation manager with hot-reload and fallback support."""

    def __init__(self):
        self._lock = threading.RLock()
        self._translations: Optional[ImmutableTranslationMapping] = None
        self._file_mtime: Optional[float] = None
        self._file_hash: Optional[str] = None
        self._using_fallback = False
        self._watchdog_alert_triggered = False
        self._cold_start_time = time.time()
        self._validator = SecurityValidator()

    def load_translations(self, *, allow_fallback: bool = True) -> Mapping[str, Any]:
        """
        Load translations from file with fallback support.

        Args:
            allow_fallback: Whether to use fallback bundle on failure

        Returns:
            Immutable mapping of translations

        Raises:
            TranslationsLoadError: If loading fails and fallback is disabled
        """
        start_time = time.monotonic()

        try:
            file_path = self._validator.validate_file_path(TRANSLATION_FILE)

            if not file_path.exists():
                raise TranslationsIOError(f"Translation file not found: {file_path}")

            file_size = file_path.stat().st_size
            if file_size > MAX_TRANSLATION_FILE_SIZE:
                raise TranslationsIOError(f"File too large: {file_size} bytes")
            if file_size == 0:
                raise TranslationsIOError("File is empty")

            content = file_path.read_bytes()

            if content.startswith(b"\xef\xbb\xbf"):
                content = content[3:]

            data = json.loads(content.decode("utf-8"))

            self._validator.validate_schema(data)

            file_hash = hashlib.sha256(content).hexdigest()

            with self._lock:
                self._translations = ImmutableTranslationMapping(data)
                self._file_mtime = file_path.stat().st_mtime
                self._file_hash = file_hash
                self._using_fallback = False

            duration = time.monotonic() - start_time
            metrics.record_load(duration, "success")
            metrics.set_entries(
                sum(len(ns) for locale in data.values() for ns in locale.values())
            )
            metrics.set_size(file_size)
            metrics.set_fallback(False)

            logger.log(
                "INFO",
                "load",
                status="success",
                duration_ms=int(duration * 1000),
                entries=len(data),
                size_bytes=file_size,
                hash=file_hash[:8],
                slow=duration > SLOW_LOAD_THRESHOLD_MS / 1000,
            )

            return self._translations

        except Exception as e:
            duration = time.monotonic() - start_time
            metrics.record_load(duration, "fail")

            logger.log(
                "ERROR",
                "load",
                status="fail",
                duration_ms=int(duration * 1000),
                error_type=type(e).__name__,
                msg=str(e),
                retryable=not isinstance(e, TranslationsSchemaError),
            )

            if allow_fallback:
                with self._lock:
                    self._translations = ImmutableTranslationMapping(FALLBACK_BUNDLE)
                    self._using_fallback = True

                metrics.set_fallback(True)
                metrics.record_load(0, "fallback")

                logger.log(
                    "ERROR",
                    "translation_fallback_activated",
                    status="fallback",
                    msg="Translation system degraded - using fallback bundle",
                    original_error=str(e),
                    action_required="Check translation file and schema",
                )

                return self._translations
            else:
                raise TranslationsLoadError(f"Failed to load translations: {e}") from e

    def reload_if_changed(self) -> bool:
        """
        Reload translations if file has changed.

        Returns:
            True if reloaded, False if unchanged
        """
        try:
            file_path = self._validator.validate_file_path(TRANSLATION_FILE)

            if not file_path.exists():
                return False

            current_mtime = file_path.stat().st_mtime

            with self._lock:
                if current_mtime == self._file_mtime:
                    return False

            content = file_path.read_bytes()
            current_hash = hashlib.sha256(content).hexdigest()

            with self._lock:
                if current_hash == self._file_hash:
                    self._file_mtime = current_mtime
                    return False

            self.load_translations(allow_fallback=False)
            metrics.record_reload()

            logger.log(
                "INFO",
                "reload",
                status="success",
                old_hash=self._file_hash[:8] if self._file_hash else None,
                new_hash=current_hash[:8],
            )

            return True

        except Exception as e:
            self._watchdog_alert_triggered = True

            logger.log(
                "ERROR",
                "reload",
                status="fail",
                error_type=type(e).__name__,
                msg=str(e),
            )

            return False

    def get(
        self,
        locale: str,
        key: str,
        /,
        default: Optional[str] = None,
        *,
        safe_format: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Get a translation with safe formatting.

        Args:
            locale: Language locale (e.g., 'en', 'fr')
            key: Translation key in format 'namespace.key'
            default: Default value if key not found
            safe_format: Dictionary of values for safe string formatting

        Returns:
            Translated and formatted string
        """
        parts = key.split(".", 1)
        if len(parts) != 2:
            metrics.record_missing_key(locale, key)
            return default or f"[{key}]"

        namespace, key_name = parts

        with self._lock:
            if not self._translations:
                return default or f"[{key}]"

            value = self._translations.get_nested(locale, namespace, key_name)

        if value is None:
            with self._lock:
                value = self._translations.get_nested("en", namespace, key_name)

        if value is None:
            metrics.record_missing_key(locale, key)

            if os.environ.get("ENV") == "production":
                return default or f"[{namespace}.{key_name}]"
            else:
                raise KeyError(
                    f"Translation not found: {locale}/{namespace}/{key_name}"
                )

        if safe_format:
            try:
                formatted = value
                for key, val in safe_format.items():
                    if os.environ.get("ENV") == "production":
                        if key in ("guild_id", "user_id", "channel_id"):
                            val = "REDACTED"

                    formatted = formatted.replace(f"{{{key}}}", str(val))

                return formatted
            except Exception as e:
                logger.log(
                    "ERROR",
                    "format",
                    locale=locale,
                    key=f"{namespace}.{key_name}",
                    error_type=type(e).__name__,
                )
                return value
        else:
            return value

    def stats(self) -> Dict[str, Any]:
        """
        Get translation system statistics.

        Returns:
            Dictionary of statistics and health information
        """
        with self._lock:
            loaded = self._translations is not None

            if loaded:
                locale_count = len(self._translations._data)
                entry_count = sum(
                    len(ns)
                    for locale in self._translations._data.values()
                    for ns in locale.values()
                )
            else:
                locale_count = entry_count = 0

        metric_stats = metrics.get_stats()

        in_cold_start = (time.time() - self._cold_start_time) < 300

        return {
            "loaded": loaded,
            "locales": locale_count,
            "entries": entry_count,
            "fallback": self._using_fallback,
            "watchdog_alert": self._watchdog_alert_triggered and not in_cold_start,
            "file_hash": self._file_hash[:8] if self._file_hash else None,
            "metrics": metric_stats,
        }

# #################################################################################### #
#                                Global Instance
# #################################################################################### #
_manager = TranslationManager()

def load_translations(*, allow_fallback: bool = True) -> Mapping[str, Any]:
    """Load translations from file."""
    return _manager.load_translations(allow_fallback=allow_fallback)

def reload_if_changed() -> bool:
    """Reload translations if file has changed."""
    return _manager.reload_if_changed()

def get(
    locale: str,
    key: str,
    /,
    default: Optional[str] = None,
    *,
    safe_format: Optional[Dict[str, Any]] = None,
) -> str:
    """Get a translation with safe formatting."""
    return _manager.get(locale, key, default, safe_format=safe_format)

def stats() -> Dict[str, Any]:
    """Get translation system statistics."""
    return _manager.stats()

# #################################################################################### #
#                                  Auto-load
# #################################################################################### #
try:
    translations = load_translations(allow_fallback=True)
except Exception as e:
    logger.log(
        "CRITICAL", "init", status="fail", error_type=type(e).__name__, msg=str(e)
    )
    translations = None
