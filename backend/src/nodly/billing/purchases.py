"""Confirmed store purchases → access grants (CLAUDE.md §10). Every step is idempotent: the
same transaction can arrive by webhook, by refresh, twice, or out of order (a refund before
its purchase), and the ledger ends up the same."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.billing.revenuecat import (
    StorePurchase,
    purchase_from_event,
    purchases_from_subscriber,
    revenuecat_api,
)
from nodly.config import Settings
from nodly.models import (
    AccessGrant,
    FamilyMember,
    GrantSource,
    Purchase,
    PurchaseKind,
    PurchaseSource,
    User,
)


async def record_purchase(
    session: AsyncSession,
    settings: Settings,
    found: StorePurchase,
    *,
    family_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    source: PurchaseSource,
    now: datetime,
) -> Purchase | None:
    """Store the purchase once, attach it to a family if it has none yet (the first family
    wins), and keep its grant in step: granted once, revoked if refunded. None for sandbox
    purchases where they aren't accepted. Doesn't commit."""
    if found.environment != "PRODUCTION" and not settings.billing_accept_sandbox:
        return None
    await session.execute(
        insert(Purchase)
        .values(
            id=uuid.uuid4(),
            family_id=family_id,
            user_id=user_id,
            app_user_id=found.app_user_id,
            store=found.store,
            environment=found.environment,
            product_id=found.product_id,
            kind=found.kind,
            transaction_id=found.transaction_id,
            purchased_at=found.purchased_at,
            expires_at=found.expires_at,
            refunded_at=found.refunded_at,
            source=source,
            raw=found.raw,
        )
        .on_conflict_do_nothing()  # any of the unique keys: it's already here
    )
    purchase = await session.scalar(
        select(Purchase).where(
            Purchase.store == found.store,
            or_(
                Purchase.transaction_id == found.transaction_id,
                and_(
                    Purchase.app_user_id == found.app_user_id,
                    Purchase.product_id == found.product_id,
                    Purchase.purchased_at == found.purchased_at,
                ),
            ),
        )
    )
    assert purchase is not None
    if purchase.family_id is None and family_id is not None:
        purchase.family_id = family_id
    if purchase.user_id is None and user_id is not None:
        purchase.user_id = user_id
    if purchase.refunded_at is None and found.refunded_at is not None:
        purchase.refunded_at = found.refunded_at
    await session.flush()
    await _sync_grant(session, settings, purchase, now)
    return purchase


def _window(settings: Settings, purchase: Purchase) -> tuple[datetime, datetime] | None:
    if purchase.kind == PurchaseKind.day_pass:
        # §10: 24 hours from the purchase time RevenueCat confirmed.
        return purchase.purchased_at, purchase.purchased_at + timedelta(
            hours=settings.day_pass_hours
        )
    if purchase.expires_at is not None and purchase.expires_at > purchase.purchased_at:
        return purchase.purchased_at, purchase.expires_at
    return None


async def _sync_grant(
    session: AsyncSession, settings: Settings, purchase: Purchase, now: datetime
) -> None:
    window = _window(settings, purchase)
    if purchase.family_id is None or window is None:
        return
    await session.execute(
        insert(AccessGrant)
        .values(
            id=uuid.uuid4(),
            family_id=purchase.family_id,
            source=GrantSource.day_pass
            if purchase.kind == PurchaseKind.day_pass
            else GrantSource.subscription,
            starts_at=window[0],
            ends_at=window[1],
            purchase_id=purchase.id,
        )
        .on_conflict_do_nothing(
            index_elements=[AccessGrant.purchase_id],
            index_where=text("purchase_id IS NOT NULL"),
        )
    )
    if purchase.refunded_at is not None:
        await session.execute(
            update(AccessGrant)
            .where(AccessGrant.purchase_id == purchase.id, AccessGrant.revoked_at.is_(None))
            .values(revoked_at=now, revoke_reason="refunded")
        )


async def _user_for(session: AsyncSession, event: dict[str, Any]) -> uuid.UUID | None:
    """Our user, from the App User ID (the app logs in to RevenueCat with our user id) or one
    of its aliases (a purchase made before logging in)."""
    candidates = [event.get("app_user_id"), event.get("original_app_user_id")]
    candidates += list(event.get("aliases") or [])
    for candidate in candidates:
        try:
            user_id = uuid.UUID(str(candidate))
        except ValueError:
            continue
        if await session.get(User, user_id) is not None:
            return user_id
    return None


async def _family_for(
    session: AsyncSession, event: dict[str, Any], user_id: uuid.UUID | None
) -> uuid.UUID | None:
    """The family the app set on the customer (`family_id` attribute) if the purchaser is a
    member of it; otherwise their only family. Unknown → the purchase waits for a refresh."""
    if user_id is None:
        return None
    families = set(
        await session.scalars(select(FamilyMember.family_id).where(FamilyMember.user_id == user_id))
    )
    attribute = ((event.get("subscriber_attributes") or {}).get("family_id") or {}).get("value")
    try:
        chosen = uuid.UUID(str(attribute)) if attribute else None
    except ValueError:
        chosen = None
    if chosen in families:
        return chosen
    return next(iter(families)) if len(families) == 1 else None


async def apply_event(
    session: AsyncSession, settings: Settings, event: dict[str, Any], now: datetime
) -> str:
    """Act on one webhook event. Returns what happened, for the event log. Doesn't commit."""
    if event.get("type") == "TEST":
        return "test"
    found = purchase_from_event(event, settings)
    if found is None:
        return "ignored"
    user_id = await _user_for(session, event)
    family_id = await _family_for(session, event, user_id)
    purchase = await record_purchase(
        session,
        settings,
        found,
        family_id=family_id,
        user_id=user_id,
        source=PurchaseSource.webhook,
        now=now,
    )
    if purchase is None:
        return "sandbox_not_accepted"
    if purchase.refunded_at is not None:
        return "refunded"
    return "granted" if purchase.family_id else "waiting_for_family"


async def refresh_from_revenuecat(
    session: AsyncSession, settings: Settings, family_id: uuid.UUID, user: User, now: datetime
) -> int:
    """Ask RevenueCat for this user's purchases and record them; any not yet tied to a family
    are for this one. Returns how many Plus purchases RevenueCat listed. Doesn't commit."""
    body = await revenuecat_api(settings).subscriber(str(user.id))
    found = purchases_from_subscriber(body, str(user.id), settings)
    for purchase in found:
        await record_purchase(
            session,
            settings,
            purchase,
            family_id=family_id,
            user_id=user.id,
            source=PurchaseSource.refresh,
            now=now,
        )
    return len(found)
