"""Help, for the family (CLAUDE.md §8): live requests, "I'm on it", resolve, test alerts."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.api.common import USER_AUTH_ERRORS, SettingsDep, problems
from nodly.audit import record_audit
from nodly.auth.access import ElderMemberAccess, FamilyAccess, MemberAccess, _family_access
from nodly.auth.users import OnboardedUser
from nodly.clock import utcnow
from nodly.db import SessionDep
from nodly.errors import NotFoundError, TooManyRequestsError
from nodly.help.service import LIVE, acknowledge, close, open_test
from nodly.models import (
    ActorType,
    Checkin,
    Elder,
    FamilyMember,
    HelpEvent,
    HelpEventKind,
    HelpKind,
    HelpRequest,
    HelpStatus,
    User,
)

router = APIRouter(tags=["help"])


class HelpRecipient(BaseModel):
    user_id: uuid.UUID
    name: str | None
    delivered: bool = Field(description="Their phone accepted at least one alert")


class HelpEventOut(BaseModel):
    kind: HelpEventKind
    at: datetime
    name: str | None = Field(description="The family member involved, if any")


class HelpOut(BaseModel):
    id: uuid.UUID
    elder_id: uuid.UUID
    elder_name: str = Field(description="How the family refers to the elder")
    elder_phone_e164: str | None
    kind: HelpKind
    status: HelpStatus
    is_test: bool
    created_at: datetime
    acked_at: datetime | None
    acked_by_name: str | None
    closed_at: datetime | None
    closed_by_name: str | None
    resolution_note: str | None
    latitude: float | None
    longitude: float | None
    location_accuracy_m: float | None
    battery_percent: int | None
    network: str | None
    last_checkin_at: datetime | None
    recipients: list[HelpRecipient]
    timeline: list[HelpEventOut]


class ResolveIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class TestsUsedUpError(TooManyRequestsError):
    code = "help_tests_used_up"
    title = "No more test alerts today"


async def help_out(session: AsyncSession, request: HelpRequest) -> HelpOut:
    elder = await session.get_one(Elder, request.elder_id)
    members = list(
        await session.execute(
            select(User.id, User.display_name)
            .join(FamilyMember, FamilyMember.user_id == User.id)
            .where(FamilyMember.family_id == request.family_id)
            .order_by(FamilyMember.created_at)
        )
    )
    names = {user_id: name for user_id, name in members}
    events = list(
        await session.scalars(
            select(HelpEvent).where(HelpEvent.request_id == request.id).order_by(HelpEvent.id)
        )
    )
    delivered = {
        user_id
        for event in events
        if event.kind == HelpEventKind.pushed
        for user_id in event.data.get("delivered", [])
    }
    for user_id in (request.acked_by_user_id, request.closed_by_user_id):
        if user_id and user_id not in names:
            names[user_id] = await session.scalar(
                select(User.display_name).where(User.id == user_id)
            )
    last_checkin = await session.scalar(
        select(func.max(Checkin.checked_in_at)).where(Checkin.elder_id == elder.id)
    )
    return HelpOut(
        id=request.id,
        elder_id=elder.id,
        elder_name=elder.relation_label or elder.display_name,
        elder_phone_e164=elder.phone_e164,
        kind=HelpKind(request.kind),
        status=HelpStatus(request.status),
        is_test=request.is_test,
        created_at=request.created_at,
        acked_at=request.acked_at,
        acked_by_name=names.get(request.acked_by_user_id) if request.acked_by_user_id else None,
        closed_at=request.closed_at,
        closed_by_name=names.get(request.closed_by_user_id) if request.closed_by_user_id else None,
        resolution_note=request.resolution_note,
        latitude=request.latitude,
        longitude=request.longitude,
        location_accuracy_m=request.location_accuracy_m,
        battery_percent=request.battery_percent,
        network=request.network,
        last_checkin_at=last_checkin,
        recipients=[
            HelpRecipient(user_id=user_id, name=name, delivered=str(user_id) in delivered)
            for user_id, name in members
        ],
        timeline=[
            HelpEventOut(
                kind=HelpEventKind(event.kind),
                at=event.at,
                name=names.get(event.user_id) if event.user_id else None,
            )
            for event in events
        ],
    )


async def help_member(
    request_id: uuid.UUID, session: SessionDep, user: OnboardedUser
) -> tuple[HelpRequest, FamilyAccess]:
    """A request in one of your families; otherwise it doesn't exist (404)."""
    request = await session.get(HelpRequest, request_id)
    if request is None:
        raise NotFoundError("Help request not found.")
    return request, await _family_access(session, request.family_id, user)


HelpAccess = Annotated[tuple[HelpRequest, FamilyAccess], Depends(help_member)]


def _audit(session: AsyncSession, access: FamilyAccess, action: str, request: HelpRequest) -> None:
    record_audit(
        session,
        actor_type=ActorType.user,
        actor_id=access.user.id,
        family_id=access.family.id,
        action=action,
        entity_type="help_request",
        entity_id=request.id,
    )


@router.get("/v1/families/{family_id}/help", responses=problems(*USER_AUTH_ERRORS, 404))
async def live_help(access: MemberAccess, session: SessionDep) -> list[HelpOut]:
    """Help requests nobody has closed yet, newest first (tests included, and labelled)."""
    requests = await session.scalars(
        select(HelpRequest)
        .where(HelpRequest.family_id == access.family.id, HelpRequest.status.in_(LIVE))
        .order_by(HelpRequest.created_at.desc())
    )
    return [await help_out(session, request) for request in requests]


@router.get("/v1/help/{request_id}", responses=problems(*USER_AUTH_ERRORS, 404))
async def get_help(access: HelpAccess, session: SessionDep) -> HelpOut:
    """One request with its whole timeline."""
    request, _ = access
    return await help_out(session, request)


@router.post("/v1/help/{request_id}/ack", responses=problems(*USER_AUTH_ERRORS, 404))
async def ack_help(access: HelpAccess, session: SessionDep) -> HelpOut:
    """ "I'm on it". The first one stops the repeats, tells the rest of the family and shows
    on the elder's screen."""
    request, family = access
    if await acknowledge(session, request, family.user.id, utcnow()):
        _audit(session, family, "help.acknowledged", request)
        await session.commit()
    return await help_out(session, request)


@router.post("/v1/help/{request_id}/resolve", responses=problems(*USER_AUTH_ERRORS, 404, 422))
async def resolve_help(body: ResolveIn, access: HelpAccess, session: SessionDep) -> HelpOut:
    """Close a request, with an optional note for the timeline."""
    request, family = access
    if await close(
        session, request, utcnow(), by_elder=False, user_id=family.user.id, note=body.note
    ):
        _audit(session, family, "help.resolved", request)
        await session.commit()
    return await help_out(session, request)


@router.post(
    "/v1/elders/{elder_id}/help/test",
    status_code=status.HTTP_201_CREATED,
    responses=problems(*USER_AUTH_ERRORS, 404, 429),
)
async def test_help(
    access: ElderMemberAccess, session: SessionDep, settings: SettingsDep
) -> HelpOut:
    """A clearly labelled test alert to every family phone, to check they all ring (§8).
    Limited to a few a day per family; real Help never is."""
    request = await open_test(session, access.elder, access.user.id, utcnow(), settings)
    if request is None:
        raise TestsUsedUpError(
            f"Test alerts are limited to {settings.help_tests_per_day} a day. Try again tomorrow."
        )
    return await help_out(session, request)
