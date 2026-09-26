"""Help requests and the escalation ladder (CLAUDE.md §8).

T+0: an urgent push to every family member. Then every HELP_REPEAT_SECONDS, again, until the
first "I'm on it" (at most HELP_REPEAT_MINUTES). SMS at T+2 min and a voice call at T+5 min
come in Phase 15; until then the timeline records that they were skipped.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.config import Settings
from nodly.jobs.queue import enqueue
from nodly.models import (
    Elder,
    HelpEvent,
    HelpEventKind,
    HelpKind,
    HelpRequest,
    HelpStatus,
)

NOTIFY_JOB = "help.notify"
LIVE = (HelpStatus.open, HelpStatus.acknowledged)
# The WHERE of uq_help_requests_one_live_per_elder (models/help.py).
LIVE_PREDICATE = "status IN ('open', 'acknowledged') AND NOT is_test"


@dataclass(frozen=True)
class PhoneInfo:
    """What the phone knew when it asked (§8). Everything is optional."""

    latitude: float | None = None
    longitude: float | None = None
    accuracy_m: float | None = None
    battery_percent: int | None = None
    network: str | None = None


def add_event(
    session: AsyncSession,
    request_id: uuid.UUID,
    kind: HelpEventKind,
    at: datetime,
    *,
    user_id: uuid.UUID | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    session.add(
        HelpEvent(request_id=request_id, kind=kind, at=at, user_id=user_id, data=data or {})
    )


async def notify(
    session: AsyncSession, request_id: uuid.UUID, what: str, at: datetime, key: str
) -> None:
    """Queue notifications about a request (alert, acknowledged, cancelled, resolved)."""
    await enqueue(
        session,
        NOTIFY_JOB,
        {"request_id": str(request_id), "what": what},
        run_at=at,
        idempotency_key=f"{request_id}:{key}",
    )


async def live_request(session: AsyncSession, elder_id: uuid.UUID) -> HelpRequest | None:
    return await session.scalar(
        select(HelpRequest).where(
            HelpRequest.elder_id == elder_id,
            HelpRequest.status.in_(LIVE),
            HelpRequest.is_test.is_(False),
        )
    )


async def open_request(
    session: AsyncSession,
    elder: Elder,
    now: datetime,
    kind: HelpKind,
    *,
    device_id: uuid.UUID | None = None,
    info: PhoneInfo | None = None,
) -> tuple[HelpRequest, bool]:
    """Ask for help. Pressing again while a request is live returns that one (the first push
    already went out). "Please call me" never upgrades to Help or back. Commits."""
    info = info or PhoneInfo()
    new_id = await session.scalar(
        insert(HelpRequest)
        .values(
            elder_id=elder.id,
            family_id=elder.family_id,
            device_id=device_id,
            kind=kind,
            status=HelpStatus.open,
            created_at=now,
            latitude=info.latitude,
            longitude=info.longitude,
            location_accuracy_m=info.accuracy_m,
            battery_percent=info.battery_percent,
            network=info.network,
            last_pushed_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=[HelpRequest.elder_id],
            # Postgres infers the partial unique index from this: it must match its WHERE.
            index_where=text(LIVE_PREDICATE),
        )
        .returning(HelpRequest.id)
    )
    if new_id is None:
        existing = await live_request(session, elder.id)
        assert existing is not None
        return existing, False
    add_event(session, new_id, HelpEventKind.created, now, data={"kind": kind.value})
    await notify(session, new_id, "alert", now, "alert:0")
    await session.commit()
    request = await session.get_one(HelpRequest, new_id)
    return request, True


async def open_test(
    session: AsyncSession, elder: Elder, user_id: uuid.UUID, now: datetime, settings: Settings
) -> HelpRequest | None:
    """A clearly labelled test alert to every family device (§8). None if the family used up
    today's tests. Commits."""
    used = await session.scalar(
        select(func.count())
        .select_from(HelpRequest)
        .where(
            HelpRequest.family_id == elder.family_id,
            HelpRequest.is_test.is_(True),
            HelpRequest.created_at > now - timedelta(days=1),
        )
    )
    if (used or 0) >= settings.help_tests_per_day:
        return None
    request = HelpRequest(
        elder_id=elder.id,
        family_id=elder.family_id,
        kind=HelpKind.help,
        status=HelpStatus.open,
        is_test=True,
        created_at=now,
        last_pushed_at=now,
    )
    session.add(request)
    await session.flush()
    add_event(session, request.id, HelpEventKind.created, now, user_id=user_id, data={"test": True})
    await notify(session, request.id, "alert", now, "alert:0")
    await session.commit()
    return request


async def acknowledge(
    session: AsyncSession, request: HelpRequest, user_id: uuid.UUID, now: datetime
) -> bool:
    """ "I'm on it". The first one stops the repeats and tells everyone else; later ones only
    go in the timeline. Returns whether this was the first. Commits."""
    if request.status != HelpStatus.open:
        if request.status == HelpStatus.acknowledged:
            add_event(session, request.id, HelpEventKind.acknowledged, now, user_id=user_id)
            await session.commit()
        return False
    request.status = HelpStatus.acknowledged
    request.acked_at = now
    request.acked_by_user_id = user_id
    add_event(
        session, request.id, HelpEventKind.acknowledged, now, user_id=user_id, data={"first": True}
    )
    await notify(session, request.id, "acknowledged", now, "acknowledged")
    await session.commit()
    return True


async def close(
    session: AsyncSession,
    request: HelpRequest,
    now: datetime,
    *,
    by_elder: bool,
    user_id: uuid.UUID | None = None,
    note: str | None = None,
) -> bool:
    """The elder's "I'm okay now" (cancelled) or a family member's "resolved". False if it
    was already closed. Commits."""
    if request.status not in LIVE:
        return False
    request.status = HelpStatus.cancelled if by_elder else HelpStatus.resolved
    request.closed_at = now
    request.closed_by_user_id = user_id
    request.resolution_note = note
    kind = HelpEventKind.cancelled if by_elder else HelpEventKind.resolved
    add_event(
        session, request.id, kind, now, user_id=user_id, data={"note": note} if note else None
    )
    await notify(session, request.id, kind.value, now, kind.value)
    await session.commit()
    return True


async def run_help_tick(session: AsyncSession, now: datetime, settings: Settings) -> int:
    """Repeat unanswered Help alerts, and note the SMS/voice steps (Phase 15) as skipped.
    Returns how many repeats it queued. Commits."""
    repeat = timedelta(seconds=settings.help_repeat_seconds)
    stop_after = timedelta(minutes=settings.help_repeat_minutes)
    requests = await session.scalars(
        select(HelpRequest)
        .where(
            HelpRequest.status == HelpStatus.open,
            HelpRequest.kind == HelpKind.help,
            HelpRequest.is_test.is_(False),
            HelpRequest.created_at > now - stop_after,
        )
        .with_for_update(skip_locked=True)
    )
    repeats = 0
    for request in requests:
        age = now - request.created_at
        if request.last_pushed_at is None or now - request.last_pushed_at >= repeat:
            round_ = int(age / repeat)
            request.last_pushed_at = now
            await notify(session, request.id, "alert", now, f"alert:{round_}")
            repeats += 1
        for after, kind in (
            (settings.help_sms_after_seconds, HelpEventKind.sms_skipped),
            (settings.help_voice_after_seconds, HelpEventKind.voice_skipped),
        ):
            if age >= timedelta(seconds=after):
                done = await session.scalar(
                    select(func.count())
                    .select_from(HelpEvent)
                    .where(HelpEvent.request_id == request.id, HelpEvent.kind == kind)
                )
                if not done:
                    add_event(session, request.id, kind, now, data={"reason": "Phase 15"})
    await session.commit()
    return repeats
