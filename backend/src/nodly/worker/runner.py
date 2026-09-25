"""The worker loop: claim due jobs, run their handlers, record the outcome."""

import asyncio
import logging
import os
import random
import secrets
import socket
import time
import traceback
from collections.abc import Callable, Mapping
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nodly.clock import utcnow
from nodly.config import Settings
from nodly.jobs.queue import (
    ClaimedJob,
    backoff_seconds,
    claim_due,
    mark_failed,
    mark_succeeded,
    reclaim_stale,
)
from nodly.jobs.registry import HANDLERS, JobContext, JobHandler, PermanentJobError
from nodly.log import bind_log_context
from nodly.models import JobStatus

logger = logging.getLogger("nodly.worker")


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(3)}"


class Worker:
    def __init__(
        self,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        handlers: Mapping[str, JobHandler] | None = None,
        worker_id: str | None = None,
        clock: Callable[[], datetime] = utcnow,
        rand: Callable[[], float] = random.random,
    ) -> None:
        self.settings = settings
        self.sessionmaker = sessionmaker
        self.handlers = HANDLERS if handlers is None else handlers
        self.worker_id = worker_id or default_worker_id()
        self.clock = clock
        self.rand = rand
        self._running: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------ loop

    async def run(self, stop: asyncio.Event, force: asyncio.Event | None = None) -> None:
        """Run until `stop` is set, then wait for running jobs (up to the shutdown grace
        period, or until `force` is set) and cancel whatever is left."""
        logger.info(
            "worker started",
            extra={
                "worker_id": self.worker_id,
                "concurrency": self.settings.worker_concurrency,
                "handlers": sorted(self.handlers),
            },
        )
        stop_waiter = asyncio.create_task(stop.wait())
        try:
            while not stop.is_set():
                try:
                    await self._reclaim_stale()
                    free = self.settings.worker_concurrency - len(self._running)
                    if free > 0:
                        for job in await self._claim(free):
                            self._start(job)
                except Exception:
                    # e.g. the database is briefly unreachable: log and try again next poll.
                    logger.exception("worker poll failed")
                # Wake on: stop requested, a job finishing (a slot frees up), or the poll interval.
                await asyncio.wait(
                    {stop_waiter, *self._running},
                    timeout=self.settings.worker_poll_interval_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
        finally:
            stop_waiter.cancel()
            await self._drain(force)
            logger.info("worker stopped", extra={"worker_id": self.worker_id})

    async def run_once(self) -> int:
        """One pass: reclaim stale jobs, claim up to `concurrency` due jobs and run them to the
        end. Returns how many ran. For tests and scripts."""
        await self._reclaim_stale()
        jobs = await self._claim(self.settings.worker_concurrency)
        await asyncio.gather(*(self._execute(job) for job in jobs))
        return len(jobs)

    def _start(self, job: ClaimedJob) -> None:
        task = asyncio.create_task(self._execute(job), name=f"job-{job.id}")
        self._running.add(task)
        task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._running.discard(task)
        if not task.cancelled() and task.exception() is not None:
            # Recording the outcome failed (e.g. DB down); the lock will expire and the job
            # will be reclaimed.
            logger.error("could not record job outcome", exc_info=task.exception())

    async def _drain(self, force: asyncio.Event | None) -> None:
        if not self._running:
            return
        logger.info("waiting for running jobs", extra={"running": len(self._running)})
        deadline = time.monotonic() + self.settings.worker_shutdown_grace_seconds
        force_waiter = asyncio.create_task(force.wait()) if force else None
        try:
            while self._running and (force is None or not force.is_set()):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                waiters: set[asyncio.Task[object]] = set(self._running)
                if force_waiter:
                    waiters.add(force_waiter)
                await asyncio.wait(waiters, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
        finally:
            if force_waiter:
                force_waiter.cancel()
        if self._running:
            logger.warning("cancelling running jobs", extra={"running": len(self._running)})
            for task in list(self._running):
                task.cancel()
            await asyncio.gather(*self._running, return_exceptions=True)

    # ------------------------------------------------------------ queue calls

    async def _reclaim_stale(self) -> None:
        async with self.sessionmaker() as session:
            count = await reclaim_stale(
                session, now=self.clock(), lock_timeout=self.settings.job_lock_timeout_seconds
            )
        if count:
            logger.warning("reclaimed stale jobs", extra={"count": count})

    async def _claim(self, limit: int) -> list[ClaimedJob]:
        async with self.sessionmaker() as session:
            return await claim_due(session, worker_id=self.worker_id, limit=limit, now=self.clock())

    async def _fail(self, job: ClaimedJob, error: str, *, retry: bool) -> JobStatus | None:
        retry_in = (
            backoff_seconds(
                job.attempt,
                base=self.settings.job_backoff_base_seconds,
                cap=self.settings.job_backoff_max_seconds,
                rand=self.rand,
            )
            if retry
            else None
        )
        async with self.sessionmaker() as session:
            return await mark_failed(
                session,
                job,
                error,
                worker_id=self.worker_id,
                now=self.clock(),
                retry_in=retry_in,
            )

    # ------------------------------------------------------------ one job

    async def _execute(self, job: ClaimedJob) -> None:
        with bind_log_context(job_id=job.id, job_type=job.type, attempt=job.attempt):
            started = time.perf_counter()

            def elapsed_ms() -> float:
                return round((time.perf_counter() - started) * 1000, 1)

            handler = self.handlers.get(job.type)
            if handler is None:
                status = await self._fail(
                    job, f"No handler is registered for job type {job.type!r}.", retry=False
                )
                logger.error("job has no handler", extra={"outcome": status})
                return

            context = JobContext(
                job_id=job.id,
                job_type=job.type,
                attempt=job.attempt,
                max_attempts=job.max_attempts,
                settings=self.settings,
                sessionmaker=self.sessionmaker,
            )
            timeout = self.settings.job_timeout_seconds
            try:
                async with asyncio.timeout(timeout):
                    await handler(context, job.payload)
            except asyncio.CancelledError:
                # Shutting down: record the attempt so the job is retried, then stop.
                await asyncio.shield(
                    self._fail(job, "Cancelled: the worker shut down mid-job.", retry=True)
                )
                raise
            except PermanentJobError as exc:
                status = await self._fail(job, f"PermanentJobError: {exc}", retry=False)
                logger.error("job failed permanently", extra={"outcome": status, "error": str(exc)})
            except TimeoutError:
                status = await self._fail(job, f"Timed out after {timeout:g}s.", retry=True)
                logger.warning(
                    "job timed out", extra={"outcome": status, "duration_ms": elapsed_ms()}
                )
            except Exception as exc:
                status = await self._fail(job, traceback.format_exc(), retry=True)
                logger.log(
                    logging.ERROR if status is JobStatus.dead else logging.WARNING,
                    "job failed",
                    exc_info=exc,
                    extra={"outcome": status, "duration_ms": elapsed_ms()},
                )
            else:
                async with self.sessionmaker() as session:
                    recorded = await mark_succeeded(
                        session, job.id, worker_id=self.worker_id, now=self.clock()
                    )
                if recorded:
                    logger.info("job succeeded", extra={"duration_ms": elapsed_ms()})
                else:
                    logger.warning("job finished after its lock expired; outcome not recorded")
