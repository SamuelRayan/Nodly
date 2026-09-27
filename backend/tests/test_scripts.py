"""The dev scripts in backend/scripts: the demo flow runs end to end against the app."""

import importlib.util
from pathlib import Path
from types import ModuleType

import httpx

from nodly.config import BACKEND_DIR
from tests.fake_supabase import FakeSupabase


def load_script(name: str) -> ModuleType:
    path = Path(BACKEND_DIR, "scripts", f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"scripts_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_demo_flow_runs_end_to_end(
    client: httpx.AsyncClient, fake_supabase: FakeSupabase
) -> None:
    demo = load_script("demo_flow")
    lines: list[str] = []
    result = await demo.run_flow(
        client,
        fake_supabase.token(email="priya@example.com"),
        name="Priya",
        timezone="Asia/Kolkata",
        country="IN",
        say=lines.append,
    )
    assert result["device_me"]["elder"]["id"] == result["elder"]["id"]
    assert result["device_me"]["family"]["id"] == result["family"]["id"]
    assert [line[:2] for line in lines if line[0].isdigit()] == ["1.", "2.", "3.", "4.", "5.", "6."]


async def test_demo_flow_never_guesses_a_timezone(
    client: httpx.AsyncClient, fake_supabase: FakeSupabase
) -> None:
    demo = load_script("demo_flow")
    token = fake_supabase.token(email="newbie@example.com")
    try:
        await demo.run_flow(client, token, country="IN", say=lambda _: None)
    except demo.FlowError as exc:
        assert "--timezone" in str(exc)
    else:
        raise AssertionError("expected FlowError")


# ---------------------------------------------------------------- demo_state.py


def test_demo_schedule_is_minutes_from_now_on_the_local_clock() -> None:
    from datetime import datetime, time
    from zoneinfo import ZoneInfo

    demo = load_script("demo_state")
    now = datetime(2026, 9, 27, 10, 41, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
    schedule = demo.schedule_from(now, 2, 4, 2)
    assert (schedule.remind_at, schedule.due_by, schedule.grace_minutes) == (
        time(10, 44),
        time(10, 46),
        2,
    )
    late = datetime(2026, 9, 27, 23, 57, tzinfo=ZoneInfo("Asia/Kolkata"))
    for bad in ((late, 2, 4, 2), (now, 5, 4, 2), (now, 1, 2, 999)):
        try:
            demo.schedule_from(*bad)
        except demo.DemoStateError:
            continue
        raise AssertionError(f"accepted {bad}")


async def test_demo_state_resets_today_and_closes_alerts(session) -> None:  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime

    from sqlalchemy import func, select

    from nodly.checkins.service import record_checkin
    from nodly.help.service import open_request
    from nodly.models import Checkin, CheckinSource, HelpKind, HelpRequest
    from tests.test_checkins import make_home

    demo = load_script("demo_state")
    home = await make_home(session)
    now = datetime.now(UTC)
    await record_checkin(session, home.elder, now, CheckinSource.app)
    await session.commit()
    request, _ = await open_request(session, home.elder, now, HelpKind.help)

    elder = await demo.find_elder(session, "amma")  # by relation label, any case
    schedule = demo.schedule_from(now.astimezone(demo.ZoneInfo(elder.timezone)), 2, 4, 2)
    await demo.set_schedule(session, elder, schedule, reset_today=True, now=now)
    assert await session.scalar(select(func.count()).select_from(Checkin)) == 0
    assert elder.checkin_remind_at == schedule.remind_at

    assert await demo.close_alerts(session, now) == (1, 0)
    await session.refresh(request)
    assert request.status == "resolved"
    assert (
        await session.scalar(
            select(func.count()).select_from(HelpRequest).where(HelpRequest.status == "open")
        )
        == 0
    )


async def test_demo_state_is_dev_only(settings) -> None:  # type: ignore[no-untyped-def]
    demo = load_script("demo_state")
    args = demo.parse(["close-alerts"])
    try:
        await demo.main(args, settings)  # ENV=test
    except demo.DemoStateError as error:
        assert "dev only" in str(error)
    else:
        raise AssertionError("ran outside ENV=dev")
