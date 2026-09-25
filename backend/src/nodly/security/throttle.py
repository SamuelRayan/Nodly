"""Brute-force protection for code guessing, with fixed-window counters in Postgres.

Only failures count (wrong, expired or used codes). Before a code is checked, every bucket
that applies (the client IP, the signed-in user, everyone) must be under its limit, or the
request gets 429 with Retry-After. The global bucket stops guessing spread over many IPs, at
the cost that a flood of failures briefly blocks everyone's pairing; codes are rare, short-
lived operations, so that's the right trade.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.config import Settings
from nodly.errors import TooManyRequestsError
from nodly.models import ThrottleCounter

# Counters older than this are deleted as new failures come in.
_KEEP_COUNTERS_FOR = timedelta(days=1)


@dataclass(frozen=True)
class Limit:
    bucket: str
    max_failures: int


class CodeAttemptThrottle:
    def __init__(self, settings: Settings) -> None:
        self.window = settings.throttle_window_seconds
        self.per_ip = settings.throttle_max_failures_per_ip
        self.per_user = settings.throttle_max_failures_per_user
        self.global_ = settings.throttle_max_failures_global

    def limits(self, *, ip: str | None, user_id: object | None = None) -> list[Limit]:
        limits = [Limit("code:global", self.global_)]
        if ip:
            limits.append(Limit(f"code:ip:{ip}", self.per_ip))
        if user_id is not None:
            limits.append(Limit(f"code:user:{user_id}", self.per_user))
        return limits

    def _window_start(self, now: datetime) -> datetime:
        epoch = now.timestamp()
        return datetime.fromtimestamp(epoch - epoch % self.window, tz=now.tzinfo)

    async def check(self, session: AsyncSession, limits: list[Limit], now: datetime) -> None:
        window_start = self._window_start(now)
        rows = await session.execute(
            select(ThrottleCounter.bucket, ThrottleCounter.count).where(
                ThrottleCounter.bucket.in_([limit.bucket for limit in limits]),
                ThrottleCounter.window_start == window_start,
            )
        )
        counts: dict[str, int] = {bucket: count for bucket, count in rows}
        if any(counts.get(limit.bucket, 0) >= limit.max_failures for limit in limits):
            retry_after = max(
                1, ceil((window_start + timedelta(seconds=self.window) - now).total_seconds())
            )
            raise TooManyRequestsError(
                "Too many wrong codes. Wait a few minutes and try again.",
                headers={"Retry-After": str(retry_after)},
                retry_after=retry_after,
            )

    async def record_failure(
        self, session: AsyncSession, limits: list[Limit], now: datetime
    ) -> None:
        """Counts one failure in every bucket and commits (the request is about to fail)."""
        window_start = self._window_start(now)
        for limit in limits:
            statement = insert(ThrottleCounter).values(
                bucket=limit.bucket, window_start=window_start, count=1
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[ThrottleCounter.bucket, ThrottleCounter.window_start],
                    set_={"count": ThrottleCounter.count + 1},
                )
            )
        await session.execute(
            delete(ThrottleCounter).where(ThrottleCounter.window_start < now - _KEEP_COUNTERS_FOR)
        )
        await session.commit()
