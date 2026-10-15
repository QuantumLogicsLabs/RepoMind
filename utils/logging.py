"""utils/logging.py

Structured JSON Logging module for RepoMind.

Provides structured JSON log formatting for production monitoring, event tracing,
and unified log structure across API handlers, agent execution, tools, and job management.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from datetime import UTC, datetime
from typing import Any


class JSONFormatter(logging.Formatter):
    """
    Formatter that outputs log records as structured JSON lines.
    Includes standard metadata and extra attributes passed via extra={...}.
    """

    RESERVED_ATTRS: set[str] = {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        log_obj: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
        }

        # Include exception details if present
        if record.exc_info:
            exc_type, exc_val, exc_tb = record.exc_info
            log_obj["exception"] = {
                "type": exc_type.__name__ if exc_type else "Exception",
                "message": str(exc_val),
                "traceback": "".join(traceback.format_exception(exc_type, exc_val, exc_tb)),
            }

        # Collect extra attributes passed in extra={...}
        extra_fields = {
            key: value
            for key, value in record.__dict__.items()
            if key not in self.RESERVED_ATTRS and not key.startswith("_")
        }
        if extra_fields:
            log_obj["extra"] = extra_fields

        return json.dumps(log_obj, default=str)


def setup_logging(
    log_level: str = "INFO",
    json_format: bool = True,
    stream: Any = None,
) -> logging.Logger:
    """
    Configure root logging handlers and formatters for RepoMind.

    Args:
        log_level: Log level string (e.g. "DEBUG", "INFO", "WARNING", "ERROR").
        json_format: If True, log records are output in JSON format.
        stream: Output stream (defaults to sys.stdout).

    Returns:
        The configured root logger.
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Remove existing handlers to avoid duplicate logs
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setLevel(numeric_level)

    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        fmt = "%(asctime)s [%(levelname)s] %(name)s (%(module)s:%(lineno)d): %(message)s"
        handler.setFormatter(logging.Formatter(fmt))

    root_logger.addHandler(handler)
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Return a logger instance for the given module name."""
    return logging.getLogger(name)
