"""Job handlers, registered by type with @job_handler("type.name")."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
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


# ---------------------------------------------------------------- periodic tasks


@dataclass(frozen=True)
class PeriodicContext:
    settings: Settings
    sessionmaker: async_sessionmaker[AsyncSession]
    now: datetime  # the worker's clock when this run started


PeriodicRun = Callable[[PeriodicContext], Awaitable[None]]


@dataclass(frozen=True)
class PeriodicTask:
    name: str
    interval: Callable[[Settings], float]  # seconds between starts
    run: PeriodicRun


PERIODIC: dict[str, PeriodicTask] = {}


def periodic_task(
    name: str, interval: Callable[[Settings], float]
) -> Callable[[PeriodicRun], PeriodicRun]:
    """Run a function every `interval(settings)` seconds inside the worker (e.g. the check-in
    engine's tick). A run that's still going when the next is due is not started twice.
    Tasks must be safe to run concurrently from several workers."""

    def register(run: PeriodicRun) -> PeriodicRun:
        if name in PERIODIC:
            raise ValueError(f"A periodic task {name!r} is already registered")
        PERIODIC[name] = PeriodicTask(name, interval, run)
        return run

    return register
