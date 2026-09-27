"""Moments: photos, videos and voice recordings shared inside a family (CLAUDE.md §9), and
whether each one earns the family's free day of Plus (§10)."""

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Identity, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from nodly.models.base import Base, CreatedAt, UUIDPrimaryKey, one_of


class MomentKind(StrEnum):
    photo = "photo"
    video = "video"
    voice = "voice"


class MomentStatus(StrEnum):
    awaiting_upload = "awaiting_upload"  # intent made; the file hasn't arrived yet
    checking = "checking"  # uploaded and "complete"; the worker is verifying it
    published = "published"
    rejected = "rejected"  # see reject_reason


class Moment(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "moments"
    __table_args__ = (
        one_of("kind", MomentKind, "kind"),
        one_of("status", MomentStatus, "status"),
        CheckConstraint("num_nonnulls(author_user_id, author_device_id) <= 1", name="one_author"),
        CheckConstraint(
            "NOT qualifies OR qualifying_local_date IS NOT NULL", name="qualifying_has_a_day"
        ),
        # The feed, newest first; and the near-duplicate lookback (§10: 90 days of photos).
        Index("ix_moments_family_feed", "family_id", "published_at"),
    )

    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'awaiting_upload'"))
    # A family member, or an elder's phone (elders can post too, §9). Both null once the author
    # is gone; the moment stays for the family.
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    author_device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("elder_devices.id", ondelete="SET NULL")
    )
    by_elder: Mapped[bool] = mapped_column(server_default=text("false"))
    # §10: the server timestamp of the upload intent is when the moment "happened".
    intent_at: Mapped[datetime]
    content_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    width: Mapped[int | None]
    height: Mapped[int | None]
    duration_ms: Mapped[int | None]
    # Perceptual hash (hex) for photos, to spot near-duplicates.
    phash: Mapped[str | None] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text)
    thumbnail_key: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None]
    verified_at: Mapped[datetime | None]
    published_at: Mapped[datetime | None]
    reject_reason: Mapped[str | None] = mapped_column(Text)
    # §10: whether this moment earns the family's free Plus for qualifying_local_date (family
    # clock) and the day after. The server decides; never the client.
    qualifies: Mapped[bool] = mapped_column(server_default=text("false"))
    qualifying_local_date: Mapped[date | None]
    not_qualifying_reason: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None]


class MomentView(Base):
    """Who has seen what, for "new" counts (one row per viewer and moment)."""

    __tablename__ = "moment_views"
    __table_args__ = (
        CheckConstraint("num_nonnulls(user_id, device_id) = 1", name="one_viewer"),
        Index(
            "uq_moment_views_user",
            "moment_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_moment_views_device",
            "moment_id",
            "device_id",
            unique=True,
            postgresql_where=text("device_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    moment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("moments.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("elder_devices.id", ondelete="CASCADE")
    )
    viewed_at: Mapped[datetime]


class MomentReaction(CreatedAt, Base):
    """A heart (the only reaction; behind REACTIONS_ENABLED). One per person per moment."""

    __tablename__ = "moment_reactions"
    __table_args__ = (
        CheckConstraint("num_nonnulls(user_id, device_id) = 1", name="one_reactor"),
        Index(
            "uq_moment_reactions_user",
            "moment_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_moment_reactions_device",
            "moment_id",
            "device_id",
            unique=True,
            postgresql_where=text("device_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    moment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("moments.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("elder_devices.id", ondelete="CASCADE")
    )
