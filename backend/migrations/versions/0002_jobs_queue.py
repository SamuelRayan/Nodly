"""Jobs table for the DB-backed queue (python -m nodly.worker).

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-25 15:33:14.462698
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'running') = (locked_at IS NOT NULL AND locked_by IS NOT NULL)",
            name=op.f("ck_jobs_locked_iff_running"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'dead')", name=op.f("ck_jobs_status")
        ),
        sa.CheckConstraint("type <> ''", name=op.f("ck_jobs_type_not_empty")),
        sa.CheckConstraint(
            "attempts BETWEEN 0 AND max_attempts", name=op.f("ck_jobs_attempts_in_range")
        ),
        sa.CheckConstraint("max_attempts >= 1", name=op.f("ck_jobs_max_attempts_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("type", "idempotency_key", name=op.f("uq_jobs_type_idempotency_key")),
    )
    op.create_index(
        "ix_jobs_due",
        "jobs",
        ["run_at"],
        unique=False,
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index(
        "ix_jobs_running_locked_at",
        "jobs",
        ["locked_at"],
        unique=False,
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_jobs_running_locked_at",
        table_name="jobs",
        postgresql_where=sa.text("status = 'running'"),
    )
    op.drop_index("ix_jobs_due", table_name="jobs", postgresql_where=sa.text("status = 'queued'"))
    op.drop_table("jobs")
