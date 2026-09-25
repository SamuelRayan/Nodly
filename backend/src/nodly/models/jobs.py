"""The DB-backed job queue (CLAUDE.md §4). See nodly.jobs for how jobs move between states."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Identity, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from nodly.models.base import Base, Timestamps, one_of


class JobStatus(StrEnum):
    queued = "queued"  # waiting for run_at (new, or retrying after a failure)
    running = "running"  # claimed by a worker (locked_by / locked_at)
    succeeded = "succeeded"
    dead = "dead"  # dead-letter: out of attempts or a permanent error; kept for inspection


class Job(Timestamps, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        one_of("status", JobStatus, "status"),
        CheckConstraint("type <> ''", name="type_not_empty"),
        CheckConstraint("max_attempts >= 1", name="max_attempts_positive"),
        CheckConstraint("attempts BETWEEN 0 AND max_attempts", name="attempts_in_range"),
        CheckConstraint(
            "(status = 'running') = (locked_at IS NOT NULL AND locked_by IS NOT NULL)",
            name="locked_iff_running",
        ),
        # Enqueueing the same (type, key) twice returns the first job. Jobs without a key never
        # conflict: Postgres treats NULLs as distinct in unique constraints.
        UniqueConstraint("type", "idempotency_key"),
        Index("ix_jobs_due", "run_at", postgresql_where=text("status = 'queued'")),
        Index(
            "ix_jobs_running_locked_at", "locked_at", postgresql_where=text("status = 'running'")
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, sort_order=-100
    )
    type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'queued'"))
    run_at: Mapped[datetime]
    attempts: Mapped[int] = mapped_column(server_default=text("0"))
    max_attempts: Mapped[int]
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None]
    locked_by: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None]
