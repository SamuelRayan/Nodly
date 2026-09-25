"""Queue operations on the jobs table.

Life of a job:
    enqueue()      -> queued (run_at)
    claim_due()    -> running, attempts += 1, locked_by/locked_at set
    mark_succeeded -> succeeded
    mark_failed    -> queued again at now + backoff, or dead when out of attempts / permanent
    reclaim_stale  -> a job whose worker vanished (lock older than the lock timeout) is failed
                      the same way, so a crash counts as an attempt
    requeue_dead   -> dead back to queued with a fresh set of attempts (manual)

enqueue() does not commit: the job is written in the caller's transaction, so it exists if and
only if the caller's own changes are committed. Worker-side functions commit their own work.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.clock import utcnow
from nodly.config import get_settings
from nodly.errors import ConflictError, NotFoundError
from nodly.models import Job, JobStatus

MAX_ERROR_LENGTH = 4000
JITTER_FRACTION = 0.1


@dataclass(frozen=True)
class EnqueueResult:
    job: Job
    created: bool  # False when (type, idempotency_key) already existed


@dataclass(frozen=True)
class ClaimedJob:
    id: int
    type: str
    payload: dict[str, Any]
    attempt: int  # 1 on the first run
    max_attempts: int


def backoff_seconds(
    attempt: int, *, base: float, cap: float, rand: Callable[[], float] = random.random
) -> float:
    """Delay before retrying after failed attempt number `attempt` (1-based):
    min(base * 2^(attempt-1), cap), plus up to 10% jitter so retries don't stampede."""
    delay = min(base * 2 ** min(attempt - 1, 60), cap)
    return delay + delay * JITTER_FRACTION * rand()


async def enqueue(
    session: AsyncSession,
    job_type: str,
    payload: dict[str, Any] | None = None,
    *,
    run_at: datetime | None = None,
    idempotency_key: str | None = None,
    max_attempts: int | None = None,
) -> EnqueueResult:
    """Add a job in the caller's transaction (the caller commits).

    With an idempotency key, a second enqueue of the same (type, key) returns the first job,
    whatever state it is in, instead of adding another.
    """
    values = {
        "type": job_type,
        "payload": payload or {},
        "run_at": run_at or utcnow(),
        "idempotency_key": idempotency_key,
        "max_attempts": max_attempts or get_settings().job_default_max_attempts,
    }
    statement = (
        insert(Job)
        .values(**values)
        .on_conflict_do_nothing(index_elements=[Job.type, Job.idempotency_key])
        .returning(Job.id)
    )
    new_id = await session.scalar(statement)
    if new_id is not None:
        job = await session.get_one(Job, new_id)
        return EnqueueResult(job=job, created=True)
    existing = await session.scalar(
        select(Job).where(Job.type == job_type, Job.idempotency_key == idempotency_key)
    )
    assert existing is not None
    return EnqueueResult(job=existing, created=False)


async def claim_due(
    session: AsyncSession, *, worker_id: str, limit: int, now: datetime
) -> list[ClaimedJob]:
    """Lock up to `limit` due jobs for this worker and commit.

    FOR UPDATE SKIP LOCKED lets several workers claim at once without taking the same job.
    """
    due = (
        select(Job.id)
        .where(Job.status == JobStatus.queued, Job.run_at <= now)
        .order_by(Job.run_at, Job.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    statement = (
        update(Job)
        .where(Job.id.in_(due))
        .values(
            status=JobStatus.running,
            attempts=Job.attempts + 1,
            locked_at=now,
            locked_by=worker_id,
            updated_at=now,
        )
        .returning(Job.id, Job.type, Job.payload, Job.attempts, Job.max_attempts)
    )
    rows = (await session.execute(statement)).all()
    await session.commit()
    claimed = [
        ClaimedJob(
            id=r.id, type=r.type, payload=r.payload, attempt=r.attempts, max_attempts=r.max_attempts
        )
        for r in rows
    ]
    return sorted(claimed, key=lambda job: job.id)


def _running_and_ours(job_id: int, worker_id: str) -> list[Any]:
    # Guards against a slow worker overwriting a job that was reclaimed and re-run elsewhere.
    return [Job.id == job_id, Job.status == JobStatus.running, Job.locked_by == worker_id]


async def mark_succeeded(
    session: AsyncSession, job_id: int, *, worker_id: str, now: datetime
) -> bool:
    """Returns False if the job was no longer ours (its lock had expired and it was reclaimed)."""
    result = await session.execute(
        update(Job)
        .where(*_running_and_ours(job_id, worker_id))
        .values(
            status=JobStatus.succeeded,
            finished_at=now,
            locked_at=None,
            locked_by=None,
            updated_at=now,
        )
    )
    await session.commit()
    return result.rowcount == 1  # type: ignore[attr-defined]


async def mark_failed(
    session: AsyncSession,
    job: ClaimedJob,
    error: str,
    *,
    worker_id: str,
    now: datetime,
    retry_in: float | None,
) -> JobStatus | None:
    """Queue a retry `retry_in` seconds from now, or move to dead when `retry_in` is None or
    the job is out of attempts. Returns the new status, or None if the job was no longer ours."""
    dead = retry_in is None or job.attempt >= job.max_attempts
    values: dict[str, Any] = {
        "last_error": error[:MAX_ERROR_LENGTH],
        "locked_at": None,
        "locked_by": None,
        "updated_at": now,
    }
    if dead:
        values |= {"status": JobStatus.dead, "finished_at": now}
    else:
        assert retry_in is not None
        values |= {"status": JobStatus.queued, "run_at": now + timedelta(seconds=retry_in)}
    result = await session.execute(
        update(Job).where(*_running_and_ours(job.id, worker_id)).values(**values)
    )
    await session.commit()
    if result.rowcount != 1:  # type: ignore[attr-defined]
        return None
    return JobStatus.dead if dead else JobStatus.queued


async def reclaim_stale(session: AsyncSession, *, now: datetime, lock_timeout: float) -> int:
    """Fail jobs whose lock is older than `lock_timeout` seconds (their worker died or hung).
    The claim already counted the attempt; they are retried immediately or go dead."""
    cutoff = now - timedelta(seconds=lock_timeout)
    stale = (
        select(Job.id)
        .where(Job.status == JobStatus.running, Job.locked_at < cutoff)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    out_of_attempts = Job.attempts >= Job.max_attempts
    result = await session.execute(
        update(Job)
        .where(Job.id.in_(stale))
        .values(
            status=case((out_of_attempts, JobStatus.dead.value), else_=JobStatus.queued.value),
            finished_at=case((out_of_attempts, now), else_=None),
            run_at=now,
            last_error="Lock expired: the worker stopped or hung before finishing this attempt.",
            locked_at=None,
            locked_by=None,
            updated_at=now,
        )
    )
    await session.commit()
    return result.rowcount  # type: ignore[attr-defined, no-any-return]


async def requeue_dead(session: AsyncSession, job_id: int, *, now: datetime) -> Job:
    """Give a dead job a fresh set of attempts, due now. Commits."""
    job = await session.get(Job, job_id)
    if job is None:
        raise NotFoundError(f"Job {job_id} doesn't exist.")
    if job.status != JobStatus.dead:
        raise ConflictError(f"Only dead jobs can be requeued; job {job_id} is {job.status}.")
    job.status = JobStatus.queued
    job.attempts = 0
    job.run_at = now
    job.finished_at = None
    job.updated_at = now
    await session.commit()
    return job
