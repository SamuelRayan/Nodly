"""Moments (CLAUDE.md §9) and whether they qualify for the free day of Plus (§10)."""

import io
import shutil
import subprocess
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import time_machine
from PIL import Image, ImageDraw
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import nodly.jobs.handlers  # registers moments.verify
import nodly.push
from nodly.config import Settings
from nodly.db import create_sessionmaker
from nodly.media import signed_path
from nodly.models import Job, Moment
from nodly.moments.service import VERIFY_JOB, long_enough, verify
from nodly.push import RecordingPushSender
from nodly.worker import Worker
from tests.conftest import app_client, make_settings
from tests.fake_supabase import FakeSupabase, SupabaseUser
from tests.test_checkins import Home, device_headers, signed_in_home

# 20:00Z on 25 Sep is 01:30 on 26 Sep in Kolkata: the family clock's day is the 26th.
INTENT = datetime(2026, 9, 25, 20, 0, tzinfo=UTC)


def photo(seed: int = 0, *, brighten: int = 0, size: int = 256, fmt: str = "JPEG") -> bytes:
    """A photo-like test image: shapes that depend on `seed`, optionally a little brighter
    (a near-duplicate of the same seed)."""
    image = Image.new("RGB", (size, size), (40 + brighten, 90 + brighten, 140 + brighten))
    draw = ImageDraw.Draw(image)
    for n in range(6):
        x = (seed * 37 + n * 53) % size
        y = (seed * 91 + n * 29) % size
        draw.ellipse(
            (x, y, x + size // 3, y + size // 4), fill=(200 + brighten // 2, 60 * (n % 3), 30 * n)
        )
    buffer = io.BytesIO()
    image.save(buffer, fmt)
    return buffer.getvalue()


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> RecordingPushSender:
    fresh = RecordingPushSender()
    monkeypatch.setattr(nodly.push, "_recorder", fresh)
    return fresh


@pytest.fixture
def settings(test_database_url: str, tmp_path: Path) -> Settings:
    return make_settings(
        test_database_url,
        push_provider="record",
        media_dir=str(tmp_path / "media"),
        moment_photo_max_bytes=200_000,
    )


@pytest.fixture
async def api(
    settings: Settings, clean_db: AsyncEngine, fake_supabase: FakeSupabase
) -> AsyncIterator[httpx.AsyncClient]:
    async with app_client(settings, fake_supabase) as client:
        yield client


async def run_jobs(engine: AsyncEngine, settings: Settings, at: datetime | None = None) -> int:
    """Run queued jobs as if it were `at` (default: a few hours after INTENT), so the
    24-hour qualifying window is judged against the test's clock, not today's."""
    at = at or INTENT + timedelta(hours=5)
    ran = 0
    with time_machine.travel(at, tick=False):
        worker = Worker(settings, create_sessionmaker(engine), worker_id="t")
        while count := await worker.run_once():
            ran += count
    return ran


async def ok(response: httpx.Response, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json() if response.content else None


async def share(
    api: httpx.AsyncClient,
    home: Home,
    person: SupabaseUser,
    data: bytes,
    at: datetime = INTENT,
    *,
    kind: str = "photo",
    content_type: str = "image/jpeg",
) -> dict[str, Any]:
    """Start → upload → complete, as a family member, at `at`."""
    with time_machine.travel(at, tick=False):
        started = await ok(
            await api.post(
                f"/v1/families/{home.family.id}/moments",
                headers=person.headers,
                json={"kind": kind, "content_type": content_type},
            ),
            201,
        )
        assert started["status"] == "awaiting_upload"
        await ok(
            await api.put(
                started["upload_path"],
                headers={**person.headers, "Content-Type": content_type},
                content=data,
            )
        )
        return await ok(
            await api.post(f"/v1/moments/{started['id']}/complete", headers=person.headers)
        )


async def fetch(api: httpx.AsyncClient, moment_id: str, person: SupabaseUser) -> dict[str, Any]:
    return await ok(await api.get(f"/v1/moments/{moment_id}", headers=person.headers))


# ---------------------------------------------------------------- the pipeline


async def test_share_a_photo(
    api: httpx.AsyncClient,
    session: AsyncSession,
    clean_db: AsyncEngine,
    settings: Settings,
    fake_supabase: FakeSupabase,
    recorder: RecordingPushSender,
) -> None:
    home, priya, _ = await signed_in_home(session, fake_supabase)
    checking = await share(api, home, priya, photo(1))
    assert checking["status"] == "checking" and checking["url"] is None
    assert await run_jobs(clean_db, settings) == 1

    posted = await fetch(api, checking["id"], priya)
    assert posted["status"] == "published"
    assert posted["qualifies"] is True
    assert posted["qualifying_local_date"] == "2026-09-26"  # the family clock's day, not UTC's
    assert (posted["width"], posted["height"]) == (256, 256)
    assert posted["author_name"] == "Priya Rayan" and posted["is_mine"] is True

    # The file and its thumbnail come through the signed links.
    image = await api.get(posted["url"])
    assert image.status_code == 200 and image.content == photo(1)
    assert (await api.get(posted["thumbnail_url"])).status_code == 200

    # The elder's phone and the rest of the family hear about it; the author doesn't.
    [push] = recorder.sent
    assert push.title == "Priya sent a photo" and push.channel_id == "moments"
    assert set(push.tokens) == {f"fam-{home.member.id}", "elder-phone"}


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True)
    path.write_bytes(data)


async def test_signed_links_expire_and_cant_be_forged(
    api: httpx.AsyncClient, settings: Settings
) -> None:
    key = "family/moment/original.jpg"
    _write(Path(settings.media_dir, key), b"x")
    good = signed_path(settings, key)
    assert (await api.get(good)).status_code == 200
    assert (await api.get(good.replace("sig=", "sig=0"))).status_code == 403
    old = signed_path(settings, key, now=datetime.now(UTC).timestamp() - 3600)
    assert (await api.get(old)).status_code == 403
    sneaky = signed_path(settings, "../secret.txt")
    assert (await api.get(sneaky)).status_code in (403, 404)


async def test_near_duplicates_post_but_dont_count(
    api: httpx.AsyncClient,
    session: AsyncSession,
    clean_db: AsyncEngine,
    settings: Settings,
    fake_supabase: FakeSupabase,
    recorder: RecordingPushSender,
) -> None:
    home, priya, arjun = await signed_in_home(session, fake_supabase)
    first = await share(api, home, priya, photo(3))
    await run_jobs(clean_db, settings)
    again = await share(api, home, arjun, photo(3, brighten=6), INTENT + timedelta(hours=2))
    different = await share(api, home, arjun, photo(40), INTENT + timedelta(hours=3))
    await run_jobs(clean_db, settings)

    assert (await fetch(api, first["id"], priya))["qualifies"] is True
    duplicate = await fetch(api, again["id"], arjun)
    assert duplicate["status"] == "published"
    assert (duplicate["qualifies"], duplicate["not_qualifying_reason"]) == (False, "near_duplicate")
    assert (await fetch(api, different["id"], arjun))["qualifies"] is True


async def test_a_second_complete_changes_nothing(
    api: httpx.AsyncClient, session: AsyncSession, fake_supabase: FakeSupabase
) -> None:
    home, priya, _ = await signed_in_home(session, fake_supabase)
    first = await share(api, home, priya, photo(5))
    again = await ok(await api.post(f"/v1/moments/{first['id']}/complete", headers=priya.headers))
    assert again["status"] == "checking"
    jobs = await session.scalar(select(func.count()).select_from(Job).where(Job.type == VERIFY_JOB))
    assert jobs == 1


@pytest.mark.parametrize(("hours", "qualifies"), [(23, True), (25, False)])
async def test_late_checks_dont_count(
    api: httpx.AsyncClient,
    session: AsyncSession,
    settings: Settings,
    fake_supabase: FakeSupabase,
    hours: int,
    qualifies: bool,
) -> None:
    home, priya, _ = await signed_in_home(session, fake_supabase)
    started = await share(api, home, priya, photo(7))
    moment = await session.get_one(Moment, started["id"])
    await verify(session, moment, INTENT + timedelta(hours=hours), settings)
    assert moment.status == "published"
    assert moment.qualifies is qualifies
    assert moment.not_qualifying_reason == (None if qualifies else "late")


async def test_elder_posts_never_count(
    api: httpx.AsyncClient,
    session: AsyncSession,
    clean_db: AsyncEngine,
    settings: Settings,
    fake_supabase: FakeSupabase,
    recorder: RecordingPushSender,
) -> None:
    home, priya, _ = await signed_in_home(session, fake_supabase)
    phone = device_headers(home)
    with time_machine.travel(INTENT, tick=False):
        started = await ok(
            await api.post(
                "/v1/device/moments",
                headers=phone,
                json={"kind": "photo", "content_type": "image/jpeg"},
            ),
            201,
        )
        assert started["upload_path"] == f"/v1/device/moments/{started['id']}/file"
        await ok(await api.put(started["upload_path"], headers=phone, content=photo(9)))
        await ok(await api.post(f"/v1/device/moments/{started['id']}/complete", headers=phone))
    await run_jobs(clean_db, settings)
    posted = await fetch(api, started["id"], priya)
    assert posted["status"] == "published" and posted["by_elder"] is True
    assert (posted["qualifies"], posted["not_qualifying_reason"]) == (False, "posted_by_elder")
    assert posted["author_name"] == "Amma"
    [push] = recorder.sent
    assert push.title == "Amma sent a photo" and "elder-phone" not in push.tokens


async def test_rejections_say_why(
    api: httpx.AsyncClient,
    session: AsyncSession,
    clean_db: AsyncEngine,
    settings: Settings,
    fake_supabase: FakeSupabase,
) -> None:
    home, priya, _ = await signed_in_home(session, fake_supabase)
    not_photo = await share(api, home, priya, b"this is not an image at all")
    # Started and completed without ever sending the file.
    with time_machine.travel(INTENT, tick=False):
        started = await ok(
            await api.post(
                f"/v1/families/{home.family.id}/moments",
                headers=priya.headers,
                json={"kind": "photo", "content_type": "image/jpeg"},
            ),
            201,
        )
        await ok(await api.post(f"/v1/moments/{started['id']}/complete", headers=priya.headers))
    await run_jobs(clean_db, settings)
    assert (await fetch(api, not_photo["id"], priya))["reject_reason"] == "not_a_photo"
    missing = await fetch(api, started["id"], priya)
    assert (missing["status"], missing["reject_reason"]) == ("rejected", "upload_missing")

    # Too big for the (test) limit of 200 KB: refused at upload.
    big = await ok(
        await api.post(
            f"/v1/families/{home.family.id}/moments",
            headers=priya.headers,
            json={"kind": "photo", "content_type": "image/png"},
        ),
        201,
    )
    response = await api.put(big["upload_path"], headers=priya.headers, content=b"0" * 300_000)
    assert (response.status_code, response.json()["code"]) == (422, "too_large")


# ---------------------------------------------------------------- feeds, views, hearts


async def test_new_counts_hearts_and_deleting(
    api: httpx.AsyncClient,
    session: AsyncSession,
    clean_db: AsyncEngine,
    settings: Settings,
    fake_supabase: FakeSupabase,
) -> None:
    home, priya, arjun = await signed_in_home(session, fake_supabase)
    phone = device_headers(home)
    posted = await share(api, home, priya, photo(11))
    await run_jobs(clean_db, settings)

    feed = await ok(await api.get("/v1/device/moments", headers=phone))
    assert feed["new_count"] == 1
    assert (await ok(await api.get("/v1/device/today", headers=phone)))["new_moments"] == 1
    [item] = feed["items"]
    assert item["viewed_by_me"] is False and item["url"]
    await ok(await api.post(f"/v1/device/moments/{item['id']}/view", headers=phone), 204)
    await ok(await api.post(f"/v1/device/moments/{item['id']}/view", headers=phone), 204)
    assert (await ok(await api.get("/v1/device/moments", headers=phone)))["new_count"] == 0

    # Priya's own photo is never "new" for her; Arjun hasn't seen it yet.
    own = await ok(await api.get(f"/v1/families/{home.family.id}/moments", headers=priya.headers))
    assert own["new_count"] == 0
    others = await ok(
        await api.get(f"/v1/families/{home.family.id}/moments", headers=arjun.headers)
    )
    assert others["new_count"] == 1

    loved = await ok(await api.put(f"/v1/device/moments/{item['id']}/heart", headers=phone))
    assert (loved["hearts"], loved["hearted_by_me"]) == (1, True)
    await ok(await api.put(f"/v1/moments/{item['id']}/heart", headers=arjun.headers))
    await ok(await api.put(f"/v1/moments/{item['id']}/heart", headers=arjun.headers))  # idempotent
    both = await fetch(api, posted["id"], priya)
    assert (both["hearts"], both["hearted_by_me"]) == (2, False)
    unloved = await ok(await api.delete(f"/v1/moments/{item['id']}/heart", headers=arjun.headers))
    assert unloved["hearts"] == 1

    response = await api.delete(f"/v1/moments/{posted['id']}", headers=arjun.headers)
    assert (response.status_code, response.json()["code"]) == (403, "not_your_moment")
    await ok(await api.delete(f"/v1/moments/{posted['id']}", headers=priya.headers), 204)
    assert (await ok(await api.get("/v1/device/moments", headers=phone)))["items"] == []
    assert (await api.get(f"/v1/moments/{posted['id']}", headers=priya.headers)).status_code == 404


async def test_hearts_can_be_turned_off(
    session: AsyncSession,
    clean_db: AsyncEngine,
    fake_supabase: FakeSupabase,
    tmp_path: Path,
    test_database_url: str,
) -> None:
    off = make_settings(
        test_database_url,
        push_provider="record",
        media_dir=str(tmp_path / "m"),
        reactions_enabled=False,
    )
    async with app_client(off, fake_supabase) as api:
        home, priya, _ = await signed_in_home(session, fake_supabase)
        posted = await share(api, home, priya, photo(13))
        await run_jobs(clean_db, off)
        response = await api.put(f"/v1/moments/{posted['id']}/heart", headers=priya.headers)
    assert (response.status_code, response.json()["code"]) == (409, "reactions_disabled")


# ---------------------------------------------------------------- voice notes

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="needs ffmpeg and ffprobe on PATH (winget install ffmpeg)",
)


@pytest.fixture(scope="module")
def recordings(tmp_path_factory: pytest.TempPathFactory) -> dict[str, bytes]:
    """Real files made with ffmpeg: voice notes (AAC in .m4a, like the app records) of 12 s
    and 5 s, and a short video that isn't a voice note."""
    if not shutil.which("ffmpeg"):
        return {}
    folder = tmp_path_factory.mktemp("recordings")

    def make(name: str, *args: str) -> bytes:
        out = folder / name
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", *args, str(out)], check=True, capture_output=True
        )
        return out.read_bytes()

    def voice(seconds: int) -> bytes:
        return make(
            f"voice-{seconds}.m4a",
            *("-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}"),
            *("-c:a", "aac", "-b:a", "48k"),
        )

    return {
        "12s": voice(12),
        "5s": voice(5),
        "video": make(
            "clip.mp4",
            *("-f", "lavfi", "-i", "testsrc=duration=2:size=64x64:rate=10"),
            *("-f", "lavfi", "-i", "sine=duration=2"),
            *("-c:v", "mpeg4", "-c:a", "aac", "-shortest"),
        ),
    }


async def share_voice(
    api: httpx.AsyncClient, home: Home, person: SupabaseUser, data: bytes, at: datetime = INTENT
) -> dict[str, Any]:
    return await share(api, home, person, data, at, kind="voice", content_type="audio/mp4")


@pytest.mark.parametrize(("ms", "counts"), [(9_900, False), (9_999, False), (10_000, True)])
def test_voice_notes_count_from_ten_seconds(settings: Settings, ms: int, counts: bool) -> None:
    assert long_enough(ms, settings) is counts


@needs_ffmpeg
async def test_share_voice_notes(
    api: httpx.AsyncClient,
    session: AsyncSession,
    clean_db: AsyncEngine,
    settings: Settings,
    fake_supabase: FakeSupabase,
    recorder: RecordingPushSender,
    recordings: dict[str, bytes],
) -> None:
    home, priya, arjun = await signed_in_home(session, fake_supabase)
    long = await share_voice(api, home, priya, recordings["12s"])
    short = await share_voice(api, home, arjun, recordings["5s"], INTENT + timedelta(hours=1))
    assert await run_jobs(clean_db, settings) == 2

    posted = await fetch(api, long["id"], priya)
    assert (posted["kind"], posted["status"], posted["qualifies"]) == ("voice", "published", True)
    assert posted["qualifying_local_date"] == "2026-09-26"
    assert 11_900 <= posted["duration_ms"] <= 12_100
    assert posted["thumbnail_url"] is None and posted["width"] is None
    audio = await api.get(posted["url"])
    assert audio.status_code == 200 and audio.content == recordings["12s"]
    assert audio.headers["content-type"] == "audio/mp4"

    # Posted for everyone to hear, but too short to count for the day.
    brief = await fetch(api, short["id"], arjun)
    assert brief["status"] == "published"
    assert (brief["qualifies"], brief["not_qualifying_reason"]) == (False, "too_short")
    assert 4_900 <= brief["duration_ms"] <= 5_100

    titles = sorted(push.title for push in recorder.sent)
    assert titles == ["Arjun sent a voice note", "Priya sent a voice note"]
    assert recorder.sent[0].body == "Open Nodly to hear it."


@needs_ffmpeg
async def test_voice_notes_that_cant_be_played_are_rejected(
    api: httpx.AsyncClient,
    session: AsyncSession,
    clean_db: AsyncEngine,
    settings: Settings,
    fake_supabase: FakeSupabase,
    recordings: dict[str, bytes],
) -> None:
    home, priya, _ = await signed_in_home(session, fake_supabase)
    garbage = await share_voice(api, home, priya, b"definitely not a recording" * 50)
    # The recording cut off halfway (ffmpeg writes the index at the end, so it's unreadable).
    cut = await share_voice(api, home, priya, recordings["12s"][: len(recordings["12s"]) // 2])
    video = await share_voice(api, home, priya, recordings["video"])
    await run_jobs(clean_db, settings)
    for moment in (garbage, cut, video):
        rejected = await fetch(api, moment["id"], priya)
        assert (rejected["status"], rejected["reject_reason"]) == ("rejected", "not_audio")
        assert rejected["qualifies"] is False and rejected["url"] is None


@needs_ffmpeg
async def test_voice_notes_over_the_limit_are_rejected(
    session: AsyncSession,
    clean_db: AsyncEngine,
    fake_supabase: FakeSupabase,
    tmp_path: Path,
    test_database_url: str,
    recordings: dict[str, bytes],
) -> None:
    short_limit = make_settings(
        test_database_url,
        push_provider="record",
        media_dir=str(tmp_path / "m"),
        moment_voice_max_seconds=11,
    )
    async with app_client(short_limit, fake_supabase) as api:
        home, priya, _ = await signed_in_home(session, fake_supabase)
        started = await share_voice(api, home, priya, recordings["12s"])
        await run_jobs(clean_db, short_limit)
        rejected = await fetch(api, started["id"], priya)
    assert (rejected["status"], rejected["reject_reason"]) == ("rejected", "too_long")


@pytest.mark.parametrize(
    ("kind", "content_type"),
    [("voice", "image/jpeg"), ("photo", "audio/mp4"), ("voice", "audio/mpeg")],
)
async def test_the_file_type_must_fit_the_kind(
    api: httpx.AsyncClient,
    session: AsyncSession,
    fake_supabase: FakeSupabase,
    kind: str,
    content_type: str,
) -> None:
    home, priya, _ = await signed_in_home(session, fake_supabase)
    response = await api.post(
        f"/v1/families/{home.family.id}/moments",
        headers=priya.headers,
        json={"kind": kind, "content_type": content_type},
    )
    assert response.status_code == 422


def test_family_clock_day_is_used_even_across_utc_dates() -> None:
    # Documenting the fixture: INTENT is the 25th in UTC but the 26th on the family clock.
    assert INTENT.date() == date(2026, 9, 25)
