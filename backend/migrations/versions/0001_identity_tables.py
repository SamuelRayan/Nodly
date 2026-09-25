"""Identity tables: families, users, family_members, elders, elder_devices, invites,
push_tokens, audit_log (CLAUDE.md §5-§7).

Revision ID: 0001
Revises:
Create Date: 2026-09-25 15:24:48.858099
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("family_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=True),
        sa.Column("entity_id", sa.Text(), nullable=True),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "actor_type IN ('user', 'elder_device', 'system', 'dev')",
            name=op.f("ck_audit_log_actor_type"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"], unique=False)
    op.create_index(
        "ix_audit_log_family_id_occurred_at",
        "audit_log",
        ["family_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "families",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
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
            "length(btrim(name)) BETWEEN 1 AND 100", name=op.f("ck_families_name_not_blank")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_families")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("auth_user_id", sa.Uuid(), nullable=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("phone_e164", sa.Text(), nullable=True),
        sa.Column("locale", sa.Text(), nullable=True),
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
            "country_code IS NULL OR country_code ~ '^[A-Z]{2}$'",
            name=op.f("ck_users_country_code"),
        ),
        sa.CheckConstraint(
            "email ~ '^[^@\\s]+@[^@\\s]+$' AND length(email) <= 254", name=op.f("ck_users_email")
        ),
        sa.CheckConstraint(
            "locale IS NULL OR locale ~ '^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$'",
            name=op.f("ck_users_locale"),
        ),
        sa.CheckConstraint(
            "phone_e164 IS NULL OR phone_e164 ~ '^\\+[1-9][0-9]{6,14}$'",
            name=op.f("ck_users_phone_e164"),
        ),
        sa.CheckConstraint("timezone <> ''", name=op.f("ck_users_timezone_not_empty")),
        sa.CheckConstraint(
            "length(btrim(display_name)) BETWEEN 1 AND 80",
            name=op.f("ck_users_display_name_not_blank"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("auth_user_id", name=op.f("uq_users_auth_user_id")),
    )
    op.create_index(
        "uq_users_email_lower", "users", [sa.literal_column("lower(email)")], unique=True
    )
    op.create_table(
        "elders",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("phone_e164", sa.Text(), nullable=True),
        sa.Column("locale", sa.Text(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "checkin_remind_at", sa.Time(), server_default=sa.text("'09:00'"), nullable=False
        ),
        sa.Column("checkin_due_by", sa.Time(), server_default=sa.text("'12:00'"), nullable=False),
        sa.Column(
            "checkin_grace_minutes", sa.Integer(), server_default=sa.text("60"), nullable=False
        ),
        sa.Column(
            "checkin_activity_counts_as_ok",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
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
        sa.CheckConstraint("country_code ~ '^[A-Z]{2}$'", name=op.f("ck_elders_country_code")),
        sa.CheckConstraint(
            "locale IS NULL OR locale ~ '^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$'",
            name=op.f("ck_elders_locale"),
        ),
        sa.CheckConstraint(
            "phone_e164 IS NULL OR phone_e164 ~ '^\\+[1-9][0-9]{6,14}$'",
            name=op.f("ck_elders_phone_e164"),
        ),
        sa.CheckConstraint("timezone <> ''", name=op.f("ck_elders_timezone_not_empty")),
        sa.CheckConstraint(
            "checkin_grace_minutes BETWEEN 0 AND 720", name=op.f("ck_elders_checkin_grace_minutes")
        ),
        sa.CheckConstraint(
            "checkin_remind_at <= checkin_due_by", name=op.f("ck_elders_checkin_remind_before_due")
        ),
        sa.CheckConstraint(
            "length(btrim(display_name)) BETWEEN 1 AND 80",
            name=op.f("ck_elders_display_name_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["families.id"],
            name=op.f("fk_elders_family_id_families"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_elders")),
    )
    op.create_index(op.f("ix_elders_family_id"), "elders", ["family_id"], unique=False)
    op.create_index(
        "uq_elders_one_primary_per_family",
        "elders",
        ["family_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )
    op.create_table(
        "family_members",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('organizer', 'member')", name=op.f("ck_family_members_role")),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["families.id"],
            name=op.f("fk_family_members_family_id_families"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_family_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_family_members")),
        sa.UniqueConstraint(
            "family_id", "user_id", name=op.f("uq_family_members_family_id_user_id")
        ),
    )
    op.create_index(op.f("ix_family_members_user_id"), "family_members", ["user_id"], unique=False)
    op.create_index(
        "uq_family_members_one_organizer",
        "family_members",
        ["family_id"],
        unique=True,
        postgresql_where=sa.text("role = 'organizer'"),
    )
    op.create_table(
        "elder_devices",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("elder_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("device_model", sa.Text(), nullable=True),
        sa.Column("app_version", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "platform IN ('android', 'ios')", name=op.f("ck_elder_devices_platform")
        ),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_elder_devices_token_hash")
        ),
        sa.ForeignKeyConstraint(
            ["elder_id"],
            ["elders.id"],
            name=op.f("fk_elder_devices_elder_id_elders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"],
            ["users.id"],
            name=op.f("fk_elder_devices_revoked_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_elder_devices")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_elder_devices_token_hash")),
    )
    op.create_index(op.f("ix_elder_devices_elder_id"), "elder_devices", ["elder_id"], unique=False)
    op.create_table(
        "invites",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("elder_id", sa.Uuid(), nullable=True),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("consumed_by_elder_device_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind = 'elder_pairing') = (elder_id IS NOT NULL)",
            name=op.f("ck_invites_pairing_has_elder"),
        ),
        sa.CheckConstraint("code_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_invites_code_hash")),
        sa.CheckConstraint("kind IN ('member', 'elder_pairing')", name=op.f("ck_invites_kind")),
        sa.CheckConstraint(
            "consumed_at IS NOT NULL OR (consumed_by_user_id IS NULL AND consumed_by_elder_device_id IS NULL)",
            name=op.f("ck_invites_consumer_only_when_consumed"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_invites_expires_after_created")
        ),
        sa.ForeignKeyConstraint(
            ["consumed_by_elder_device_id"],
            ["elder_devices.id"],
            name=op.f("fk_invites_consumed_by_elder_device_id_elder_devices"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["consumed_by_user_id"],
            ["users.id"],
            name=op.f("fk_invites_consumed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_invites_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["elder_id"], ["elders.id"], name=op.f("fk_invites_elder_id_elders"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["families.id"],
            name=op.f("fk_invites_family_id_families"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invites")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_invites_code_hash")),
    )
    op.create_index(op.f("ix_invites_elder_id"), "invites", ["elder_id"], unique=False)
    op.create_index(op.f("ix_invites_family_id"), "invites", ["family_id"], unique=False)
    op.create_index(
        "ix_invites_open_expires_at",
        "invites",
        ["expires_at"],
        unique=False,
        postgresql_where=sa.text("consumed_at IS NULL AND revoked_at IS NULL"),
    )
    op.create_table(
        "push_tokens",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("elder_device_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("platform IN ('android', 'ios')", name=op.f("ck_push_tokens_platform")),
        sa.CheckConstraint(
            "provider IN ('expo', 'fcm', 'apns')", name=op.f("ck_push_tokens_provider")
        ),
        sa.CheckConstraint(
            "num_nonnulls(user_id, elder_device_id) = 1",
            name=op.f("ck_push_tokens_exactly_one_owner"),
        ),
        sa.ForeignKeyConstraint(
            ["elder_device_id"],
            ["elder_devices.id"],
            name=op.f("fk_push_tokens_elder_device_id_elder_devices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_push_tokens_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_push_tokens")),
        sa.UniqueConstraint("provider", "token", name=op.f("uq_push_tokens_provider_token")),
    )
    op.create_index(
        op.f("ix_push_tokens_elder_device_id"), "push_tokens", ["elder_device_id"], unique=False
    )
    op.create_index(op.f("ix_push_tokens_user_id"), "push_tokens", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_push_tokens_user_id"), table_name="push_tokens")
    op.drop_index(op.f("ix_push_tokens_elder_device_id"), table_name="push_tokens")
    op.drop_table("push_tokens")
    op.drop_index(
        "ix_invites_open_expires_at",
        table_name="invites",
        postgresql_where=sa.text("consumed_at IS NULL AND revoked_at IS NULL"),
    )
    op.drop_index(op.f("ix_invites_family_id"), table_name="invites")
    op.drop_index(op.f("ix_invites_elder_id"), table_name="invites")
    op.drop_table("invites")
    op.drop_index(op.f("ix_elder_devices_elder_id"), table_name="elder_devices")
    op.drop_table("elder_devices")
    op.drop_index(
        "uq_family_members_one_organizer",
        table_name="family_members",
        postgresql_where=sa.text("role = 'organizer'"),
    )
    op.drop_index(op.f("ix_family_members_user_id"), table_name="family_members")
    op.drop_table("family_members")
    op.drop_index(
        "uq_elders_one_primary_per_family",
        table_name="elders",
        postgresql_where=sa.text("is_primary"),
    )
    op.drop_index(op.f("ix_elders_family_id"), table_name="elders")
    op.drop_table("elders")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_table("users")
    op.drop_table("families")
    op.drop_index("ix_audit_log_family_id_occurred_at", table_name="audit_log")
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
    op.drop_table("audit_log")
