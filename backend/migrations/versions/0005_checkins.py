"""Check-ins (§7): checkins, the engine_actions idempotency ledger, missed check-in alerts.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-26 12:55:43.334352
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "checkin_alerts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("elder_id", sa.Uuid(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "resolution IN ('checked_in', 'marked_okay')", name=op.f("ck_checkin_alerts_resolution")
        ),
        sa.ForeignKeyConstraint(
            ["acked_by_user_id"],
            ["users.id"],
            name=op.f("fk_checkin_alerts_acked_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["elder_id"],
            ["elders.id"],
            name=op.f("fk_checkin_alerts_elder_id_elders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checkin_alerts")),
        sa.UniqueConstraint(
            "elder_id", "local_date", name=op.f("uq_checkin_alerts_elder_id_local_date")
        ),
    )
    op.create_table(
        "engine_actions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("elder_id", sa.Uuid(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('remind', 'due_remind', 'family_late', 'missed', 'all_good')",
            name=op.f("ck_engine_actions_action"),
        ),
        sa.ForeignKeyConstraint(
            ["elder_id"],
            ["elders.id"],
            name=op.f("fk_engine_actions_elder_id_elders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engine_actions")),
        sa.UniqueConstraint(
            "elder_id",
            "local_date",
            "action",
            name=op.f("uq_engine_actions_elder_id_local_date_action"),
        ),
    )
    op.create_table(
        "checkins",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("elder_id", sa.Uuid(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('app', 'notification', 'family')", name=op.f("ck_checkins_source")
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["elder_devices.id"],
            name=op.f("fk_checkins_device_id_elder_devices"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["elder_id"],
            ["elders.id"],
            name=op.f("fk_checkins_elder_id_elders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_checkins_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checkins")),
        sa.UniqueConstraint("elder_id", "local_date", name=op.f("uq_checkins_elder_id_local_date")),
    )


def downgrade() -> None:
    op.drop_table("checkins")
    op.drop_table("engine_actions")
    op.drop_table("checkin_alerts")
