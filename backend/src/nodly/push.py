"""Registering push destinations (Expo push tokens for now; FCM/APNs later)."""

import uuid

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.clock import utcnow
from nodly.models import PushToken


async def register_push_token(
    session: AsyncSession,
    *,
    provider: str,
    token: str,
    platform: str,
    user_id: uuid.UUID | None = None,
    elder_device_id: uuid.UUID | None = None,
) -> None:
    """Upsert by (provider, token). A token belongs to one phone install; if that phone is now
    used by someone else (sign-out/in, re-pairing), the token moves to the new owner. Re-
    registering also re-enables a token the provider had reported dead. Caller commits."""
    assert (user_id is None) != (elder_device_id is None)
    now = utcnow()
    owner = {"user_id": user_id, "elder_device_id": elder_device_id}
    statement = insert(PushToken).values(provider=provider, token=token, platform=platform, **owner)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[PushToken.provider, PushToken.token],
            set_={**owner, "platform": platform, "disabled_at": None, "updated_at": now},
        )
    )
