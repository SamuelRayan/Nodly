"""billing reports

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-28 16:39:51.335495
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "billing_reports",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "reason IN ('wrong_charge', 'plus_not_working', 'missing_purchase', 'other')",
            name=op.f("ck_billing_reports_reason"),
        ),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["families.id"],
            name=op.f("fk_billing_reports_family_id_families"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_billing_reports_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_reports")),
    )
    op.create_index(
        "ix_billing_reports_family_id_created_at",
        "billing_reports",
        ["family_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_billing_reports_family_id_created_at", table_name="billing_reports")
    op.drop_table("billing_reports")
