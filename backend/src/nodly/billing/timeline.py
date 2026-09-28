"""The billing timeline (CLAUDE.md §10): "why do I have / not have Plus, what was charged,
when", plus "Report a problem". Read-only assembly over the ledger already built in access.py
and purchases.py — friendly wording is the app's job (it already turns other codes into
copy, e.g. moments' reject/not-qualifying reasons)."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.models import (
    AccessGrant,
    BillingReport,
    Elder,
    ElderDevice,
    Moment,
    Purchase,
    ReportReason,
    User,
)

DEFAULT_LIMIT = 100


@dataclass(frozen=True)
class TimelineEntry:
    id: uuid.UUID
    source: str  # moment | day_pass | subscription | goodwill
    starts_at: datetime
    ends_at: datetime
    revoked_at: datetime | None
    revoke_reason: str | None
    note: str | None  # goodwill only
    # source == "moment"
    moment_kind: str | None
    moment_author_name: str | None
    # source in (day_pass, subscription)
    product_id: str | None
    store: str | None
    environment: str | None  # SANDBOX | PRODUCTION: the app can label test purchases
    purchased_at: datetime | None
    refunded_at: datetime | None


async def billing_timeline(
    session: AsyncSession, family_id: uuid.UUID, limit: int = DEFAULT_LIMIT
) -> list[TimelineEntry]:
    grants = list(
        await session.scalars(
            select(AccessGrant)
            .where(AccessGrant.family_id == family_id)
            .order_by(AccessGrant.starts_at.desc())
            .limit(limit)
        )
    )
    moment_ids = {grant.moment_id for grant in grants if grant.moment_id}
    purchase_ids = {grant.purchase_id for grant in grants if grant.purchase_id}

    moments: dict[uuid.UUID, Moment] = {}
    author_names: dict[uuid.UUID, str | None] = {}
    if moment_ids:
        moments = {
            moment.id: moment
            for moment in await session.scalars(select(Moment).where(Moment.id.in_(moment_ids)))
        }
        user_ids = {m.author_user_id for m in moments.values() if m.author_user_id}
        if user_ids:
            rows = await session.execute(
                select(User.id, User.display_name).where(User.id.in_(user_ids))
            )
            author_names.update(dict(rows.all()))
        device_ids = {m.author_device_id for m in moments.values() if m.author_device_id}
        if device_ids:
            rows = await session.execute(
                select(ElderDevice.id, Elder.relation_label, Elder.display_name)
                .join(Elder, Elder.id == ElderDevice.elder_id)
                .where(ElderDevice.id.in_(device_ids))
            )
            author_names.update({device: label or name for device, label, name in rows})

    purchases: dict[uuid.UUID, Purchase] = {}
    if purchase_ids:
        purchases = {
            purchase.id: purchase
            for purchase in await session.scalars(
                select(Purchase).where(Purchase.id.in_(purchase_ids))
            )
        }

    entries = []
    for grant in grants:
        moment = moments.get(grant.moment_id) if grant.moment_id else None
        purchase = purchases.get(grant.purchase_id) if grant.purchase_id else None
        author = None
        if moment:
            key = moment.author_user_id or moment.author_device_id
            author = author_names.get(key) if key else None
        entries.append(
            TimelineEntry(
                id=grant.id,
                source=grant.source,
                starts_at=grant.starts_at,
                ends_at=grant.ends_at,
                revoked_at=grant.revoked_at,
                revoke_reason=grant.revoke_reason,
                note=grant.note,
                moment_kind=moment.kind if moment else None,
                moment_author_name=author,
                product_id=purchase.product_id if purchase else None,
                store=purchase.store if purchase else None,
                environment=purchase.environment if purchase else None,
                purchased_at=purchase.purchased_at if purchase else None,
                refunded_at=purchase.refunded_at if purchase else None,
            )
        )
    return entries


async def file_report(
    session: AsyncSession,
    *,
    family_id: uuid.UUID,
    user_id: uuid.UUID,
    reason: ReportReason,
    message: str | None,
) -> BillingReport:
    """ "Report a problem" (§10): stored for support to find, and logged to the audit trail.
    Doesn't commit."""
    report = BillingReport(family_id=family_id, user_id=user_id, reason=reason, message=message)
    session.add(report)
    return report
