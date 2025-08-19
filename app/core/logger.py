"""
Global Logger - Centralized JSON structured logging for all components.

Provides unified logging functionality across the Discord bot with features including:
- Standardized JSON output format with correlation ID support
- PII masking for production compliance
- Component-specific logging with version tracking
- Thread-safe operations for multi-component usage
- Consistent timestamp and field formatting
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional
from contextvars import ContextVar

correlation_id_context: ContextVar[Optional[str]] = ContextVar(
    "correlation_id", default=None
)

def log_json(component: str, level: str, event: str, **fields) -> None:
    """
    Log structured JSON message with correlation ID and PII masking.

    Args:
        component: Component name (e.g., "cache", "reliability")
        level: Log level ("debug", "info", "warning", "error", "critical")
        event: Event identifier
        **fields: Additional fields to log
    """
    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "level": level.upper(),
        "event": event,
        "component": component,
        "version": "1.0",
    }

    correlation_id = correlation_id_context.get(None)
    if correlation_id:
        log_entry["correlation_id"] = (
            str(correlation_id)[:8] if len(str(correlation_id)) > 8 else correlation_id
        )

    is_production = os.environ.get("PRODUCTION", "False").lower() == "true"
    for key, value in fields.items():
        if (
            "password" in key.lower()
            or "token" in key.lower()
            or "secret" in key.lower()
        ):
            log_entry[key] = "REDACTED"
        elif is_production and key in (
            "guild_id",
            "user_id",
            "guild_ids",
            "user_ids",
            "member_id",
            "channel_id",
        ):
            log_entry[key] = "REDACTED"
        elif key == "exc_info" and is_production:
            if isinstance(value, tuple) and len(value) >= 2:
                log_entry["exception_type"] = value[0].__name__ if value[0] else "Unknown"
                log_entry["exception_message"] = str(value[1]) if value[1] else "No message"
            elif value is True:
                import sys
                exc_info = sys.exc_info()
                if exc_info[0]:
                    log_entry["exception_type"] = exc_info[0].__name__
                    log_entry["exception_message"] = str(exc_info[1])
        elif key == "exc_info" and not is_production:
            log_entry[key] = value
        else:
            log_entry[key] = value

    json_str = json.dumps(log_entry, separators=(",", ":"))
    getattr(logging, level.lower())(json_str)

class ComponentLogger:
    """
    Component-specific logger wrapper for consistent logging.

    Automatically includes component name in all log calls.
    """

    def __init__(self, component_name: str):
        """
        Initialize component logger.

        Args:
            component_name: Name of the component using this logger
        """
        self.component_name = component_name

    def debug(self, event: str, **fields) -> None:
        """Log debug message."""
        log_json(self.component_name, "debug", event, **fields)

    def info(self, event: str, **fields) -> None:
        """Log info message."""
        log_json(self.component_name, "info", event, **fields)

    def warning(self, event: str, **fields) -> None:
        """Log warning message."""
        log_json(self.component_name, "warning", event, **fields)

    def error(self, event: str, **fields) -> None:
        """Log error message."""
        log_json(self.component_name, "error", event, **fields)

    def critical(self, event: str, **fields) -> None:
        """Log critical message."""
        log_json(self.component_name, "critical", event, **fields)
