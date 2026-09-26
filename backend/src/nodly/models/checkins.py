"""Daily check-ins (CLAUDE.md §7): the check-ins themselves, the engine's idempotency ledger and
missed-check-in alerts."""

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import BigInteger, ForeignKey, Identity, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from nodly.models.base import Base, CreatedAt, UUIDPrimaryKey, one_of


class CheckinSource(StrEnum):
    app = "app"  # the elder tapped "I'm okay" in the app
    notification = "notification"  # the "I'm okay" button on a reminder
    family = "family"  # a family member marked them okay ("I've talked to her")


class EngineActionKind(StrEnum):
    remind = "remind"  # §7.1: reminder to the elder at remind_at
    due_remind = "due_remind"  # §7.2: second reminder to the elder at due_by
    family_late = "family_late"  # §7.2: normal push to the family at due_by
    missed = "missed"  # §7.3: missed check-in alert to every family member
    all_good = "all_good"  # §7.4: "All good" to the family after they were told


class AlertResolution(StrEnum):
    checked_in = "checked_in"  # the elder tapped
    marked_okay = "marked_okay"  # a family member marked them okay


class Checkin(UUIDPrimaryKey, CreatedAt, Base):
    """At most one per elder per local day (the elder's timezone). The first one counts; a later
    tap by the elder replaces a family "marked okay" (the elder's own word is stronger)."""

    __tablename__ = "checkins"
    __table_args__ = (
        UniqueConstraint("elder_id", "local_date"),
        one_of("source", CheckinSource, "source"),
    )

    elder_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elders.id", ondelete="CASCADE"))
    local_date: Mapped[date]
    checked_in_at: Mapped[datetime]
    source: Mapped[str] = mapped_column(Text)
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("elder_devices.id", ondelete="SET NULL")
    )
    # Who marked them okay (source = family).
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class EngineAction(Base):
    """One row per action the check-in engine took: the unique key makes re-running a tick (or
    two workers ticking at once) harmless (§7)."""

    __tablename__ = "engine_actions"
    __table_args__ = (
        UniqueConstraint("elder_id", "local_date", "action"),
        one_of("action", EngineActionKind, "action"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    elder_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elders.id", ondelete="CASCADE"))
    local_date: Mapped[date]
    action: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CheckinAlert(UUIDPrimaryKey, CreatedAt, Base):
    """A missed check-in alert (§7.3). High priority, but not the Help ladder. The first family
    member to say "I'm on it" is recorded; a check-in or "mark okay" resolves it."""

    __tablename__ = "checkin_alerts"
    __table_args__ = (
        UniqueConstraint("elder_id", "local_date"),
        one_of("resolution", AlertResolution, "resolution"),
    )

    elder_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elders.id", ondelete="CASCADE"))
    local_date: Mapped[date]
    raised_at: Mapped[datetime]
    acked_at: Mapped[datetime | None]
    acked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None]
    resolution: Mapped[str | None] = mapped_column(Text)
