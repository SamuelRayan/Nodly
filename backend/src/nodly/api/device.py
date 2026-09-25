"""Endpoints for a paired elder phone, authenticated with its device token."""

from datetime import datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel, Field

from nodly.api.common import SettingsDep, problems
from nodly.api.pairing import FamilyRef
from nodly.api.schemas import DeviceOut, ElderOut, device_out, elder_out
from nodly.audit import record_audit
from nodly.auth.devices import CurrentDevice
from nodly.clock import utcnow
from nodly.db import SessionDep
from nodly.models import ActorType
from nodly.security.credentials import generate_device_token, hash_device_token

router = APIRouter(prefix="/v1/device", tags=["device"])


class DeviceMe(BaseModel):
    device: DeviceOut
    elder: ElderOut
    family: FamilyRef


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
    )


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
