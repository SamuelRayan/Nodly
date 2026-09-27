"""Check-ins against the database (CLAUDE.md §7): the engine's tick, recording a check-in, and
the family's view of an elder's day.

Every engine action goes through `engine_actions` (unique per elder, local day and action), so
a tick that runs twice, or two workers ticking at once, can't notify anyone twice.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.checkins.engine import (
    CheckinSettings,
    DayState,
    Schedule,
    actions_due,
    days_to_check,
    local_today,
    schedule_for,
    start_of_day,
)
from nodly.jobs.queue import enqueue
from nodly.models import (
    AlertResolution,
    Checkin,
    CheckinAlert,
    CheckinSource,
    Elder,
    ElderDevice,
    EngineAction,
    EngineActionKind,
)

NOTIFY_JOB = "checkins.notify"
# Actions that told the family something is wrong, so a later check-in earns an "All good".
FAMILY_WARNINGS = (EngineActionKind.family_late, EngineActionKind.missed)
REMINDERS = (EngineActionKind.remind, EngineActionKind.due_remind)
WEEK = 7

CheckinStatus = Literal[
    "waiting", "late", "active", "missed", "okay", "paused", "no_phone", "starts_tomorrow"
]
DayMark = Literal["okay", "missed", "none"]


def checkin_settings(elder: Elder) -> CheckinSettings:
    return CheckinSettings(
        timezone=elder.timezone,
        remind_at=elder.checkin_remind_at,
        due_by=elder.checkin_due_by,
        grace_minutes=elder.checkin_grace_minutes,
        activity_counts_as_ok=elder.checkin_activity_counts_as_ok,
    )


@dataclass(frozen=True)
class PhoneState:
    connected_since: datetime  # the earliest connected phone's pairing
    last_seen: datetime | None  # the latest use of any connected phone


async def phone_states(
    session: AsyncSession, elder_ids: list[uuid.UUID] | None = None
) -> dict[uuid.UUID, PhoneState]:
    """Elders with at least one connected phone. No phone, nobody to remind: the engine
    leaves those elders alone."""
    query = (
        select(
            ElderDevice.elder_id,
            func.min(ElderDevice.created_at),
            func.max(ElderDevice.last_seen_at),
        )
        .where(ElderDevice.revoked_at.is_(None))
        .group_by(ElderDevice.elder_id)
    )
    if elder_ids is not None:
        query = query.where(ElderDevice.elder_id.in_(elder_ids))
    rows = await session.execute(query)
    return {elder_id: PhoneState(since, seen) for elder_id, since, seen in rows}


def _active_on(day: date, tz: ZoneInfo, phone: PhoneState | None) -> bool:
    """Used Nodly since `day` began (the ACTIVITY signal)."""
    return bool(phone and phone.last_seen and phone.last_seen >= start_of_day(day, tz))


async def _done_actions(
    session: AsyncSession, elder_id: uuid.UUID, days: list[date]
) -> dict[date, set[EngineActionKind]]:
    rows = await session.execute(
        select(EngineAction.local_date, EngineAction.action).where(
            EngineAction.elder_id == elder_id, EngineAction.local_date.in_(days)
        )
    )
    done: dict[date, set[EngineActionKind]] = {day: set() for day in days}
    for day, action in rows:
        done[day].add(EngineActionKind(action))
    return done


async def take_action(
    session: AsyncSession, elder_id: uuid.UUID, day: date, action: EngineActionKind, now: datetime
) -> bool:
    """Record an action and queue its notifications, once. False if it was already taken.
    Caller commits (the ledger row, the alert and the job land together or not at all)."""
    taken = await session.scalar(
        insert(EngineAction)
        .values(elder_id=elder_id, local_date=day, action=action)
        .on_conflict_do_nothing()
        .returning(EngineAction.id)
    )
    if taken is None:
        return False
    if action == EngineActionKind.missed:
        await session.execute(
            insert(CheckinAlert)
            .values(elder_id=elder_id, local_date=day, raised_at=now)
            .on_conflict_do_nothing()
        )
    await enqueue(
        session,
        NOTIFY_JOB,
        {"elder_id": str(elder_id), "local_date": day.isoformat(), "action": action.value},
        run_at=now,
        # One job per ledger row (not per elder/day/action): if a day is ever reset (dev tools,
        # support), the new action still gets its notification.
        idempotency_key=f"engine_action:{taken}",
    )
    return True


async def run_tick(session: AsyncSession, now: datetime) -> int:
    """One pass of the engine over every elder with a connected phone. Returns how many
    actions it took. Commits."""
    phones = await phone_states(session)
    if not phones:
        return 0
    elders = await session.scalars(select(Elder).where(Elder.id.in_(list(phones))))
    taken = 0
    for elder in elders:
        if elder.is_paused(now):
            continue
        settings = checkin_settings(elder)
        tz = ZoneInfo(settings.timezone)
        days = days_to_check(now, settings)
        checked_in = set(
            await session.scalars(
                select(Checkin.local_date).where(
                    Checkin.elder_id == elder.id, Checkin.local_date.in_(days)
                )
            )
        )
        done = await _done_actions(session, elder.id, days)
        phone = phones[elder.id]
        for day in days:
            schedule = schedule_for(day, settings)
            # A phone connected after the day's due time starts with tomorrow.
            if phone.connected_since > schedule.due:
                continue
            state = DayState(
                checked_in=day in checked_in,
                active=_active_on(day, tz, phone),
                done=frozenset(done[day]),
            )
            for action in actions_due(now, schedule, state, settings):
                taken += await take_action(session, elder.id, day, action, now)
    await session.commit()
    return taken


async def record_checkin(
    session: AsyncSession,
    elder: Elder,
    now: datetime,
    source: CheckinSource,
    *,
    device_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> tuple[Checkin, bool]:
    """Today's check-in (the elder's local day). Returns (check-in, whether this call made or
    upgraded it). A tap after "marked okay" replaces it; anything else keeps the first.

    Resolves an open missed check-in alert, and queues "All good" for the family if they'd
    been told something was wrong. Caller commits.
    """
    day = local_today(now, ZoneInfo(elder.timezone))
    values = {
        "elder_id": elder.id,
        "local_date": day,
        "checked_in_at": now,
        "source": source,
        "device_id": device_id,
        "user_id": user_id,
    }
    new_id = await session.scalar(
        insert(Checkin).values(**values).on_conflict_do_nothing().returning(Checkin.id)
    )
    existing = await session.scalar(
        select(Checkin)
        .where(Checkin.elder_id == elder.id, Checkin.local_date == day)
        .with_for_update()
    )
    assert existing is not None
    changed = new_id is not None
    if not changed and existing.source == CheckinSource.family and source != CheckinSource.family:
        existing.source, existing.checked_in_at = source, now
        existing.device_id, existing.user_id = device_id, None
        changed = True
    if new_id is None:
        # The elder's own tap after "marked okay" doesn't resolve or notify twice.
        return existing, changed

    alert = await session.scalar(
        select(CheckinAlert).where(
            CheckinAlert.elder_id == elder.id,
            CheckinAlert.local_date == day,
            CheckinAlert.resolved_at.is_(None),
        )
    )
    if alert is not None:
        alert.resolved_at = now
        alert.resolution = (
            AlertResolution.marked_okay
            if source == CheckinSource.family
            else AlertResolution.checked_in
        )
    warned = await session.scalar(
        select(func.count())
        .select_from(EngineAction)
        .where(
            EngineAction.elder_id == elder.id,
            EngineAction.local_date == day,
            EngineAction.action.in_(FAMILY_WARNINGS),
        )
    )
    if warned:
        await take_action(session, elder.id, day, EngineActionKind.all_good, now)
    return existing, True


# ---------------------------------------------------------------- the family's view


@dataclass(frozen=True)
class DayRecord:
    day: date
    state: DayMark  # for today, see ElderDay.status


@dataclass(frozen=True)
class ElderDay:
    """An elder's check-in day as the family sees it."""

    day: date
    schedule: Schedule
    status: CheckinStatus
    # The engine watches today: a phone was connected before today's due time.
    watched: bool
    checkin: Checkin | None
    alert: CheckinAlert | None
    reminded: list[tuple[EngineActionKind, datetime]]
    active_today: bool
    last_seen: datetime | None
    last_checkin: Checkin | None  # the latest check-in before today
    week: list[DayRecord]  # the last 7 local days, oldest first, today last


async def elder_day(session: AsyncSession, elder: Elder, now: datetime) -> ElderDay:
    settings = checkin_settings(elder)
    tz = ZoneInfo(settings.timezone)
    today = local_today(now, tz)
    schedule = schedule_for(today, settings)
    week_days = [today - timedelta(days=offset) for offset in range(WEEK - 1, -1, -1)]

    checkins = {
        checkin.local_date: checkin
        for checkin in await session.scalars(
            select(Checkin).where(Checkin.elder_id == elder.id, Checkin.local_date.in_(week_days))
        )
    }
    actions = list(
        await session.execute(
            select(EngineAction.local_date, EngineAction.action, EngineAction.created_at)
            .where(EngineAction.elder_id == elder.id, EngineAction.local_date.in_(week_days))
            .order_by(EngineAction.created_at)
        )
    )
    missed_days = {day for day, action, _ in actions if action == EngineActionKind.missed}
    alert = await session.scalar(
        select(CheckinAlert).where(
            CheckinAlert.elder_id == elder.id, CheckinAlert.local_date == today
        )
    )
    last_checkin = await session.scalar(
        select(Checkin)
        .where(Checkin.elder_id == elder.id, Checkin.local_date < today)
        .order_by(Checkin.local_date.desc())
        .limit(1)
    )
    phone = (await phone_states(session, [elder.id])).get(elder.id)
    active = _active_on(today, tz, phone)
    checkin = checkins.get(today)
    # Same rule as the tick: a phone connected after today's due time starts tomorrow.
    watched = phone is not None and phone.connected_since <= schedule.due

    status: CheckinStatus
    if checkin is not None:
        status = "okay"
    elif phone is None:
        status = "no_phone"
    elif elder.is_paused(now):
        status = "paused"
    elif not watched:
        status = "starts_tomorrow"
    elif alert is not None and alert.resolved_at is None:
        status = "missed"
    elif now >= schedule.due:
        status = "active" if settings.activity_counts_as_ok and active else "late"
    else:
        status = "waiting"

    def past(day: date) -> DayMark:
        return "okay" if day in checkins else "missed" if day in missed_days else "none"

    week = [DayRecord(day, past(day)) for day in week_days]
    reminded = [
        (EngineActionKind(action), at)
        for day, action, at in actions
        if day == today and action in REMINDERS
    ]
    return ElderDay(
        day=today,
        schedule=schedule,
        status=status,
        watched=watched,
        checkin=checkin,
        alert=alert,
        reminded=reminded,
        active_today=active,
        last_seen=phone.last_seen if phone else None,
        last_checkin=last_checkin,
        week=week,
    )


async def history(session: AsyncSession, elder: Elder, now: datetime, days: int) -> list[DayRecord]:
    """The last `days` local days, oldest first, today last: okay, missed or nothing."""
    tz = ZoneInfo(checkin_settings(elder).timezone)
    today = local_today(now, tz)
    first = today - timedelta(days=days - 1)
    checked = set(
        await session.scalars(
            select(Checkin.local_date).where(
                Checkin.elder_id == elder.id, Checkin.local_date.between(first, today)
            )
        )
    )
    missed = set(
        await session.scalars(
            select(EngineAction.local_date).where(
                EngineAction.elder_id == elder.id,
                EngineAction.action == EngineActionKind.missed,
                EngineAction.local_date.between(first, today),
            )
        )
    )
    return [
        DayRecord(day, "okay" if day in checked else "missed" if day in missed else "none")
        for day in (first + timedelta(days=offset) for offset in range(days))
    ]
