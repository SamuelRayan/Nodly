"""The check-in engine's pure decisions (CLAUDE.md §7), with frozen instants across timezones
and DST changes (§5: local days can be 23 or 25 hours long)."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from nodly.checkins.engine import (
    CheckinSettings,
    DayState,
    actions_due,
    days_to_check,
    local_instant,
    schedule_for,
    start_of_day,
)
from nodly.models import EngineActionKind as A


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def settings(
    timezone: str = "Asia/Kolkata",
    remind: time = time(9, 0),
    due: time = time(12, 0),
    grace: int = 60,
    activity_counts: bool = True,
) -> CheckinSettings:
    return CheckinSettings(timezone, remind, due, grace, activity_counts)


NOTHING = DayState(checked_in=False, active=False, done=frozenset())


# ---------------------------------------------------------------- local wall times


def test_plain_offset_zone() -> None:
    # Kolkata is UTC+05:30 all year.
    assert local_instant(date(2026, 9, 26), time(9, 0), ZoneInfo("Asia/Kolkata")) == utc(
        2026, 9, 26, 3, 30
    )


def test_spring_forward_gap_moves_to_the_next_valid_minute() -> None:
    # New York, 8 Mar 2026: 02:00 EST jumps to 03:00 EDT, so 02:30 doesn't exist.
    ny = ZoneInfo("America/New_York")
    assert local_instant(date(2026, 3, 8), time(2, 30), ny) == utc(2026, 3, 8, 7, 0)  # 03:00 EDT
    # Just outside the gap, nothing moves.
    assert local_instant(date(2026, 3, 8), time(1, 59), ny) == utc(2026, 3, 8, 6, 59)  # EST
    assert local_instant(date(2026, 3, 8), time(3, 0), ny) == utc(2026, 3, 8, 7, 0)  # EDT


def test_fall_back_overlap_uses_the_first_occurrence() -> None:
    # New York, 1 Nov 2026: 01:00-01:59 happens twice (EDT, then EST). fold=0 is the EDT one.
    ny = ZoneInfo("America/New_York")
    assert local_instant(date(2026, 11, 1), time(1, 30), ny) == utc(2026, 11, 1, 5, 30)


def test_half_hour_dst_shift() -> None:
    # Lord Howe Island, 4 Oct 2026: 02:00 (+10:30) jumps to 02:30 (+11:00).
    lord_howe = ZoneInfo("Australia/Lord_Howe")
    assert local_instant(date(2026, 10, 4), time(2, 10), lord_howe) == local_instant(
        date(2026, 10, 4), time(2, 30), lord_howe
    )
    assert local_instant(date(2026, 10, 4), time(2, 30), lord_howe) == utc(2026, 10, 3, 15, 30)


def test_a_zone_that_skips_midnight() -> None:
    # Havana, 8 Mar 2026: clocks go from 00:00 straight to 01:00, so the day starts at 01:00.
    havana = ZoneInfo("America/Havana")
    assert start_of_day(date(2026, 3, 8), havana) == local_instant(
        date(2026, 3, 8), time(1, 0), havana
    )
    assert start_of_day(date(2026, 3, 8), havana).astimezone(havana).hour == 1


def test_23_and_25_hour_days() -> None:
    ny = ZoneInfo("America/New_York")
    spring = start_of_day(date(2026, 3, 9), ny) - start_of_day(date(2026, 3, 8), ny)
    autumn = start_of_day(date(2026, 11, 2), ny) - start_of_day(date(2026, 11, 1), ny)
    assert spring == timedelta(hours=23)
    assert autumn == timedelta(hours=25)


# ---------------------------------------------------------------- the day's schedule


def test_schedule_in_local_time() -> None:
    schedule = schedule_for(date(2026, 9, 26), settings())
    assert schedule.remind == utc(2026, 9, 26, 3, 30)  # 09:00 IST
    assert schedule.due == utc(2026, 9, 26, 6, 30)  # 12:00 IST
    assert schedule.missed == utc(2026, 9, 26, 7, 30)  # + 60 min


def test_schedule_on_a_dst_day_keeps_wall_times() -> None:
    # On New York's 23-hour day, 09:00 and 12:00 are EDT (UTC-4).
    schedule = schedule_for(date(2026, 3, 8), settings("America/New_York"))
    assert schedule.remind == utc(2026, 3, 8, 13, 0)
    assert schedule.due == utc(2026, 3, 8, 16, 0)


def test_grace_is_elapsed_time_and_can_cross_midnight() -> None:
    schedule = schedule_for(date(2026, 9, 26), settings(due=time(23, 30), grace=90))
    assert schedule.missed.astimezone(ZoneInfo("Asia/Kolkata")) == datetime(
        2026, 9, 27, 1, 0, tzinfo=ZoneInfo("Asia/Kolkata")
    )


def test_grace_across_a_fall_back_is_real_minutes() -> None:
    # Due 00:30 EDT on 1 Nov + 120 min = 01:30 EST (the second 01:30), not the first one.
    schedule = schedule_for(
        date(2026, 11, 1), settings("America/New_York", due=time(0, 30), grace=120)
    )
    assert schedule.missed - schedule.due == timedelta(minutes=120)
    assert schedule.missed == utc(2026, 11, 1, 6, 30)


# ---------------------------------------------------------------- what to do when


DAY = date(2026, 9, 26)
S = schedule_for(DAY, settings())  # remind 03:30Z, due 06:30Z, missed 07:30Z


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (S.remind - timedelta(minutes=1), []),
        (S.remind, [A.remind]),
        (S.due - timedelta(minutes=1), [A.remind]),
        (S.due, [A.due_remind, A.family_late]),
        (S.missed - timedelta(minutes=1), [A.due_remind, A.family_late]),
        (S.missed, [A.missed]),
        (S.missed + timedelta(hours=5, minutes=59), [A.missed]),  # e.g. the worker was down
        (S.missed + timedelta(hours=6), []),  # stale: not worth waking anyone for
    ],
)
def test_stages(now: datetime, expected: list[A]) -> None:
    assert actions_due(now, S, NOTHING, settings()) == expected


def test_a_tap_ends_the_day() -> None:
    tapped = DayState(checked_in=True, active=True, done=frozenset())
    for now in (S.remind, S.due, S.missed):
        assert actions_due(now, S, tapped, settings()) == []


def test_done_actions_are_not_repeated() -> None:
    state = DayState(checked_in=False, active=False, done=frozenset({A.due_remind, A.family_late}))
    assert actions_due(S.due, S, state, settings()) == []
    assert actions_due(S.missed, S, state, settings()) == [A.missed]


def test_activity_spares_the_family_but_still_reminds_the_elder() -> None:
    active = DayState(checked_in=False, active=True, done=frozenset())
    assert actions_due(S.remind, S, active, settings()) == [A.remind]
    assert actions_due(S.due, S, active, settings()) == []
    assert actions_due(S.missed, S, active, settings()) == []


def test_activity_doesnt_count_when_the_family_says_so() -> None:
    active = DayState(checked_in=False, active=True, done=frozenset())
    strict = settings(activity_counts=False)
    assert actions_due(S.due, S, active, strict) == [A.due_remind, A.family_late]
    assert actions_due(S.missed, S, active, strict) == [A.missed]


def test_zero_grace_goes_straight_to_the_missed_alert() -> None:
    no_grace = settings(grace=0)
    schedule = schedule_for(DAY, no_grace)
    assert actions_due(schedule.due, schedule, NOTHING, no_grace) == [A.missed]


def test_remind_at_equal_to_due_by_skips_the_early_reminder() -> None:
    same = settings(remind=time(12, 0))
    schedule = schedule_for(DAY, same)
    assert actions_due(schedule.due, schedule, NOTHING, same) == [A.due_remind, A.family_late]


def test_days_to_check_are_local_yesterday_and_today() -> None:
    # 20:00Z on 25 Sep is 01:30 on 26 Sep in Kolkata.
    assert days_to_check(utc(2026, 9, 25, 20, 0), settings()) == [
        date(2026, 9, 25),
        date(2026, 9, 26),
    ]
    # ...and still 25 Sep in Los Angeles (13:00).
    assert days_to_check(utc(2026, 9, 25, 20, 0), settings("America/Los_Angeles")) == [
        date(2026, 9, 24),
        date(2026, 9, 25),
    ]


def test_yesterdays_late_missed_alert_fires_after_midnight() -> None:
    late = settings(due=time(23, 30), grace=90)  # missed at 01:00 the next day
    yesterday = schedule_for(date(2026, 9, 26), late)
    now = yesterday.missed + timedelta(minutes=1)
    assert date(2026, 9, 26) in days_to_check(now, late)
    assert actions_due(now, yesterday, NOTHING, late) == [A.missed]
