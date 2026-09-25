"""Phase 2: onboarding fields on users, elder profile/pause fields, device token rotation,
locale -> language, and throttle counters for brute-force protection.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-25 16:05:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SHA256_HEX = "^[0-9a-f]{64}$"


def _rename_locale_to_language(table: str) -> None:
    # Postgres updates the CHECK expression to the new column name; only its name needs fixing.
    op.alter_column(table, "locale", new_column_name="language")
    op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT ck_{table}_locale TO ck_{table}_language")


def upgrade() -> None:
    # ---- users: profile is filled during onboarding, so these start empty.
    _rename_locale_to_language("users")
    op.alter_column("users", "display_name", nullable=True)
    op.alter_column("users", "timezone", nullable=True)
    op.add_column("users", sa.Column("age_confirmed_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("onboarded_at", sa.DateTime(timezone=True)))
    # Users created before this migration (dev routes) are complete profiles; mark them.
    op.execute(
        "UPDATE users SET age_confirmed_at = created_at, onboarded_at = created_at"
        " WHERE country_code IS NOT NULL"
    )
    op.create_check_constraint(
        op.f("ck_users_onboarded_profile_complete"),
        "users",
        "onboarded_at IS NULL OR (display_name IS NOT NULL AND timezone IS NOT NULL"
        " AND country_code IS NOT NULL AND age_confirmed_at IS NOT NULL)",
    )

    # ---- elders
    _rename_locale_to_language("elders")
    op.add_column("elders", sa.Column("relation_label", sa.Text()))
    op.add_column("elders", sa.Column("full_name", sa.Text()))
    op.add_column("elders", sa.Column("paused_at", sa.DateTime(timezone=True)))
    op.add_column("elders", sa.Column("paused_until", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        op.f("ck_elders_relation_label_not_blank"),
        "elders",
        "length(btrim(relation_label)) BETWEEN 1 AND 40",
    )
    op.create_check_constraint(
        op.f("ck_elders_full_name_not_blank"),
        "elders",
        "length(btrim(full_name)) BETWEEN 1 AND 120",
    )
    op.create_check_constraint(
        op.f("ck_elders_paused_until_after_paused_at"),
        "elders",
        "paused_until IS NULL OR (paused_at IS NOT NULL AND paused_until > paused_at)",
    )

    # ---- elder_devices: token rotation grace
    op.add_column("elder_devices", sa.Column("previous_token_hash", sa.String(length=64)))
    op.add_column(
        "elder_devices", sa.Column("previous_token_expires_at", sa.DateTime(timezone=True))
    )
    op.create_check_constraint(
        op.f("ck_elder_devices_previous_token_hash"),
        "elder_devices",
        f"previous_token_hash IS NULL OR previous_token_hash ~ '{SHA256_HEX}'",
    )
    op.create_check_constraint(
        op.f("ck_elder_devices_previous_token_has_expiry"),
        "elder_devices",
        "(previous_token_hash IS NULL) = (previous_token_expires_at IS NULL)",
    )
    op.create_index(
        "ix_elder_devices_previous_token_hash",
        "elder_devices",
        ["previous_token_hash"],
        postgresql_where=sa.text("previous_token_hash IS NOT NULL"),
    )

    # ---- throttle counters
    op.create_table(
        "throttle_counters",
        sa.Column("bucket", sa.Text(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.CheckConstraint("count >= 0", name=op.f("ck_throttle_counters_count_not_negative")),
        sa.PrimaryKeyConstraint("bucket", "window_start", name=op.f("pk_throttle_counters")),
    )
    op.create_index("ix_throttle_counters_window_start", "throttle_counters", ["window_start"])


def downgrade() -> None:
    op.drop_index("ix_throttle_counters_window_start", table_name="throttle_counters")
    op.drop_table("throttle_counters")

    op.drop_index("ix_elder_devices_previous_token_hash", table_name="elder_devices")
    op.drop_constraint(op.f("ck_elder_devices_previous_token_has_expiry"), "elder_devices")
    op.drop_constraint(op.f("ck_elder_devices_previous_token_hash"), "elder_devices")
    op.drop_column("elder_devices", "previous_token_expires_at")
    op.drop_column("elder_devices", "previous_token_hash")

    op.drop_constraint(op.f("ck_elders_paused_until_after_paused_at"), "elders")
    op.drop_constraint(op.f("ck_elders_full_name_not_blank"), "elders")
    op.drop_constraint(op.f("ck_elders_relation_label_not_blank"), "elders")
    op.drop_column("elders", "paused_until")
    op.drop_column("elders", "paused_at")
    op.drop_column("elders", "full_name")
    op.drop_column("elders", "relation_label")
    op.alter_column("elders", "language", new_column_name="locale")
    op.execute("ALTER TABLE elders RENAME CONSTRAINT ck_elders_language TO ck_elders_locale")

    op.drop_constraint(op.f("ck_users_onboarded_profile_complete"), "users")
    op.drop_column("users", "onboarded_at")
    op.drop_column("users", "age_confirmed_at")
    # Users who never finished onboarding can't satisfy the old NOT NULLs; drop them.
    op.execute("DELETE FROM users WHERE display_name IS NULL OR timezone IS NULL")
    op.alter_column("users", "timezone", nullable=False)
    op.alter_column("users", "display_name", nullable=False)
    op.alter_column("users", "language", new_column_name="locale")
    op.execute("ALTER TABLE users RENAME CONSTRAINT ck_users_language TO ck_users_locale")
