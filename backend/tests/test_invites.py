"""Member invites: codes, links, single use, expiry, revoke, preview and brute-force limits."""

import re
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import time_machine
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from nodly.models import AuditLog, ThrottleCounter
from tests.api_support import People, create_family, create_invite, join, ok, problem_code
from tests.conftest import app_client, make_settings
from tests.fake_supabase import FakeSupabase


@pytest.fixture
def people(client: httpx.AsyncClient, fake_supabase: FakeSupabase) -> People:
    return People(client, fake_supabase)


async def accept(client: httpx.AsyncClient, person, code: str) -> httpx.Response:
    return await client.post("/v1/invites/accept", headers=person.headers, json={"code": code})


async def test_invite_shape(client: httpx.AsyncClient, people: People) -> None:
    priya = await people.new("Priya")
    family = await create_family(client, priya)
    before = datetime.now(UTC)
    invite = await create_invite(client, family["id"], priya)

    assert re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{5}-[0-9A-HJKMNP-TV-Z]{5}", invite["code"])
    assert invite["link"] == "nodly://invite/" + invite["code"].replace("-", "")
    assert invite["qr_payload"] == invite["link"]
    expires = datetime.fromisoformat(invite["expires_at"])
    assert timedelta(hours=47, minutes=59) < expires - before <= timedelta(hours=48, seconds=5)


async def test_accept_with_a_sloppily_typed_code(
    client: httpx.AsyncClient, people: People, session: AsyncSession
) -> None:
    priya, arjun = await people.new("Priya"), await people.new("Arjun")
    family = await create_family(client, priya)
    invite = await create_invite(client, family["id"], priya)
    typed = " " + invite["code"].lower().replace("0", "o").replace("-", " ") + " "

    joined = await ok(await accept(client, arjun, typed))
    assert joined["my_role"] == "member"
    assert {m["display_name"] for m in joined["members"]} == {"Priya", "Arjun"}
    assert (
        await ok(await client.get(f"/v1/families/{family['id']}/invites", headers=priya.headers))
        == []
    )
    entry = await session.scalar(select(AuditLog).where(AuditLog.action == "member.joined"))
    assert entry is not None and entry.actor_id is not None


async def test_codes_are_single_use(client: httpx.AsyncClient, people: People) -> None:
    priya, arjun, meera = (
        await people.new("Priya"),
        await people.new("Arjun"),
        await people.new("Meera"),
    )
    family = await create_family(client, priya)
    invite = await create_invite(client, family["id"], priya)
    await ok(await accept(client, arjun, invite["code"]))
    assert problem_code(await accept(client, meera, invite["code"])) == (410, "code_used")


async def test_existing_member_does_not_use_up_the_code(
    client: httpx.AsyncClient, people: People
) -> None:
    priya, arjun = await people.new("Priya"), await people.new("Arjun")
    family = await create_family(client, priya)
    invite = await create_invite(client, family["id"], priya)
    assert problem_code(await accept(client, priya, invite["code"])) == (409, "already_member")
    await ok(await accept(client, arjun, invite["code"]))


async def test_codes_expire_after_48_hours(client: httpx.AsyncClient, people: People) -> None:
    priya, arjun = await people.new("Priya"), await people.new("Arjun")
    family = await create_family(client, priya)
    invite = await create_invite(client, family["id"], priya)
    with time_machine.travel(datetime.now(UTC) + timedelta(hours=48, minutes=1)):
        assert problem_code(await accept(client, arjun, invite["code"])) == (410, "code_expired")


async def test_unknown_code(client: httpx.AsyncClient, people: People) -> None:
    arjun = await people.new("Arjun")
    assert problem_code(await accept(client, arjun, "ZZZZZ-ZZZZZ")) == (422, "invalid_code")
    assert problem_code(await accept(client, arjun, "not a code")) == (422, "invalid_code")


async def test_revoke(client: httpx.AsyncClient, people: People) -> None:
    priya, arjun, meera = (
        await people.new("Priya"),
        await people.new("Arjun"),
        await people.new("Meera"),
    )
    family = await create_family(client, priya)
    await join(client, family["id"], priya, arjun)
    await join(client, family["id"], priya, meera)
    arjuns = await create_invite(client, family["id"], arjun)
    priyas = await create_invite(client, family["id"], priya)
    base = f"/v1/families/{family['id']}/invites"

    not_creator = await client.delete(f"{base}/{priyas['id']}", headers=meera.headers)
    assert problem_code(not_creator) == (403, "organizer_required")
    assert (await client.delete(f"{base}/{arjuns['id']}", headers=arjun.headers)).status_code == 204
    assert (await client.delete(f"{base}/{priyas['id']}", headers=priya.headers)).status_code == 204
    open_invites = await ok(await client.get(base, headers=priya.headers))
    assert open_invites == []

    stranger = await people.new("Stranger")
    assert problem_code(await accept(client, stranger, arjuns["code"])) == (410, "code_used")


async def test_preview_before_onboarding(client: httpx.AsyncClient, people: People) -> None:
    priya = await people.new("Priya")
    newbie = await people.new("Newbie", onboard=False)
    family = await create_family(client, priya)
    invite = await create_invite(client, family["id"], priya)

    preview = await ok(
        await client.post(
            "/v1/invites/preview", headers=newbie.headers, json={"code": invite["code"]}
        )
    )
    assert (preview["family_name"], preview["invited_by"]) == ("The Sharmas", "Priya")
    assert preview["already_member"] is False
    # Preview doesn't use the code; accepting still needs onboarding.
    assert problem_code(await accept(client, newbie, invite["code"])) == (
        403,
        "onboarding_required",
    )


# ---------------------------------------------------------------- brute-force protection


async def test_too_many_wrong_codes_per_user(
    test_database_url: str, clean_db: AsyncEngine, fake_supabase: FakeSupabase
) -> None:
    settings = make_settings(test_database_url, throttle_max_failures_per_user=3)
    async with app_client(settings, fake_supabase) as client:
        people = People(client, fake_supabase)
        priya, guesser = await people.new("Priya"), await people.new("Guesser")
        family = await create_family(client, priya)
        invite = await create_invite(client, family["id"], priya)

        for _ in range(3):
            assert problem_code(await accept(client, guesser, "AAAAA-AAAAA"))[0] == 422
        blocked = await accept(client, guesser, invite["code"])  # even the right code
        assert problem_code(blocked) == (429, "rate_limited")
        assert 1 <= int(blocked.headers["retry-after"]) <= 900

        # Someone else on the same IP isn't blocked by the per-user limit.
        other = await people.new("Other")
        await ok(await accept(client, other, invite["code"]))

        with time_machine.travel(datetime.now(UTC) + timedelta(minutes=16)):
            assert problem_code(await accept(client, guesser, "AAAAA-AAAAA"))[0] == 422


async def test_too_many_wrong_codes_per_ip(
    test_database_url: str, clean_db: AsyncEngine, fake_supabase: FakeSupabase
) -> None:
    settings = make_settings(test_database_url, throttle_max_failures_per_ip=2)
    async with app_client(settings, fake_supabase) as client:
        people = People(client, fake_supabase)
        first, second = await people.new("First"), await people.new("Second")
        await accept(client, first, "AAAAA-AAAAA")
        await accept(client, second, "AAAAA-AAAAA")
        assert problem_code(await accept(client, second, "AAAAA-AAAAA")) == (429, "rate_limited")


async def test_global_limit(
    test_database_url: str,
    clean_db: AsyncEngine,
    fake_supabase: FakeSupabase,
    session: AsyncSession,
) -> None:
    settings = make_settings(test_database_url, throttle_max_failures_global=2)
    async with app_client(settings, fake_supabase) as client:
        people = People(client, fake_supabase)
        guesser = await people.new("Guesser")
        await accept(client, guesser, "AAAAA-AAAAA")
        await accept(client, guesser, "AAAAA-AAAAA")
        assert problem_code(await accept(client, guesser, "AAAAA-AAAAA"))[0] == 429
    buckets = set((await session.scalars(select(ThrottleCounter.bucket))).all())
    assert buckets == {"code:global", "code:ip:127.0.0.1", f"code:user:{people.ids['Guesser']}"}
