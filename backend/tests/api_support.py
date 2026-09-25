"""Helpers for API tests: people who sign in through the fake Supabase and onboard."""

from typing import Any

import httpx

from tests.fake_supabase import FakeSupabase, SupabaseUser

PROFILE = {"timezone": "Europe/London", "country_code": "GB", "confirm_age_16_plus": True}


class People:
    """Creates signed-in people on demand: people.new("priya") -> SupabaseUser."""

    def __init__(self, client: httpx.AsyncClient, supabase: FakeSupabase) -> None:
        self.client = client
        self.supabase = supabase
        self.ids: dict[str, str] = {}

    async def new(self, name: str, *, onboard: bool = True) -> SupabaseUser:
        person = SupabaseUser(self.supabase, f"{name.lower()}@example.com")
        me = await self.client.get("/v1/me", headers=person.headers)
        assert me.status_code == 200, me.text
        self.ids[name] = me.json()["id"]
        if onboard:
            response = await self.client.patch(
                "/v1/me", headers=person.headers, json={"display_name": name, **PROFILE}
            )
            assert response.status_code == 200, response.text
        return person


async def ok(response: httpx.Response, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json() if response.content else None


async def create_family(
    client: httpx.AsyncClient, organizer: SupabaseUser, name: str = "The Sharmas"
) -> dict[str, Any]:
    response = await client.post("/v1/families", headers=organizer.headers, json={"name": name})
    return await ok(response, 201)


async def create_invite(
    client: httpx.AsyncClient, family_id: str, inviter: SupabaseUser
) -> dict[str, Any]:
    response = await client.post(f"/v1/families/{family_id}/invites", headers=inviter.headers)
    return await ok(response, 201)


async def join(
    client: httpx.AsyncClient, family_id: str, inviter: SupabaseUser, joiner: SupabaseUser
) -> None:
    invite = await create_invite(client, family_id, inviter)
    response = await client.post(
        "/v1/invites/accept", headers=joiner.headers, json={"code": invite["code"]}
    )
    await ok(response)


def problem_code(response: httpx.Response) -> tuple[int, str | None]:
    body = response.json() if response.content else {}
    return response.status_code, body.get("code")
