"""The check-in engine's tick (every CHECKIN_TICK_SECONDS) and its notifications (CLAUDE.md §7).

Notification copy is English for now; per-person languages come with server-side i18n.
"""

import logging
import uuid
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from nodly.checkins.engine import schedule_for
from nodly.checkins.service import NOTIFY_JOB, checkin_settings, run_tick
from nodly.clock import utcnow
from nodly.jobs.registry import (
    JobContext,
    PeriodicContext,
    PermanentJobError,
    job_handler,
    periodic_task,
)
from nodly.models import Checkin, CheckinSource, Elder, EngineActionKind, User
from nodly.push import Push, deliver, elder_tokens, family_tokens, push_sender

logger = logging.getLogger(__name__)

# The app registers this category with an "I'm okay" button (mobile/src/push/notifications.ts).
REMINDER_CATEGORY = "checkin_reminder"


@periodic_task("checkins.tick", interval=lambda settings: settings.checkin_tick_seconds)
async def tick(ctx: PeriodicContext) -> None:
    async with ctx.sessionmaker() as session:
        taken = await run_tick(session, ctx.now)
    if taken:
        logger.info("check-in engine acted", extra={"actions": taken})


def clock_time(at: datetime, tz: str) -> str:
    """8:14 AM, in the elder's timezone."""
    local = at.astimezone(ZoneInfo(tz))
    return local.strftime("%I:%M %p").lstrip("0")


def family_name(elder: Elder) -> str:
    """How the family refers to the elder ("Amma"), or their name."""
    return elder.relation_label or elder.display_name


def build_push(
    action: EngineActionKind,
    elder: Elder,
    day: date,
    checkin: Checkin | None,
    marked_by: str | None,
) -> tuple[str, Push] | None:
    """(audience, notification) for an action: audience is "elder" or "family"."""
    name = family_name(elder)
    schedule = schedule_for(day, checkin_settings(elder))
    due = clock_time(schedule.due, elder.timezone)
    data: dict[str, Any] = {"elder_id": str(elder.id), "local_date": day.isoformat()}
    match action:
        case EngineActionKind.remind:
            return "elder", Push(
                tokens=[],
                title=f"Good morning, {elder.display_name}",
                body="Tap \"I'm okay\" so your family knows you're well today.",
                channel_id="checkin",
                data={**data, "type": "checkin_reminder"},
                category_id=REMINDER_CATEGORY,
            )
        case EngineActionKind.due_remind:
            return "elder", Push(
                tokens=[],
                title="Your family would love to hear from you",
                body="Tap \"I'm okay\" to let them know you're well.",
                channel_id="checkin",
                data={**data, "type": "checkin_reminder"},
                category_id=REMINDER_CATEGORY,
            )
        case EngineActionKind.family_late:
            return "family", Push(
                tokens=[],
                title=f"{name} hasn't checked in yet",
                body=f"It was due at {due}, {name}'s time. We've reminded them again.",
                channel_id="checkin",
                data={**data, "type": "checkin_late"},
                priority="normal",
            )
        case EngineActionKind.missed:
            return "family", Push(
                tokens=[],
                title=f"{name} hasn't checked in",
                body=f"Nothing since the {due} check-in time ({name}'s time). "
                "Call, or mark them okay once you've talked.",
                channel_id="checkin",
                data={**data, "type": "checkin_missed"},
            )
        case EngineActionKind.all_good:
            if checkin is None:
                return None
            at = clock_time(checkin.checked_in_at, elder.timezone)
            if checkin.source == CheckinSource.family:
                title = f"{marked_by or 'Someone'} marked {name} okay"
            else:
                title = f"All good: {name} checked in"
            return "family", Push(
                tokens=[],
                title=title,
                body=f"At {at}, {name}'s time.",
                channel_id="checkin",
                data={**data, "type": "checkin_ok"},
                priority="normal",
            )


@job_handler(NOTIFY_JOB)
async def notify(ctx: JobContext, payload: dict[str, Any]) -> None:
    try:
        elder_id = uuid.UUID(payload["elder_id"])
        day = date.fromisoformat(payload["local_date"])
        action = EngineActionKind(payload["action"])
    except (KeyError, ValueError) as error:
        raise PermanentJobError(f"Bad payload: {error}") from error

    async with ctx.sessionmaker() as session:
        elder = await session.get(Elder, elder_id)
        if elder is None:
            return  # deleted since
        checkin = await session.scalar(
            select(Checkin).where(Checkin.elder_id == elder_id, Checkin.local_date == day)
        )
        # Checked in (or paused) between the tick and now: the warning is stale.
        if action != EngineActionKind.all_good and (
            checkin is not None or elder.is_paused(utcnow())
        ):
            return
        marked_by = None
        if checkin is not None and checkin.user_id is not None:
            user = await session.get(User, checkin.user_id)
            marked_by = user.display_name if user else None
        built = build_push(action, elder, day, checkin, marked_by)
        if built is None:
            return
        audience, push = built
        if audience == "elder":
            tokens = await elder_tokens(session, elder_id)
        else:
            # Whoever marked them okay already knows.
            skip = checkin.user_id if checkin is not None else None
            tokens = await family_tokens(session, elder.family_id, exclude_user=skip)
        push = Push(**{**push.__dict__, "tokens": tokens})
        await deliver(session, push_sender(ctx.settings), push)
        await session.commit()
