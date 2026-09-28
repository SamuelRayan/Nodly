"""Nodly Plus (CLAUDE.md §10): store purchases, the access-grant ledger, and RevenueCat webhook
events. A family has Plus at time t if any non-revoked grant covers t; nothing else decides."""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from nodly.models.base import Base, CreatedAt, UUIDPrimaryKey, one_of


class PurchaseKind(StrEnum):
    day_pass = "day_pass"  # consumable: 24 hours from the confirmed purchase time
    subscription = "subscription"  # Nodly Plus monthly / annual: one row per paid period


class PurchaseSource(StrEnum):
    webhook = "webhook"  # RevenueCat told us
    refresh = "refresh"  # we asked RevenueCat's REST API (the app polls after buying)


class Purchase(UUIDPrimaryKey, CreatedAt, Base):
    """One store transaction, as confirmed by RevenueCat (never by the app)."""

    __tablename__ = "purchases"
    __table_args__ = (
        one_of("kind", PurchaseKind, "kind"),
        one_of("source", PurchaseSource, "source"),
        # Idempotency: the same transaction arrives by webhook, by refresh, and by retries.
        UniqueConstraint("store", "transaction_id"),
        # Belt and braces for a webhook and a refresh that name the transaction differently.
        UniqueConstraint("store", "app_user_id", "product_id", "purchased_at"),
    )

    # Null until we know which family it's for (a webhook without the family attribute); the
    # purchaser's next /access/refresh claims it.
    family_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    app_user_id: Mapped[str] = mapped_column(Text)  # RevenueCat's App User ID (= our user id)
    store: Mapped[str] = mapped_column(Text)  # TEST_STORE, PLAY_STORE, APP_STORE, GALAXY, ...
    environment: Mapped[str] = mapped_column(Text)  # SANDBOX | PRODUCTION
    product_id: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    transaction_id: Mapped[str] = mapped_column(Text)
    # Whole seconds: RevenueCat's REST API reports seconds, webhooks milliseconds.
    purchased_at: Mapped[datetime]
    expires_at: Mapped[datetime | None]  # subscriptions: the end of this paid period
    refunded_at: Mapped[datetime | None]
    source: Mapped[str] = mapped_column(Text)
    raw: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))


class GrantSource(StrEnum):
    moment = "moment"  # a qualifying moment on family-clock day D: D and D+1
    day_pass = "day_pass"
    subscription = "subscription"
    goodwill = "goodwill"  # compensation or support


class AccessGrant(UUIDPrimaryKey, CreatedAt, Base):
    """The ledger: [starts_at, ends_at) of Plus for a family. Never edited except to revoke."""

    __tablename__ = "access_grants"
    __table_args__ = (
        one_of("source", GrantSource, "source"),
        CheckConstraint("ends_at > starts_at", name="ends_after_start"),
        CheckConstraint(
            "source <> 'moment' OR local_date IS NOT NULL",
            name="moment_credit_has_its_day",
        ),
        CheckConstraint(
            "source NOT IN ('day_pass', 'subscription') OR purchase_id IS NOT NULL",
            name="purchase_grant_has_its_purchase",
        ),
        # §10: one moment credit per family and day; extra moments don't stack.
        Index(
            "uq_access_grants_moment_day",
            "family_id",
            "local_date",
            unique=True,
            postgresql_where=text("source = 'moment'"),
        ),
        # One grant per purchase.
        Index(
            "uq_access_grants_purchase",
            "purchase_id",
            unique=True,
            postgresql_where=text("purchase_id IS NOT NULL"),
        ),
        Index("ix_access_grants_family_window", "family_id", "ends_at"),
    )

    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    local_date: Mapped[date | None]  # moment credits: day D on the family clock
    # A deleted moment keeps the day it earned.
    moment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("moments.id", ondelete="SET NULL")
    )
    purchase_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("purchases.id", ondelete="CASCADE")
    )
    note: Mapped[str | None] = mapped_column(Text)
    revoked_at: Mapped[datetime | None]
    revoke_reason: Mapped[str | None] = mapped_column(Text)


class ReportReason(StrEnum):
    wrong_charge = "wrong_charge"
    plus_not_working = "plus_not_working"
    missing_purchase = "missing_purchase"
    other = "other"


class BillingReport(UUIDPrimaryKey, CreatedAt, Base):
    """ "Report a problem" on the billing timeline (§10). No workflow yet (Next Gen scope):
    it's stored so support can find it, and logged to the audit trail when it's filed."""

    __tablename__ = "billing_reports"
    __table_args__ = (
        one_of("reason", ReportReason, "reason"),
        Index("ix_billing_reports_family_id_created_at", "family_id", "created_at"),
    )

    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reason: Mapped[str] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)


class RevenueCatEvent(Base):
    """Every webhook delivery we accepted, once (RevenueCat retries reuse the event id)."""

    __tablename__ = "revenuecat_events"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    type: Mapped[str] = mapped_column(Text)
    app_user_id: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    outcome: Mapped[str] = mapped_column(Text)  # what we did with it, for the audit trail
    payload: Mapped[dict[str, Any]]
