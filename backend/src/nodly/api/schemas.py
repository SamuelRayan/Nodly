"""Response schemas shared by several /v1 routers, and builders that fill them."""

import uuid
from datetime import datetime, time

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.clock import utcnow
from nodly.models import Elder, ElderDevice, Family, FamilyMember, FamilyRole, User


class CheckinSettings(BaseModel):
    remind_at: time = Field(description="Local time (elder's timezone) of the daily reminder")
    due_by: time = Field(description="Local time by which a check-in is expected")
    grace_minutes: int = Field(description="Minutes after due_by before the family is alerted")
    activity_counts_as_ok: bool = Field(
        description="Using Nodly counts as OK even without tapping 'I'm okay'"
    )


class Pause(BaseModel):
    paused: bool
    since: datetime | None
    until: datetime | None = Field(description="Null while paused means until someone resumes")


class ElderOut(BaseModel):
    id: uuid.UUID
    family_id: uuid.UUID
    display_name: str
    relation_label: str | None
    full_name: str | None
    timezone: str
    country_code: str
    phone_e164: str | None
    language: str | None
    is_primary: bool = Field(description="The primary elder's timezone is the family clock")
    checkin: CheckinSettings
    pause: Pause
    created_at: datetime


class MemberOut(BaseModel):
    user_id: uuid.UUID
    display_name: str | None
    role: FamilyRole
    country_code: str | None
    timezone: str | None
    joined_at: datetime


class FamilyClock(BaseModel):
    """'Today' for check-ins and billing is always the date in this timezone."""

    timezone: str
    elder_id: uuid.UUID


class FamilySummary(BaseModel):
    id: uuid.UUID
    name: str
    my_role: FamilyRole
    created_at: datetime


class FamilyDetail(FamilySummary):
    clock: FamilyClock | None = Field(description="Null until the family has an elder")
    has_pin: bool = Field(description="Whether a family PIN is set (never the PIN itself)")
    members: list[MemberOut]
    elders: list[ElderOut]


class DeviceOut(BaseModel):
    id: uuid.UUID
    elder_id: uuid.UUID
    platform: str
    device_model: str | None
    app_version: str | None
    paired_at: datetime
    last_seen_at: datetime | None
    revoked_at: datetime | None


def elder_out(elder: Elder, now: datetime | None = None) -> ElderOut:
    paused = elder.is_paused(now or utcnow())
    return ElderOut(
        id=elder.id,
        family_id=elder.family_id,
        display_name=elder.display_name,
        relation_label=elder.relation_label,
        full_name=elder.full_name,
        timezone=elder.timezone,
        country_code=elder.country_code,
        phone_e164=elder.phone_e164,
        language=elder.language,
        is_primary=elder.is_primary,
        checkin=CheckinSettings(
            remind_at=elder.checkin_remind_at,
            due_by=elder.checkin_due_by,
            grace_minutes=elder.checkin_grace_minutes,
            activity_counts_as_ok=elder.checkin_activity_counts_as_ok,
        ),
        pause=Pause(
            paused=paused,
            since=elder.paused_at if paused else None,
            until=elder.paused_until if paused else None,
        ),
        created_at=elder.created_at,
    )


def device_out(device: ElderDevice) -> DeviceOut:
    return DeviceOut(
        id=device.id,
        elder_id=device.elder_id,
        platform=device.platform,
        device_model=device.device_model,
        app_version=device.app_version,
        paired_at=device.created_at,
        last_seen_at=device.last_seen_at,
        revoked_at=device.revoked_at,
    )


async def family_detail(session: AsyncSession, family: Family, my_role: str) -> FamilyDetail:
    members = (
        await session.execute(
            select(FamilyMember, User)
            .join(User, User.id == FamilyMember.user_id)
            .where(FamilyMember.family_id == family.id)
            .order_by(FamilyMember.created_at, User.id)
        )
    ).all()
    elders = (
        await session.scalars(
            select(Elder).where(Elder.family_id == family.id).order_by(Elder.created_at, Elder.id)
        )
    ).all()
    primary = next((elder for elder in elders if elder.is_primary), None)
    now = utcnow()
    return FamilyDetail(
        id=family.id,
        name=family.name,
        my_role=FamilyRole(my_role),
        created_at=family.created_at,
        clock=FamilyClock(timezone=primary.timezone, elder_id=primary.id) if primary else None,
        has_pin=family.pin_hash is not None,
        members=[
            MemberOut(
                user_id=user.id,
                display_name=user.display_name,
                role=FamilyRole(member.role),
                country_code=user.country_code,
                timezone=user.timezone,
                joined_at=member.created_at,
            )
            for member, user in members
        ],
        elders=[elder_out(elder, now) for elder in elders],
    )
