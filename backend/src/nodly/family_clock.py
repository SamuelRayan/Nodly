"""The family clock (CLAUDE.md §5): the primary elder's timezone decides what "today" is for
check-ins and billing."""

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.models import Elder


async def family_timezone(session: AsyncSession, family_id: uuid.UUID) -> str | None:
    """None until the family has a primary elder (the first elder becomes primary)."""
    return await session.scalar(
        select(Elder.timezone).where(Elder.family_id == family_id, Elder.is_primary.is_(True))
    )


def family_date(at: datetime, timezone: str) -> date:
    return at.astimezone(ZoneInfo(timezone)).date()
