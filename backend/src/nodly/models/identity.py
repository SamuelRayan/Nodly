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
    __table_args__ = (
        not_blank("name", 100),
        CheckConstraint("pin_hash IS NULL OR pin_hash LIKE 'scrypt$%'", name="pin_hash_format"),
    )

    name: Mapped[str] = mapped_column(Text)
    # The family PIN (organizer sets it) lets someone take a paired phone out of elder mode.
    # scrypt, see nodly.security.pins. Null = no PIN; the family disconnects the phone instead.
    pin_hash: Mapped[str | None] = mapped_column(Text)


class User(UUIDPrimaryKey, Timestamps, Base):
    """A family member account (Supabase Auth). Elders are not users: they have no login."""

    __tablename__ = "users"
    __table_args__ = (
        not_blank("display_name", 80),
        CheckConstraint("email ~ '^[^@\\s]+@[^@\\s]+$' AND length(email) <= 254", name="email"),
        CheckConstraint("timezone <> ''", name="timezone_not_empty"),
        matches("country_code", COUNTRY_CODE_PATTERN, "country_code", nullable=True),
        matches("phone_e164", E164_PATTERN, "phone_e164", nullable=True),
        matches("language", LOCALE_PATTERN, "language", nullable=True),
        # Onboarding is done only with a name, timezone, country and the 16+ confirmation.
        CheckConstraint(
            "onboarded_at IS NULL OR (display_name IS NOT NULL AND timezone IS NOT NULL"
            " AND country_code IS NOT NULL AND age_confirmed_at IS NOT NULL)",
            name="onboarded_profile_complete",
        ),
        Index("uq_users_email_lower", func.lower(text("email")), unique=True),
    )

    # Supabase Auth user id (the JWT "sub"). Null only for users made by the /dev routes.
    auth_user_id: Mapped[uuid.UUID | None] = mapped_column(unique=True)
    email: Mapped[str] = mapped_column(Text)
    # Profile fields are filled during onboarding (PATCH /v1/me).
    display_name: Mapped[str | None] = mapped_column(Text)
    # User-picked IANA name. Required to finish onboarding, never defaulted (CLAUDE.md §5).
    timezone: Mapped[str | None] = mapped_column(Text)
    country_code: Mapped[str | None] = mapped_column(String(2))
    phone_e164: Mapped[str | None] = mapped_column(Text)
    # BCP 47 language tag the app should use, e.g. "hi" or "en-GB".
    language: Mapped[str | None] = mapped_column(Text)
    # When the user confirmed they are 16 or older (CLAUDE.md §5).
    age_confirmed_at: Mapped[datetime | None]
    onboarded_at: Mapped[datetime | None]

    @property
    def is_onboarded(self) -> bool:
        return self.onboarded_at is not None


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
        not_blank("relation_label", 40),
        not_blank("full_name", 120),
        CheckConstraint("timezone <> ''", name="timezone_not_empty"),
        matches("country_code", COUNTRY_CODE_PATTERN, "country_code"),
        matches("phone_e164", E164_PATTERN, "phone_e164", nullable=True),
        matches("language", LOCALE_PATTERN, "language", nullable=True),
        CheckConstraint("checkin_grace_minutes BETWEEN 0 AND 720", name="checkin_grace_minutes"),
        CheckConstraint("checkin_remind_at <= checkin_due_by", name="checkin_remind_before_due"),
        CheckConstraint(
            "paused_until IS NULL OR (paused_at IS NOT NULL AND paused_until > paused_at)",
            name="paused_until_after_paused_at",
        ),
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
    # What the family app shows ("Asha"); relation_label is how the family refers to them
    # ("Mom", "Nani"); full_name is for recipe bylines later (CLAUDE.md §11).
    display_name: Mapped[str] = mapped_column(Text)
    relation_label: Mapped[str | None] = mapped_column(Text)
    full_name: Mapped[str | None] = mapped_column(Text)
    # User-picked IANA name. Required, never defaulted (CLAUDE.md §5).
    timezone: Mapped[str] = mapped_column(Text)
    # Required: the Help screen shows the emergency number for this country.
    country_code: Mapped[str] = mapped_column(String(2))
    phone_e164: Mapped[str | None] = mapped_column(Text)
    # BCP 47 language tag for the elder's app, e.g. "hi-IN".
    language: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(server_default=text("false"))
    # Paused elders get no check-in reminders or missed-check-in alerts (Phase 4).
    # Help is never paused. paused_until = null means "until someone resumes".
    paused_at: Mapped[datetime | None]
    paused_until: Mapped[datetime | None]

    def is_paused(self, now: datetime) -> bool:
        """Paused right now; a pause whose paused_until has passed has ended by itself."""
        return self.paused_at is not None and (self.paused_until is None or self.paused_until > now)

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
        matches("previous_token_hash", SHA256_HEX_PATTERN, "previous_token_hash", nullable=True),
        CheckConstraint(
            "(previous_token_hash IS NULL) = (previous_token_expires_at IS NULL)",
            name="previous_token_has_expiry",
        ),
        one_of("platform", DevicePlatform, "platform"),
        Index(
            "ix_elder_devices_previous_token_hash",
            "previous_token_hash",
            postgresql_where=text("previous_token_hash IS NOT NULL"),
        ),
    )

    elder_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("elders.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # After a rotation the old token stays valid until previous_token_expires_at, so a
    # lost response can't lock the phone out.
    previous_token_hash: Mapped[str | None] = mapped_column(String(64))
    previous_token_expires_at: Mapped[datetime | None]
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
