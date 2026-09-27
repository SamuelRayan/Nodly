"""Whether a family has Nodly Plus (CLAUDE.md §10). `evaluate_access` is the only judge: a
family has Plus at t if any non-revoked access grant covers t. The app never decides."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import exists, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.checkins.engine import local_instant
from nodly.family_clock import family_date, family_timezone
from nodly.models import AccessGrant, GrantSource, Moment, MomentStatus


def local_day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """[start of `day`, start of the next day) in UTC. Days can be 23 or 25 hours (§5)."""
    return local_instant(day, time(0), tz), local_instant(day + timedelta(days=1), time(0), tz)


def moment_credit_window(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """§10: a qualifying moment on family-clock day D gives Plus from the start of D until the
    end of D+1."""
    return local_instant(day, time(0), tz), local_instant(day + timedelta(days=2), time(0), tz)


@dataclass(frozen=True)
class Access:
    has_plus: bool
    sources: list[str]  # what covers now: moment, day_pass, subscription, goodwill
    # The end of the unbroken run of grants covering now (a later grant that starts before
    # one ends extends it).
    plus_until: datetime | None


async def evaluate_access(session: AsyncSession, family_id: uuid.UUID, at: datetime) -> Access:
    grants = list(
        await session.scalars(
            select(AccessGrant)
            .where(
                AccessGrant.family_id == family_id,
                AccessGrant.revoked_at.is_(None),
                AccessGrant.ends_at > at,
            )
            .order_by(AccessGrant.starts_at)
        )
    )
    covering = [grant for grant in grants if grant.starts_at <= at]
    if not covering:
        return Access(has_plus=False, sources=[], plus_until=None)
    until = max(grant.ends_at for grant in covering)
    for grant in grants:  # by start time, so one pass follows the chain
        if grant.starts_at <= until < grant.ends_at:
            until = grant.ends_at
    return Access(
        has_plus=True,
        sources=sorted({grant.source for grant in covering}),
        plus_until=until,
    )


@dataclass(frozen=True)
class TodayMoment:
    """Today's moment on the family clock."""

    local_date: date | None  # None until the family has an elder (no clock, no "today")
    timezone: str | None
    shared: bool  # a qualifying moment already earned today
    # A family member's moment is on its way (started today, not checked yet) and could
    # still earn today. §10: no Day Pass is offered meanwhile.
    pending: bool


async def today_moment(session: AsyncSession, family_id: uuid.UUID, now: datetime) -> TodayMoment:
    timezone = await family_timezone(session, family_id)
    if timezone is None:
        return TodayMoment(local_date=None, timezone=None, shared=False, pending=False)
    today = family_date(now, timezone)
    start, end = local_day_bounds(today, ZoneInfo(timezone))
    shared = await session.scalar(
        select(
            exists().where(
                AccessGrant.family_id == family_id,
                AccessGrant.source == GrantSource.moment,
                AccessGrant.local_date == today,
                AccessGrant.revoked_at.is_(None),
            )
        )
    )
    pending = await session.scalar(
        select(
            exists().where(
                Moment.family_id == family_id,
                Moment.by_elder.is_(False),
                Moment.deleted_at.is_(None),
                Moment.status.in_([MomentStatus.awaiting_upload, MomentStatus.checking]),
                Moment.intent_at >= start,
                Moment.intent_at < end,
            )
        )
    )
    return TodayMoment(
        local_date=today, timezone=timezone, shared=bool(shared), pending=bool(pending)
    )


@dataclass(frozen=True)
class DayPassOffer:
    offered: bool
    reason: str | None  # has_plus | moment_pending (why not)


def day_pass_offer(access: Access, today: TodayMoment) -> DayPassOffer:
    """§10: a Day Pass is offered only to a family without Plus and without a moment on its
    way that would unlock today for free."""
    if access.has_plus:
        return DayPassOffer(offered=False, reason="has_plus")
    if today.pending:
        return DayPassOffer(offered=False, reason="moment_pending")
    return DayPassOffer(offered=True, reason=None)


async def grant_moment_credit(session: AsyncSession, moment: Moment) -> None:
    """A qualifying moment earns its day (idempotent: one credit per family and day, extra
    moments don't stack). Doesn't commit."""
    if not moment.qualifies or moment.qualifying_local_date is None:
        return
    timezone = await family_timezone(session, moment.family_id)
    if timezone is None:
        return
    starts_at, ends_at = moment_credit_window(moment.qualifying_local_date, ZoneInfo(timezone))
    await session.execute(
        insert(AccessGrant)
        .values(
            id=uuid.uuid4(),
            family_id=moment.family_id,
            source=GrantSource.moment,
            starts_at=starts_at,
            ends_at=ends_at,
            local_date=moment.qualifying_local_date,
            moment_id=moment.id,
        )
        .on_conflict_do_nothing(
            index_elements=[AccessGrant.family_id, AccessGrant.local_date],
            # Literal SQL: Postgres matches a partial index only against the same predicate.
            index_where=text("source = 'moment'"),
        )
    )
