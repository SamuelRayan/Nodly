"""Pairing codes, the device-token claim, device auth, rotation and revocation."""

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import time_machine
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from nodly.models import AuditLog, ElderDevice
from tests.api_support import People, create_family, ok, problem_code
from tests.conftest import app_client, make_settings
from tests.fake_supabase import FakeSupabase, SupabaseUser

ELDER = {"display_name": "Asha", "timezone": "Asia/Kolkata", "country_code": "IN"}


@pytest.fixture
def people(client: httpx.AsyncClient, fake_supabase: FakeSupabase) -> People:
    return People(client, fake_supabase)


async def family_with_elder(
    client: httpx.AsyncClient, people: People
) -> tuple[SupabaseUser, dict[str, Any], dict[str, Any]]:
    priya = await people.new("Priya")
    family = await create_family(client, priya)
    elder = await ok(
        await client.post(f"/v1/families/{family['id']}/elders", headers=priya.headers, json=ELDER),
        201,
    )
    return priya, family, elder


async def new_code(
    client: httpx.AsyncClient, person: SupabaseUser, elder_id: str
) -> dict[str, Any]:
    return await ok(
        await client.post(f"/v1/elders/{elder_id}/pairing-codes", headers=person.headers), 201
    )


async def claim(client: httpx.AsyncClient, code: str) -> httpx.Response:
    return await client.post(
        "/v1/pairing/claim",
        json={
            "code": code,
            "platform": "android",
            "device_model": "SM-S921B",
            "app_version": "1.0.0",
        },
    )


def device_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_pairing_code_shape(client: httpx.AsyncClient, people: People) -> None:
    priya, _, elder = await family_with_elder(client, people)
    before = datetime.now(UTC)
    code = await new_code(client, priya, elder["id"])
    assert re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}", code["code"])
    assert code["qr_payload"] == "nodly://pair/" + code["code"].replace("-", "")
    lifetime = datetime.fromisoformat(code["expires_at"]) - before
    assert timedelta(minutes=14, seconds=55) < lifetime <= timedelta(minutes=15, seconds=5)


async def test_claim_pairs_the_phone(
    client: httpx.AsyncClient, people: People, session: AsyncSession
) -> None:
    priya, family, elder = await family_with_elder(client, people)
    code = await new_code(client, priya, elder["id"])

    claimed = await ok(await claim(client, code["code"].lower()), 201)
    token = claimed["device_token"]
    assert token.startswith("ndt_") and len(token) == 4 + 43
    assert (claimed["elder"]["id"], claimed["family"]) == (
        elder["id"],
        {"id": family["id"], "name": "The Sharmas"},
    )
    # Stored only as a hash.
    device = await session.get_one(ElderDevice, claimed["device"]["id"])
    assert token not in device.token_hash and len(device.token_hash) == 64

    me = await ok(await client.get("/v1/device/me", headers=device_headers(token)))
    assert (me["elder"]["display_name"], me["family"]["name"]) == ("Asha", "The Sharmas")

    devices = await ok(await client.get(f"/v1/elders/{elder['id']}/devices", headers=priya.headers))
    assert [(d["platform"], d["device_model"]) for d in devices] == [("android", "SM-S921B")]
    assert problem_code(await claim(client, code["code"])) == (410, "code_used")

    entry = await session.scalar(select(AuditLog).where(AuditLog.action == "device.paired"))
    assert entry is not None and (entry.actor_type, str(entry.actor_id)) == (
        "elder_device",
        claimed["device"]["id"],
    )


async def test_new_code_replaces_the_old_one(client: httpx.AsyncClient, people: People) -> None:
    priya, _, elder = await family_with_elder(client, people)
    old = await new_code(client, priya, elder["id"])
    new = await new_code(client, priya, elder["id"])
    assert problem_code(await claim(client, old["code"])) == (410, "code_used")
    await ok(await claim(client, new["code"]), 201)


async def test_codes_expire_after_15_minutes(client: httpx.AsyncClient, people: People) -> None:
    priya, _, elder = await family_with_elder(client, people)
    code = await new_code(client, priya, elder["id"])
    with time_machine.travel(datetime.now(UTC) + timedelta(minutes=15, seconds=1)):
        assert problem_code(await claim(client, code["code"])) == (410, "code_expired")


async def test_unknown_code(client: httpx.AsyncClient) -> None:
    assert problem_code(await claim(client, "ZZZZ-ZZZZ")) == (422, "invalid_code")


async def test_tokens_are_not_interchangeable(client: httpx.AsyncClient, people: People) -> None:
    priya, family, elder = await family_with_elder(client, people)
    token = (
        await ok(await claim(client, (await new_code(client, priya, elder["id"]))["code"]), 201)
    )["device_token"]
    as_user = await client.get(f"/v1/families/{family['id']}", headers=device_headers(token))
    assert problem_code(as_user) == (401, "invalid_token")
    as_device = await client.get("/v1/device/me", headers=priya.headers)
    assert problem_code(as_device) == (401, "invalid_token")
    missing = await client.get("/v1/device/me")
    assert problem_code(missing) == (401, "not_authenticated")
    unknown = await client.get("/v1/device/me", headers=device_headers("ndt_" + "A" * 43))
    assert problem_code(unknown) == (401, "invalid_token")


async def test_revoked_device_is_locked_out(client: httpx.AsyncClient, people: People) -> None:
    priya, _, elder = await family_with_elder(client, people)
    claimed = await ok(
        await claim(client, (await new_code(client, priya, elder["id"]))["code"]), 201
    )
    stranger = await people.new("Stranger")
    url = f"/v1/elders/{elder['id']}/devices/{claimed['device']['id']}"

    assert problem_code(await client.delete(url, headers=stranger.headers)) == (404, "not_found")
    assert (await client.delete(url, headers=priya.headers)).status_code == 204
    assert (await client.delete(url, headers=priya.headers)).status_code == 204  # idempotent
    response = await client.get("/v1/device/me", headers=device_headers(claimed["device_token"]))
    assert problem_code(response) == (401, "device_revoked")
    devices = await ok(await client.get(f"/v1/elders/{elder['id']}/devices", headers=priya.headers))
    assert devices[0]["revoked_at"] is not None


async def test_token_rotation_with_grace_period(client: httpx.AsyncClient, people: People) -> None:
    priya, _, elder = await family_with_elder(client, people)
    old = (
        await ok(await claim(client, (await new_code(client, priya, elder["id"]))["code"]), 201)
    )["device_token"]
    rotated = await ok(await client.post("/v1/device/token/rotate", headers=device_headers(old)))
    new = rotated["device_token"]
    assert new != old

    # The response might be lost: the old token keeps working for the grace period...
    await ok(await client.get("/v1/device/me", headers=device_headers(old)))
    await ok(await client.get("/v1/device/me", headers=device_headers(new)))
    # ...and rotating again with the old token keeps *it* valid (not the one never received).
    again = await ok(await client.post("/v1/device/token/rotate", headers=device_headers(old)))
    await ok(await client.get("/v1/device/me", headers=device_headers(old)))
    newest = again["device_token"]
    assert problem_code(await client.get("/v1/device/me", headers=device_headers(new))) == (
        401,
        "invalid_token",
    )

    with time_machine.travel(datetime.now(UTC) + timedelta(minutes=11)):
        assert problem_code(await client.get("/v1/device/me", headers=device_headers(old))) == (
            401,
            "invalid_token",
        )
        await ok(await client.get("/v1/device/me", headers=device_headers(newest)))


async def test_last_seen_is_written_at_most_every_five_minutes(
    client: httpx.AsyncClient, people: People, session: AsyncSession
) -> None:
    priya, _, elder = await family_with_elder(client, people)
    claimed = await ok(
        await claim(client, (await new_code(client, priya, elder["id"]))["code"]), 201
    )
    headers = device_headers(claimed["device_token"])
    paired_seen = (await session.get_one(ElderDevice, claimed["device"]["id"])).last_seen_at

    await client.get("/v1/device/me", headers=headers)
    session.expire_all()
    assert (await session.get_one(ElderDevice, claimed["device"]["id"])).last_seen_at == paired_seen

    with time_machine.travel(datetime.now(UTC) + timedelta(minutes=6)):
        await client.get("/v1/device/me", headers=headers)
    session.expire_all()
    assert (await session.get_one(ElderDevice, claimed["device"]["id"])).last_seen_at > paired_seen


async def test_claims_are_throttled_per_ip(
    test_database_url: str, clean_db: AsyncEngine, fake_supabase: FakeSupabase
) -> None:
    settings = make_settings(test_database_url, throttle_max_failures_per_ip=3)
    async with app_client(settings, fake_supabase) as client:
        people = People(client, fake_supabase)
        priya, _, elder = await family_with_elder(client, people)
        code = await new_code(client, priya, elder["id"])
        for _ in range(3):
            assert (await claim(client, "AAAA-AAAA")).status_code == 422
        blocked = await claim(client, code["code"])
        assert problem_code(blocked) == (429, "rate_limited")
        assert "retry-after" in blocked.headers
