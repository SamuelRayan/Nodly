"""Nodly Plus (CLAUDE.md §10): the grant ledger, moment credits, Day Passes and subscriptions
through RevenueCat (webhook and refresh), refunds, and the Plus-only check-in history."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
import time_machine
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import nodly.billing.revenuecat
from nodly.billing.access import evaluate_access, moment_credit_window
from nodly.config import Settings
from nodly.models import AccessGrant, Checkin, FamilyRole, Purchase, RevenueCatEvent
from tests.conftest import TEST_SUPABASE_URL, app_client, make_settings
from tests.fake_supabase import FakeSupabase, SupabaseUser
from tests.support import make_family, make_member
from tests.test_checkins import Home, device_headers, signed_in_home
from tests.test_moments import INTENT, ok, photo, run_jobs, share

# 06:00Z on 26 Sep is 11:30 on the family clock (Asia/Kolkata).
T = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)
WEBHOOK_AUTH = "Bearer rc-webhook-test"


def ms(at: datetime) -> int:
    return int(at.timestamp() * 1000)


def iso(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeRevenueCat:
    """RevenueCat's REST API v1 GET /subscribers, as far as we read it."""

    def __init__(self) -> None:
        self.non_subscriptions: dict[str, list[dict[str, Any]]] = {}
        self.subscriptions: dict[str, dict[str, Any]] = {}
        self.calls: list[str] = []

    def day_pass(self, transaction_id: str, at: datetime, *, sandbox: bool = True) -> None:
        self.non_subscriptions.setdefault("day_pass", []).append(
            {
                "id": f"rc-{transaction_id}",
                "store_transaction_id": transaction_id,
                "is_sandbox": sandbox,
                "purchase_date": iso(at),
                "store": "test_store",
            }
        )

    async def subscriber(self, app_user_id: str) -> dict[str, Any]:
        self.calls.append(app_user_id)
        return {
            "request_date": iso(T),
            "subscriber": {
                "non_subscriptions": self.non_subscriptions,
                "subscriptions": self.subscriptions,
                "entitlements": {},
            },
        }


@pytest.fixture
def settings(test_database_url: str, tmp_path: Path) -> Settings:
    return make_settings(
        test_database_url,
        push_provider="record",
        media_dir=str(tmp_path / "media"),
        revenuecat_webhook_authorization=WEBHOOK_AUTH,
    )


@pytest.fixture
async def api(
    settings: Settings, clean_db: AsyncEngine, fake_supabase: FakeSupabase
) -> AsyncIterator[httpx.AsyncClient]:
    async with app_client(settings, fake_supabase) as client:
        yield client


@pytest.fixture
def revenuecat(monkeypatch: pytest.MonkeyPatch) -> FakeRevenueCat:
    fake = FakeRevenueCat()
    monkeypatch.setattr(nodly.billing.revenuecat, "_fake", fake)
    return fake


def event(kind: str, user: uuid.UUID, **fields: Any) -> dict[str, Any]:
    """A webhook body. Defaults: a Test Store Day Pass bought at T."""
    body = {
        "id": uuid.uuid4().hex,
        "type": kind,
        "app_user_id": str(user),
        "original_app_user_id": str(user),
        "aliases": [str(user)],
        "product_id": "day_pass",
        "store": "TEST_STORE",
        "environment": "SANDBOX",
        "transaction_id": "tx-1",
        "purchased_at_ms": ms(T),
        "event_timestamp_ms": ms(T),
    }
    return {"api_version": "1.0", "event": body | fields}


async def hook(
    api: httpx.AsyncClient, body: dict[str, Any], auth: str | None = WEBHOOK_AUTH
) -> httpx.Response:
    headers = {"Authorization": auth} if auth else {}
    return await api.post("/v1/billing/revenuecat/webhook", json=body, headers=headers)


async def access(
    api: httpx.AsyncClient, home: Home, person: SupabaseUser, at: datetime = T
) -> dict[str, Any]:
    with time_machine.travel(at, tick=False):
        return await ok(
            await api.get(f"/v1/families/{home.family.id}/access", headers=person.headers)
        )


async def refresh(
    api: httpx.AsyncClient, home: Home, person: SupabaseUser, at: datetime = T
) -> dict[str, Any]:
    with time_machine.travel(at, tick=False):
        return await ok(
            await api.post(f"/v1/families/{home.family.id}/access/refresh", headers=person.headers)
        )


async def count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


# ---------------------------------------------------------------- the ledger


@pytest.mark.parametrize(
    ("timezone", "day", "starts", "ends", "hours"),
    [
        ("Asia/Kolkata", date(2026, 9, 26), "2026-09-25T18:30", "2026-09-27T18:30", 48),
        # D+1 is the day New York falls back: 25 hours.
        ("America/New_York", date(2026, 10, 31), "2026-10-31T04:00", "2026-11-02T05:00", 49),
        # D+1 is the day Berlin springs forward: 23 hours.
        ("Europe/Berlin", date(2026, 3, 28), "2026-03-27T23:00", "2026-03-29T22:00", 47),
        # Santiago skips midnight on 6 Sep: the day starts at 01:00.
        ("America/Santiago", date(2026, 9, 6), "2026-09-06T04:00", "2026-09-08T03:00", 47),
        # +12:45 → +13:45 on D+1.
        ("Pacific/Chatham", date(2026, 9, 26), "2026-09-25T11:15", "2026-09-27T10:15", 47),
    ],
)
def test_a_moment_credit_covers_its_day_and_the_next(
    timezone: str, day: date, starts: str, ends: str, hours: int
) -> None:
    start, end = moment_credit_window(day, ZoneInfo(timezone))
    assert start == datetime.fromisoformat(starts).replace(tzinfo=UTC)
    assert end == datetime.fromisoformat(ends).replace(tzinfo=UTC)
    assert end - start == timedelta(hours=hours)


async def test_access_follows_unbroken_grants_and_ignores_revoked(
    session: AsyncSession, fake_supabase: FakeSupabase
) -> None:
    home, _, _ = await signed_in_home(session, fake_supabase)

    def goodwill(start: timedelta, end: timedelta, *, revoked: bool = False) -> AccessGrant:
        return AccessGrant(
            family_id=home.family.id,
            source="goodwill",
            starts_at=T + start,
            ends_at=T + end,
            revoked_at=T if revoked else None,
        )

    hour = timedelta(hours=1)
    session.add_all(
        [
            goodwill(-hour, hour),
            goodwill(hour / 2, 5 * hour),  # overlaps the first: the run continues
            goodwill(0 * hour, 10 * hour, revoked=True),
            goodwill(6 * hour, 7 * hour),  # after a gap
        ]
    )
    await session.commit()

    now = await evaluate_access(session, home.family.id, T)
    assert (now.has_plus, now.sources, now.plus_until) == (True, ["goodwill"], T + 5 * hour)
    assert (await evaluate_access(session, home.family.id, T + hour)).has_plus is True
    # Half-open: a grant ending at 11:00 doesn't cover 11:00; the revoked one never counts.
    assert (await evaluate_access(session, home.family.id, T + 5 * hour)).has_plus is False
    later = await evaluate_access(session, home.family.id, T + 6 * hour)
    assert later.plus_until == T + 7 * hour


# ---------------------------------------------------------------- moment credits


async def test_a_qualifying_moment_unlocks_its_day_and_the_next(
    api: httpx.AsyncClient,
    session: AsyncSession,
    clean_db: AsyncEngine,
    settings: Settings,
    fake_supabase: FakeSupabase,
) -> None:
    home, priya, arjun = await signed_in_home(session, fake_supabase)
    before = await access(api, home, priya, INTENT)
    assert before["has_plus"] is False and before["day_pass"] == {"offered": True, "reason": None}

    await share(api, home, priya, photo(1))  # 26 Sep on the family clock
    await share(api, home, arjun, photo(60), INTENT + timedelta(hours=1))  # doesn't stack
    await run_jobs(clean_db, settings)

    day = await access(api, home, arjun, INTENT + timedelta(hours=6))
    assert (day["has_plus"], day["sources"]) == (True, ["moment"])
    assert day["plus_until"] == "2026-09-27T18:30:00Z"  # the end of 27 Sep in Kolkata
    assert day["today"]["shared"] is True and day["today"]["local_date"] == "2026-09-26"
    assert day["day_pass"] == {"offered": False, "reason": "has_plus"}
    assert await count(session, AccessGrant) == 1

    # D+1 is still covered, but "today" has no moment yet; D+2 is locked again.
    next_day = await access(api, home, priya, datetime(2026, 9, 27, 12, 0, tzinfo=UTC))
    assert next_day["has_plus"] is True and next_day["today"]["shared"] is False
    over = await access(api, home, priya, datetime(2026, 9, 27, 18, 30, tzinfo=UTC))
    assert over["has_plus"] is False and over["day_pass"]["offered"] is True


async def test_a_moment_on_its_way_holds_back_the_day_pass(
    api: httpx.AsyncClient, session: AsyncSession, fake_supabase: FakeSupabase
) -> None:
    home, priya, _ = await signed_in_home(session, fake_supabase)
    with time_machine.travel(T, tick=False):
        # An elder's own photo never earns the day, so it doesn't hold anything back.
        await ok(
            await api.post(
                "/v1/device/moments",
                headers=device_headers(home),
                json={"kind": "photo", "content_type": "image/jpeg"},
            ),
            201,
        )
    assert (await access(api, home, priya))["day_pass"]["offered"] is True
    with time_machine.travel(T, tick=False):
        await ok(
            await api.post(
                f"/v1/families/{home.family.id}/moments",
                headers=priya.headers,
                json={"kind": "voice", "content_type": "audio/mp4"},
            ),
            201,
        )
    held = await access(api, home, priya)
    assert held["today"]["pending"] is True
    assert held["day_pass"] == {"offered": False, "reason": "moment_pending"}
    with time_machine.travel(T, tick=False):
        eligibility = await api.get(
            f"/v1/families/{home.family.id}/access/day-pass-eligibility", headers=priya.headers
        )
    assert (await ok(eligibility)) == {"offered": False, "reason": "moment_pending"}


# ---------------------------------------------------------------- Day Pass


async def test_a_day_pass_counts_only_once_revenuecat_confirms_it(
    api: httpx.AsyncClient,
    session: AsyncSession,
    fake_supabase: FakeSupabase,
    revenuecat: FakeRevenueCat,
) -> None:
    home, priya, _ = await signed_in_home(session, fake_supabase)
    # Nothing confirmed yet: refreshing changes nothing.
    assert (await refresh(api, home, priya))["has_plus"] is False

    bought = T - timedelta(minutes=1)
    revenuecat.day_pass("tx-1", bought)
    unlocked = await refresh(api, home, priya)
    assert (unlocked["has_plus"], unlocked["sources"]) == (True, ["day_pass"])
    assert unlocked["plus_until"] == iso(bought + timedelta(hours=24))
    # Again (the app polls): still one purchase, one grant.
    await refresh(api, home, priya)
    assert (await count(session, Purchase), await count(session, AccessGrant)) == (1, 1)
    assert revenuecat.calls == [str(home.organizer.id)] * 3
    purchase = await session.scalar(select(Purchase))
    assert purchase is not None and purchase.family_id == home.family.id
    assert (purchase.store, purchase.environment, purchase.source) == (
        "TEST_STORE",
        "SANDBOX",
        "refresh",
    )
    # 24 hours from the confirmed purchase time, not from when we heard about it.
    assert (await access(api, home, priya, bought + timedelta(hours=24)))["has_plus"] is False


async def test_refresh_needs_the_server_key(
    api: httpx.AsyncClient, session: AsyncSession, fake_supabase: FakeSupabase
) -> None:
    home, priya, _ = await signed_in_home(session, fake_supabase)
    response = await api.post(
        f"/v1/families/{home.family.id}/access/refresh", headers=priya.headers
    )
    assert (response.status_code, response.json()["code"]) == (503, "billing_not_configured")


async def test_a_webhook_and_a_refresh_grant_once(
    api: httpx.AsyncClient,
    session: AsyncSession,
    fake_supabase: FakeSupabase,
    revenuecat: FakeRevenueCat,
) -> None:
    home, priya, arjun = await signed_in_home(session, fake_supabase)
    body = event("NON_RENEWING_PURCHASE", home.member.id, transaction_id="tx-9")
    assert (await ok(await hook(api, body)))["outcome"] == "granted"
    assert (await ok(await hook(api, body)))["outcome"] == "duplicate"  # a retry
    # The same purchase through the REST API (a different RevenueCat id, same store id).
    revenuecat.day_pass("tx-9", T)
    await refresh(api, home, arjun)
    assert (await count(session, Purchase), await count(session, AccessGrant)) == (1, 1)
    assert (await count(session, RevenueCatEvent)) == 1
    day = await access(api, home, priya)
    assert (day["has_plus"], day["sources"]) == (True, ["day_pass"])


async def test_webhooks_only_from_revenuecat(
    api: httpx.AsyncClient, session: AsyncSession, fake_supabase: FakeSupabase
) -> None:
    home, _, _ = await signed_in_home(session, fake_supabase)
    body = event("NON_RENEWING_PURCHASE", home.member.id)
    for auth in (None, "Bearer guess"):
        response = await hook(api, body, auth)
        assert (response.status_code, response.json()["code"]) == (401, "webhook_unauthorized")
    assert (await hook(api, {"nope": 1})).status_code == 422
    assert await count(session, Purchase) == 0


async def test_a_webhook_finds_the_family(
    api: httpx.AsyncClient,
    session: AsyncSession,
    fake_supabase: FakeSupabase,
    revenuecat: FakeRevenueCat,
) -> None:
    home, _, arjun = await signed_in_home(session, fake_supabase)
    second = await make_family(session, name="Arjun's in-laws")
    await make_member(session, second, home.member, FamilyRole.organizer)
    await session.commit()

    # Two families and no attribute: it waits until Arjun's app refreshes from one of them.
    waiting = event("NON_RENEWING_PURCHASE", home.member.id, transaction_id="tx-a")
    assert (await ok(await hook(api, waiting)))["outcome"] == "waiting_for_family"
    revenuecat.day_pass("tx-a", T)
    assert (await refresh(api, home, arjun))["has_plus"] is True

    # The family the app set on the customer before buying.
    chosen = event(
        "NON_RENEWING_PURCHASE",
        home.member.id,
        transaction_id="tx-b",
        purchased_at_ms=ms(T + timedelta(minutes=5)),
        subscriber_attributes={"family_id": {"value": str(second.id)}},
    )
    assert (await ok(await hook(api, chosen)))["outcome"] == "granted"
    grant = await session.scalar(
        select(AccessGrant).join(Purchase).where(Purchase.transaction_id == "tx-b")
    )
    assert grant is not None and grant.family_id == second.id


async def test_refunds_take_it_back_even_out_of_order(
    api: httpx.AsyncClient, session: AsyncSession, fake_supabase: FakeSupabase
) -> None:
    home, priya, _ = await signed_in_home(session, fake_supabase)
    user = home.member.id
    await ok(await hook(api, event("NON_RENEWING_PURCHASE", user, transaction_id="tx-r")))
    # Turning off auto-renew isn't a refund.
    unsubscribed = event("CANCELLATION", user, transaction_id="tx-r", cancel_reason="UNSUBSCRIBE")
    assert (await ok(await hook(api, unsubscribed)))["outcome"] == "ignored"
    assert (await access(api, home, priya))["has_plus"] is True

    refund = event("CANCELLATION", user, transaction_id="tx-r", cancel_reason="CUSTOMER_SUPPORT")
    assert (await ok(await hook(api, refund)))["outcome"] == "refunded"
    assert (await access(api, home, priya))["has_plus"] is False
    grant = await session.scalar(select(AccessGrant))
    assert grant is not None and grant.revoke_reason == "refunded"

    # A refund that arrives before its purchase: the late purchase can't unlock anything.
    early = event(
        "CANCELLATION",
        user,
        transaction_id="tx-late",
        purchased_at_ms=ms(T + timedelta(minutes=10)),
        cancel_reason="CUSTOMER_SUPPORT",
    )
    assert (await ok(await hook(api, early)))["outcome"] == "refunded"
    late = event(
        "NON_RENEWING_PURCHASE",
        user,
        transaction_id="tx-late",
        purchased_at_ms=ms(T + timedelta(minutes=10)),
    )
    assert (await ok(await hook(api, late)))["outcome"] == "refunded"
    assert (await access(api, home, priya, T + timedelta(minutes=20)))["has_plus"] is False


async def test_a_moment_and_a_day_pass_on_the_same_day(
    api: httpx.AsyncClient,
    session: AsyncSession,
    clean_db: AsyncEngine,
    settings: Settings,
    fake_supabase: FakeSupabase,
) -> None:
    home, priya, _ = await signed_in_home(session, fake_supabase)
    bought = INTENT + timedelta(hours=1)
    await ok(
        await hook(api, event("NON_RENEWING_PURCHASE", home.member.id, purchased_at_ms=ms(bought)))
    )
    await share(api, home, priya, photo(2), INTENT + timedelta(hours=2))
    await run_jobs(clean_db, settings)
    both = await access(api, home, priya, INTENT + timedelta(hours=6))
    assert both["sources"] == ["day_pass", "moment"]
    # The moment's day (to the end of 27 Sep) outlasts the pass (to 21:00Z on 26 Sep).
    assert both["plus_until"] == "2026-09-27T18:30:00Z"


# ---------------------------------------------------------------- subscriptions


async def test_subscription_periods_follow_each_other(
    api: httpx.AsyncClient, session: AsyncSession, fake_supabase: FakeSupabase
) -> None:
    home, priya, _ = await signed_in_home(session, fake_supabase)
    month = timedelta(days=30)
    first = event(
        "INITIAL_PURCHASE",
        home.organizer.id,
        product_id="plus_monthly",
        transaction_id="sub-1",
        expiration_at_ms=ms(T + month),
    )
    renewal = event(
        "RENEWAL",
        home.organizer.id,
        product_id="plus_monthly",
        transaction_id="sub-2",
        purchased_at_ms=ms(T + month),
        expiration_at_ms=ms(T + 2 * month),
    )
    # Out of order on purpose: the renewal lands first.
    for body in (renewal, first):
        assert (await ok(await hook(api, body)))["outcome"] == "granted"
    now = await access(api, home, priya, T + timedelta(days=10))
    assert now["sources"] == ["subscription"]
    assert now["plus_until"] == iso(T + 2 * month)
    assert (await access(api, home, priya, T + 2 * month))["has_plus"] is False


async def test_sandbox_purchases_only_where_accepted(
    session: AsyncSession,
    clean_db: AsyncEngine,
    fake_supabase: FakeSupabase,
    tmp_path: Path,
    test_database_url: str,
) -> None:
    strict = make_settings(
        test_database_url,
        push_provider="record",
        media_dir=str(tmp_path / "m"),
        revenuecat_webhook_authorization=WEBHOOK_AUTH,
        billing_accept_sandbox=False,
    )
    async with app_client(strict, fake_supabase) as api:
        home, priya, _ = await signed_in_home(session, fake_supabase)
        sandbox = event("NON_RENEWING_PURCHASE", home.member.id)
        assert (await ok(await hook(api, sandbox)))["outcome"] == "sandbox_not_accepted"
        assert (await access(api, home, priya))["has_plus"] is False
        real = event(
            "NON_RENEWING_PURCHASE",
            home.member.id,
            store="PLAY_STORE",
            environment="PRODUCTION",
            transaction_id="GPA.1",
        )
        assert (await ok(await hook(api, real)))["outcome"] == "granted"


def test_prod_never_accepts_sandbox_purchases(test_database_url: str) -> None:
    prod = make_settings(test_database_url, env="prod", supabase_url=TEST_SUPABASE_URL)
    assert prod.billing_accept_sandbox is False
    with pytest.raises(ValueError, match="BILLING_ACCEPT_SANDBOX"):
        make_settings(
            test_database_url,
            env="prod",
            supabase_url=TEST_SUPABASE_URL,
            billing_accept_sandbox=True,
        )


# ---------------------------------------------------------------- who can see it


async def test_an_elders_phone_never_reaches_billing(
    api: httpx.AsyncClient, session: AsyncSession, fake_supabase: FakeSupabase
) -> None:
    home, _, _ = await signed_in_home(session, fake_supabase)
    phone = device_headers(home)
    base = f"/v1/families/{home.family.id}/access"
    for method, path in (
        ("GET", base),
        ("GET", f"{base}/day-pass-eligibility"),
        ("POST", f"{base}/refresh"),
    ):
        assert (await api.request(method, path, headers=phone)).status_code == 401


# ---------------------------------------------------------------- the Plus feature


async def test_history_beyond_a_week_needs_plus(
    api: httpx.AsyncClient, session: AsyncSession, fake_supabase: FakeSupabase
) -> None:
    home, priya, _ = await signed_in_home(session, fake_supabase)
    session.add(
        Checkin(
            elder_id=home.elder.id,
            local_date=date(2026, 9, 10),
            checked_in_at=datetime(2026, 9, 10, 4, 0, tzinfo=UTC),
            source="app",
        )
    )
    await session.commit()
    path = f"/v1/elders/{home.elder.id}/checkins/history"

    async def history(days: int) -> httpx.Response:
        with time_machine.travel(T, tick=False):
            return await api.get(path, headers=priya.headers, params={"days": days})

    week = await ok(await history(7))
    assert [day["local_date"] for day in week["days"]][-1] == "2026-09-26"
    assert (week["free_days"], week["plus_days"], len(week["days"])) == (7, 30, 7)
    locked = await history(30)
    assert (locked.status_code, locked.json()["code"]) == (403, "plus_required")
    assert (await history(31)).status_code == 422

    session.add(
        AccessGrant(
            family_id=home.family.id,
            source="goodwill",
            starts_at=T - timedelta(hours=1),
            ends_at=T + timedelta(hours=1),
        )
    )
    await session.commit()
    month = await ok(await history(30))
    assert len(month["days"]) == 30 and month["days"][0]["local_date"] == "2026-08-28"
    assert {"local_date": "2026-09-10", "state": "okay"} in month["days"]
