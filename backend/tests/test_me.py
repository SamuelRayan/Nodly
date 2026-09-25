"""GET/PATCH /v1/me: account creation on first sight and onboarding."""

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.errors import PROBLEM_MEDIA_TYPE
from nodly.models import AuditLog, User
from tests.conftest import app_client, make_settings
from tests.fake_supabase import FakeSupabase, SupabaseUser
from tests.support import make_user

COMPLETE_PROFILE = {
    "display_name": "Priya",
    "timezone": "Europe/London",
    "country_code": "GB",
    "confirm_age_16_plus": True,
}


@pytest.fixture
def priya(fake_supabase: FakeSupabase) -> SupabaseUser:
    return SupabaseUser(fake_supabase, "priya@example.com")


async def test_no_token_is_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/me")
    assert response.status_code == 401
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["code"] == "not_authenticated"


async def test_device_token_is_not_a_user_token(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/me", headers={"Authorization": "Bearer ndt_abc"})
    assert (response.status_code, response.json()["code"]) == (401, "invalid_token")


async def test_expired_token_is_401_token_expired(
    client: httpx.AsyncClient, fake_supabase: FakeSupabase
) -> None:
    token = fake_supabase.token(lifetime=-120)
    response = await client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert (response.status_code, response.json()["code"]) == (401, "token_expired")


async def test_first_call_creates_the_account(
    client: httpx.AsyncClient, priya: SupabaseUser, session: AsyncSession
) -> None:
    first = (await client.get("/v1/me", headers=priya.headers)).json()
    again = (await client.get("/v1/me", headers=priya.headers)).json()
    assert first["id"] == again["id"]
    assert first["email"] == "priya@example.com"
    assert first["onboarding"] == {
        "complete": False,
        "missing": ["display_name", "timezone", "country_code", "age_confirmation"],
    }
    users = (await session.scalars(select(User))).all()
    assert [u.auth_user_id for u in users] == [priya.auth_id]
    actions = (await session.scalars(select(AuditLog.action))).all()
    assert actions == ["user.created"]


async def test_email_follows_supabase(
    client: httpx.AsyncClient, fake_supabase: FakeSupabase
) -> None:
    auth_id = uuid.uuid4()
    for email in ("old@example.com", "New@Example.com"):
        token = fake_supabase.token(sub=auth_id, email=email)
        me = (await client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})).json()
    assert me["email"] == "new@example.com"


async def test_token_without_email_is_refused(
    client: httpx.AsyncClient, fake_supabase: FakeSupabase
) -> None:
    token = fake_supabase.token(email=None)
    response = await client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert (response.status_code, response.json()["code"]) == (403, "email_required")


async def test_email_taken_by_another_row_is_409(
    client: httpx.AsyncClient, priya: SupabaseUser, session: AsyncSession
) -> None:
    await make_user(session, email="priya@example.com")
    await session.commit()
    response = await client.get("/v1/me", headers=priya.headers)
    assert (response.status_code, response.json()["code"]) == (409, "email_in_use")


async def test_onboarding_step_by_step(
    client: httpx.AsyncClient, priya: SupabaseUser, session: AsyncSession
) -> None:
    await client.get("/v1/me", headers=priya.headers)
    partial = await client.patch(
        "/v1/me",
        headers=priya.headers,
        json={"display_name": " Priya ", "timezone": "Asia/Calcutta", "language": "en-GB"},
    )
    assert partial.status_code == 200
    body = partial.json()
    assert (body["display_name"], body["timezone"]) == ("Priya", "Asia/Kolkata")
    assert body["onboarding"]["missing"] == ["country_code", "age_confirmation"]

    done = await client.patch(
        "/v1/me",
        headers=priya.headers,
        json={"country_code": "in", "phone": "098765 43210", "confirm_age_16_plus": True},
    )
    body = done.json()
    assert body["onboarding"] == {"complete": True, "missing": []}
    assert (body["country_code"], body["phone_e164"]) == ("IN", "+919876543210")

    # Changing a field later doesn't re-run onboarding.
    await client.patch("/v1/me", headers=priya.headers, json={"display_name": "Priya S"})
    actions = (await session.scalars(select(AuditLog.action).order_by(AuditLog.id))).all()
    assert actions == ["user.created", "user.onboarded"]


@pytest.mark.parametrize(
    ("body", "error_type"),
    [
        ({"timezone": "Mars/Base"}, "invalid_timezone"),
        ({"country_code": "UK"}, "invalid_country"),
        ({"display_name": None}, "cannot_clear"),
        ({"timezone": None}, "cannot_clear"),
        ({"confirm_age_16_plus": False}, "literal_error"),
        ({"language": "not a language"}, "string_pattern_mismatch"),
    ],
)
async def test_invalid_profile_updates(
    client: httpx.AsyncClient, priya: SupabaseUser, body: dict, error_type: str
) -> None:
    response = await client.patch("/v1/me", headers=priya.headers, json=body)
    assert response.status_code == 422
    assert response.json()["errors"][0]["type"] == error_type


async def test_invalid_phone_is_a_problem(client: httpx.AsyncClient, priya: SupabaseUser) -> None:
    response = await client.patch("/v1/me", headers=priya.headers, json={"phone": "12345"})
    assert (response.status_code, response.json()["code"]) == (422, "invalid_phone")


async def test_phone_can_be_cleared(client: httpx.AsyncClient, priya: SupabaseUser) -> None:
    await client.patch("/v1/me", headers=priya.headers, json={"phone": "+44 20 7946 0958"})
    body = (await client.patch("/v1/me", headers=priya.headers, json={"phone": None})).json()
    assert body["phone_e164"] is None


async def test_without_supabase_configured_user_endpoints_are_503(
    test_database_url: str, clean_db: object, fake_supabase: FakeSupabase
) -> None:
    settings = make_settings(test_database_url, supabase_url=None)
    async with app_client(settings, fake_supabase) as client:
        response = await client.get("/v1/me", headers={"Authorization": "Bearer x"})
    assert (response.status_code, response.json()["code"]) == (503, "auth_not_configured")


async def test_supabase_down_on_first_request_is_503(
    client: httpx.AsyncClient, fake_supabase: FakeSupabase, priya: SupabaseUser
) -> None:
    fake_supabase.down = True
    response = await client.get("/v1/me", headers=priya.headers)
    assert (response.status_code, response.json()["code"]) == (503, "auth_unavailable")


async def test_complete_profile_constant_is_valid(
    client: httpx.AsyncClient, priya: SupabaseUser
) -> None:
    body = (await client.patch("/v1/me", headers=priya.headers, json=COMPLETE_PROFILE)).json()
    assert body["onboarding"]["complete"] is True
