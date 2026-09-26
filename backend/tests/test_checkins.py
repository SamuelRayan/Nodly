"""Check-ins against the database (CLAUDE.md §7): the tick, notifications, taps, "mark okay",
missed check-in alerts, and what the family and the elder's phone see.

Elder "Mom" lives in Asia/Kolkata (UTC+05:30). On 26 Sep 2026 with the default settings:
reminder 09:00 = 03:30Z, due 12:00 = 06:30Z, missed alert 13:00 = 07:30Z.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
import time_machine
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import nodly.jobs.handlers  # registers checkins.notify
import nodly.push
from nodly.checkins.service import record_checkin, run_tick
from nodly.config import Settings
from nodly.db import create_sessionmaker
from nodly.models import (
    Checkin,
    CheckinAlert,
    CheckinSource,
    Elder,
    ElderDevice,
    EngineAction,
    Family,
    FamilyRole,
    Job,
    PushToken,
    User,
)
from nodly.push import RecordingPushSender
from nodly.security.credentials import generate_device_token, hash_device_token
from nodly.worker import Worker
from tests.conftest import app_client, make_settings
from tests.fake_supabase import FakeSupabase, SupabaseUser
from tests.support import make_elder, make_family, make_member, make_user

DAY = date(2026, 9, 26)
BEFORE = datetime(2026, 9, 26, 3, 0, tzinfo=UTC)  # 08:30 IST
REMIND = datetime(2026, 9, 26, 3, 30, tzinfo=UTC)
DUE = datetime(2026, 9, 26, 6, 30, tzinfo=UTC)
MISSED = datetime(2026, 9, 26, 7, 30, tzinfo=UTC)
PAIRED = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
WORKER_NOW = datetime(2026, 10, 3, tzinfo=UTC)


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> RecordingPushSender:
    fresh = RecordingPushSender()
    monkeypatch.setattr(nodly.push, "_recorder", fresh)
    return fresh


@pytest.fixture
def record_settings(test_database_url: str) -> Settings:
    return make_settings(test_database_url, push_provider="record")


@dataclass
class Home:
    family: Family
    organizer: User
    member: User
    elder: Elder
    device: ElderDevice
    device_token: str


async def make_home(session: AsyncSession, *, paired_at: datetime = PAIRED) -> Home:
    family = await make_family(session, name="The Rayans")
    organizer = await make_user(session, display_name="Priya Rayan")
    member = await make_user(session, display_name="Arjun")
    await make_member(session, family, organizer, FamilyRole.organizer)
    await make_member(session, family, member)
    elder = await make_elder(session, family, relation_label="Amma", is_primary=True)
    token = generate_device_token()
    device = ElderDevice(
        elder_id=elder.id,
        token_hash=hash_device_token(token),
        platform="android",
        created_at=paired_at,
        last_seen_at=paired_at,
    )
    session.add(device)
    await session.flush()
    for owner in ({"user_id": organizer.id}, {"user_id": member.id}):
        session.add(
            PushToken(provider="expo", token=f"fam-{owner['user_id']}", platform="android", **owner)
        )
    session.add(
        PushToken(
            provider="expo", token="elder-phone", platform="android", elder_device_id=device.id
        )
    )
    await session.commit()
    return Home(family, organizer, member, elder, device, token)


async def actions(session: AsyncSession, elder: Elder) -> list[str]:
    rows = await session.scalars(
        select(EngineAction.action)
        .where(EngineAction.elder_id == elder.id)
        .order_by(EngineAction.id)
    )
    return list(rows)


async def run_jobs(engine: AsyncEngine, settings: Settings) -> int:
    """Run every queued job. The worker's clock is a fixed instant after the test day, so jobs
    queued at frozen times are due whatever the real date is."""
    worker = Worker(
        settings, create_sessionmaker(engine), worker_id="test", clock=lambda: WORKER_NOW
    )
    ran = 0
    while count := await worker.run_once():
        ran += count
    return ran


# ---------------------------------------------------------------- the tick


async def test_tick_follows_the_day_and_never_repeats(session: AsyncSession) -> None:
    home = await make_home(session)
    assert await run_tick(session, BEFORE) == 0
    assert await run_tick(session, REMIND) == 1
    assert await run_tick(session, REMIND + timedelta(minutes=1)) == 0  # re-running is safe
    assert await run_tick(session, DUE) == 2
    assert await run_tick(session, MISSED) == 1
    assert await run_tick(session, MISSED + timedelta(minutes=5)) == 0
    assert await actions(session, home.elder) == ["remind", "due_remind", "family_late", "missed"]
    alert = await session.scalar(select(CheckinAlert).where(CheckinAlert.elder_id == home.elder.id))
    assert alert is not None and alert.local_date == DAY and alert.raised_at == MISSED
    jobs = await session.scalar(
        select(func.count()).select_from(Job).where(Job.type == "checkins.notify")
    )
    assert jobs == 4


async def test_a_tap_stops_the_engine(session: AsyncSession) -> None:
    home = await make_home(session)
    await run_tick(session, REMIND)
    await record_checkin(session, home.elder, REMIND + timedelta(minutes=10), CheckinSource.app)
    await session.commit()
    assert await run_tick(session, DUE) == 0
    assert await run_tick(session, MISSED) == 0
    assert await actions(session, home.elder) == ["remind"]  # no "all good": nobody was worried


async def test_paused_elders_and_elders_without_phones_are_left_alone(
    session: AsyncSession,
) -> None:
    home = await make_home(session)
    home.elder.paused_at = BEFORE
    await session.commit()
    assert await run_tick(session, MISSED) == 0

    home.elder.paused_at = None
    home.device.revoked_at = BEFORE
    await session.commit()
    assert await run_tick(session, MISSED) == 0


async def test_a_phone_paired_after_the_due_time_starts_tomorrow(session: AsyncSession) -> None:
    home = await make_home(session, paired_at=DUE + timedelta(minutes=5))
    assert await run_tick(session, MISSED) == 0
    tomorrow_remind = REMIND + timedelta(days=1)
    assert await run_tick(session, tomorrow_remind) == 1
    assert await actions(session, home.elder) == ["remind"]


async def test_using_nodly_spares_the_family(session: AsyncSession) -> None:
    home = await make_home(session)
    home.device.last_seen_at = REMIND + timedelta(minutes=30)  # opened the app today
    await session.commit()
    await run_tick(session, REMIND)
    await run_tick(session, DUE)
    await run_tick(session, MISSED)
    assert await actions(session, home.elder) == ["remind"]

    # ...unless the family asked for a tap, activity or not.
    home.elder.checkin_activity_counts_as_ok = False
    await session.commit()
    assert await run_tick(session, MISSED) == 1
    assert await actions(session, home.elder) == ["remind", "missed"]


# ---------------------------------------------------------------- notifications


async def test_notifications_go_to_the_right_people(
    session: AsyncSession,
    clean_db: AsyncEngine,
    record_settings: Settings,
    recorder: RecordingPushSender,
) -> None:
    home = await make_home(session)
    await run_tick(session, REMIND)
    await run_tick(session, DUE)
    await run_tick(session, MISSED)
    assert await run_jobs(clean_db, record_settings) == 4

    by_type = {push.data["type"]: push for push in recorder.sent}
    reminders = [push for push in recorder.sent if push.data["type"] == "checkin_reminder"]
    assert len(reminders) == 2
    assert all(push.tokens == ["elder-phone"] for push in reminders)
    assert all(push.category_id == "checkin_reminder" for push in reminders)
    family = {f"fam-{home.organizer.id}", f"fam-{home.member.id}"}
    assert set(by_type["checkin_late"].tokens) == family
    assert by_type["checkin_late"].title == "Amma hasn't checked in yet"
    assert "12:00 PM" in by_type["checkin_late"].body
    missed = by_type["checkin_missed"]
    assert set(missed.tokens) == family and missed.priority == "high"
    assert all(push.channel_id == "checkin" for push in recorder.sent)


async def test_a_late_tap_resolves_the_alert_and_says_all_good(
    session: AsyncSession,
    clean_db: AsyncEngine,
    record_settings: Settings,
    recorder: RecordingPushSender,
) -> None:
    home = await make_home(session)
    await run_tick(session, DUE)
    await run_tick(session, MISSED)
    await run_jobs(clean_db, record_settings)
    recorder.sent.clear()

    tapped = MISSED + timedelta(minutes=20)
    _, changed = await record_checkin(session, home.elder, tapped, CheckinSource.notification)
    await session.commit()
    assert changed
    alert = await session.scalar(select(CheckinAlert).where(CheckinAlert.elder_id == home.elder.id))
    assert alert is not None
    await session.refresh(alert)
    assert (alert.resolved_at, alert.resolution) == (tapped, "checked_in")
    assert (await actions(session, home.elder))[-1] == "all_good"

    await run_jobs(clean_db, record_settings)
    [good] = recorder.sent
    assert good.title == "All good: Amma checked in"
    assert good.body == "At 1:20 PM, Amma's time."


async def test_a_notification_that_went_stale_is_dropped(
    session: AsyncSession,
    clean_db: AsyncEngine,
    record_settings: Settings,
    recorder: RecordingPushSender,
) -> None:
    home = await make_home(session)
    await run_tick(session, DUE)  # queues "late" for the family...
    await record_checkin(session, home.elder, DUE + timedelta(seconds=30), CheckinSource.app)
    await session.commit()  # ...but she tapped before the worker got to it
    await run_jobs(clean_db, record_settings)
    assert [push.data["type"] for push in recorder.sent] == ["checkin_ok"]


async def test_dead_tokens_are_disabled(session: AsyncSession) -> None:
    await make_home(session)

    class DeadSender:
        async def send(self, push: nodly.push.Push) -> list[nodly.push.Ticket]:
            return [nodly.push.Ticket(token, False, "DeviceNotRegistered") for token in push.tokens]

    push = nodly.push.Push(tokens=["elder-phone"], title="t", body="b", channel_id="checkin")
    await nodly.push.deliver(session, DeadSender(), push)
    await session.commit()
    token = await session.scalar(select(PushToken).where(PushToken.token == "elder-phone"))
    assert token is not None and token.disabled_at is not None


async def test_expo_sender_request_shape() -> None:
    seen: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        messages = __import__("json").loads(request.content)
        tickets = [{"status": "ok", "id": "x"}] * (len(messages) - 1)
        tickets.append({"status": "error", "details": {"error": "DeviceNotRegistered"}})
        return httpx.Response(200, json={"data": tickets})

    settings = make_settings("postgresql+asyncpg://unused/nodly_test")
    tokens = [f"ExponentPushToken[{n}]" for n in range(150)]
    push = nodly.push.Push(
        tokens=tokens,
        title="Hi",
        body="There",
        channel_id="checkin",
        category_id="checkin_reminder",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tickets = await nodly.push.ExpoPushSender(settings, client).send(push)
    assert len(seen) == 2  # 100 + 50
    first = __import__("json").loads(seen[0].content)[0]
    assert first == {
        "to": tokens[0],
        "title": "Hi",
        "body": "There",
        "data": {},
        "sound": "default",
        "priority": "high",
        "channelId": "checkin",
        "categoryId": "checkin_reminder",
    }
    assert [ticket.error for ticket in tickets if not ticket.ok] == ["DeviceNotRegistered"] * 2


# ---------------------------------------------------------------- the API


@pytest.fixture
async def api(
    record_settings: Settings, clean_db: AsyncEngine, fake_supabase: FakeSupabase
) -> AsyncIterator[httpx.AsyncClient]:
    async with app_client(record_settings, fake_supabase) as client:
        yield client


async def signed_in_home(
    session: AsyncSession, fake_supabase: FakeSupabase
) -> tuple[Home, SupabaseUser, SupabaseUser]:
    home = await make_home(session)
    priya = SupabaseUser(fake_supabase, "priya@example.com")
    arjun = SupabaseUser(fake_supabase, "arjun@example.com")
    home.organizer.auth_user_id, home.organizer.email = priya.auth_id, priya.email
    home.member.auth_user_id, home.member.email = arjun.auth_id, arjun.email
    for user in (home.organizer, home.member):
        user.timezone, user.country_code = "Asia/Kolkata", "IN"
        user.age_confirmed_at = user.onboarded_at = PAIRED
    await session.commit()
    return home, priya, arjun


def device_headers(home: Home) -> dict[str, str]:
    return {"Authorization": f"Bearer {home.device_token}"}


async def status(api: httpx.AsyncClient, home: Home, person: SupabaseUser) -> dict[str, Any]:
    response = await api.get(f"/v1/elders/{home.elder.id}/checkins/today", headers=person.headers)
    assert response.status_code == 200, response.text
    return response.json()


async def test_family_status_through_the_day(
    api: httpx.AsyncClient, session: AsyncSession, fake_supabase: FakeSupabase
) -> None:
    home, priya, _ = await signed_in_home(session, fake_supabase)
    with time_machine.travel(BEFORE, tick=False):
        body = await status(api, home, priya)
        assert body["status"] == "waiting"
        assert body["local_date"] == "2026-09-26"
        assert body["timezone"] == "Asia/Kolkata"
        assert body["schedule"] == {
            "remind_at": "2026-09-26T03:30:00Z",
            "due_at": "2026-09-26T06:30:00Z",
            "alert_at": "2026-09-26T07:30:00Z",
        }
        assert [day["state"] for day in body["week"]] == ["none"] * 7
        assert body["week"][-1]["local_date"] == "2026-09-26"
    await run_tick(session, REMIND)
    await run_tick(session, DUE)
    with time_machine.travel(DUE + timedelta(minutes=1), tick=False):
        body = await status(api, home, priya)
        assert body["status"] == "late"
        assert [r["kind"] for r in body["reminders"]] == ["remind", "due_remind"]
    await run_tick(session, MISSED)
    with time_machine.travel(MISSED + timedelta(minutes=1), tick=False):
        body = await status(api, home, priya)
        assert body["status"] == "missed"
        assert body["alert"]["raised_at"] == "2026-09-26T07:30:00Z"
        assert body["alert"]["acked_by_name"] is None


async def test_im_on_it_then_mark_okay(
    api: httpx.AsyncClient,
    session: AsyncSession,
    clean_db: AsyncEngine,
    fake_supabase: FakeSupabase,
    record_settings: Settings,
    recorder: RecordingPushSender,
) -> None:
    home, priya, arjun = await signed_in_home(session, fake_supabase)
    base = f"/v1/elders/{home.elder.id}/checkins"
    with time_machine.travel(BEFORE, tick=False):
        response = await api.post(f"{base}/alert/ack", headers=arjun.headers)
        assert (response.status_code, response.json()["code"]) == (409, "no_open_alert")

    await run_tick(session, DUE)
    await run_tick(session, MISSED)
    await run_jobs(clean_db, record_settings)
    recorder.sent.clear()
    with time_machine.travel(MISSED + timedelta(minutes=2), tick=False):
        acked = (await api.post(f"{base}/alert/ack", headers=arjun.headers)).json()
        assert acked["alert"]["acked_by_name"] == "Arjun"
        again = (await api.post(f"{base}/alert/ack", headers=priya.headers)).json()
        assert again["alert"]["acked_by_name"] == "Arjun"  # the first one stays

    with time_machine.travel(MISSED + timedelta(minutes=10), tick=False):
        marked = (await api.post(f"{base}/mark-okay", headers=arjun.headers)).json()
    assert marked["status"] == "okay"
    assert marked["checkin"]["source"] == "family"
    assert marked["checkin"]["marked_by_name"] == "Arjun"
    assert marked["alert"]["resolved_at"] is not None

    await run_jobs(clean_db, record_settings)
    [told] = recorder.sent
    assert told.title == "Arjun marked Amma okay"
    assert told.tokens == [f"fam-{home.organizer.id}"]  # not back to Arjun

    # Her own tap later that day replaces "marked okay", without another notification.
    with time_machine.travel(MISSED + timedelta(minutes=40), tick=False):
        today = (await api.post("/v1/device/checkin", headers=device_headers(home), json={})).json()
    assert today["checked_in_at"] == "2026-09-26T08:10:00Z"
    assert today["marked_okay_by_family"] is False
    assert await run_jobs(clean_db, record_settings) == 0


async def test_the_elders_phone(
    api: httpx.AsyncClient, session: AsyncSession, fake_supabase: FakeSupabase
) -> None:
    home, priya, _ = await signed_in_home(session, fake_supabase)
    headers = device_headers(home)
    with time_machine.travel(BEFORE, tick=False):
        today = (await api.get("/v1/device/today", headers=headers)).json()
        assert today["checked_in_at"] is None
        assert today["family_names"] == ["Priya", "Arjun"]  # organizer first, first names
        assert today["schedule"]["alert_at"] == "2026-09-26T07:30:00Z"
        assert today["family_alerted_at"] is None

        tapped = (await api.post("/v1/device/checkin", headers=headers, json={})).json()
        assert tapped["checked_in_at"] == "2026-09-26T03:00:00Z"
    with time_machine.travel(BEFORE + timedelta(hours=1), tick=False):
        again = (await api.post("/v1/device/checkin", headers=headers, json={})).json()
        assert again["checked_in_at"] == "2026-09-26T03:00:00Z"  # once a day

    count = await session.scalar(select(func.count()).select_from(Checkin))
    assert count == 1
    with time_machine.travel(BEFORE + timedelta(hours=1), tick=False):
        body = await status(api, home, priya)
    assert body["status"] == "okay"
    assert body["checkin"]["source"] == "app"
    assert body["week"][-1]["state"] == "okay"


async def test_the_day_is_the_elders_local_day(
    api: httpx.AsyncClient, session: AsyncSession, fake_supabase: FakeSupabase
) -> None:
    home, _, _ = await signed_in_home(session, fake_supabase)
    # 20:00Z on 25 Sep is already 26 Sep, 01:30, in Kolkata.
    with time_machine.travel(datetime(2026, 9, 25, 20, 0, tzinfo=UTC), tick=False):
        today = (await api.post("/v1/device/checkin", headers=device_headers(home), json={})).json()
    assert today["local_date"] == "2026-09-26"


async def test_status_for_an_elder_without_a_phone_or_paused(
    api: httpx.AsyncClient, session: AsyncSession, fake_supabase: FakeSupabase
) -> None:
    home, priya, _ = await signed_in_home(session, fake_supabase)
    home.elder.paused_at = BEFORE - timedelta(days=1)
    await session.commit()
    with time_machine.travel(BEFORE, tick=False):
        assert (await status(api, home, priya))["status"] == "paused"
    home.device.revoked_at = BEFORE - timedelta(hours=1)
    await session.commit()
    with time_machine.travel(BEFORE, tick=False):
        assert (await status(api, home, priya))["status"] == "no_phone"


async def test_the_week_shows_okay_and_missed_days(
    api: httpx.AsyncClient, session: AsyncSession, fake_supabase: FakeSupabase
) -> None:
    home, priya, _ = await signed_in_home(session, fake_supabase)
    three_days_ago = MISSED - timedelta(days=3)
    await run_tick(session, three_days_ago)  # missed that day
    await record_checkin(session, home.elder, REMIND - timedelta(days=1), CheckinSource.app)
    await session.commit()
    with time_machine.travel(BEFORE, tick=False):
        body = await status(api, home, priya)
    states = {day["local_date"]: day["state"] for day in body["week"]}
    assert states["2026-09-23"] == "missed"
    assert states["2026-09-25"] == "okay"
    assert states["2026-09-24"] == "none"
    assert body["last_checkin"]["local_date"] == "2026-09-25"
