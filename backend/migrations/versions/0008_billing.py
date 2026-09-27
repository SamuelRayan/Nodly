"""Nodly Plus (§10): purchases, access_grants, revenuecat_events; credits for moments that
already qualified.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-27 13:00:04.984150
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "revenuecat_events",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("app_user_id", sa.Text(), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_revenuecat_events")),
    )
    op.create_table(
        "purchases",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("app_user_id", sa.Text(), nullable=False),
        sa.Column("store", sa.Text(), nullable=False),
        sa.Column("environment", sa.Text(), nullable=False),
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("transaction_id", sa.Text(), nullable=False),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "raw",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('day_pass', 'subscription')", name=op.f("ck_purchases_kind")),
        sa.CheckConstraint("source IN ('webhook', 'refresh')", name=op.f("ck_purchases_source")),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["families.id"],
            name=op.f("fk_purchases_family_id_families"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_purchases_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchases")),
        sa.UniqueConstraint(
            "store",
            "app_user_id",
            "product_id",
            "purchased_at",
            name=op.f("uq_purchases_store_app_user_id_product_id_purchased_at"),
        ),
        sa.UniqueConstraint(
            "store", "transaction_id", name=op.f("uq_purchases_store_transaction_id")
        ),
    )
    op.create_index(op.f("ix_purchases_family_id"), "purchases", ["family_id"], unique=False)
    op.create_index(op.f("ix_purchases_user_id"), "purchases", ["user_id"], unique=False)
    op.create_table(
        "access_grants",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=True),
        sa.Column("moment_id", sa.Uuid(), nullable=True),
        sa.Column("purchase_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source <> 'moment' OR local_date IS NOT NULL",
            name=op.f("ck_access_grants_moment_credit_has_its_day"),
        ),
        sa.CheckConstraint(
            "source IN ('moment', 'day_pass', 'subscription', 'goodwill')",
            name=op.f("ck_access_grants_source"),
        ),
        sa.CheckConstraint(
            "source NOT IN ('day_pass', 'subscription') OR purchase_id IS NOT NULL",
            name=op.f("ck_access_grants_purchase_grant_has_its_purchase"),
        ),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_access_grants_ends_after_start")),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["families.id"],
            name=op.f("fk_access_grants_family_id_families"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["moment_id"],
            ["moments.id"],
            name=op.f("fk_access_grants_moment_id_moments"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_id"],
            ["purchases.id"],
            name=op.f("fk_access_grants_purchase_id_purchases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_grants")),
    )
    op.create_index(
        "ix_access_grants_family_window", "access_grants", ["family_id", "ends_at"], unique=False
    )
    op.create_index(
        "uq_access_grants_moment_day",
        "access_grants",
        ["family_id", "local_date"],
        unique=True,
        postgresql_where=sa.text("source = 'moment'"),
    )
    op.create_index(
        "uq_access_grants_purchase",
        "access_grants",
        ["purchase_id"],
        unique=True,
        postgresql_where=sa.text("purchase_id IS NOT NULL"),
    )

    # Moments that qualified before the ledger existed earn their day now: from the start of
    # day D to the end of D+1 on the family clock (the primary elder's timezone).
    op.execute(
        """
        INSERT INTO access_grants (family_id, source, starts_at, ends_at, local_date, moment_id)
        SELECT DISTINCT ON (m.family_id, m.qualifying_local_date)
               m.family_id, 'moment',
               m.qualifying_local_date::timestamp AT TIME ZONE e.timezone,
               (m.qualifying_local_date + 2)::timestamp AT TIME ZONE e.timezone,
               m.qualifying_local_date, m.id
        FROM moments m
        JOIN elders e ON e.family_id = m.family_id AND e.is_primary
        WHERE m.qualifies AND m.deleted_at IS NULL
        ORDER BY m.family_id, m.qualifying_local_date, m.intent_at
        """
    )


def downgrade() -> None:
    op.drop_index(
        "uq_access_grants_purchase",
        table_name="access_grants",
        postgresql_where=sa.text("purchase_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_access_grants_moment_day",
        table_name="access_grants",
        postgresql_where=sa.text("source = 'moment'"),
    )
    op.drop_index("ix_access_grants_family_window", table_name="access_grants")
    op.drop_table("access_grants")
    op.drop_index(op.f("ix_purchases_user_id"), table_name="purchases")
    op.drop_index(op.f("ix_purchases_family_id"), table_name="purchases")
    op.drop_table("purchases")
    op.drop_table("revenuecat_events")
