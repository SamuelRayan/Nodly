"""Push-token registration, the family PIN, and leaving elder mode with it."""

from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from nodly.models import AuditLog, Family, PushToken
from nodly.security.pins import hash_pin, verify_pin
from tests.api_support import People, create_family, ok, problem_code
from tests.conftest import app_client, make_settings
from tests.fake_supabase import FakeSupabase, SupabaseUser

TOKEN = "ExponentPushToken[abc123]"


@pytest.fixture
def people(client: httpx.AsyncClient, fake_supabase: FakeSupabase) -> People:
    return People(client, fake_supabase)


async def paired_family(
    client: httpx.AsyncClient, people: People
) -> tuple[SupabaseUser, dict[str, Any], dict[str, str]]:
    priya = await people.new("Priya")
    family = await create_family(client, priya)
    elder = await ok(
        await client.post(
            f"/v1/families/{family['id']}/elders",
            headers=priya.headers,
            json={"display_name": "Asha", "timezone": "Asia/Kolkata", "country_code": "IN"},
        ),
        201,
    )
    code = await ok(
        await client.post(f"/v1/elders/{elder['id']}/pairing-codes", headers=priya.headers), 201
    )
    claimed = await ok(
        await client.post("/v1/pairing/claim", json={"code": code["code"], "platform": "android"}),
        201,
    )
    return priya, family, {"Authorization": f"Bearer {claimed['device_token']}"}


# ---------------------------------------------------------------- PIN hashing


def test_pin_hash_round_trip() -> None:
    stored = hash_pin("2468")
    assert stored.startswith("scrypt$") and "2468" not in stored
    assert verify_pin("2468", stored)
    assert not verify_pin("2469", stored)
    assert hash_pin("2468") != stored  # salted
    assert not verify_pin("2468", "garbage")


# ---------------------------------------------------------------- push tokens


async def test_user_push_token_registration(
    client: httpx.AsyncClient, people: People, session: AsyncSession
) -> None:
    newbie = await people.new("Newbie", onboard=False)  # works before onboarding
    body = {"token": TOKEN, "platform": "android"}
    assert (
        await client.post("/v1/me/push-tokens", headers=newbie.headers, json=body)
    ).status_code == 204
    again = await client.post("/v1/me/push-tokens", headers=newbie.headers, json=body)
    assert again.status_code == 204  # idempotent
    rows = (await session.scalars(select(PushToken))).all()
    assert [(r.provider, r.token, str(r.user_id)) for r in rows] == [
        ("expo", TOKEN, people.ids["Newbie"])
    ]


async def test_token_moves_to_the_phones_new_owner(
    client: httpx.AsyncClient, people: People, session: AsyncSession
) -> None:
    priya, _family, device = await paired_family(client, people)
    arjun = await people.new("Arjun")
    body = {"token": TOKEN, "platform": "android"}
    await client.post("/v1/me/push-tokens", headers=priya.headers, json=body)
    await client.post("/v1/me/push-tokens", headers=arjun.headers, json=body)
    row = await session.scalar(select(PushToken))
    assert row is not None and str(row.user_id) == people.ids["Arjun"]

    # The same phone re-paired as an elder's device: the token follows.
    await client.post("/v1/device/push-token", headers=device, json=body)
    session.expire_all()
    row = await session.scalar(select(PushToken))
    assert row is not None and row.user_id is None and row.elder_device_id is not None
    assert len((await session.scalars(select(PushToken))).all()) == 1


async def test_sign_out_removes_only_your_own_token(
    client: httpx.AsyncClient, people: People, session: AsyncSession
) -> None:
    priya, arjun = await people.new("Priya"), await people.new("Arjun")
    await client.post(
        "/v1/me/push-tokens", headers=priya.headers, json={"token": TOKEN, "platform": "android"}
    )
    not_mine = await client.delete(
        "/v1/me/push-tokens", headers=arjun.headers, params={"token": TOKEN}
    )
    assert not_mine.status_code == 204
    assert (await session.scalar(select(PushToken))) is not None
    await client.delete("/v1/me/push-tokens", headers=priya.headers, params={"token": TOKEN})
    session.expire_all()
    assert (await session.scalar(select(PushToken))) is None


async def test_invalid_push_token_body(client: httpx.AsyncClient, people: People) -> None:
    priya = await people.new("Priya")
    response = await client.post(
        "/v1/me/push-tokens", headers=priya.headers, json={"token": "", "platform": "windows"}
    )
    assert response.status_code == 422


# ---------------------------------------------------------------- family PIN & leaving


async def test_pin_is_organizer_only_and_never_shown(
    client: httpx.AsyncClient, people: People, session: AsyncSession
) -> None:
    priya, family, device = await paired_family(client, people)
    url = f"/v1/families/{family['id']}/pin"
    bad = await client.put(url, headers=priya.headers, json={"pin": "12a4"})
    assert bad.status_code == 422
    assert (await client.put(url, headers=priya.headers, json={"pin": "2468"})).status_code == 204

    detail = await ok(await client.get(f"/v1/families/{family['id']}", headers=priya.headers))
    assert detail["has_pin"] is True and "2468" not in str(detail)
    me = await ok(await client.get("/v1/device/me", headers=device))
    assert me["family_has_pin"] is True

    stored = await session.scalar(select(Family.pin_hash).where(Family.id == family["id"]))
    assert stored is not None and verify_pin("2468", stored)

    assert (await client.delete(url, headers=priya.headers)).status_code == 204
    me = await ok(await client.get("/v1/device/me", headers=device))
    assert me["family_has_pin"] is False


async def test_leave_with_the_right_pin_disconnects_the_phone(
    client: httpx.AsyncClient, people: People, session: AsyncSession
) -> None:
    priya, family, device = await paired_family(client, people)
    no_pin = await client.post("/v1/device/leave", headers=device, json={"pin": "2468"})
    assert problem_code(no_pin) == (409, "no_family_pin")

    await client.put(
        f"/v1/families/{family['id']}/pin", headers=priya.headers, json={"pin": "2468"}
    )
    wrong = await client.post("/v1/device/leave", headers=device, json={"pin": "1111"})
    assert problem_code(wrong) == (422, "wrong_pin")
    assert (
        await client.post("/v1/device/leave", headers=device, json={"pin": "2468"})
    ).status_code == 204

    after = await client.get("/v1/device/me", headers=device)
    assert problem_code(after) == (401, "device_revoked")
    actions = (await session.scalars(select(AuditLog.action).order_by(AuditLog.id))).all()
    assert "family.pin_set" in actions and actions[-1] == "device.left"


async def test_wrong_pins_are_limited(
    test_database_url: str, clean_db: AsyncEngine, fake_supabase: FakeSupabase
) -> None:
    settings = make_settings(test_database_url, throttle_max_pin_failures_per_device=3)
    async with app_client(settings, fake_supabase) as client:
        people = People(client, fake_supabase)
        priya, family, device = await paired_family(client, people)
        await client.put(
            f"/v1/families/{family['id']}/pin", headers=priya.headers, json={"pin": "2468"}
        )
        for _ in range(3):
            assert (
                await client.post("/v1/device/leave", headers=device, json={"pin": "0000"})
            ).status_code == 422
        blocked = await client.post("/v1/device/leave", headers=device, json={"pin": "2468"})
        assert problem_code(blocked) == (429, "rate_limited")
