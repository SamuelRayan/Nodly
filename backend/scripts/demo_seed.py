"""Dev-only: seed the "Rayan family" demo used for the Shipaton video (never runs outside
ENV=dev). Idempotent: finds the family/elder/member if they already exist.

    python scripts/demo_seed.py                    # seed (or top up) the demo
    python scripts/demo_seed.py --remind-in-2       # ...and set today's reminder for +2 min

Needs Samuel's real user row to already exist (sign in once in the app first) — this script
never fabricates a Supabase login.
"""

import argparse
import asyncio
import io
import sys
import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import imagehash
from PIL import Image, ImageDraw
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.clock import utcnow
from nodly.config import Settings, get_settings
from nodly.db import create_engine, create_sessionmaker
from nodly.media import path_for
from nodly.models import (
    AccessGrant,
    AlertResolution,
    BillingReport,
    Checkin,
    CheckinAlert,
    CheckinSource,
    Elder,
    EngineAction,
    EngineActionKind,
    Family,
    FamilyMember,
    FamilyRole,
    HelpRequest,
    Moment,
    MomentKind,
    MomentStatus,
    Purchase,
    User,
)
from nodly.moments.service import storage_key

FAMILY_NAME = "Rayan family"
ELDER_NAME = "Mom"
MEMBER_DISPLAY_NAME = "Samuel"
TZ = "Asia/Kolkata"


class DemoSeedError(Exception):
    pass


def _photo_bytes(seed: int) -> bytes:
    image = Image.new("RGB", (640, 480), (40 + seed * 17 % 180, 90, 140 - seed * 11 % 100))
    draw = ImageDraw.Draw(image)
    for n in range(5):
        x, y = (seed * 41 + n * 53) % 600, (seed * 97 + n * 31) % 440
        draw.ellipse((x, y, x + 90, y + 70), fill=(200, 60 * (n % 3) + seed, 30 * n))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG")
    return buffer.getvalue()


async def find_user(session: AsyncSession, display_name: str) -> User:
    user = await session.scalar(select(User).where(User.display_name == display_name))
    if user is None:
        raise DemoSeedError(
            f"No user called {display_name!r}. Sign in once in the app first (real Supabase "
            "login) — this script never fabricates one."
        )
    return user


async def find_or_create_family(session: AsyncSession, name: str) -> Family:
    family = await session.scalar(select(Family).where(Family.name == name))
    if family is None:
        family = Family(name=name)
        session.add(family)
        await session.flush()
    return family


async def find_or_create_elder(session: AsyncSession, family: Family, name: str) -> Elder:
    elder = await session.scalar(
        select(Elder).where(Elder.family_id == family.id, Elder.relation_label == name)
    )
    if elder is None:
        elder = Elder(
            family_id=family.id,
            display_name="Mary Rayan",
            relation_label=name,
            timezone=TZ,
            country_code="IN",
            is_primary=True,
            checkin_remind_at=time(9, 0),
            checkin_due_by=time(12, 0),
            checkin_grace_minutes=60,
        )
        session.add(elder)
        await session.flush()
    return elder


async def clear_demo_data(session: AsyncSession, settings: Settings, family: Family) -> None:
    """Wipe this family's check-ins, Help, moments and billing history so seeding starts clean."""
    elder = await session.scalar(select(Elder).where(Elder.family_id == family.id))
    if elder is not None:
        for model in (Checkin, EngineAction, CheckinAlert):
            await session.execute(delete(model).where(model.elder_id == elder.id))
        await session.execute(delete(HelpRequest).where(HelpRequest.elder_id == elder.id))
    for moment in await session.scalars(select(Moment).where(Moment.family_id == family.id)):
        for variant in ("original", "thumbnail"):
            path_for(settings, storage_key(moment, variant)).unlink(missing_ok=True)
    await session.execute(delete(Moment).where(Moment.family_id == family.id))
    await session.execute(delete(AccessGrant).where(AccessGrant.family_id == family.id))
    await session.execute(delete(BillingReport).where(BillingReport.family_id == family.id))
    purchase_ids = list(
        await session.scalars(select(Purchase.id).where(Purchase.family_id == family.id))
    )
    if purchase_ids:
        await session.execute(delete(Purchase).where(Purchase.id.in_(purchase_ids)))
    await session.commit()


async def seed(session: AsyncSession, settings: Settings, now: datetime) -> str:
    family = await find_or_create_family(session, FAMILY_NAME)
    samuel = await find_user(session, MEMBER_DISPLAY_NAME)
    if (
        await session.scalar(
            select(FamilyMember).where(
                FamilyMember.family_id == family.id, FamilyMember.user_id == samuel.id
            )
        )
        is None
    ):
        session.add(FamilyMember(family_id=family.id, user_id=samuel.id, role=FamilyRole.organizer))
    elder = await find_or_create_elder(session, family, ELDER_NAME)
    await session.commit()

    tz = ZoneInfo(TZ)
    today = now.astimezone(tz).date()

    # 6 past days: 5 checked in, 1 missed (then resolved) — never touches today. Skipped if
    # already seeded (idempotent: demo_seed.py can be re-run safely).
    missed_day = today - timedelta(days=3)
    has_history = await session.scalar(
        select(func.count()).select_from(Checkin).where(Checkin.elder_id == elder.id)
    )
    for offset in range(1, 7) if not has_history else ():
        day = today - timedelta(days=offset)
        if day == missed_day:
            due = datetime.combine(day, elder.checkin_due_by, tz)
            session.add(
                EngineAction(elder_id=elder.id, local_date=day, action=EngineActionKind.missed)
            )
            session.add(
                CheckinAlert(
                    elder_id=elder.id,
                    local_date=day,
                    raised_at=due,
                    acked_at=due + timedelta(minutes=20),
                    acked_by_user_id=samuel.id,
                    resolved_at=due + timedelta(minutes=25),
                    resolution=AlertResolution.marked_okay,
                )
            )
        else:
            session.add(
                Checkin(
                    elder_id=elder.id,
                    local_date=day,
                    checked_in_at=datetime.combine(day, elder.checkin_remind_at, tz)
                    + timedelta(minutes=15),
                    source=CheckinSource.app,
                )
            )
    await session.commit()

    # 4-5 past photo moments (not today, so they don't affect the live "today's moment" demo).
    existing = await session.scalar(
        select(func.count()).select_from(Moment).where(Moment.family_id == family.id)
    )
    made = 0
    if existing == 0:
        for n, days_ago in enumerate((2, 3, 4, 5, 6)):
            data = _photo_bytes(n)
            image = Image.open(io.BytesIO(data))
            moment = Moment(
                id=uuid.uuid4(),
                family_id=family.id,
                kind=MomentKind.photo,
                status=MomentStatus.published,
                author_user_id=samuel.id,
                by_elder=False,
                intent_at=now - timedelta(days=days_ago, hours=2),
                content_type="image/jpeg",
                storage_key="",
                size_bytes=len(data),
                width=image.width,
                height=image.height,
                phash=str(imagehash.phash(image)),
                qualifies=True,
                qualifying_local_date=today - timedelta(days=days_ago),
                completed_at=now - timedelta(days=days_ago, hours=2),
                verified_at=now - timedelta(days=days_ago, hours=1, minutes=59),
                published_at=now - timedelta(days=days_ago, hours=1, minutes=59),
            )
            moment.storage_key = storage_key(moment)
            moment.thumbnail_key = storage_key(moment, "thumbnail")
            original = path_for(settings, moment.storage_key)
            original.parent.mkdir(parents=True, exist_ok=True)
            original.write_bytes(data)
            thumb = image.copy()
            thumb.thumbnail((settings.moment_thumbnail_px, settings.moment_thumbnail_px))
            thumb.save(path_for(settings, moment.thumbnail_key), "JPEG", quality=82)
            session.add(moment)
            made += 1
    await session.commit()

    return (
        f"Seeded {FAMILY_NAME} / elder {elder.display_name} ({elder.relation_label}); "
        f"6 days of check-ins (1 resolved miss on {missed_day}); {made} new photo moment(s) "
        f"({existing} already there); no open alerts; Plus not active."
    )


async def main(args: argparse.Namespace, settings: Settings) -> str:
    if settings.env != "dev":
        raise DemoSeedError(f"Refusing to run with ENV={settings.env}: dev only.")
    engine = create_engine(settings)
    try:
        async with create_sessionmaker(engine)() as session:
            now = utcnow()
            message = await seed(session, settings, now)
            if args.remind_in_2:
                from demo_state import schedule_from, set_schedule  # sibling script

                elder = await session.scalar(
                    select(Elder).join(Family).where(Family.name == FAMILY_NAME)
                )
                assert elder is not None
                tz = ZoneInfo(elder.timezone)
                schedule = schedule_from(now.astimezone(tz), 2, 4, 2)
                await set_schedule(session, elder, schedule, reset_today=True, now=now)
                message += (
                    f" Reminder set for {schedule.remind_at:%H:%M} (elder's time, due "
                    f"{schedule.due_by:%H:%M})."
                )
            return message
    finally:
        await engine.dispose()


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--remind-in-2", action="store_true", help="also move today's reminder to +2 minutes"
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    try:
        print(asyncio.run(main(parse(), get_settings())))
    except DemoSeedError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
