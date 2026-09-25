"""Structured logging: one JSON object per line on stdout.

Context such as the request ID (API) or job ID (worker) is bound with `bind_log_context()` and
added to every line logged inside it, including lines from libraries.
"""

import json
import logging
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from nodly.config import Settings

_log_context: ContextVar[Mapping[str, Any]] = ContextVar("nodly_log_context", default={})  # noqa: B039  # read-only default, never mutated

# Attributes every LogRecord has; anything else on a record came from `extra=`.
_RECORD_ATTRS = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}
# Extras that uvicorn adds for its own coloured console output.
_IGNORED_EXTRAS = frozenset({"color_message"})

_HANDLER_MARK = "_nodly_handler"


@contextmanager
def bind_log_context(**values: Any) -> Iterator[None]:
    """Add key/values to every log line written inside this block (nested blocks merge)."""
    token = _log_context.set({**_log_context.get(), **values})
    try:
        yield
    finally:
        _log_context.reset(token)


def current_log_context() -> Mapping[str, Any]:
    return _log_context.get()


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.__dict__.items()
        if key not in _RECORD_ATTRS and key not in _IGNORED_EXTRAS and not key.startswith("_")
    }


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        created = datetime.fromtimestamp(record.created, UTC)
        payload: dict[str, Any] = {
            "ts": created.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update(_log_context.get())
        payload.update(_extras(record))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        # ensure_ascii keeps lines safe on Windows consoles with legacy code pages.
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human-readable lines for local development (LOG_FORMAT=console)."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        fields = {**_log_context.get(), **_extras(record)}
        if fields:
            line += "  " + " ".join(f"{key}={value}" for key, value in fields.items())
        return line


def configure_logging(settings: Settings) -> None:
    """Send all logging (ours, uvicorn's, SQLAlchemy's) through one stdout handler. Idempotent."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if settings.log_format == "json" else ConsoleFormatter())
    setattr(handler, _HANDLER_MARK, True)
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    # uvicorn installs its own handlers before it imports the app; route them through ours.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    # Our request middleware writes one access line per request (with the request ID).
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    access.disabled = True

    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.db_echo else logging.WARNING
    )
