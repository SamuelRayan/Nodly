"""An elder's check-in day, for the family (CLAUDE.md §7): status, "mark okay" and "I'm on it"."""

import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.api.common import USER_AUTH_ERRORS, problems
from nodly.audit import record_audit
from nodly.auth.access import ElderMemberAccess
from nodly.checkins.engine import Schedule
from nodly.checkins.service import (
    CheckinStatus,
    DayMark,
    ElderDay,
    elder_day,
    record_checkin,
)
from nodly.clock import utcnow
from nodly.db import SessionDep
from nodly.errors import ConflictError
from nodly.models import ActorType, Checkin, CheckinSource, Elder, User

router = APIRouter(tags=["checkins"])


class ScheduleOut(BaseModel):
    remind_at: datetime = Field(description="Reminder to the elder (UTC)")
    due_at: datetime = Field(description="Check in by (UTC); the family hears after this")
    alert_at: datetime = Field(description="Missed check-in alert to the family (UTC)")


class CheckinOut(BaseModel):
    local_date: date = Field(description="The elder's local day")
    checked_in_at: datetime
    source: CheckinSource
    marked_by_name: str | None = Field(description="Who marked them okay (source = family)")


class AlertOut(BaseModel):
    raised_at: datetime
    acked_at: datetime | None
    acked_by_name: str | None = Field(description='Who said "I\'m on it"')
    resolved_at: datetime | None


class ReminderOut(BaseModel):
    kind: Literal["remind", "due_remind"]
    at: datetime


class DayOut(BaseModel):
    local_date: date
    state: DayMark


class CheckinStatusOut(BaseModel):
    elder_id: uuid.UUID
    timezone: str
    local_date: date = Field(description="Today, in the elder's timezone")
    status: CheckinStatus = Field(
        description="okay: checked in (or marked okay). waiting: not due yet. late: past due, "
        "family told. active: past due but used Nodly today (activity counts as okay). "
        "missed: missed check-in alert is open. paused: check-ins paused. no_phone: no "
        "connected phone, so no reminders or alerts. starts_tomorrow: the phone was connected "
        "after today's due time, so check-ins begin tomorrow."
    )
    schedule: ScheduleOut
    checkin: CheckinOut | None
    alert: AlertOut | None
    reminders: list[ReminderOut] = Field(description="Reminders sent to the elder today")
    active_today: bool
    last_seen_at: datetime | None = Field(description="The elder's phone last used Nodly")
    last_checkin: CheckinOut | None = Field(description="The latest check-in before today")
    week: list[DayOut] = Field(description="The last 7 days, oldest first, today last")


class NoOpenAlertError(ConflictError):
    code = "no_open_alert"
    title = "There's no open missed check-in alert"


def schedule_out(schedule: Schedule) -> ScheduleOut:
    return ScheduleOut(remind_at=schedule.remind, due_at=schedule.due, alert_at=schedule.missed)


async def _names(session: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = [user_id for user_id in ids if user_id is not None]
    if not wanted:
        return {}
    rows = await session.execute(select(User.id, User.display_name).where(User.id.in_(wanted)))
    return {user_id: name for user_id, name in rows if name}


def _checkin_out(checkin: Checkin | None, names: dict[uuid.UUID, str]) -> CheckinOut | None:
    if checkin is None:
        return None
    return CheckinOut(
        local_date=checkin.local_date,
        checked_in_at=checkin.checked_in_at,
        source=CheckinSource(checkin.source),
        marked_by_name=names.get(checkin.user_id) if checkin.user_id else None,
    )


async def status_out(session: AsyncSession, elder: Elder, day: ElderDay) -> CheckinStatusOut:
    people = {
        day.checkin.user_id if day.checkin else None,
        day.last_checkin.user_id if day.last_checkin else None,
        day.alert.acked_by_user_id if day.alert else None,
    }
    names = await _names(session, people)
    alert = day.alert
    return CheckinStatusOut(
        elder_id=elder.id,
        timezone=elder.timezone,
        local_date=day.day,
        status=day.status,
        schedule=schedule_out(day.schedule),
        checkin=_checkin_out(day.checkin, names),
        alert=AlertOut(
            raised_at=alert.raised_at,
            acked_at=alert.acked_at,
            acked_by_name=names.get(alert.acked_by_user_id) if alert.acked_by_user_id else None,
            resolved_at=alert.resolved_at,
        )
        if alert
        else None,
        reminders=[
            ReminderOut(kind="remind" if kind == "remind" else "due_remind", at=at)
            for kind, at in day.reminded
        ],
        active_today=day.active_today,
        last_seen_at=day.last_seen,
        last_checkin=_checkin_out(day.last_checkin, names),
        week=[DayOut(local_date=record.day, state=record.state) for record in day.week],
    )


async def _status(session: AsyncSession, access: ElderMemberAccess) -> CheckinStatusOut:
    day = await elder_day(session, access.elder, utcnow())
    return await status_out(session, access.elder, day)


@router.get("/v1/elders/{elder_id}/checkins/today", responses=problems(*USER_AUTH_ERRORS, 404))
async def checkin_status(access: ElderMemberAccess, session: SessionDep) -> CheckinStatusOut:
    """Today in the elder's timezone: checked in or not, reminders, alerts, and the week."""
    return await _status(session, access)


@router.post("/v1/elders/{elder_id}/checkins/mark-okay", responses=problems(*USER_AUTH_ERRORS, 404))
async def mark_okay(access: ElderMemberAccess, session: SessionDep) -> CheckinStatusOut:
    """ "I've talked to them": counts as today's check-in, closes a missed check-in alert and
    tells the rest of the family. If they already checked in, nothing changes."""
    _, changed = await record_checkin(
        session, access.elder, utcnow(), CheckinSource.family, user_id=access.user.id
    )
    if changed:
        record_audit(
            session,
            actor_type=ActorType.user,
            actor_id=access.user.id,
            family_id=access.family.id,
            action="checkin.marked_okay",
            entity_type="elder",
            entity_id=access.elder.id,
        )
    await session.commit()
    return await _status(session, access)


@router.post(
    "/v1/elders/{elder_id}/checkins/alert/ack", responses=problems(*USER_AUTH_ERRORS, 404, 409)
)
async def ack_alert(access: ElderMemberAccess, session: SessionDep) -> CheckinStatusOut:
    """ "I'm on it" for today's missed check-in alert. The first member to say so is kept."""
    day = await elder_day(session, access.elder, utcnow())
    alert = day.alert
    if alert is None or alert.resolved_at is not None:
        raise NoOpenAlertError("Nothing to acknowledge: no open missed check-in alert today.")
    if alert.acked_at is None:
        alert.acked_at = utcnow()
        alert.acked_by_user_id = access.user.id
        record_audit(
            session,
            actor_type=ActorType.user,
            actor_id=access.user.id,
            family_id=access.family.id,
            action="checkin.alert_acked",
            entity_type="elder",
            entity_id=access.elder.id,
        )
        await session.commit()
    return await _status(session, access)
