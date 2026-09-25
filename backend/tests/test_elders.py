"""Elder profiles: create, update, pause/resume, primary elder (family clock)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import time_machine
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.models import AuditLog
from tests.api_support import People, create_family, join, ok, problem_code
from tests.fake_supabase import FakeSupabase, SupabaseUser

MOM = {
    "display_name": "Asha",
    "relation_label": "Mom",
    "full_name": "Asha Sharma",
    "timezone": "Asia/Calcutta",
    "country_code": "in",
    "language": "hi-IN",
    "phone": "098765 43210",
}


@pytest.fixture
def people(client: httpx.AsyncClient, fake_supabase: FakeSupabase) -> People:
    return People(client, fake_supabase)


async def add_elder(
    client: httpx.AsyncClient, family_id: str, person: SupabaseUser, **fields: Any
) -> dict[str, Any]:
    response = await client.post(
        f"/v1/families/{family_id}/elders", headers=person.headers, json={**MOM, **fields}
    )
    return await ok(response, 201)


async def test_create_elder(client: httpx.AsyncClient, people: People) -> None:
    priya = await people.new("Priya")
    family = await create_family(client, priya)
    mom = await add_elder(client, family["id"], priya)

    assert (mom["timezone"], mom["country_code"], mom["phone_e164"]) == (
        "Asia/Kolkata",
        "IN",
        "+919876543210",
    )
    assert (mom["relation_label"], mom["full_name"], mom["language"]) == (
        "Mom",
        "Asha Sharma",
        "hi-IN",
    )
    assert mom["checkin"] == {
        "remind_at": "09:00:00",
        "due_by": "12:00:00",
        "grace_minutes": 60,
        "activity_counts_as_ok": True,
    }
    assert mom["pause"] == {"paused": False, "since": None, "until": None}
    assert mom["is_primary"] is True  # the first elder sets the family clock

    dad = await add_elder(
        client,
        family["id"],
        priya,
        display_name="Raj",
        relation_label="Dad",
        timezone="Europe/London",
        country_code="GB",
        phone=None,
        checkin={"remind_at": "08:00", "grace_minutes": 30},
    )
    assert dad["is_primary"] is False
    assert (dad["checkin"]["remind_at"], dad["checkin"]["grace_minutes"]) == ("08:00:00", 30)

    detail = await ok(await client.get(f"/v1/families/{family['id']}", headers=priya.headers))
    assert detail["clock"] == {"timezone": "Asia/Kolkata", "elder_id": mom["id"]}
    assert [e["display_name"] for e in detail["elders"]] == ["Asha", "Raj"]


@pytest.mark.parametrize(
    ("changes", "error_type"),
    [
        ({"timezone": None}, "string_type"),
        ({"timezone": "Mars/Base"}, "invalid_timezone"),
        ({"country_code": "UK"}, "invalid_country"),
        ({"phone": "12345"}, "invalid_phone"),
        ({"checkin": {"remind_at": "13:00"}}, "reminder_after_due"),
        ({"checkin": {"grace_minutes": 721}}, "less_than_equal"),
        ({"relation_label": "x" * 41}, "string_too_long"),
    ],
)
async def test_create_validation(
    client: httpx.AsyncClient, people: People, changes: dict, error_type: str
) -> None:
    priya = await people.new("Priya")
    family = await create_family(client, priya)
    response = await client.post(
        f"/v1/families/{family['id']}/elders", headers=priya.headers, json={**MOM, **changes}
    )
    assert response.status_code == 422
    assert response.json()["errors"][0]["type"] == error_type


async def test_timezone_is_required(client: httpx.AsyncClient, people: People) -> None:
    priya = await people.new("Priya")
    family = await create_family(client, priya)
    body = {k: v for k, v in MOM.items() if k != "timezone"}
    response = await client.post(
        f"/v1/families/{family['id']}/elders", headers=priya.headers, json=body
    )
    assert response.json()["errors"][0]["loc"] == ["body", "timezone"]


async def test_update(client: httpx.AsyncClient, people: People, session: AsyncSession) -> None:
    priya, arjun = await people.new("Priya"), await people.new("Arjun")
    family = await create_family(client, priya)
    await join(client, family["id"], priya, arjun)
    mom = await add_elder(client, family["id"], priya)
    url = f"/v1/elders/{mom['id']}"

    updated = await ok(
        await client.patch(
            url,
            headers=arjun.headers,  # any member
            json={
                "relation_label": None,
                "checkin": {"due_by": "11:00", "activity_counts_as_ok": False},
            },
        )
    )
    assert updated["relation_label"] is None
    assert (updated["checkin"]["due_by"], updated["checkin"]["activity_counts_as_ok"]) == (
        "11:00:00",
        False,
    )
    too_late = await client.patch(
        url, headers=arjun.headers, json={"checkin": {"remind_at": "11:30"}}
    )
    assert problem_code(too_late) == (422, "reminder_after_due")
    clear_name = await client.patch(url, headers=arjun.headers, json={"display_name": None})
    assert clear_name.json()["errors"][0]["type"] == "cannot_clear"

    entry = await session.scalar(select(AuditLog).where(AuditLog.action == "elder.updated"))
    assert entry is not None
    assert entry.data["fields"] == [
        "relation_label",
        "checkin.due_by",
        "checkin.activity_counts_as_ok",
    ]


async def test_pause_and_resume(client: httpx.AsyncClient, people: People) -> None:
    priya = await people.new("Priya")
    family = await create_family(client, priya)
    mom = await add_elder(client, family["id"], priya)
    url = f"/v1/elders/{mom['id']}"

    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    assert problem_code(
        await client.post(f"{url}/pause", headers=priya.headers, json={"until": past})
    ) == (
        422,
        "invalid_input",
    )
    until = datetime.now(UTC) + timedelta(days=3)
    paused = await ok(
        await client.post(f"{url}/pause", headers=priya.headers, json={"until": until.isoformat()})
    )
    assert paused["pause"]["paused"] is True
    assert datetime.fromisoformat(paused["pause"]["until"]) == until

    with time_machine.travel(until + timedelta(minutes=1)):
        later = await ok(await client.get(url, headers=priya.headers))
        assert later["pause"]["paused"] is False  # the pause ended by itself

    open_ended = await ok(await client.post(f"{url}/pause", headers=priya.headers, json={}))
    assert (open_ended["pause"]["paused"], open_ended["pause"]["until"]) == (True, None)
    resumed = await ok(await client.post(f"{url}/resume", headers=priya.headers))
    assert resumed["pause"] == {"paused": False, "since": None, "until": None}


async def test_primary_elder_is_organizer_only(client: httpx.AsyncClient, people: People) -> None:
    priya, arjun, stranger = (
        await people.new("Priya"),
        await people.new("Arjun"),
        await people.new("Stranger"),
    )
    family = await create_family(client, priya)
    await join(client, family["id"], priya, arjun)
    mom = await add_elder(client, family["id"], priya)
    dad = await add_elder(
        client,
        family["id"],
        priya,
        display_name="Raj",
        timezone="Europe/London",
        country_code="GB",
        phone=None,
    )
    url = f"/v1/elders/{dad['id']}/primary"

    assert problem_code(await client.post(url, headers=arjun.headers)) == (
        403,
        "organizer_required",
    )
    assert problem_code(await client.post(url, headers=stranger.headers)) == (404, "not_found")
    detail = await ok(await client.post(url, headers=priya.headers))
    assert detail["clock"] == {"timezone": "Europe/London", "elder_id": dad["id"]}
    primaries = [e["id"] for e in detail["elders"] if e["is_primary"]]
    assert primaries == [dad["id"]]
    assert mom["id"] != dad["id"]


async def test_outsiders_cannot_see_elders(client: httpx.AsyncClient, people: People) -> None:
    priya, stranger = await people.new("Priya"), await people.new("Stranger")
    family = await create_family(client, priya)
    mom = await add_elder(client, family["id"], priya)
    assert problem_code(await client.get(f"/v1/elders/{mom['id']}", headers=stranger.headers)) == (
        404,
        "not_found",
    )
