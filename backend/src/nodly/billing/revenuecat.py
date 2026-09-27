"""RevenueCat, the only source of truth about store purchases (CLAUDE.md §10).

Two ways in, one shape out (`StorePurchase`):
- the REST API v1 `GET /subscribers/{app_user_id}` (secret key), which the app triggers through
  /access/refresh after a purchase: https://www.revenuecat.com/docs/api-v1/customers
- webhooks: https://www.revenuecat.com/docs/integrations/webhooks and their fields,
  https://www.revenuecat.com/docs/integrations/webhooks/event-types-and-fields
"""

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from nodly.config import Settings
from nodly.errors import ServiceUnavailableError
from nodly.models import PurchaseKind


class BillingNotConfiguredError(ServiceUnavailableError):
    code = "billing_not_configured"
    title = "Purchases can't be checked right now"


class BillingUnavailableError(ServiceUnavailableError):
    code = "billing_unavailable"
    title = "RevenueCat didn't answer"


@dataclass(frozen=True)
class StorePurchase:
    """One store transaction as RevenueCat reports it, normalised."""

    app_user_id: str
    store: str  # upper case, as webhooks spell it: TEST_STORE, PLAY_STORE, APP_STORE, ...
    environment: str  # SANDBOX | PRODUCTION
    product_id: str
    kind: PurchaseKind
    transaction_id: str
    purchased_at: datetime  # whole seconds
    expires_at: datetime | None = None
    refunded_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def product_kind(product_id: str, settings: Settings) -> PurchaseKind | None:
    """Only our Plus products count; anything else is ignored."""
    if product_id in settings.day_pass_product_ids:
        return PurchaseKind.day_pass
    if product_id in settings.plus_subscription_product_ids:
        return PurchaseKind.subscription
    return None


def _seconds(at: datetime) -> datetime:
    return at.astimezone(UTC).replace(microsecond=0)


def _iso(value: Any) -> datetime | None:
    if not value:
        return None
    return _seconds(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def _ms(value: Any) -> datetime | None:
    if value is None:
        return None
    return _seconds(datetime.fromtimestamp(int(value) / 1000, tz=UTC))


def purchases_from_subscriber(
    body: dict[str, Any], app_user_id: str, settings: Settings
) -> list[StorePurchase]:
    """The Plus purchases in a REST v1 Customer Info response."""
    subscriber = body.get("subscriber") or {}
    found: list[StorePurchase] = []
    for product_id, items in (subscriber.get("non_subscriptions") or {}).items():
        if product_kind(product_id, settings) != PurchaseKind.day_pass:
            continue
        for item in items:
            purchased_at = _iso(item.get("purchase_date"))
            if purchased_at is None:
                continue
            found.append(
                StorePurchase(
                    app_user_id=app_user_id,
                    store=str(item.get("store", "unknown")).upper(),
                    environment="SANDBOX" if item.get("is_sandbox") else "PRODUCTION",
                    product_id=product_id,
                    kind=PurchaseKind.day_pass,
                    # The store's id when RevenueCat gives it (webhooks use the same one).
                    transaction_id=str(item.get("store_transaction_id") or item["id"]),
                    purchased_at=purchased_at,
                    raw=item,
                )
            )
    for product_id, item in (subscriber.get("subscriptions") or {}).items():
        if product_kind(product_id, settings) != PurchaseKind.subscription:
            continue
        purchased_at = _iso(item.get("purchase_date"))
        expires_at = _iso(item.get("expires_date"))
        if purchased_at is None or expires_at is None:
            continue
        # The latest paid period only; each renewal is a new transaction and a new grant.
        transaction_id = item.get("store_transaction_id") or (
            f"{product_id}@{int(purchased_at.timestamp())}"
        )
        found.append(
            StorePurchase(
                app_user_id=app_user_id,
                store=str(item.get("store", "unknown")).upper(),
                environment="SANDBOX" if item.get("is_sandbox") else "PRODUCTION",
                product_id=product_id,
                kind=PurchaseKind.subscription,
                transaction_id=str(transaction_id),
                purchased_at=purchased_at,
                expires_at=expires_at,
                refunded_at=_iso(item.get("refunded_at")),
                raw=item,
            )
        )
    return found


# Events that mean "money changed hands for this period / pass".
PURCHASE_EVENTS = {"INITIAL_PURCHASE", "RENEWAL", "NON_RENEWING_PURCHASE"}


def purchase_from_event(event: dict[str, Any], settings: Settings) -> StorePurchase | None:
    """The purchase a webhook is about: a new pass or paid period, or a refund of one. A refund
    carries the same transaction fields, so one that arrives before its purchase still
    records it (as refunded) and the late purchase event can't grant anything."""
    refund = is_refund(event)
    if event.get("type") not in PURCHASE_EVENTS and not refund:
        return None
    product_id = str(event.get("product_id") or "")
    kind = product_kind(product_id, settings)
    purchased_at = _ms(event.get("purchased_at_ms"))
    if kind is None or purchased_at is None or not event.get("transaction_id"):
        return None
    expires_at = _ms(event.get("expiration_at_ms"))
    if kind == PurchaseKind.subscription and expires_at is None:
        return None
    return StorePurchase(
        app_user_id=str(event.get("app_user_id") or ""),
        store=str(event.get("store") or "unknown").upper(),
        environment=str(event.get("environment") or "PRODUCTION").upper(),
        product_id=product_id,
        kind=kind,
        transaction_id=str(event["transaction_id"]),
        purchased_at=purchased_at,
        expires_at=expires_at if kind == PurchaseKind.subscription else None,
        refunded_at=(_ms(event.get("event_timestamp_ms")) or purchased_at) if refund else None,
        raw=event,
    )


def is_refund(event: dict[str, Any]) -> bool:
    """A CANCELLATION for a refund (cancel_reason CUSTOMER_SUPPORT), as opposed to someone
    turning off auto-renew, which keeps access until the period ends."""
    return event.get("type") == "CANCELLATION" and event.get("cancel_reason") == "CUSTOMER_SUPPORT"


def webhook_is_authentic(
    settings: Settings, authorization: str | None, signature: str | None, body: bytes
) -> bool:
    """The Authorization header must match the one set in RevenueCat's dashboard; if an HMAC
    signing secret is configured, the signature over the raw body must match too."""
    expected = settings.revenuecat_webhook_authorization
    if expected is None or authorization is None:
        return False
    if not hmac.compare_digest(authorization.encode(), expected.get_secret_value().encode()):
        return False
    secret = settings.revenuecat_webhook_signing_secret
    if secret is None:
        return True
    if not signature:
        return False
    try:
        parts = dict(part.split("=", 1) for part in signature.split(","))
        timestamp, given = parts["t"], parts["v1"]
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except (KeyError, ValueError):
        return False
    computed = hmac.new(
        secret.get_secret_value().encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, given)


class RevenueCatApi(Protocol):
    async def subscriber(self, app_user_id: str) -> dict[str, Any]: ...


class HttpRevenueCat:
    def __init__(self, settings: Settings) -> None:
        assert settings.revenuecat_secret_api_key is not None
        self._url = settings.revenuecat_api_url.rstrip("/")
        self._key = settings.revenuecat_secret_api_key.get_secret_value()

    async def subscriber(self, app_user_id: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self._url}/subscribers/{quote(app_user_id, safe='')}",
                    headers={"Authorization": f"Bearer {self._key}"},
                )
        except httpx.HTTPError as error:
            raise BillingUnavailableError("Couldn't reach RevenueCat.") from error
        if response.status_code not in (200, 201):
            raise BillingUnavailableError(f"RevenueCat answered {response.status_code}.")
        return response.json()  # type: ignore[no-any-return]


# Tests put a fake here.
_fake: RevenueCatApi | None = None


def revenuecat_api(settings: Settings) -> RevenueCatApi:
    if _fake is not None:
        return _fake
    if settings.revenuecat_secret_api_key is None:
        raise BillingNotConfiguredError("REVENUECAT_SECRET_API_KEY isn't set on the server.")
    return HttpRevenueCat(settings)
