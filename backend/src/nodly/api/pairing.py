"""Pairing an elder's phone: a family member makes a 15-minute code, the phone claims it
(no login) and receives a device token once. Plus listing and revoking paired devices."""

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from nodly.api.codes import CodeIn, redeem_code
from nodly.api.common import USER_AUTH_ERRORS, SettingsDep, problems
from nodly.api.invites import create_code_row
from nodly.api.schemas import DeviceOut, ElderOut, device_out, elder_out
from nodly.audit import record_audit
from nodly.auth.access import ElderMemberAccess
from nodly.clock import utcnow
from nodly.db import SessionDep
from nodly.errors import NotFoundError
from nodly.models import (
    ActorType,
    DevicePlatform,
    Elder,
    ElderDevice,
    Family,
    Invite,
    InviteKind,
)
from nodly.security.credentials import (
    CodeKind,
    format_code,
    generate_device_token,
    hash_device_token,
)

router = APIRouter(tags=["pairing"])


class PairingCodeOut(BaseModel):
    code: str = Field(description="Shown only now; type it on the elder's phone, or scan the QR")
    qr_payload: str
    expires_at: datetime


class ClaimIn(CodeIn):
    platform: DevicePlatform
    device_model: str | None = Field(default=None, max_length=100, examples=["SM-S921B"])
    app_version: str | None = Field(default=None, max_length=40, examples=["1.0.0"])


class FamilyRef(BaseModel):
    id: uuid.UUID
    name: str


class ClaimOut(BaseModel):
    device_token: str = Field(
        description="Returned only once. Store it in secure storage; send it as "
        "Authorization: Bearer <token> on /v1/device/* endpoints."
    )
    device: DeviceOut
    elder: ElderOut
    family: FamilyRef


@router.post(
    "/v1/elders/{elder_id}/pairing-codes",
    status_code=status.HTTP_201_CREATED,
    responses=problems(*USER_AUTH_ERRORS, 404),
)
async def create_pairing_code(
    access: ElderMemberAccess, session: SessionDep, settings: SettingsDep
) -> PairingCodeOut:
    """Any member can start pairing. Earlier unused codes for this elder stop working."""
    now = utcnow()
    await session.execute(
        update(Invite)
        .where(
            Invite.elder_id == access.elder.id,
            Invite.kind == InviteKind.elder_pairing,
            Invite.consumed_at.is_(None),
            Invite.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    pairing, code = await create_code_row(
        session,
        settings,
        CodeKind.pairing,
        family_id=access.family.id,
        elder_id=access.elder.id,
        kind=InviteKind.elder_pairing,
        created_by_user_id=access.user.id,
        created_at=now,
        expires_at=now + timedelta(minutes=settings.pairing_code_ttl_minutes),
    )
    record_audit(
        session,
        actor_type=ActorType.user,
        actor_id=access.user.id,
        family_id=access.family.id,
        action="pairing_code.created",
        entity_type="elder",
        entity_id=access.elder.id,
        data={"invite_id": str(pairing.id)},
    )
    await session.commit()
    return PairingCodeOut(
        code=format_code(code),
        qr_payload=f"{settings.pairing_qr_base_url}{code}",
        expires_at=pairing.expires_at,
    )


@router.post(
    "/v1/pairing/claim",
    status_code=status.HTTP_201_CREATED,
    responses=problems(410, 422, 429),
)
async def claim_pairing_code(
    body: ClaimIn, request: Request, session: SessionDep, settings: SettingsDep
) -> ClaimOut:
    """Called by the elder's phone, without signing in. Wrong codes count towards the
    brute-force limit (per IP and globally)."""
    pairing = await redeem_code(request, session, settings, body.code, CodeKind.pairing)
    assert pairing.elder_id is not None
    now = utcnow()
    token = generate_device_token()
    device = ElderDevice(
        elder_id=pairing.elder_id,
        token_hash=hash_device_token(token),
        platform=body.platform,
        device_model=body.device_model,
        app_version=body.app_version,
        last_seen_at=now,
    )
    session.add(device)
    await session.flush()
    pairing.consumed_at = now
    pairing.consumed_by_elder_device_id = device.id
    record_audit(
        session,
        actor_type=ActorType.elder_device,
        actor_id=device.id,
        family_id=pairing.family_id,
        action="device.paired",
        entity_type="elder_device",
        entity_id=device.id,
        data={
            "elder_id": str(pairing.elder_id),
            "platform": body.platform,
            "paired_by": str(pairing.created_by_user_id) if pairing.created_by_user_id else None,
        },
    )
    await session.commit()
    elder = await session.get_one(Elder, pairing.elder_id)
    family = await session.get_one(Family, pairing.family_id)
    return ClaimOut(
        device_token=token,
        device=device_out(device),
        elder=elder_out(elder, now),
        family=FamilyRef(id=family.id, name=family.name),
    )


@router.get("/v1/elders/{elder_id}/devices", responses=problems(*USER_AUTH_ERRORS, 404))
async def list_devices(access: ElderMemberAccess, session: SessionDep) -> list[DeviceOut]:
    """Phones paired to this elder, including revoked ones."""
    devices = await session.scalars(
        select(ElderDevice)
        .where(ElderDevice.elder_id == access.elder.id)
        .order_by(ElderDevice.created_at, ElderDevice.id)
    )
    return [device_out(device) for device in devices]


@router.delete(
    "/v1/elders/{elder_id}/devices/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problems(*USER_AUTH_ERRORS, 404),
)
async def revoke_device(
    device_id: uuid.UUID, access: ElderMemberAccess, session: SessionDep
) -> Response:
    """Any member can disconnect a phone (e.g. lost or replaced). Its token stops working
    immediately."""
    device = await session.get(ElderDevice, device_id)
    if device is None or device.elder_id != access.elder.id:
        raise NotFoundError("Device not found.")
    if device.revoked_at is None:
        device.revoked_at = utcnow()
        device.revoked_by_user_id = access.user.id
        device.previous_token_hash = None
        device.previous_token_expires_at = None
        record_audit(
            session,
            actor_type=ActorType.user,
            actor_id=access.user.id,
            family_id=access.family.id,
            action="device.revoked",
            entity_type="elder_device",
            entity_id=device.id,
            data={"elder_id": str(access.elder.id)},
        )
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
