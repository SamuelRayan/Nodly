"""Nodly Plus for a family (CLAUDE.md §10): whether it's on and why, the Day Pass offer, the
post-purchase refresh, and RevenueCat's webhook. Family members only: an elder's phone has no
access to any of this (§1: elders never see purchase UI)."""

import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert

from nodly.api.common import USER_AUTH_ERRORS, SettingsDep, problems
from nodly.audit import record_audit
from nodly.auth.access import MemberAccess
from nodly.billing.access import (
    DayPassOffer,
    day_pass_offer,
    evaluate_access,
    today_moment,
)
from nodly.billing.purchases import apply_event, refresh_from_revenuecat
from nodly.billing.revenuecat import webhook_is_authentic
from nodly.billing.timeline import billing_timeline, file_report
from nodly.clock import utcnow
from nodly.db import SessionDep
from nodly.errors import InvalidInputError, UnauthorizedError
from nodly.models import ActorType, ReportReason, RevenueCatEvent

router = APIRouter(tags=["billing"])


class TodayMomentOut(BaseModel):
    local_date: date | None = Field(description="Today on the family clock (null: no elder yet)")
    timezone: str | None
    shared: bool = Field(description="A qualifying moment already earned today")
    pending: bool = Field(description="A family member's moment is on its way; it may still count")


class DayPassOut(BaseModel):
    offered: bool
    reason: str | None = Field(description="Why not: has_plus | moment_pending")


class AccessOut(BaseModel):
    has_plus: bool
    sources: list[str] = Field(description="What gives Plus now: moment, day_pass, subscription")
    plus_until: datetime | None = Field(description="When the current run of Plus ends")
    today: TodayMomentOut
    day_pass: DayPassOut
    checked_at: datetime = Field(description="The server's clock when this was decided")


async def _access_out(session: SessionDep, access: MemberAccess) -> AccessOut:
    now = utcnow()
    state = await evaluate_access(session, access.family.id, now)
    today = await today_moment(session, access.family.id, now)
    offer: DayPassOffer = day_pass_offer(state, today)
    return AccessOut(
        has_plus=state.has_plus,
        sources=state.sources,
        plus_until=state.plus_until,
        today=TodayMomentOut(
            local_date=today.local_date,
            timezone=today.timezone,
            shared=today.shared,
            pending=today.pending,
        ),
        day_pass=DayPassOut(offered=offer.offered, reason=offer.reason),
        checked_at=now,
    )


AUTH = problems(*USER_AUTH_ERRORS, 404)


@router.get("/v1/families/{family_id}/access", responses=AUTH)
async def family_access(access: MemberAccess, session: SessionDep) -> AccessOut:
    """Does this family have Plus right now, why, until when, and is a Day Pass on offer.
    The app polls this after a purchase; it never unlocks anything by itself."""
    return await _access_out(session, access)


@router.get("/v1/families/{family_id}/access/day-pass-eligibility", responses=AUTH)
async def day_pass_eligibility(access: MemberAccess, session: SessionDep) -> DayPassOut:
    """§10: offered only without Plus, and without a moment on its way that would unlock
    today for free."""
    return (await _access_out(session, access)).day_pass


@router.post("/v1/families/{family_id}/access/refresh", responses=AUTH)
async def refresh_access(
    access: MemberAccess, session: SessionDep, settings: SettingsDep
) -> AccessOut:
    """After a purchase: ask RevenueCat (server to server) for this member's purchases, record
    any new ones for this family, then answer like GET .../access. Safe to repeat."""
    await refresh_from_revenuecat(session, settings, access.family.id, access.user, utcnow())
    await session.commit()
    return await _access_out(session, access)


class TimelineEntryOut(BaseModel):
    id: uuid.UUID
    source: str = Field(description="moment | day_pass | subscription | goodwill")
    starts_at: datetime
    ends_at: datetime
    revoked_at: datetime | None
    revoke_reason: str | None
    note: str | None = Field(description="A goodwill grant's note, if any")
    moment_kind: str | None = Field(description="source == moment: photo | voice | video")
    moment_author_name: str | None
    product_id: str | None = Field(description="source in (day_pass, subscription)")
    store: str | None
    environment: str | None = Field(description="SANDBOX | PRODUCTION")
    purchased_at: datetime | None
    refunded_at: datetime | None


class BillingTimelineOut(BaseModel):
    access: AccessOut = Field(description="Why Plus is (or isn't) on right now")
    entries: list[TimelineEntryOut] = Field(description="Newest first")


@router.get("/v1/families/{family_id}/billing/timeline", responses=AUTH)
async def get_billing_timeline(access: MemberAccess, session: SessionDep) -> BillingTimelineOut:
    """ "Why do I have / not have Plus, what was charged, when" (§10)."""
    entries = await billing_timeline(session, access.family.id)
    return BillingTimelineOut(
        access=await _access_out(session, access),
        entries=[
            TimelineEntryOut(
                id=e.id,
                source=e.source,
                starts_at=e.starts_at,
                ends_at=e.ends_at,
                revoked_at=e.revoked_at,
                revoke_reason=e.revoke_reason,
                note=e.note,
                moment_kind=e.moment_kind,
                moment_author_name=e.moment_author_name,
                product_id=e.product_id,
                store=e.store,
                environment=e.environment,
                purchased_at=e.purchased_at,
                refunded_at=e.refunded_at,
            )
            for e in entries
        ],
    )


class ReportIn(BaseModel):
    reason: Literal["wrong_charge", "plus_not_working", "missing_purchase", "other"]
    message: str | None = Field(default=None, max_length=2000)


class ReportOut(BaseModel):
    id: uuid.UUID
    reason: str
    created_at: datetime


@router.post(
    "/v1/families/{family_id}/billing/report",
    status_code=201,
    responses=problems(*USER_AUTH_ERRORS, 404, 422),
)
async def report_billing_problem(
    body: ReportIn, access: MemberAccess, session: SessionDep
) -> ReportOut:
    """ "Report a problem" on the billing timeline (§10): stored, and logged to the audit
    trail. No automatic action; a person follows up."""
    report = await file_report(
        session,
        family_id=access.family.id,
        user_id=access.user.id,
        reason=ReportReason(body.reason),
        message=body.message,
    )
    await session.flush()
    record_audit(
        session,
        actor_type=ActorType.user,
        actor_id=access.user.id,
        family_id=access.family.id,
        action="billing.report",
        entity_type="billing_report",
        entity_id=report.id,
        data={"reason": body.reason, "message": body.message},
    )
    await session.commit()
    return ReportOut(id=report.id, reason=report.reason, created_at=report.created_at)


class WebhookOut(BaseModel):
    outcome: str


class NotRevenueCatError(UnauthorizedError):
    code = "webhook_unauthorized"
    title = "Not a RevenueCat webhook"


@router.post(
    "/v1/billing/revenuecat/webhook",
    responses=problems(401, 422),
)
async def revenuecat_webhook(
    request: Request, session: SessionDep, settings: SettingsDep
) -> WebhookOut:
    """RevenueCat's events (purchases, renewals, refunds). Checked against the Authorization
    header set in RevenueCat's dashboard (and its HMAC signature when configured). Each event
    id is handled once; RevenueCat's retries are answered without doing anything again."""
    body = await request.body()
    if not webhook_is_authentic(
        settings,
        request.headers.get("authorization"),
        request.headers.get("x-revenuecat-webhook-signature"),
        body,
    ):
        raise NotRevenueCatError("Unknown webhook sender.")
    try:
        event = (await request.json())["event"]
        event_id = str(event["id"])
    except (ValueError, KeyError, TypeError) as error:
        raise InvalidInputError("Not a RevenueCat event.") from error

    stored = await session.scalar(
        insert(RevenueCatEvent)
        .values(
            id=event_id,
            type=str(event.get("type")),
            app_user_id=event.get("app_user_id"),
            outcome="received",
            payload=event,
        )
        .on_conflict_do_nothing()
        .returning(RevenueCatEvent.id)
    )
    if stored is None:
        return WebhookOut(outcome="duplicate")
    outcome = await apply_event(session, settings, event, utcnow())
    row = await session.get(RevenueCatEvent, event_id)
    assert row is not None
    row.outcome = outcome
    # All or nothing: if anything above failed, nothing is stored and RevenueCat retries.
    await session.commit()
    return WebhookOut(outcome=outcome)
