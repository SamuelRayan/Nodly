"""Families and membership: create, list, rename, transfer organizer, remove, leave."""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.models import AuditLog, Invite
from tests.api_support import People, create_family, create_invite, join, ok, problem_code
from tests.fake_supabase import FakeSupabase


@pytest.fixture
def people(client: httpx.AsyncClient, fake_supabase: FakeSupabase) -> People:
    return People(client, fake_supabase)


async def test_onboarding_is_required_first(client: httpx.AsyncClient, people: People) -> None:
    newbie = await people.new("Newbie", onboard=False)
    response = await client.post("/v1/families", headers=newbie.headers, json={"name": "X"})
    assert problem_code(response) == (403, "onboarding_required")


async def test_create_and_list(client: httpx.AsyncClient, people: People) -> None:
    priya = await people.new("Priya")
    family = await create_family(client, priya)
    assert family["name"] == "The Sharmas"
    assert family["my_role"] == "organizer"
    assert family["clock"] is None
    assert [(m["display_name"], m["role"]) for m in family["members"]] == [("Priya", "organizer")]

    mine = await ok(await client.get("/v1/families", headers=priya.headers))
    assert [(f["id"], f["my_role"]) for f in mine] == [(family["id"], "organizer")]


async def test_outsiders_cannot_see_a_family(client: httpx.AsyncClient, people: People) -> None:
    priya, stranger = await people.new("Priya"), await people.new("Stranger")
    family = await create_family(client, priya)
    response = await client.get(f"/v1/families/{family['id']}", headers=stranger.headers)
    assert problem_code(response) == (404, "not_found")
    assert await ok(await client.get("/v1/families", headers=stranger.headers)) == []


async def test_rename_is_organizer_only(client: httpx.AsyncClient, people: People) -> None:
    priya, arjun = await people.new("Priya"), await people.new("Arjun")
    family = await create_family(client, priya)
    await join(client, family["id"], priya, arjun)

    url = f"/v1/families/{family['id']}"
    denied = await client.patch(url, headers=arjun.headers, json={"name": "Arjun's"})
    assert problem_code(denied) == (403, "organizer_required")
    renamed = await ok(await client.patch(url, headers=priya.headers, json={"name": " Sharmas "}))
    assert renamed["name"] == "Sharmas"


async def test_transfer_organizer(
    client: httpx.AsyncClient, people: People, session: AsyncSession
) -> None:
    priya, arjun = await people.new("Priya"), await people.new("Arjun")
    await people.new("Stranger")  # signed up, but not in the family
    family = await create_family(client, priya)
    await join(client, family["id"], priya, arjun)
    url = f"/v1/families/{family['id']}/organizer"

    self_transfer = await client.post(
        url, headers=priya.headers, json={"user_id": people.ids["Priya"]}
    )
    assert problem_code(self_transfer) == (409, "already_organizer")
    to_outsider = await client.post(
        url, headers=priya.headers, json={"user_id": people.ids["Stranger"]}
    )
    assert problem_code(to_outsider) == (404, "not_found")

    after = await ok(
        await client.post(url, headers=priya.headers, json={"user_id": people.ids["Arjun"]})
    )
    roles = {m["display_name"]: m["role"] for m in after["members"]}
    assert roles == {"Priya": "member", "Arjun": "organizer"}
    assert after["my_role"] == "member"

    # Priya lost organizer powers; Arjun has them.
    rename = await client.patch(
        f"/v1/families/{family['id']}", headers=priya.headers, json={"name": "x"}
    )
    assert problem_code(rename) == (403, "organizer_required")
    actions = (await session.scalars(select(AuditLog.action))).all()
    assert "family.organizer_transferred" in actions


async def test_remove_member_revokes_their_invites(
    client: httpx.AsyncClient, people: People, session: AsyncSession
) -> None:
    priya, arjun, meera = (
        await people.new("Priya"),
        await people.new("Arjun"),
        await people.new("Meera"),
    )
    family = await create_family(client, priya)
    await join(client, family["id"], priya, arjun)
    await join(client, family["id"], priya, meera)
    arjuns_invite = await create_invite(client, family["id"], arjun)

    base = f"/v1/families/{family['id']}/members"
    by_member = await client.delete(f"{base}/{people.ids['Meera']}", headers=arjun.headers)
    assert problem_code(by_member) == (403, "organizer_required")
    remove_self = await client.delete(f"{base}/{people.ids['Priya']}", headers=priya.headers)
    assert problem_code(remove_self) == (409, "organizer_must_transfer")

    removed = await client.delete(f"{base}/{people.ids['Arjun']}", headers=priya.headers)
    assert removed.status_code == 204
    again = await client.delete(f"{base}/{people.ids['Arjun']}", headers=priya.headers)
    assert problem_code(again) == (404, "not_found")

    lost_access = await client.get(f"/v1/families/{family['id']}", headers=arjun.headers)
    assert problem_code(lost_access) == (404, "not_found")
    invite = await session.get_one(Invite, arjuns_invite["id"])
    assert invite.revoked_at is not None


async def test_leave(client: httpx.AsyncClient, people: People, session: AsyncSession) -> None:
    priya, arjun = await people.new("Priya"), await people.new("Arjun")
    family = await create_family(client, priya)
    await join(client, family["id"], priya, arjun)
    url = f"/v1/families/{family['id']}/leave"

    organizer_leaves = await client.post(url, headers=priya.headers)
    assert problem_code(organizer_leaves) == (409, "organizer_must_transfer")
    assert (await client.post(url, headers=arjun.headers)).status_code == 204
    assert await ok(await client.get("/v1/families", headers=arjun.headers)) == []

    actions = (await session.scalars(select(AuditLog.action).order_by(AuditLog.id))).all()
    assert [a for a in actions if a.startswith(("family.", "member."))] == [
        "family.created",
        "member.joined",
        "member.left",
    ]
