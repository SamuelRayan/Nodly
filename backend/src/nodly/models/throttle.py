"""Fixed-window counters for brute-force protection (see nodly.security.throttle)."""

from datetime import datetime

from sqlalchemy import CheckConstraint, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from nodly.models.base import Base


class ThrottleCounter(Base):
    __tablename__ = "throttle_counters"
    __table_args__ = (
        CheckConstraint("count >= 0", name="count_not_negative"),
        Index("ix_throttle_counters_window_start", "window_start"),
    )

    # e.g. "code:ip:203.0.113.7", "code:user:<uuid>", "code:global"
    bucket: Mapped[str] = mapped_column(Text, primary_key=True)
    window_start: Mapped[datetime] = mapped_column(primary_key=True)
    count: Mapped[int]
