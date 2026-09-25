"""Job handlers, registered by type with @job_handler("type.name")."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nodly.config import Settings


class PermanentJobError(Exception):
    """Raise from a handler when retrying can't help (e.g. a malformed payload): the job goes
    straight to dead instead of using up its remaining attempts."""


@dataclass(frozen=True)
class JobContext:
    job_id: int
    job_type: str
    attempt: int  # 1 on the first run
    max_attempts: int
    settings: Settings
    # Handlers open their own sessions and commit their own work.
    sessionmaker: async_sessionmaker[AsyncSession]


JobHandler = Callable[[JobContext, dict[str, Any]], Awaitable[None]]

HANDLERS: dict[str, JobHandler] = {}


def job_handler(job_type: str) -> Callable[[JobHandler], JobHandler]:
    def register(handler: JobHandler) -> JobHandler:
        if job_type in HANDLERS:
            raise ValueError(f"A handler for job type {job_type!r} is already registered")
        HANDLERS[job_type] = handler
        return handler

    return register
