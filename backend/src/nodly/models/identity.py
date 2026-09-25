"""Identity: families, family member accounts, elders and their devices, invites, push tokens,
and the audit log (CLAUDE.md §5, §6)."""

import uuid
from datetime import datetime, time
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from nodly.models.base import (
    COUNTRY_CODE_PATTERN,
    E164_PATTERN,
    LOCALE_PATTERN,
    SHA256_HEX_PATTERN,
    Base,
    CreatedAt,
    Timestamps,
    UUIDPrimaryKey,
    matches,
    not_blank,
    one_of,
)


class FamilyRole(StrEnum):
    organizer = "organizer"  # created the family, manages billing; transferable
    member = "member"


class InviteKind(StrEnum):
    member = "member"  # a family member joins (48h)
    elder_pairing = "elder_pairing"  # an elder's phone claims an elder profile (15 min)


class DevicePlatform(StrEnum):
    android = "android"
    ios = "ios"


class PushProvider(StrEnum):
    expo = "expo"
    fcm = "fcm"
    apns = "apns"


class ActorType(StrEnum):
    user = "user"
    elder_device = "elder_device"
    system = "system"
    dev = "dev"  # the dev-only helper routes


class Family(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "families"
    __table_args__ = (not_blank("name", 100),)

    name: Mapped[str] = mapped_column(Text)


class User(UUIDPrimaryKey, Timestamps, Base):
    """A family member account (Supabase Auth). Elders are not users: they have no login."""

    __tablename__ = "users"
    __table_args__ = (
        not_blank("display_name", 80),
        CheckConstraint("email ~ '^[^@\\s]+@[^@\\s]+$' AND length(email) <= 254", name="email"),
        CheckConstraint("timezone <> ''", name="timezone_not_empty"),
        matches("country_code", COUNTRY_CODE_PATTERN, "country_code", nullable=True),
        matches("phone_e164", E164_PATTERN, "phone_e164", nullable=True),
        matches("locale", LOCALE_PATTERN, "locale", nullable=True),
        Index("uq_users_email_lower", func.lower(text("email")), unique=True),
    )

    # Filled when the account is linked to Supabase Auth (Phase 2).
    auth_user_id: Mapped[uuid.UUID | None] = mapped_column(unique=True)
    email: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    # User-picked IANA name. Required, never defaulted (CLAUDE.md §5).
    timezone: Mapped[str] = mapped_column(Text)
    country_code: Mapped[str | None] = mapped_column(String(2))
    phone_e164: Mapped[str | None] = mapped_column(Text)
    locale: Mapped[str | None] = mapped_column(Text)


class FamilyMember(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "family_members"
    __table_args__ = (
        UniqueConstraint("family_id", "user_id"),
        one_of("role", FamilyRole, "role"),
        Index(
            "uq_family_members_one_organizer",
            "family_id",
            unique=True,
            postgresql_where=text("role = 'organizer'"),
        ),
    )

    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(Text)


class Elder(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "elders"
    __table_args__ = (
        not_blank("display_name", 80),
        CheckConstraint("timezone <> ''", name="timezone_not_empty"),
        matches("country_code", COUNTRY_CODE_PATTERN, "country_code"),
        matches("phone_e164", E164_PATTERN, "phone_e164", nullable=True),
        matches("locale", LOCALE_PATTERN, "locale", nullable=True),
        CheckConstraint("checkin_grace_minutes BETWEEN 0 AND 720", name="checkin_grace_minutes"),
        CheckConstraint("checkin_remind_at <= checkin_due_by", name="checkin_remind_before_due"),
        # The primary elder's timezone is the family clock (CLAUDE.md §5).
        Index(
            "uq_elders_one_primary_per_family",
            "family_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )

    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    display_name: Mapped[str] = mapped_column(Text)
    # User-picked IANA name. Required, never defaulted (CLAUDE.md §5).
    timezone: Mapped[str] = mapped_column(Text)
    # Required: the Help screen shows the emergency number for this country.
    country_code: Mapped[str] = mapped_column(String(2))
    phone_e164: Mapped[str | None] = mapped_column(Text)
    locale: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(server_default=text("false"))

    # Check-in settings, local time in `timezone` (CLAUDE.md §7).
    checkin_remind_at: Mapped[time] = mapped_column(server_default=text("'09:00'"))
    checkin_due_by: Mapped[time] = mapped_column(server_default=text("'12:00'"))
    checkin_grace_minutes: Mapped[int] = mapped_column(server_default=text("60"))
    checkin_activity_counts_as_ok: Mapped[bool] = mapped_column(server_default=text("true"))


class ElderDevice(UUIDPrimaryKey, CreatedAt, Base):
    """A paired elder phone. Holds only a SHA-256 hash of its 256-bit device token."""

    __tablename__ = "elder_devices"
    __table_args__ = (
        matches("token_hash", SHA256_HEX_PATTERN, "token_hash"),
        one_of("platform", DevicePlatform, "platform"),
    )

    elder_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("elders.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    platform: Mapped[str] = mapped_column(Text)
    device_model: Mapped[str | None] = mapped_column(Text)
    app_version: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    revoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class Invite(UUIDPrimaryKey, CreatedAt, Base):
    """Single-use code for a member invite (48h) or an elder pairing (15 min)."""

    __tablename__ = "invites"
    __table_args__ = (
        one_of("kind", InviteKind, "kind"),
        CheckConstraint(
            "(kind = 'elder_pairing') = (elder_id IS NOT NULL)", name="pairing_has_elder"
        ),
        matches("code_hash", SHA256_HEX_PATTERN, "code_hash"),
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        CheckConstraint(
            "consumed_at IS NOT NULL"
            " OR (consumed_by_user_id IS NULL AND consumed_by_elder_device_id IS NULL)",
            name="consumer_only_when_consumed",
        ),
        Index(
            "ix_invites_open_expires_at",
            "expires_at",
            postgresql_where=text("consumed_at IS NULL AND revoked_at IS NULL"),
        ),
    )

    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(Text)
    elder_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("elders.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime]
    consumed_at: Mapped[datetime | None]
    consumed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    consumed_by_elder_device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("elder_devices.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None]


class PushToken(UUIDPrimaryKey, Timestamps, Base):
    """A push destination belonging to exactly one user or one elder device."""

    __tablename__ = "push_tokens"
    __table_args__ = (
        CheckConstraint("num_nonnulls(user_id, elder_device_id) = 1", name="exactly_one_owner"),
        one_of("provider", PushProvider, "provider"),
        one_of("platform", DevicePlatform, "platform"),
        UniqueConstraint("provider", "token"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    elder_device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("elder_devices.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(Text)
    token: Mapped[str] = mapped_column(Text)
    platform: Mapped[str] = mapped_column(Text)
    # Set when the provider reports the token dead (e.g. DeviceNotRegistered).
    disabled_at: Mapped[datetime | None]


class AuditLog(Base):
    """Append-only record of who did what. No foreign keys: history outlives the rows it
    describes. Personal data in `data` is scrubbed on account deletion (Phase 16)."""

    __tablename__ = "audit_log"
    __table_args__ = (
        one_of("actor_type", ActorType, "actor_type"),
        Index("ix_audit_log_family_id_occurred_at", "family_id", "occurred_at"),
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now())
    actor_type: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID | None]
    family_id: Mapped[uuid.UUID | None]
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    request_id: Mapped[str | None] = mapped_column(Text)
