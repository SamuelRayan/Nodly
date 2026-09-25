"""Helpers shared by tests: running migrations and building rows."""

from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.config import BACKEND_DIR
from nodly.models import Elder, Family, FamilyMember, FamilyRole, User


def migrate(connection: Connection, direction: str, revision: str) -> None:
    """Run an Alembic upgrade/downgrade on an already-open connection (see migrations/env.py)."""
    config = Config(
        toml_file=BACKEND_DIR / "pyproject.toml",
        attributes={"connection": connection, "configure_logger": False},
    )
    getattr(command, direction)(config, revision)


async def make_family(session: AsyncSession, **fields: Any) -> Family:
    family = Family(**{"name": "The Sharmas", **fields})
    session.add(family)
    await session.flush()
    return family


_user_count = 0


async def make_user(session: AsyncSession, **fields: Any) -> User:
    global _user_count
    _user_count += 1
    user = User(
        **{
            "email": f"user{_user_count}@example.com",
            "display_name": "Priya",
            "timezone": "Europe/London",
            **fields,
        }
    )
    session.add(user)
    await session.flush()
    return user


async def make_member(
    session: AsyncSession, family: Family, user: User, role: FamilyRole = FamilyRole.member
) -> FamilyMember:
    member = FamilyMember(family_id=family.id, user_id=user.id, role=role)
    session.add(member)
    await session.flush()
    return member


async def make_elder(session: AsyncSession, family: Family, **fields: Any) -> Elder:
    elder = Elder(
        **{
            "family_id": family.id,
            "display_name": "Mom",
            "timezone": "Asia/Kolkata",
            "country_code": "IN",
            **fields,
        }
    )
    session.add(elder)
    await session.flush()
    return elder
