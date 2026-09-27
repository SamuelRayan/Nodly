"""Dev-only helpers for testing on emulators and recording the demo (never runs outside ENV=dev).

    # Reminder in 2 minutes, due in 4, missed alert 2 minutes after that; today starts fresh
    python scripts/demo_state.py schedule --elder "Mary Rayan" --remind-in 2 --due-in 4 --grace 2

    # Close every open Help request and missed check-in alert (a clean dashboard)
    python scripts/demo_state.py close-alerts

--elder takes an elder id, display name or relation label (case-insensitive).
Times are the elder's own wall-clock times, like everywhere in Nodly (CLAUDE.md §5).
"""

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.clock import utcnow
from nodly.config import Settings, get_settings
from nodly.db import create_engine, create_sessionmaker
from nodly.help.service import LIVE, add_event
from nodly.models import (
    AlertResolution,
    Checkin,
    CheckinAlert,
    Elder,
    EngineAction,
    HelpEventKind,
    HelpRequest,
    HelpStatus,
)

CLOSED_NOTE = "Closed by scripts/demo_state.py"


class DemoStateError(Exception):
    pass


@dataclass(frozen=True)
class DemoSchedule:
    remind_at: time
    due_by: time
    grace_minutes: int


def schedule_from(now_local: datetime, remind_in: int, due_in: int, grace: int) -> DemoSchedule:
    """Wall-clock times `remind_in` and `due_in` minutes from now (rounded up to the minute).
    Both must fall on today's local date, because settings are times of day."""
    if not 0 <= remind_in <= due_in:
        raise DemoStateError("Need 0 <= --remind-in <= --due-in.")
    if not 0 <= grace <= 720:
        raise DemoStateError("--grace must be between 0 and 720 minutes.")
    start = now_local.replace(second=0, microsecond=0) + timedelta(minutes=1)
    remind = start + timedelta(minutes=remind_in)
    due = start + timedelta(minutes=due_in)
    if due.date() != now_local.date():
        raise DemoStateError("That would cross the elder's midnight; use smaller numbers.")
    return DemoSchedule(remind.time(), due.time(), grace)


async def find_elder(session: AsyncSession, needle: str) -> Elder:
    try:
        elder = await session.get(Elder, uuid.UUID(needle))
    except ValueError:
        elder = None
    if elder is not None:
        return elder
    matches = list(
        await session.scalars(
            select(Elder).where(
                or_(
                    func.lower(Elder.display_name) == needle.lower(),
                    func.lower(Elder.relation_label) == needle.lower(),
                )
            )
        )
    )
    if not matches:
        raise DemoStateError(f"No elder called {needle!r}.")
    if len(matches) > 1:
        listing = ", ".join(f"{e.display_name} ({e.relation_label}) {e.id}" for e in matches)
        raise DemoStateError(f"{needle!r} matches several elders; pass an id: {listing}")
    return matches[0]


async def set_schedule(
    session: AsyncSession, elder: Elder, schedule: DemoSchedule, *, reset_today: bool, now: datetime
) -> None:
    elder.checkin_remind_at = schedule.remind_at
    elder.checkin_due_by = schedule.due_by
    elder.checkin_grace_minutes = schedule.grace_minutes
    elder.paused_at = elder.paused_until = None
    if reset_today:
        today = now.astimezone(ZoneInfo(elder.timezone)).date()
        for model in (Checkin, EngineAction, CheckinAlert):
            await session.execute(
                delete(model).where(model.elder_id == elder.id, model.local_date == today)
            )
    await session.commit()


async def close_alerts(session: AsyncSession, now: datetime) -> tuple[int, int]:
    """Resolve live Help requests and open missed check-in alerts. Returns (help, missed)."""
    helps = list(await session.scalars(select(HelpRequest).where(HelpRequest.status.in_(LIVE))))
    for request in helps:
        request.status = HelpStatus.resolved
        request.closed_at = now
        request.resolution_note = CLOSED_NOTE
        add_event(session, request.id, HelpEventKind.resolved, now, data={"note": CLOSED_NOTE})
    alerts = list(
        await session.scalars(select(CheckinAlert).where(CheckinAlert.resolved_at.is_(None)))
    )
    for alert in alerts:
        alert.resolved_at = now
        alert.resolution = AlertResolution.marked_okay
    await session.commit()
    return len(helps), len(alerts)


async def main(args: argparse.Namespace, settings: Settings) -> str:
    if settings.env != "dev":
        raise DemoStateError(f"Refusing to run with ENV={settings.env}: dev only.")
    engine = create_engine(settings)
    try:
        async with create_sessionmaker(engine)() as session:
            now = utcnow()
            if args.command == "close-alerts":
                helps, missed = await close_alerts(session, now)
                return f"Closed {helps} Help request(s) and {missed} missed check-in alert(s)."
            elder = await find_elder(session, args.elder)
            tz = ZoneInfo(elder.timezone)
            schedule = schedule_from(now.astimezone(tz), args.remind_in, args.due_in, args.grace)
            await set_schedule(session, elder, schedule, reset_today=not args.keep_today, now=now)
            alert_at = (
                datetime.combine(now.astimezone(tz).date(), schedule.due_by, tz)
                + timedelta(minutes=schedule.grace_minutes)
            ).time()
            return (
                f"{elder.display_name} ({elder.timezone}): reminder {schedule.remind_at:%H:%M}, "
                f"due {schedule.due_by:%H:%M}, missed alert {alert_at:%H:%M} (their time)"
                + ("" if args.keep_today else "; today's check-in state was reset")
            )
    finally:
        await engine.dispose()


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    schedule = commands.add_parser("schedule", help="move an elder's check-in times close to now")
    schedule.add_argument("--elder", required=True)
    schedule.add_argument("--remind-in", type=int, default=2, help="minutes (default 2)")
    schedule.add_argument("--due-in", type=int, default=4, help="minutes (default 4)")
    schedule.add_argument("--grace", type=int, default=2, help="minutes after due (default 2)")
    schedule.add_argument(
        "--keep-today", action="store_true", help="keep today's check-in, reminders and alerts"
    )
    commands.add_parser("close-alerts", help="resolve open Help requests and missed alerts")
    return parser.parse_args(argv)


if __name__ == "__main__":
    try:
        print(asyncio.run(main(parse(), get_settings())))
    except DemoStateError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
