"""FastAPI dependency for paired elder phones (device tokens, `Authorization: Bearer ndt_...`).

A device can only ever reach its own elder and family: device endpoints take no elder or
family ids, they use the ones the token belongs to.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from nodly.api.common import SettingsDep
from nodly.auth.supabase import InvalidTokenError
from nodly.auth.users import NotAuthenticatedError
from nodly.clock import utcnow
from nodly.db import SessionDep
from nodly.errors import UnauthorizedError
from nodly.models import Elder, ElderDevice, Family
from nodly.security.credentials import hash_device_token, is_device_token

device_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="DeviceToken",
    description="A paired elder phone's device token (Authorization: Bearer ndt_...).",
)


class DeviceRevokedError(UnauthorizedError):
    code = "device_revoked"
    title = "This phone was disconnected from the family"


@dataclass(frozen=True)
class DeviceAccess:
    device: ElderDevice
    elder: Elder
    family: Family
    # Hash of the token actually presented (the current one, or the previous one during the
    # rotation grace window): rotation keeps *that* one valid for the grace period.
    presented_token_hash: str


async def current_device(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(device_bearer)],
    session: SessionDep,
    settings: SettingsDep,
) -> DeviceAccess:
    if credentials is None:
        raise NotAuthenticatedError("Send Authorization: Bearer <device token>.")
    token = credentials.credentials
    if not is_device_token(token):
        raise InvalidTokenError("This endpoint is for paired elder devices only.")
    token_hash = hash_device_token(token)
    now = utcnow()
    device = await session.scalar(select(ElderDevice).where(ElderDevice.token_hash == token_hash))
    if device is None:
        device = await session.scalar(
            select(ElderDevice).where(
                ElderDevice.previous_token_hash == token_hash,
                ElderDevice.previous_token_expires_at > now,
            )
        )
    if device is None:
        raise InvalidTokenError("Unknown or expired device token.")
    if device.revoked_at is not None:
        raise DeviceRevokedError("Ask your family to pair this phone again.")

    elder = await session.get_one(Elder, device.elder_id)
    family = await session.get_one(Family, elder.family_id)
    interval = timedelta(seconds=settings.device_last_seen_interval_seconds)
    if device.last_seen_at is None or now - device.last_seen_at >= interval:
        device.last_seen_at = now
        await session.commit()
    return DeviceAccess(device=device, elder=elder, family=family, presented_token_hash=token_hash)


CurrentDevice = Annotated[DeviceAccess, Depends(current_device)]
