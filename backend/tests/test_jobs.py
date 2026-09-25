"""The job queue and worker: enqueue idempotency, retries with backoff, dead-letter, stale-lock
reclaim, concurrent claims, and the run loop's shutdown."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import nodly.jobs.handlers  # noqa: F401  # registers the debug handlers
from nodly.config import get_settings
from nodly.errors import ConflictError
from nodly.jobs.queue import (
    backoff_seconds,
    claim_due,
    enqueue,
    mark_succeeded,
    reclaim_stale,
    requeue_dead,
)
from nodly.jobs.registry import HANDLERS, JobContext, JobHandler, PermanentJobError, job_handler
from nodly.models import Job, JobStatus
from nodly.worker import Worker
from tests.conftest import make_settings

START = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def sessionmaker(clean_db: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(clean_db, expire_on_commit=False)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def make_worker(
    test_database_url: str, sessionmaker: async_sessionmaker[AsyncSession], clock: FakeClock
):
    def build(handlers: dict[str, JobHandler], worker_id: str = "worker-a", **settings: Any):
        values: dict[str, Any] = {
            "job_backoff_base_seconds": 10,
            "job_backoff_max_seconds": 3600,
            **settings,
        }
        return Worker(
            make_settings(test_database_url, **values),
            sessionmaker,
            handlers=handlers,
            worker_id=worker_id,
            clock=clock,
            rand=lambda: 0.0,  # no jitter: exact retry times
        )

    return build


async def add_job(
    sessionmaker: async_sessionmaker[AsyncSession],
    job_type: str,
    payload: dict[str, Any] | None = None,
    *,
    run_at: datetime = START,
    **kwargs: Any,
) -> int:
    async with sessionmaker() as session:
        result = await enqueue(session, job_type, payload, run_at=run_at, **kwargs)
        await session.commit()
        return result.job.id


async def load(sessionmaker: async_sessionmaker[AsyncSession], job_id: int) -> Job:
    async with sessionmaker() as session:
        return await session.get_one(Job, job_id)


async def ok(ctx: JobContext, payload: dict[str, Any]) -> None:
    pass


async def boom(ctx: JobContext, payload: dict[str, Any]) -> None:
    raise RuntimeError("boom")


# ---------------------------------------------------------------- backoff


def test_backoff_doubles_then_caps() -> None:
    delays = [backoff_seconds(n, base=10, cap=60, rand=lambda: 0.0) for n in range(1, 6)]
    assert delays == [10, 20, 40, 60, 60]
    assert backoff_seconds(1, base=10, cap=60, rand=lambda: 1.0) == pytest.approx(11.0)
    assert backoff_seconds(10_000, base=10, cap=60, rand=lambda: 0.0) == 60


# ---------------------------------------------------------------- enqueue


async def test_enqueue_defaults(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    async with sessionmaker() as session:
        result = await enqueue(session, "debug.echo", {"hello": "world"})
        await session.commit()
    job = await load(sessionmaker, result.job.id)
    assert result.created
    assert job.status == JobStatus.queued
    assert job.payload == {"hello": "world"}
    assert job.attempts == 0
    assert job.max_attempts == get_settings().job_default_max_attempts
    assert job.run_at is not None


async def test_idempotency_key_returns_the_existing_job(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    first = await add_job(sessionmaker, "checkin.remind", idempotency_key="elder-1:2026-09-25")
    async with sessionmaker() as session:
        again = await enqueue(
            session, "checkin.remind", {"other": 1}, idempotency_key="elder-1:2026-09-25"
        )
        await session.commit()
    assert (again.created, again.job.id) == (False, first)
    assert again.job.payload == {}  # the original job is untouched
    async with sessionmaker() as session:
        assert len((await session.scalars(select(Job))).all()) == 1


async def test_idempotency_key_holds_after_the_job_finished(
    sessionmaker: async_sessionmaker[AsyncSession], make_worker, clock: FakeClock
) -> None:
    first = await add_job(sessionmaker, "x", idempotency_key="k")
    await make_worker({"x": ok}).run_once()
    assert (await load(sessionmaker, first)).status == JobStatus.succeeded
    async with sessionmaker() as session:
        again = await enqueue(session, "x", idempotency_key="k")
    assert (again.created, again.job.id) == (False, first)


async def test_keys_are_scoped_by_type_and_optional(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    ids = {
        await add_job(sessionmaker, "a", idempotency_key="same"),
        await add_job(sessionmaker, "b", idempotency_key="same"),
        await add_job(sessionmaker, "a"),
        await add_job(sessionmaker, "a"),
    }
    assert len(ids) == 4


async def test_enqueue_rolls_back_with_the_callers_transaction(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker() as session:
        await enqueue(session, "debug.echo")
        await session.rollback()
    async with sessionmaker() as session:
        assert (await session.scalars(select(Job))).all() == []


# ---------------------------------------------------------------- running jobs


async def test_success(sessionmaker: async_sessionmaker[AsyncSession], make_worker) -> None:
    seen: list[tuple[int, dict[str, Any]]] = []

    async def record(ctx: JobContext, payload: dict[str, Any]) -> None:
        seen.append((ctx.attempt, payload))

    job_id = await add_job(sessionmaker, "record", {"n": 1})
    assert await make_worker({"record": record}).run_once() == 1

    job = await load(sessionmaker, job_id)
    assert seen == [(1, {"n": 1})]
    assert (job.status, job.attempts, job.finished_at) == (JobStatus.succeeded, 1, START)
    assert (job.locked_at, job.locked_by) == (None, None)


async def test_future_jobs_wait_until_due(
    sessionmaker: async_sessionmaker[AsyncSession], make_worker, clock: FakeClock
) -> None:
    job_id = await add_job(sessionmaker, "x", run_at=START + timedelta(minutes=5))
    worker = make_worker({"x": ok})
    assert await worker.run_once() == 0
    clock.advance(300)
    assert await worker.run_once() == 1
    assert (await load(sessionmaker, job_id)).status == JobStatus.succeeded


async def test_failures_retry_with_backoff_then_go_dead(
    sessionmaker: async_sessionmaker[AsyncSession], make_worker, clock: FakeClock
) -> None:
    job_id = await add_job(sessionmaker, "boom", max_attempts=3)
    worker = make_worker({"boom": boom})

    await worker.run_once()
    job = await load(sessionmaker, job_id)
    assert (job.status, job.attempts) == (JobStatus.queued, 1)
    assert job.run_at == START + timedelta(seconds=10)
    assert "RuntimeError: boom" in (job.last_error or "")

    assert await worker.run_once() == 0  # not due yet
    clock.advance(10)
    await worker.run_once()
    job = await load(sessionmaker, job_id)
    assert (job.status, job.attempts) == (JobStatus.queued, 2)
    assert job.run_at == clock.now + timedelta(seconds=20)

    clock.advance(20)
    await worker.run_once()
    job = await load(sessionmaker, job_id)
    assert (job.status, job.attempts, job.finished_at) == (JobStatus.dead, 3, clock.now)
    assert "boom" in (job.last_error or "")

    clock.advance(3600)
    assert await worker.run_once() == 0  # dead jobs are never picked up again


async def test_permanent_error_goes_straight_to_dead(
    sessionmaker: async_sessionmaker[AsyncSession], make_worker
) -> None:
    async def reject(ctx: JobContext, payload: dict[str, Any]) -> None:
        raise PermanentJobError("payload has no elder_id")

    job_id = await add_job(sessionmaker, "reject", max_attempts=5)
    await make_worker({"reject": reject}).run_once()
    job = await load(sessionmaker, job_id)
    assert (job.status, job.attempts) == (JobStatus.dead, 1)
    assert job.last_error == "PermanentJobError: payload has no elder_id"


async def test_unknown_job_type_goes_dead(
    sessionmaker: async_sessionmaker[AsyncSession], make_worker
) -> None:
    job_id = await add_job(sessionmaker, "nobody.handles.this")
    await make_worker({}).run_once()
    job = await load(sessionmaker, job_id)
    assert job.status == JobStatus.dead
    assert "No handler" in (job.last_error or "")


async def test_slow_handler_times_out_and_retries(
    sessionmaker: async_sessionmaker[AsyncSession], make_worker
) -> None:
    async def slow(ctx: JobContext, payload: dict[str, Any]) -> None:
        await asyncio.sleep(5)

    job_id = await add_job(sessionmaker, "slow")
    await make_worker({"slow": slow}, job_timeout_seconds=0.05).run_once()
    job = await load(sessionmaker, job_id)
    assert (job.status, job.attempts) == (JobStatus.queued, 1)
    assert job.last_error == "Timed out after 0.05s."


# ---------------------------------------------------------------- stale locks


async def test_job_of_a_crashed_worker_is_reclaimed_and_rerun(
    sessionmaker: async_sessionmaker[AsyncSession], make_worker, clock: FakeClock
) -> None:
    job_id = await add_job(sessionmaker, "x")
    async with sessionmaker() as session:  # a worker claims it, then "crashes"
        await claim_due(session, worker_id="crashed", limit=1, now=clock.now)

    worker = make_worker({"x": ok}, job_timeout_seconds=30, job_lock_timeout_seconds=60)
    clock.advance(59)
    assert await worker.run_once() == 0  # lock not expired yet
    assert (await load(sessionmaker, job_id)).status == JobStatus.running

    clock.advance(2)
    assert await worker.run_once() == 1  # reclaimed, then claimed and run in the same pass
    job = await load(sessionmaker, job_id)
    assert (job.status, job.attempts) == (JobStatus.succeeded, 2)
    assert "Lock expired" in (job.last_error or "")


async def test_stale_job_without_attempts_left_goes_dead(
    sessionmaker: async_sessionmaker[AsyncSession], make_worker, clock: FakeClock
) -> None:
    job_id = await add_job(sessionmaker, "x", max_attempts=1)
    async with sessionmaker() as session:
        await claim_due(session, worker_id="crashed", limit=1, now=clock.now)
    clock.advance(1000)
    await make_worker({"x": ok}).run_once()
    job = await load(sessionmaker, job_id)
    assert (job.status, job.attempts, job.finished_at) == (JobStatus.dead, 1, clock.now)


async def test_late_finisher_cannot_overwrite_a_reclaimed_job(
    sessionmaker: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    job_id = await add_job(sessionmaker, "x")
    async with sessionmaker() as session:
        await claim_due(session, worker_id="slow", limit=1, now=clock.now)
        clock.advance(1000)
        await reclaim_stale(session, now=clock.now, lock_timeout=900)
        await claim_due(session, worker_id="fresh", limit=1, now=clock.now)
        assert not await mark_succeeded(session, job_id, worker_id="slow", now=clock.now)
    job = await load(sessionmaker, job_id)
    assert (job.status, job.locked_by) == (JobStatus.running, "fresh")


# ---------------------------------------------------------------- concurrency


async def test_claims_skip_rows_locked_by_another_transaction(
    sessionmaker: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    locked_id = await add_job(sessionmaker, "x")
    free_id = await add_job(sessionmaker, "x")
    async with sessionmaker() as holder, sessionmaker() as claimer:
        await holder.execute(select(Job).where(Job.id == locked_id).with_for_update())
        claimed = await claim_due(claimer, worker_id="b", limit=10, now=clock.now)
        await holder.rollback()
    assert [job.id for job in claimed] == [free_id]


async def test_concurrent_workers_never_claim_the_same_job(
    sessionmaker: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    for _ in range(20):
        await add_job(sessionmaker, "x")

    async def claim(worker_id: str) -> list[int]:
        async with sessionmaker() as session:
            jobs = await claim_due(session, worker_id=worker_id, limit=10, now=clock.now)
            return [job.id for job in jobs]

    batches = await asyncio.gather(*(claim(f"w{n}") for n in range(4)))
    claimed = [job_id for batch in batches for job_id in batch]
    assert len(claimed) == len(set(claimed)) == 20


# ---------------------------------------------------------------- dead-letter requeue


async def test_requeue_dead_job(
    sessionmaker: async_sessionmaker[AsyncSession], make_worker, clock: FakeClock
) -> None:
    job_id = await add_job(sessionmaker, "boom", max_attempts=1)
    await make_worker({"boom": boom}).run_once()
    async with sessionmaker() as session:
        job = await requeue_dead(session, job_id, now=clock.now)
    assert (job.status, job.attempts, job.finished_at) == (JobStatus.queued, 0, None)
    async with sessionmaker() as session:
        with pytest.raises(ConflictError):
            await requeue_dead(session, job_id, now=clock.now)


# ---------------------------------------------------------------- the run loop


async def test_run_loop_processes_jobs_and_stops_cleanly(
    test_database_url: str, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    done: list[int] = []
    all_done = asyncio.Event()

    async def record(ctx: JobContext, payload: dict[str, Any]) -> None:
        done.append(payload["n"])
        if len(done) == 6:
            all_done.set()

    settings = make_settings(test_database_url, worker_poll_interval_seconds=0.05)
    worker = Worker(settings, sessionmaker, handlers={"record": record})
    for n in range(6):
        await add_job(sessionmaker, "record", {"n": n}, run_at=datetime.now(UTC))

    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop))

    await asyncio.wait_for(all_done.wait(), timeout=5)
    stop.set()
    await asyncio.wait_for(task, timeout=5)
    assert sorted(done) == list(range(6))


async def test_forced_shutdown_records_the_interrupted_attempt(
    test_database_url: str, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    started = asyncio.Event()

    async def hang(ctx: JobContext, payload: dict[str, Any]) -> None:
        started.set()
        await asyncio.sleep(60)

    settings = make_settings(test_database_url, worker_poll_interval_seconds=0.05)
    worker = Worker(settings, sessionmaker, handlers={"hang": hang})
    job_id = await add_job(sessionmaker, "hang", run_at=datetime.now(UTC))

    stop, force = asyncio.Event(), asyncio.Event()
    task = asyncio.create_task(worker.run(stop, force))
    await asyncio.wait_for(started.wait(), timeout=5)
    stop.set()
    force.set()
    await asyncio.wait_for(task, timeout=5)

    job = await load(sessionmaker, job_id)
    assert (job.status, job.attempts) == (JobStatus.queued, 1)
    assert job.last_error == "Cancelled: the worker shut down mid-job."


# ---------------------------------------------------------------- registry


def test_debug_handlers_are_registered() -> None:
    assert {"debug.echo", "debug.fail"} <= set(HANDLERS)


def test_duplicate_handler_registration_is_an_error() -> None:
    with pytest.raises(ValueError, match="already registered"):
        job_handler("debug.echo")(ok)
