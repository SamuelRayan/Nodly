"""The dev-only router: mounted only when ENV=dev, validates through the services, audits."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import nodly.jobs.handlers  # noqa: F401  # registers the debug handlers
from nodly.main import create_app
from nodly.models import AuditLog
from nodly.worker import Worker
from tests.conftest import make_settings


@pytest.fixture
async def dev(test_database_url: str, clean_db: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(make_settings(test_database_url, env="dev"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await app.state.engine.dispose()


async def post(client: httpx.AsyncClient, url: str, body: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(url, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def make_family_with_organizer(dev: httpx.AsyncClient) -> tuple[str, str]:
    family = await post(dev, "/dev/families", {"name": "The Sharmas"})
    user = await post(
        dev,
        "/dev/users",
        {"email": "priya@example.com", "display_name": "Priya", "timezone": "Europe/London"},
    )
    await post(
        dev, f"/dev/families/{family['id']}/members", {"user_id": user["id"], "role": "organizer"}
    )
    return family["id"], user["id"]


# ---------------------------------------------------------------- mounting


async def test_dev_routes_are_not_mounted_outside_dev(client: httpx.AsyncClient) -> None:
    response = await client.post("/dev/families", json={"name": "x"})
    assert response.status_code == 404
    paths = (await client.get("/openapi.json")).json()["paths"]
    assert not [path for path in paths if path.startswith("/dev")]


async def test_prod_hides_docs(test_database_url: str) -> None:
    app = create_app(make_settings(test_database_url, env="prod"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/docs")).status_code == 404
        assert (await client.get("/openapi.json")).status_code == 404
        assert (await client.post("/dev/families", json={"name": "x"})).status_code == 404
    await app.state.engine.dispose()


# ---------------------------------------------------------------- the happy path


async def test_create_a_family_with_an_organizer_and_an_elder(
    dev: httpx.AsyncClient, session: AsyncSession
) -> None:
    family = await post(dev, "/dev/families", {"name": "  The Sharmas "})
    assert family["name"] == "The Sharmas"
    user = await post(
        dev,
        "/dev/users",
        {
            "email": " Priya@Example.com ",
            "display_name": "Priya",
            "timezone": "Europe/London",
            "country_code": "gb",
            "phone": "020 7946 0958",
            "locale": "en-GB",
        },
    )
    assert (user["email"], user["country_code"], user["phone_e164"]) == (
        "priya@example.com",
        "GB",
        "+442079460958",
    )
    member = await post(
        dev, f"/dev/families/{family['id']}/members", {"user_id": user["id"], "role": "organizer"}
    )
    assert member["role"] == "organizer"
    elder = await post(
        dev,
        f"/dev/families/{family['id']}/elders",
        {
            "display_name": "Mom",
            "timezone": "Asia/Calcutta",
            "country_code": "IN",
            "phone": "098765 43210",
            "is_primary": True,
        },
    )
    assert (elder["timezone"], elder["phone_e164"]) == ("Asia/Kolkata", "+919876543210")
    assert (elder["checkin_remind_at"], elder["checkin_due_by"]) == ("09:00:00", "12:00:00")
    assert (elder["checkin_grace_minutes"], elder["checkin_activity_counts_as_ok"]) == (60, True)

    detail = (await dev.get(f"/dev/families/{family['id']}")).json()
    assert [(m["display_name"], m["role"]) for m in detail["members"]] == [("Priya", "organizer")]
    assert [e["display_name"] for e in detail["elders"]] == ["Mom"]

    entries = (await session.scalars(select(AuditLog).order_by(AuditLog.id))).all()
    assert [e.action for e in entries] == [
        "family.created",
        "user.created",
        "family.member_added",
        "elder.created",
    ]
    assert {e.actor_type for e in entries} == {"dev"}
    assert all(e.request_id for e in entries)


async def test_lists(dev: httpx.AsyncClient) -> None:
    await make_family_with_organizer(dev)
    assert [f["name"] for f in (await dev.get("/dev/families")).json()] == ["The Sharmas"]
    assert [u["email"] for u in (await dev.get("/dev/users")).json()] == ["priya@example.com"]


# ---------------------------------------------------------------- conflicts


async def test_second_organizer_is_a_conflict(dev: httpx.AsyncClient) -> None:
    family_id, _ = await make_family_with_organizer(dev)
    other = await post(
        dev,
        "/dev/users",
        {"email": "arjun@example.com", "display_name": "Arjun", "timezone": "Asia/Kolkata"},
    )
    response = await dev.post(
        f"/dev/families/{family_id}/members", json={"user_id": other["id"], "role": "organizer"}
    )
    assert response.status_code == 409
    assert response.json()["constraint"] == "uq_family_members_one_organizer"


async def test_email_is_unique_ignoring_case(dev: httpx.AsyncClient) -> None:
    await make_family_with_organizer(dev)
    response = await dev.post(
        "/dev/users",
        json={"email": "PRIYA@example.com", "display_name": "P2", "timezone": "Europe/London"},
    )
    assert response.status_code == 409
    assert response.json()["constraint"] == "uq_users_email_lower"


async def test_second_primary_elder_is_a_conflict(dev: httpx.AsyncClient) -> None:
    family_id, _ = await make_family_with_organizer(dev)
    elder = {"display_name": "Mom", "timezone": "Asia/Kolkata", "country_code": "IN"}
    await post(dev, f"/dev/families/{family_id}/elders", {**elder, "is_primary": True})
    response = await dev.post(
        f"/dev/families/{family_id}/elders",
        json={**elder, "display_name": "Dad", "is_primary": True},
    )
    assert response.status_code == 409
    assert response.json()["constraint"] == "uq_elders_one_primary_per_family"


async def test_unknown_family_is_404(dev: httpx.AsyncClient) -> None:
    response = await dev.post(
        "/dev/families/00000000-0000-0000-0000-000000000000/elders",
        json={"display_name": "Mom", "timezone": "Asia/Kolkata", "country_code": "IN"},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize(
    ("changes", "error_type"),
    [
        ({"timezone": "Mars/Base"}, "invalid_timezone"),
        ({"timezone": None}, "string_type"),
        ({"country_code": "UK"}, "invalid_country"),
        ({"phone": "12345"}, "invalid_phone"),
        ({"checkin_remind_at": "13:00", "checkin_due_by": "12:00"}, "reminder_after_due"),
        ({"checkin_grace_minutes": 721}, "less_than_equal"),
    ],
)
async def test_elder_validation(
    dev: httpx.AsyncClient, changes: dict[str, Any], error_type: str
) -> None:
    family_id, _ = await make_family_with_organizer(dev)
    body = {"display_name": "Mom", "timezone": "Asia/Kolkata", "country_code": "IN", **changes}
    response = await dev.post(f"/dev/families/{family_id}/elders", json=body)
    assert response.status_code == 422
    assert response.json()["errors"][0]["type"] == error_type


async def test_elder_timezone_is_required(dev: httpx.AsyncClient) -> None:
    family_id, _ = await make_family_with_organizer(dev)
    response = await dev.post(
        f"/dev/families/{family_id}/elders", json={"display_name": "Mom", "country_code": "IN"}
    )
    assert response.status_code == 422
    assert response.json()["errors"][0] == {
        "loc": ["body", "timezone"],
        "msg": "Field required",
        "type": "missing",
    }


async def test_user_phone_without_plus_needs_a_country(dev: httpx.AsyncClient) -> None:
    response = await dev.post(
        "/dev/users",
        json={
            "email": "a@example.com",
            "display_name": "A",
            "timezone": "UTC",
            "phone": "020 7946 0958",
        },
    )
    assert response.status_code == 422
    assert response.json()["errors"][0]["type"] == "invalid_phone"


# ---------------------------------------------------------------- jobs


async def test_enqueue_list_and_requeue_jobs(
    dev: httpx.AsyncClient, test_database_url: str, clean_db: AsyncEngine
) -> None:
    echo = await post(dev, "/dev/jobs", {"type": "debug.echo", "idempotency_key": "once"})
    again = await post(dev, "/dev/jobs", {"type": "debug.echo", "idempotency_key": "once"})
    assert echo["created"] and not again["created"]
    assert echo["job"]["id"] == again["job"]["id"]

    failing = await post(dev, "/dev/jobs", {"type": "debug.fail", "max_attempts": 1})
    queued = (await dev.get("/dev/jobs", params={"status": "queued"})).json()
    assert {j["id"] for j in queued} == {echo["job"]["id"], failing["job"]["id"]}

    not_dead = await dev.post(f"/dev/jobs/{echo['job']['id']}/requeue")
    assert not_dead.status_code == 409

    worker = Worker(
        make_settings(test_database_url), async_sessionmaker(clean_db, expire_on_commit=False)
    )
    assert await worker.run_once() == 2
    dead = (await dev.get("/dev/jobs", params={"status": "dead"})).json()
    assert [j["id"] for j in dead] == [failing["job"]["id"]]
    assert "debug.fail always fails" in dead[0]["last_error"]

    requeued = await dev.post(f"/dev/jobs/{failing['job']['id']}/requeue")
    assert requeued.status_code == 200
    assert (requeued.json()["status"], requeued.json()["attempts"]) == ("queued", 0)
