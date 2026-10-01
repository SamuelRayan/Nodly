"""Dev-only: wipe the "Rayan family" demo and reseed it clean, in one command (never runs
outside ENV=dev).

    python scripts/demo_reset.py                # clean slate
    python scripts/demo_reset.py --remind-in-2   # ...and set today's reminder for +2 min
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from demo_seed import (
    FAMILY_NAME,
    DemoSeedError,
    clear_demo_data,
    find_or_create_family,
    seed,
)

from nodly.clock import utcnow
from nodly.config import Settings, get_settings
from nodly.db import create_engine, create_sessionmaker


async def main(args: argparse.Namespace, settings: Settings) -> str:
    if settings.env != "dev":
        raise DemoSeedError(f"Refusing to run with ENV={settings.env}: dev only.")
    engine = create_engine(settings)
    try:
        async with create_sessionmaker(engine)() as session:
            family = await find_or_create_family(session, FAMILY_NAME)
            await session.commit()
            await clear_demo_data(session, settings, family)
            now = utcnow()
            message = await seed(session, settings, now)
            if args.remind_in_2:
                from zoneinfo import ZoneInfo

                from demo_state import schedule_from, set_schedule
                from sqlalchemy import select

                from nodly.models import Elder

                elder = await session.scalar(select(Elder).where(Elder.family_id == family.id))
                assert elder is not None
                tz = ZoneInfo(elder.timezone)
                schedule = schedule_from(now.astimezone(tz), 2, 4, 2)
                await set_schedule(session, elder, schedule, reset_today=True, now=now)
                message += (
                    f" Reminder set for {schedule.remind_at:%H:%M} (elder's time, due "
                    f"{schedule.due_by:%H:%M})."
                )
            return "Reset. " + message
    finally:
        await engine.dispose()


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--remind-in-2", action="store_true", help="also move today's reminder to +2 minutes"
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    try:
        print(asyncio.run(main(parse(), get_settings())))
    except DemoSeedError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
