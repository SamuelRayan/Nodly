"""Push notifications: registering destinations, and sending through the Expo Push Service.

Sending: https://docs.expo.dev/push-notifications/sending-notifications/ (up to 100 messages
per request; a ticket per message; DeviceNotRegistered means stop using that token).
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.clock import utcnow
from nodly.config import Settings
from nodly.models import ElderDevice, FamilyMember, PushProvider, PushToken

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_BATCH = 100


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


# ---------------------------------------------------------------- who to send to


async def family_tokens(
    session: AsyncSession, family_id: uuid.UUID, *, exclude_user: uuid.UUID | None = None
) -> list[str]:
    """Live push tokens of every member of a family (optionally leaving one person out)."""
    query = (
        select(PushToken.token)
        .join(FamilyMember, FamilyMember.user_id == PushToken.user_id)
        .where(
            FamilyMember.family_id == family_id,
            PushToken.provider == PushProvider.expo,
            PushToken.disabled_at.is_(None),
        )
    )
    if exclude_user is not None:
        query = query.where(FamilyMember.user_id != exclude_user)
    return list(await session.scalars(query))


async def family_tokens_by_user(
    session: AsyncSession, family_id: uuid.UUID
) -> list[tuple[uuid.UUID, str]]:
    """(user id, token) for every live token of every family member."""
    rows = await session.execute(
        select(FamilyMember.user_id, PushToken.token)
        .join(PushToken, PushToken.user_id == FamilyMember.user_id)
        .where(
            FamilyMember.family_id == family_id,
            PushToken.provider == PushProvider.expo,
            PushToken.disabled_at.is_(None),
        )
    )
    return [(user_id, token) for user_id, token in rows]


async def elder_tokens(session: AsyncSession, elder_id: uuid.UUID) -> list[str]:
    """Live push tokens of an elder's connected (not disconnected) phones."""
    query = (
        select(PushToken.token)
        .join(ElderDevice, ElderDevice.id == PushToken.elder_device_id)
        .where(
            ElderDevice.elder_id == elder_id,
            ElderDevice.revoked_at.is_(None),
            PushToken.provider == PushProvider.expo,
            PushToken.disabled_at.is_(None),
        )
    )
    return list(await session.scalars(query))


# ---------------------------------------------------------------- sending


Priority = Literal["default", "normal", "high"]


@dataclass(frozen=True)
class Push:
    """One notification, sent to each of `tokens`."""

    tokens: Sequence[str]
    title: str
    body: str
    channel_id: str  # Android channel: checkin | moments | help_alerts | general
    data: dict[str, Any] = field(default_factory=dict)
    priority: Priority = "high"
    category_id: str | None = None  # action buttons registered by the app


@dataclass(frozen=True)
class Ticket:
    token: str
    ok: bool
    error: str | None = None  # details.error, e.g. "DeviceNotRegistered"


class PushSender(Protocol):
    async def send(self, push: Push) -> list[Ticket]: ...


class ExpoPushSender:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.client = client

    def _message(self, token: str, push: Push) -> dict[str, Any]:
        message: dict[str, Any] = {
            "to": token,
            "title": push.title,
            "body": push.body,
            "data": push.data,
            "sound": "default",
            "priority": push.priority,
            "channelId": push.channel_id,
        }
        if push.category_id:
            message["categoryId"] = push.category_id
        return message

    async def send(self, push: Push) -> list[Ticket]:
        if self.client is not None:
            return await self._send(self.client, push)
        async with httpx.AsyncClient(timeout=15) as client:
            return await self._send(client, push)

    async def _send(self, client: httpx.AsyncClient, push: Push) -> list[Ticket]:
        headers = {"accept": "application/json", "content-type": "application/json"}
        if self.settings.expo_push_access_token:
            token = self.settings.expo_push_access_token.get_secret_value()
            headers["authorization"] = f"Bearer {token}"
        tickets: list[Ticket] = []
        tokens = list(push.tokens)
        for start in range(0, len(tokens), EXPO_BATCH):
            batch = tokens[start : start + EXPO_BATCH]
            response = await client.post(
                self.settings.expo_push_url,
                json=[self._message(token, push) for token in batch],
                headers=headers,
            )
            # A whole-request failure (4xx/5xx) raises, so the job retries with backoff.
            response.raise_for_status()
            for token, ticket in zip(batch, response.json().get("data", []), strict=False):
                error = (ticket.get("details") or {}).get("error")
                tickets.append(Ticket(token, ticket.get("status") == "ok", error))
        return tickets


class RecordingPushSender:
    """Keeps what would have been sent (tests; PUSH_PROVIDER=record in dev without a network)."""

    def __init__(self) -> None:
        self.sent: list[Push] = []

    async def send(self, push: Push) -> list[Ticket]:
        self.sent.append(push)
        return [Ticket(token, True) for token in push.tokens]


_recorder = RecordingPushSender()


def push_sender(settings: Settings) -> PushSender:
    if settings.push_provider == "record":
        return _recorder
    return ExpoPushSender(settings)


async def deliver(session: AsyncSession, sender: PushSender, push: Push) -> list[Ticket]:
    """Send, then stop using tokens the provider says are dead. Caller commits."""
    if not push.tokens:
        return []
    tickets = await sender.send(push)
    dead = [ticket.token for ticket in tickets if ticket.error == "DeviceNotRegistered"]
    if dead:
        await session.execute(
            update(PushToken)
            .where(PushToken.provider == PushProvider.expo, PushToken.token.in_(dead))
            .values(disabled_at=utcnow())
        )
    failed = [ticket for ticket in tickets if not ticket.ok]
    if failed:
        logger.warning(
            "push tickets with errors",
            extra={"errors": sorted({ticket.error or "unknown" for ticket in failed})},
        )
    return tickets
