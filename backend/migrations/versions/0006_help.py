"""Help (§8): help_requests (one live per elder, tests aside) and their help_events timeline.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-26 13:20:08.372776
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "help_requests",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("elder_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'open'"), nullable=False),
        sa.Column("is_test", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("latitude", sa.Double(), nullable=True),
        sa.Column("longitude", sa.Double(), nullable=True),
        sa.Column("location_accuracy_m", sa.Double(), nullable=True),
        sa.Column("battery_percent", sa.Integer(), nullable=True),
        sa.Column("network", sa.Text(), nullable=True),
        sa.Column("last_pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('help', 'call_me')", name=op.f("ck_help_requests_kind")),
        sa.CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved', 'cancelled')",
            name=op.f("ck_help_requests_status"),
        ),
        sa.ForeignKeyConstraint(
            ["acked_by_user_id"],
            ["users.id"],
            name=op.f("fk_help_requests_acked_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["closed_by_user_id"],
            ["users.id"],
            name=op.f("fk_help_requests_closed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["elder_devices.id"],
            name=op.f("fk_help_requests_device_id_elder_devices"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["elder_id"],
            ["elders.id"],
            name=op.f("fk_help_requests_elder_id_elders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["families.id"],
            name=op.f("fk_help_requests_family_id_families"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_help_requests")),
    )
    op.create_index(op.f("ix_help_requests_elder_id"), "help_requests", ["elder_id"], unique=False)
    op.create_index(
        op.f("ix_help_requests_family_id"), "help_requests", ["family_id"], unique=False
    )
    op.create_index(
        "uq_help_requests_one_live_per_elder",
        "help_requests",
        ["elder_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('open', 'acknowledged') AND NOT is_test"),
    )
    op.create_table(
        "help_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('created', 'pushed', 'acknowledged', 'resolved', 'cancelled', 'sms_skipped', 'voice_skipped')",
            name=op.f("ck_help_events_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["help_requests.id"],
            name=op.f("fk_help_events_request_id_help_requests"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_help_events_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_help_events")),
    )
    op.create_index(op.f("ix_help_events_request_id"), "help_events", ["request_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_help_events_request_id"), table_name="help_events")
    op.drop_table("help_events")
    op.drop_index(
        "uq_help_requests_one_live_per_elder",
        table_name="help_requests",
        postgresql_where=sa.text("status IN ('open', 'acknowledged') AND NOT is_test"),
    )
    op.drop_index(op.f("ix_help_requests_family_id"), table_name="help_requests")
    op.drop_index(op.f("ix_help_requests_elder_id"), table_name="help_requests")
    op.drop_table("help_requests")
