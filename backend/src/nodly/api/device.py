"""Endpoints for a paired elder phone, authenticated with its device token."""

from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.api.checkins import ScheduleOut, schedule_out
from nodly.api.common import SettingsDep, client_ip, problems
from nodly.api.help import HelpOut, help_out
from nodly.api.moments import Viewer, new_count
from nodly.api.pairing import FamilyRef
from nodly.api.push_tokens import PushTokenIn
from nodly.api.schemas import DeviceOut, ElderOut, device_out, elder_out
from nodly.api.types import FamilyPin
from nodly.audit import record_audit
from nodly.auth.devices import CurrentDevice, DeviceAccess
from nodly.checkins.service import elder_day, record_checkin
from nodly.clock import utcnow
from nodly.db import SessionDep
from nodly.errors import ConflictError, InvalidInputError
from nodly.help.service import PhoneInfo, close, live_request, open_request
from nodly.models import ActorType, CheckinSource, FamilyMember, FamilyRole, HelpKind, User
from nodly.push import register_push_token
from nodly.security.credentials import generate_device_token, hash_device_token
from nodly.security.pins import verify_pin
from nodly.security.throttle import CodeAttemptThrottle

router = APIRouter(prefix="/v1/device", tags=["device"])


class DeviceMe(BaseModel):
    device: DeviceOut
    elder: ElderOut
    family: FamilyRef
    family_has_pin: bool = Field(
        description="Whether the family PIN can take this phone out of elder mode"
    )


class LeaveIn(BaseModel):
    pin: FamilyPin


class WrongPinError(InvalidInputError):
    code = "wrong_pin"
    title = "That PIN isn't right"


class NoFamilyPinError(ConflictError):
    code = "no_family_pin"
    title = "The family hasn't set a PIN"


class RotatedToken(BaseModel):
    device_token: str = Field(description="The new token. Store it, then use it from now on.")
    previous_token_valid_until: datetime = Field(
        description="The token you called with keeps working until then, in case this "
        "response is lost"
    )


@router.get("/me", responses=problems(401))
async def device_me(access: CurrentDevice) -> DeviceMe:
    """What the elder's home screen needs to start: who this phone belongs to, the family,
    and the check-in settings."""
    return DeviceMe(
        device=device_out(access.device),
        elder=elder_out(access.elder),
        family=FamilyRef(id=access.family.id, name=access.family.name),
        family_has_pin=access.family.pin_hash is not None,
    )


@router.post("/push-token", status_code=status.HTTP_204_NO_CONTENT, responses=problems(401, 422))
async def register_device_push_token(
    body: PushTokenIn, access: CurrentDevice, session: SessionDep
) -> Response:
    """Call after pairing and whenever the token changes."""
    await register_push_token(
        session,
        provider=body.provider,
        token=body.token,
        platform=body.platform,
        elder_device_id=access.device.id,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/leave",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problems(401, 409, 422, 429),
)
async def leave_elder_mode(
    body: LeaveIn,
    request: Request,
    access: CurrentDevice,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    """Take this phone out of elder mode with the family PIN: the device is disconnected and
    its token stops working. Wrong PINs are limited per phone and per network address."""
    if access.family.pin_hash is None:
        raise NoFamilyPinError("Ask your family to disconnect this phone from their app.")
    throttle = CodeAttemptThrottle(settings)
    now = utcnow()
    limits = throttle.pin_limits(ip=client_ip(request), device_id=access.device.id)
    await throttle.check(session, limits, now)
    if not verify_pin(body.pin, access.family.pin_hash):
        await throttle.record_failure(session, limits, now)
        raise WrongPinError("Check the PIN and try again.")
    device = access.device
    device.revoked_at = now
    device.previous_token_hash = None
    device.previous_token_expires_at = None
    record_audit(
        session,
        actor_type=ActorType.elder_device,
        actor_id=device.id,
        family_id=access.family.id,
        action="device.left",
        entity_type="elder_device",
        entity_id=device.id,
        data={"elder_id": str(access.elder.id)},
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/token/rotate", responses=problems(401))
async def rotate_device_token(
    access: CurrentDevice, session: SessionDep, settings: SettingsDep
) -> RotatedToken:
    """Swap this phone's token for a new one."""
    now = utcnow()
    grace_until = now + timedelta(seconds=settings.device_token_rotation_grace_seconds)
    token = generate_device_token()
    device = access.device
    device.previous_token_hash = access.presented_token_hash
    device.previous_token_expires_at = grace_until
    device.token_hash = hash_device_token(token)
    record_audit(
        session,
        actor_type=ActorType.elder_device,
        actor_id=device.id,
        family_id=access.family.id,
        action="device.token_rotated",
        entity_type="elder_device",
        entity_id=device.id,
    )
    await session.commit()
    return RotatedToken(device_token=token, previous_token_valid_until=grace_until)


# ---------------------------------------------------------------- check-ins (CLAUDE.md §7)


class DeviceCheckinIn(BaseModel):
    source: Literal["app", "notification"] = Field(
        default="app", description="The home screen button, or the button on a reminder"
    )


class DeviceToday(BaseModel):
    local_date: date = Field(description="Today, in the elder's timezone")
    checked_in_at: datetime | None = Field(description='When they said "I\'m okay" today')
    marked_okay_by_family: bool = Field(
        description="A family member marked them okay (and they haven't tapped yet)"
    )
    schedule: ScheduleOut
    watched_today: bool = Field(
        description="Check-ins count today (false on the day a phone is set up after the due "
        "time: they start tomorrow)"
    )
    family_alerted_at: datetime | None = Field(
        description="When the family got today's missed check-in alert, if they did"
    )
    family_names: list[str] = Field(
        description='First names of the family members, organizer first ("Priya and Arjun")'
    )
    new_moments: int = Field(description="Moments from the family this phone hasn't opened yet")


async def _device_today(session: AsyncSession, access: DeviceAccess) -> DeviceToday:
    elder = access.elder
    day = await elder_day(session, elder, utcnow())
    members = await session.execute(
        select(User.display_name)
        .join(FamilyMember, FamilyMember.user_id == User.id)
        .where(FamilyMember.family_id == access.family.id)
        .order_by((FamilyMember.role == FamilyRole.organizer).desc(), FamilyMember.created_at)
    )
    checkin = day.checkin
    return DeviceToday(
        local_date=day.day,
        checked_in_at=checkin.checked_in_at if checkin and checkin.source != "family" else None,
        marked_okay_by_family=bool(checkin and checkin.source == "family"),
        schedule=schedule_out(day.schedule),
        watched_today=day.watched,
        family_alerted_at=day.alert.raised_at if day.alert else None,
        family_names=[name.split()[0] for (name,) in members if name and name.strip()],
        new_moments=await new_count(
            session, Viewer(family_id=access.family.id, device_id=access.device.id)
        ),
    )


@router.get("/today", responses=problems(401))
async def device_today(access: CurrentDevice, session: SessionDep) -> DeviceToday:
    """The elder's home screen: checked in today or not, when the family would hear, and
    who's in the family."""
    return await _device_today(session, access)


@router.post("/checkin", responses=problems(401, 422))
async def device_checkin(
    body: DeviceCheckinIn, access: CurrentDevice, session: SessionDep
) -> DeviceToday:
    """ "I'm okay". Once a day counts; tapping again changes nothing. Closes a missed
    check-in alert and tells the family "All good" if they'd been told to worry."""
    await record_checkin(
        session,
        access.elder,
        utcnow(),
        CheckinSource(body.source),
        device_id=access.device.id,
    )
    await session.commit()
    return await _device_today(session, access)


# ---------------------------------------------------------------- Help (CLAUDE.md §8)


class DeviceHelpIn(BaseModel):
    kind: HelpKind = Field(
        default=HelpKind.help, description='help: urgent. call_me: "Please call me", not urgent'
    )
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    location_accuracy_m: float | None = Field(default=None, ge=0)
    battery_percent: int | None = Field(default=None, ge=0, le=100)
    network: str | None = Field(default=None, max_length=20, description="wifi, cellular, ...")


class NoLiveHelpError(ConflictError):
    code = "no_live_help"
    title = "There's no open Help request"


@router.post("/help", responses=problems(401, 422))
async def device_help(body: DeviceHelpIn, access: CurrentDevice, session: SessionDep) -> HelpOut:
    """Ask the family for help. Pressing again while a request is open returns that one."""
    request, _ = await open_request(
        session,
        access.elder,
        utcnow(),
        body.kind,
        device_id=access.device.id,
        info=PhoneInfo(
            latitude=body.latitude,
            longitude=body.longitude,
            accuracy_m=body.location_accuracy_m,
            battery_percent=body.battery_percent,
            network=body.network,
        ),
    )
    return await help_out(session, request)


@router.get("/help", responses=problems(401))
async def device_current_help(access: CurrentDevice, session: SessionDep) -> HelpOut | None:
    """The open request, if any, for the elder's "Your family has been alerted" screen:
    who got it and who's on it."""
    request = await live_request(session, access.elder.id)
    return await help_out(session, request) if request else None


@router.post("/help/cancel", responses=problems(401, 409))
async def device_cancel_help(access: CurrentDevice, session: SessionDep) -> HelpOut:
    """ "I'm okay now": closes the open request and tells the family."""
    request = await live_request(session, access.elder.id)
    if request is None:
        raise NoLiveHelpError("Nothing to cancel.")
    await close(session, request, utcnow(), by_elder=True)
    return await help_out(session, request)
