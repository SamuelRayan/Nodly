"""Moments (§9, §10): moments, moment_views, moment_reactions.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-27 11:22:04.857572
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "moments",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'awaiting_upload'"), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=True),
        sa.Column("author_device_id", sa.Uuid(), nullable=True),
        sa.Column("by_elder", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("intent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("phash", sa.Text(), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("thumbnail_key", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("qualifies", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("qualifying_local_date", sa.Date(), nullable=True),
        sa.Column("not_qualifying_reason", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('photo', 'video', 'voice')", name=op.f("ck_moments_kind")),
        sa.CheckConstraint(
            "status IN ('awaiting_upload', 'checking', 'published', 'rejected')",
            name=op.f("ck_moments_status"),
        ),
        sa.CheckConstraint(
            "NOT qualifies OR qualifying_local_date IS NOT NULL",
            name=op.f("ck_moments_qualifying_has_a_day"),
        ),
        sa.CheckConstraint(
            "num_nonnulls(author_user_id, author_device_id) <= 1",
            name=op.f("ck_moments_one_author"),
        ),
        sa.ForeignKeyConstraint(
            ["author_device_id"],
            ["elder_devices.id"],
            name=op.f("fk_moments_author_device_id_elder_devices"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["users.id"],
            name=op.f("fk_moments_author_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["families.id"],
            name=op.f("fk_moments_family_id_families"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_moments")),
    )
    op.create_index(op.f("ix_moments_author_user_id"), "moments", ["author_user_id"], unique=False)
    op.create_index(
        "ix_moments_family_feed", "moments", ["family_id", "published_at"], unique=False
    )
    op.create_index(op.f("ix_moments_family_id"), "moments", ["family_id"], unique=False)
    op.create_table(
        "moment_reactions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("moment_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "num_nonnulls(user_id, device_id) = 1", name=op.f("ck_moment_reactions_one_reactor")
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["elder_devices.id"],
            name=op.f("fk_moment_reactions_device_id_elder_devices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["moment_id"],
            ["moments.id"],
            name=op.f("fk_moment_reactions_moment_id_moments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_moment_reactions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_moment_reactions")),
    )
    op.create_index(
        op.f("ix_moment_reactions_moment_id"), "moment_reactions", ["moment_id"], unique=False
    )
    op.create_index(
        "uq_moment_reactions_device",
        "moment_reactions",
        ["moment_id", "device_id"],
        unique=True,
        postgresql_where=sa.text("device_id IS NOT NULL"),
    )
    op.create_index(
        "uq_moment_reactions_user",
        "moment_reactions",
        ["moment_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_table(
        "moment_views",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("moment_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "num_nonnulls(user_id, device_id) = 1", name=op.f("ck_moment_views_one_viewer")
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["elder_devices.id"],
            name=op.f("fk_moment_views_device_id_elder_devices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["moment_id"],
            ["moments.id"],
            name=op.f("fk_moment_views_moment_id_moments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_moment_views_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_moment_views")),
    )
    op.create_index(
        "uq_moment_views_device",
        "moment_views",
        ["moment_id", "device_id"],
        unique=True,
        postgresql_where=sa.text("device_id IS NOT NULL"),
    )
    op.create_index(
        "uq_moment_views_user",
        "moment_views",
        ["moment_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_moment_views_user",
        table_name="moment_views",
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_moment_views_device",
        table_name="moment_views",
        postgresql_where=sa.text("device_id IS NOT NULL"),
    )
    op.drop_table("moment_views")
    op.drop_index(
        "uq_moment_reactions_user",
        table_name="moment_reactions",
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_moment_reactions_device",
        table_name="moment_reactions",
        postgresql_where=sa.text("device_id IS NOT NULL"),
    )
    op.drop_index(op.f("ix_moment_reactions_moment_id"), table_name="moment_reactions")
    op.drop_table("moment_reactions")
    op.drop_index(op.f("ix_moments_family_id"), table_name="moments")
    op.drop_index("ix_moments_family_feed", table_name="moments")
    op.drop_index(op.f("ix_moments_author_user_id"), table_name="moments")
    op.drop_table("moments")
