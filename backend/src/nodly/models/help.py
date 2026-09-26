"""Help requests and their timeline (CLAUDE.md §8). Not an emergency service: the elder's
screen always shows the local emergency number too."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Identity, Index, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from nodly.models.base import Base, CreatedAt, UUIDPrimaryKey, one_of


class HelpKind(StrEnum):
    help = "help"  # the Help button: urgent, the escalation ladder
    call_me = "call_me"  # "Please call me": non-urgent, one normal push


class HelpStatus(StrEnum):
    open = "open"  # sent, nobody has said "I'm on it" yet
    acknowledged = "acknowledged"  # someone is on it
    resolved = "resolved"  # a family member closed it
    cancelled = "cancelled"  # the elder said "I'm okay now"


class HelpEventKind(StrEnum):
    created = "created"
    pushed = "pushed"  # a round of notifications (the first, then the repeats)
    acknowledged = "acknowledged"
    resolved = "resolved"
    cancelled = "cancelled"
    sms_skipped = "sms_skipped"  # T+2 min SMS: Phase 15
    voice_skipped = "voice_skipped"  # T+5 min call: Phase 15


class HelpRequest(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "help_requests"
    __table_args__ = (
        one_of("kind", HelpKind, "kind"),
        one_of("status", HelpStatus, "status"),
        # One live request per elder at a time: pressing Help again returns the open one.
        # Family test alerts don't count, so a test can never stand in the way of real Help.
        Index(
            "uq_help_requests_one_live_per_elder",
            "elder_id",
            unique=True,
            postgresql_where=text(
                "status IN ('open', 'acknowledged') AND NOT is_test"
            ),  # = LIVE_PREDICATE
        ),
    )

    elder_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("elders.id", ondelete="CASCADE"), index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("elder_devices.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'open'"))
    is_test: Mapped[bool] = mapped_column(server_default=text("false"))
    # What the phone knew when it asked (§8): all optional.
    latitude: Mapped[float | None]
    longitude: Mapped[float | None]
    location_accuracy_m: Mapped[float | None]
    battery_percent: Mapped[int | None]
    network: Mapped[str | None] = mapped_column(Text)
    last_pushed_at: Mapped[datetime | None]
    acked_at: Mapped[datetime | None]
    acked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    closed_at: Mapped[datetime | None]
    closed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)


class HelpEvent(Base):
    """The request's timeline, kept whole (§8)."""

    __tablename__ = "help_events"
    __table_args__ = (one_of("kind", HelpEventKind, "kind"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("help_requests.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(server_default=func.now())
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    data: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
