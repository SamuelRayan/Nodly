"""Family PIN (scrypt hash) for taking a paired phone out of elder mode.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-25 20:43:41.584822
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("families", sa.Column("pin_hash", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_families_pin_hash_format"),
        "families",
        "pin_hash IS NULL OR pin_hash LIKE 'scrypt$%'",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_families_pin_hash_format"), "families")
    op.drop_column("families", "pin_hash")
