"""Help and the escalation ladder (CLAUDE.md §8): open, repeat until "I'm on it", stop after
15 minutes, SMS/voice steps recorded as skipped (Phase 15), cancel, resolve, test alerts."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import time_machine
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import nodly.jobs.handlers  # registers help.notify
import nodly.push
from nodly.config import Settings
from nodly.db import create_sessionmaker
from nodly.help.service import acknowledge, close, open_request, open_test, run_help_tick
from nodly.models import HelpEvent, HelpKind, HelpRequest
from nodly.push import RecordingPushSender
from nodly.worker import Worker
from tests.conftest import app_client, make_settings
from tests.fake_supabase import FakeSupabase
from tests.test_checkins import device_headers, make_home, signed_in_home

T0 = datetime(2026, 9, 26, 13, 10, tzinfo=UTC)  # 18:40 in Kolkata
WORKER_NOW = datetime(2026, 10, 3, tzinfo=UTC)


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> RecordingPushSender:
    fresh = RecordingPushSender()
    monkeypatch.setattr(nodly.push, "_recorder", fresh)
    return fresh


@pytest.fixture
def settings(test_database_url: str) -> Settings:
    return make_settings(test_database_url, push_provider="record")


async def run_jobs(engine: AsyncEngine, settings: Settings) -> int:
    worker = Worker(settings, create_sessionmaker(engine), worker_id="t", clock=lambda: WORKER_NOW)
    ran = 0
    while count := await worker.run_once():
        ran += count
    return ran


async def events(session: AsyncSession, request: HelpRequest) -> list[str]:
    rows = await session.scalars(
        select(HelpEvent.kind).where(HelpEvent.request_id == request.id).order_by(HelpEvent.id)
    )
    return list(rows)


# ---------------------------------------------------------------- the ladder


async def test_pressing_twice_keeps_one_request(session: AsyncSession) -> None:
    home = await make_home(session)
    first, created = await open_request(session, home.elder, T0, HelpKind.help)
    again, created_again = await open_request(
        session, home.elder, T0 + timedelta(seconds=5), HelpKind.help
    )
    assert created and not created_again
    assert again.id == first.id


async def test_repeats_every_minute_until_someone_is_on_it(
    session: AsyncSession, settings: Settings
) -> None:
    home = await make_home(session)
    request, _ = await open_request(session, home.elder, T0, HelpKind.help)
    assert await run_help_tick(session, T0 + timedelta(seconds=30), settings) == 0
    assert await run_help_tick(session, T0 + timedelta(seconds=60), settings) == 1
    assert await run_help_tick(session, T0 + timedelta(seconds=61), settings) == 0
    assert await run_help_tick(session, T0 + timedelta(seconds=121), settings) == 1
    assert "sms_skipped" in await events(session, request)
    await acknowledge(session, request, home.member.id, T0 + timedelta(seconds=150))
    assert await run_help_tick(session, T0 + timedelta(minutes=4), settings) == 0
    await session.refresh(request)
    assert (request.status, request.acked_by_user_id) == ("acknowledged", home.member.id)


async def test_repeats_stop_after_fifteen_minutes(
    session: AsyncSession, settings: Settings
) -> None:
    home = await make_home(session)
    request, _ = await open_request(session, home.elder, T0, HelpKind.help)
    rounds = 0
    minute = 1
    while minute <= 20:
        rounds += await run_help_tick(session, T0 + timedelta(minutes=minute), settings)
        minute += 1
    assert rounds == 14  # minutes 1..14; the 15th is out of the window
    kinds = await events(session, request)
    assert kinds.count("sms_skipped") == 1 and kinds.count("voice_skipped") == 1


async def test_please_call_me_is_one_quiet_push(
    session: AsyncSession, clean_db: AsyncEngine, settings: Settings, recorder: RecordingPushSender
) -> None:
    home = await make_home(session)
    await open_request(session, home.elder, T0, HelpKind.call_me)
    assert await run_help_tick(session, T0 + timedelta(minutes=5), settings) == 0
    await run_jobs(clean_db, settings)
    [push] = recorder.sent
    assert push.title == "Amma asked you to call"
    assert push.channel_id == "general" and push.category_id is None


async def test_alerts_reach_every_family_member_and_record_delivery(
    session: AsyncSession, clean_db: AsyncEngine, settings: Settings, recorder: RecordingPushSender
) -> None:
    home = await make_home(session)
    request, _ = await open_request(session, home.elder, T0, HelpKind.help)
    await run_jobs(clean_db, settings)
    [alert] = recorder.sent
    assert alert.title == "Amma pressed Help"
    assert alert.channel_id == "help_alerts" and alert.priority == "high"
    assert alert.category_id == "help_alert"
    assert set(alert.tokens) == {f"fam-{home.organizer.id}", f"fam-{home.member.id}"}
    assert alert.data["request_id"] == str(request.id)
    pushed = await session.scalar(
        select(HelpEvent).where(HelpEvent.request_id == request.id, HelpEvent.kind == "pushed")
    )
    assert pushed is not None
    assert set(pushed.data["delivered"]) == {str(home.organizer.id), str(home.member.id)}


async def test_im_on_it_tells_the_others_and_quiets_the_repeats(
    session: AsyncSession, clean_db: AsyncEngine, settings: Settings, recorder: RecordingPushSender
) -> None:
    home = await make_home(session)
    request, _ = await open_request(session, home.elder, T0, HelpKind.help)
    await run_jobs(clean_db, settings)  # the first alert goes out
    await run_help_tick(session, T0 + timedelta(seconds=60), settings)  # a repeat is queued...
    assert await acknowledge(session, request, home.member.id, T0 + timedelta(seconds=61))
    assert not await acknowledge(session, request, home.organizer.id, T0 + timedelta(seconds=62))
    await run_jobs(clean_db, settings)
    # ...but loses the race: only the first alert and "Arjun is on it" go out.
    titles = [push.title for push in recorder.sent]
    assert titles == ["Amma pressed Help", "Arjun is on it"]
    assert recorder.sent[1].tokens == [f"fam-{home.organizer.id}"]


async def test_im_okay_now_closes_it_for_everyone(
    session: AsyncSession, clean_db: AsyncEngine, settings: Settings, recorder: RecordingPushSender
) -> None:
    home = await make_home(session)
    request, _ = await open_request(session, home.elder, T0, HelpKind.help)
    assert await close(session, request, T0 + timedelta(seconds=20), by_elder=True)
    assert not await close(session, request, T0 + timedelta(seconds=21), by_elder=True)
    assert await run_help_tick(session, T0 + timedelta(minutes=2), settings) == 0
    await run_jobs(clean_db, settings)
    assert [push.title for push in recorder.sent] == ["Amma is okay now"]  # the alert was stale
    # A new press after that is a new request.
    again, created = await open_request(
        session, home.elder, T0 + timedelta(minutes=3), HelpKind.help
    )
    assert created and again.id != request.id


async def test_test_alerts_are_labelled_limited_and_never_block_real_help(
    session: AsyncSession, clean_db: AsyncEngine, settings: Settings, recorder: RecordingPushSender
) -> None:
    home = await make_home(session)
    for n in range(3):
        assert await open_test(
            session, home.elder, home.organizer.id, T0 + timedelta(minutes=n), settings
        )
    assert (
        await open_test(session, home.elder, home.organizer.id, T0 + timedelta(minutes=5), settings)
        is None
    )
    real, created = await open_request(
        session, home.elder, T0 + timedelta(minutes=6), HelpKind.help
    )
    assert created and not real.is_test
    # Tests never repeat.
    assert (
        await run_help_tick(session, T0 + timedelta(minutes=8), settings) == 1
    )  # only the real one
    await run_jobs(clean_db, settings)
    titles = sorted({push.title for push in recorder.sent})
    assert titles == ["Amma pressed Help", "Test: Amma pressed Help"]
    # The next day, tests are allowed again.
    assert await open_test(
        session, home.elder, home.organizer.id, T0 + timedelta(days=1, minutes=1), settings
    )


# ---------------------------------------------------------------- the API


@pytest.fixture
async def api(
    settings: Settings, clean_db: AsyncEngine, fake_supabase: FakeSupabase
) -> AsyncIterator[httpx.AsyncClient]:
    async with app_client(settings, fake_supabase) as client:
        yield client


async def ok(response: httpx.Response, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json()


async def test_help_round_trip(
    api: httpx.AsyncClient,
    session: AsyncSession,
    clean_db: AsyncEngine,
    settings: Settings,
    fake_supabase: FakeSupabase,
    recorder: RecordingPushSender,
) -> None:
    home, priya, arjun = await signed_in_home(session, fake_supabase)
    phone = device_headers(home)
    with time_machine.travel(T0, tick=False):
        assert await ok(await api.get("/v1/device/help", headers=phone)) is None
        sent = await ok(
            await api.post(
                "/v1/device/help",
                headers=phone,
                json={
                    "battery_percent": 41,
                    "network": "wifi",
                    "latitude": 13.08,
                    "longitude": 80.27,
                },
            )
        )
    assert sent["status"] == "open" and sent["kind"] == "help"
    assert sent["battery_percent"] == 41 and sent["latitude"] == 13.08
    assert [r["delivered"] for r in sent["recipients"]] == [False, False]

    await run_jobs(clean_db, settings)
    with time_machine.travel(T0 + timedelta(seconds=10), tick=False):
        seen = await ok(await api.get("/v1/device/help", headers=phone))
        assert all(r["delivered"] for r in seen["recipients"])
        [live] = await ok(
            await api.get(f"/v1/families/{home.family.id}/help", headers=priya.headers)
        )
        assert live["id"] == sent["id"] and live["elder_name"] == "Amma"
        acked = await ok(await api.post(f"/v1/help/{sent['id']}/ack", headers=arjun.headers))
        assert acked["status"] == "acknowledged" and acked["acked_by_name"] == "Arjun"
        on_phone = await ok(await api.get("/v1/device/help", headers=phone))
        assert on_phone["acked_by_name"] == "Arjun"

    with time_machine.travel(T0 + timedelta(minutes=5), tick=False):
        done = await ok(
            await api.post(
                f"/v1/help/{sent['id']}/resolve",
                headers=priya.headers,
                json={"note": "Fell, is fine"},
            )
        )
    assert done["status"] == "resolved" and done["closed_by_name"] == "Priya Rayan"
    assert done["resolution_note"] == "Fell, is fine"
    assert [event["kind"] for event in done["timeline"]] == [
        "created",
        "pushed",
        "acknowledged",
        "resolved",
    ]
    response = await api.post("/v1/device/help/cancel", headers=phone)
    assert (response.status_code, response.json()["code"]) == (409, "no_live_help")


async def test_cancel_from_the_phone(
    api: httpx.AsyncClient, session: AsyncSession, fake_supabase: FakeSupabase
) -> None:
    home, _, _ = await signed_in_home(session, fake_supabase)
    phone = device_headers(home)
    with time_machine.travel(T0, tick=False):
        await ok(await api.post("/v1/device/help", headers=phone, json={"kind": "help"}))
        cancelled = await ok(await api.post("/v1/device/help/cancel", headers=phone))
    assert cancelled["status"] == "cancelled"


async def test_test_alert_limit_over_the_api(
    api: httpx.AsyncClient, session: AsyncSession, fake_supabase: FakeSupabase
) -> None:
    home, priya, _ = await signed_in_home(session, fake_supabase)
    path = f"/v1/elders/{home.elder.id}/help/test"
    with time_machine.travel(T0, tick=False):
        for _ in range(3):
            created = await ok(await api.post(path, headers=priya.headers), 201)
            assert created["is_test"] is True
        response = await api.post(path, headers=priya.headers)
    assert (response.status_code, response.json()["code"]) == (429, "help_tests_used_up")
