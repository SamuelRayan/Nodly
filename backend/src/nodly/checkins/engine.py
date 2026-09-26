"""The check-in engine's decisions (CLAUDE.md §7), as pure functions of time and state.

Everything here is deterministic and free of I/O, so it's tested with frozen instants across
timezones and DST changes (tests/test_checkin_engine.py). The tick (nodly.checkins.service)
feeds it state from the database and records what it decides.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from nodly.models import EngineActionKind

# How long after its moment a missed check-in alert may still go out, e.g. after the worker was
# down. Later than that it's noise (possibly about yesterday, after today's check-in). Earlier
# stages need no such limit: each ends where the next begins.
MISSED_ALERT_WINDOW = timedelta(hours=6)


def local_instant(day: date, at: time, tz: ZoneInfo) -> datetime:
    """The UTC instant of wall-clock `at` on `day` in `tz` (CLAUDE.md §5).

    A time that doesn't exist (clocks spring forward over it) moves to the next valid minute;
    an ambiguous one (clocks fall back through it) is its first occurrence (fold=0).
    """
    wall = datetime.combine(day, at.replace(tzinfo=None))
    while True:
        candidate = wall.replace(tzinfo=tz, fold=0)
        # A skipped wall time doesn't survive the round trip through UTC.
        if candidate.astimezone(UTC).astimezone(tz).replace(tzinfo=None) == wall:
            return candidate.astimezone(UTC)
        wall += timedelta(minutes=1)


def start_of_day(day: date, tz: ZoneInfo) -> datetime:
    """When `day` begins in `tz`, as a UTC instant (a few zones skip midnight itself)."""
    return local_instant(day, time(0, 0), tz)


def local_today(now: datetime, tz: ZoneInfo) -> date:
    return now.astimezone(tz).date()


@dataclass(frozen=True)
class CheckinSettings:
    timezone: str
    remind_at: time
    due_by: time
    grace_minutes: int
    activity_counts_as_ok: bool


@dataclass(frozen=True)
class Schedule:
    """One local day's moments, as UTC instants."""

    day: date
    remind: datetime  # §7.1
    due: datetime  # §7.2
    missed: datetime  # §7.3: due + grace (may fall on the next local day)


def schedule_for(day: date, settings: CheckinSettings) -> Schedule:
    tz = ZoneInfo(settings.timezone)
    due = local_instant(day, settings.due_by, tz)
    return Schedule(
        day=day,
        remind=local_instant(day, settings.remind_at, tz),
        due=due,
        # Grace is elapsed time ("60 minutes after due"), so it's added to the instant.
        missed=due + timedelta(minutes=settings.grace_minutes),
    )


@dataclass(frozen=True)
class DayState:
    checked_in: bool
    # Used Nodly since the day began (the ACTIVITY signal, §7).
    active: bool
    done: frozenset[EngineActionKind]


def actions_due(
    now: datetime, schedule: Schedule, state: DayState, settings: CheckinSettings
) -> list[EngineActionKind]:
    """What the engine should do for `schedule.day` at `now`, leaving out what's done.

    A tap ends everything for the day. Activity (when it counts as okay) means the family
    isn't told, but the elder is still reminded to tap.
    """
    if state.checked_in:
        return []
    wanted: list[EngineActionKind] = []
    if schedule.remind <= now < schedule.due:
        wanted.append(EngineActionKind.remind)
    excused = settings.activity_counts_as_ok and state.active
    if not excused:
        if schedule.due <= now < schedule.missed:
            wanted += [EngineActionKind.due_remind, EngineActionKind.family_late]
        if schedule.missed <= now < schedule.missed + MISSED_ALERT_WINDOW:
            wanted.append(EngineActionKind.missed)
    return [action for action in wanted if action not in state.done]


def days_to_check(now: datetime, settings: CheckinSettings) -> list[date]:
    """Yesterday and today in the elder's timezone: with a long grace, yesterday's missed
    check-in alert can come due after midnight."""
    today = local_today(now, ZoneInfo(settings.timezone))
    return [today - timedelta(days=1), today]
