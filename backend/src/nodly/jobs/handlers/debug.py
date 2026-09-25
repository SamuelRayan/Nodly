"""Handlers for checking the worker by hand (enqueue them from the /dev routes)."""

import logging
from typing import Any

from nodly.jobs.registry import JobContext, job_handler

logger = logging.getLogger(__name__)


@job_handler("debug.echo")
async def echo(ctx: JobContext, payload: dict[str, Any]) -> None:
    """Logs its payload and succeeds."""
    logger.info("debug.echo", extra={"payload": payload})


@job_handler("debug.fail")
async def fail(ctx: JobContext, payload: dict[str, Any]) -> None:
    """Always fails, so you can watch retries with backoff and then the dead-letter state."""
    raise RuntimeError(payload.get("message", "debug.fail always fails"))
