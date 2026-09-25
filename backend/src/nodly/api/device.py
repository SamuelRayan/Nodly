"""Endpoints for a paired elder phone, authenticated with its device token."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from nodly.api.common import SettingsDep, client_ip, problems
from nodly.api.pairing import FamilyRef
from nodly.api.push_tokens import PushTokenIn
from nodly.api.schemas import DeviceOut, ElderOut, device_out, elder_out
from nodly.api.types import FamilyPin
from nodly.audit import record_audit
from nodly.auth.devices import CurrentDevice
from nodly.clock import utcnow
from nodly.db import SessionDep
from nodly.errors import ConflictError, InvalidInputError
from nodly.models import ActorType
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
