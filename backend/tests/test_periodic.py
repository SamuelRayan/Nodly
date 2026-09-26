"""Periodic tasks in the worker (the check-in engine's tick runs this way)."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncEngine

from nodly.config import Settings
from nodly.db import create_sessionmaker
from nodly.jobs.registry import PeriodicContext, PeriodicTask
from nodly.worker import Worker
from tests.conftest import make_settings


def fast(settings: Settings) -> float:
    return 0.05


async def run_for(worker: Worker, seconds: float) -> None:
    stop = asyncio.Event()
    runner = asyncio.create_task(worker.run(stop))
    await asyncio.sleep(seconds)
    stop.set()
    await runner


async def test_periodic_tasks_repeat_without_overlapping(
    clean_db: AsyncEngine, test_database_url: str
) -> None:
    settings = make_settings(test_database_url, worker_poll_interval_seconds=0.01)
    starts: list[PeriodicContext] = []
    running = 0
    overlapped = False

    async def slow(ctx: PeriodicContext) -> None:
        nonlocal running, overlapped
        starts.append(ctx)
        running += 1
        overlapped |= running > 1
        await asyncio.sleep(0.12)  # longer than the interval
        running -= 1

    worker = Worker(
        settings,
        create_sessionmaker(clean_db),
        handlers={},
        periodic={"slow": PeriodicTask("slow", fast, slow)},
    )
    await run_for(worker, 0.5)
    assert 2 <= len(starts) <= 5
    assert not overlapped
    assert all(ctx.settings is settings for ctx in starts)


async def test_a_failing_periodic_task_keeps_its_schedule(
    clean_db: AsyncEngine, test_database_url: str
) -> None:
    settings = make_settings(test_database_url, worker_poll_interval_seconds=0.01)
    runs = 0

    async def broken(ctx: PeriodicContext) -> None:
        nonlocal runs
        runs += 1
        raise RuntimeError("boom")

    worker = Worker(
        settings,
        create_sessionmaker(clean_db),
        handlers={},
        periodic={"broken": PeriodicTask("broken", fast, broken)},
    )
    await run_for(worker, 0.3)
    assert runs >= 3


async def test_workers_run_no_periodic_tasks_unless_given(
    clean_db: AsyncEngine, test_database_url: str
) -> None:
    worker = Worker(make_settings(test_database_url), create_sessionmaker(clean_db))
    assert worker.periodic == {}
