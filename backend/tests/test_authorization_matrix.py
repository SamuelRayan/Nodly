"""Every endpoint against every kind of caller, table-driven.

The world: family A (organizer + member, elder A with a paired device and a revoked one) and
family B (organizer = "outsider" to A, elder B with its own device), plus a signed-in user who
hasn't finished onboarding. Requests target family A's resources unless a case says otherwise.
`test_every_route_is_in_the_matrix` fails if an endpoint is added without a row here.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.config import Settings
from nodly.main import create_app
from nodly.models import (
    Elder,
    ElderDevice,
    Family,
    FamilyMember,
    Invite,
    InviteKind,
    User,
)
from nodly.security.credentials import (
    CodeKind,
    generate_code,
    generate_device_token,
    hash_code,
    hash_device_token,
)
from nodly.security.pins import hash_pin
from tests.conftest import TEST_CODE_SECRET
from tests.fake_supabase import FakeSupabase, SupabaseUser

ROLES = (
    "anonymous",
    "bad_token",
    "expired_token",
    "not_onboarded",
    "outsider",
    "member",
    "organizer",
    "device",
    "other_device",
    "revoked_device",
)
NOW = datetime.now(UTC)


# ---------------------------------------------------------------- the world


@dataclass(frozen=True)
class IssuedCode:
    code: str
    invite_id: uuid.UUID


@dataclass
class World:
    session: AsyncSession
    supabase: FakeSupabase
    family_a: uuid.UUID = field(init=False)
    family_b: uuid.UUID = field(init=False)
    elder_a: uuid.UUID = field(init=False)
    elder_b: uuid.UUID = field(init=False)
    organizer_a: User = field(init=False)
    member_a: User = field(init=False)
    people: dict[str, SupabaseUser] = field(default_factory=dict)
    device_tokens: dict[str, str] = field(default_factory=dict)

    async def user(self, role: str, *, onboarded: bool = True) -> User:
        person = SupabaseUser(self.supabase, f"{role}-{uuid.uuid4().hex[:6]}@example.com")
        self.people[role] = person
        profile: dict[str, Any] = {}
        if onboarded:
            profile = {
                "display_name": role.title(),
                "timezone": "Europe/London",
                "country_code": "GB",
                "age_confirmed_at": NOW,
                "onboarded_at": NOW,
            }
        user = User(auth_user_id=person.auth_id, email=person.email, **profile)
        self.session.add(user)
        await self.session.flush()
        return user

    async def family(self, organizer: User, name: str) -> uuid.UUID:
        family = Family(name=name)
        self.session.add(family)
        await self.session.flush()
        self.session.add(FamilyMember(family_id=family.id, user_id=organizer.id, role="organizer"))
        return family.id

    async def elder(self, family_id: uuid.UUID) -> uuid.UUID:
        elder = Elder(
            family_id=family_id,
            display_name="Asha",
            timezone="Asia/Kolkata",
            country_code="IN",
            is_primary=True,
        )
        self.session.add(elder)
        await self.session.flush()
        return elder.id

    async def device(self, elder_id: uuid.UUID, *, revoked: bool = False) -> tuple[uuid.UUID, str]:
        token = generate_device_token()
        device = ElderDevice(
            elder_id=elder_id,
            token_hash=hash_device_token(token),
            platform="android",
            revoked_at=NOW if revoked else None,
        )
        self.session.add(device)
        await self.session.flush()
        return device.id, token

    async def code(self, code_kind: CodeKind, **fields: Any) -> "IssuedCode":
        code = generate_code(code_kind)
        invite = Invite(
            code_hash=hash_code(code, code_kind, TEST_CODE_SECRET),
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            **fields,
        )
        self.session.add(invite)
        await self.session.commit()
        return IssuedCode(code=code, invite_id=invite.id)

    def headers(self, role: str) -> dict[str, str]:
        if role == "anonymous":
            return {}
        if role == "bad_token":
            return {"Authorization": "Bearer not-a-token"}
        if role == "expired_token":
            person = self.people["organizer"]
            token = self.supabase.token(sub=person.auth_id, email=person.email, lifetime=-120)
            return {"Authorization": f"Bearer {token}"}
        if role in self.device_tokens:
            return {"Authorization": f"Bearer {self.device_tokens[role]}"}
        return self.people[role].headers


async def build_world(session: AsyncSession, supabase: FakeSupabase) -> World:
    world = World(session, supabase)
    world.organizer_a = await world.user("organizer")
    world.member_a = await world.user("member")
    outsider = await world.user("outsider")
    await world.user("not_onboarded", onboarded=False)

    world.family_a = await world.family(world.organizer_a, "Family A")
    session.add(FamilyMember(family_id=world.family_a, user_id=world.member_a.id, role="member"))
    world.family_b = await world.family(outsider, "Family B")
    world.elder_a = await world.elder(world.family_a)
    world.elder_b = await world.elder(world.family_b)
    _, world.device_tokens["device"] = await world.device(world.elder_a)
    _, world.device_tokens["revoked_device"] = await world.device(world.elder_a, revoked=True)
    _, world.device_tokens["other_device"] = await world.device(world.elder_b)
    await session.commit()
    return world


# ---------------------------------------------------------------- expectations

UNAUTHENTICATED = {"anonymous": 401, "bad_token": 401, "expired_token": 401}
DEVICES_401 = {"device": 401, "other_device": 401, "revoked_device": 401}


def public(status: int) -> dict[str, int]:
    return dict.fromkeys(ROLES, status)


def signed_in(status: int) -> dict[str, int]:
    """Any signed-in person, onboarded or not."""
    return {
        **UNAUTHENTICATED,
        **DEVICES_401,
        "not_onboarded": status,
        "outsider": status,
        "member": status,
        "organizer": status,
    }


def onboarded(status: int) -> dict[str, int]:
    return {**signed_in(status), "not_onboarded": 403}


def family_a(*, member: int, organizer: int) -> dict[str, int]:
    """A family-A resource: outsiders get 404 (can't even tell it exists)."""
    return {**onboarded(0), "outsider": 404, "member": member, "organizer": organizer}


def device_only(status: int = 200, *, other_device: int | None = None) -> dict[str, int]:
    return {
        **UNAUTHENTICATED,
        "not_onboarded": 401,
        "outsider": 401,
        "member": 401,
        "organizer": 401,
        "device": status,
        "other_device": status if other_device is None else other_device,
        "revoked_device": 401,
    }


Prepare = Callable[[World], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class Case:
    method: str
    path: str  # the route template, filled from the world
    expect: dict[str, int]
    body: Any = None
    prepare: Prepare | None = None  # a fresh target for each caller (path values and/or body)

    @property
    def id(self) -> str:
        return f"{self.method} {self.path}"


async def fresh_invite(world: World) -> dict[str, Any]:
    code = await world.code(
        CodeKind.invite,
        family_id=world.family_a,
        kind=InviteKind.member,
        created_by_user_id=world.organizer_a.id,
    )
    return {"invite_id": code.invite_id, "__body__": {"code": code.code}}


async def fresh_pairing_code(world: World) -> dict[str, Any]:
    code = await world.code(
        CodeKind.pairing,
        family_id=world.family_a,
        elder_id=world.elder_a,
        kind=InviteKind.elder_pairing,
        created_by_user_id=world.organizer_a.id,
    )
    return {"__body__": {"code": code.code, "platform": "android"}}


async def fresh_victim(world: World) -> dict[str, Any]:
    victim = await world.user(f"victim-{uuid.uuid4().hex[:6]}")
    world.session.add(FamilyMember(family_id=world.family_a, user_id=victim.id, role="member"))
    await world.session.commit()
    return {"user_id": victim.id}


async def fresh_device(world: World) -> dict[str, Any]:
    device_id, _ = await world.device(world.elder_a)
    await world.session.commit()
    return {"device_id": device_id}


async def fresh_push_token(world: World) -> dict[str, Any]:
    token = f"ExponentPushToken[{uuid.uuid4().hex}]"
    return {"__body__": {"provider": "expo", "token": token, "platform": "android"}}


async def pin_2468(world: World) -> dict[str, Any]:
    family = await world.session.get_one(Family, world.family_a)
    family.pin_hash = hash_pin("2468")
    await world.session.commit()
    return {"__body__": {"pin": "2468"}}


async def _query(params: dict[str, str]) -> dict[str, Any]:
    return {"__query__": params}


async def transfer_target(world: World) -> dict[str, Any]:
    return {"__body__": {"user_id": str(world.member_a.id)}}


ELDER_BODY = {"display_name": "Raj", "timezone": "Europe/London", "country_code": "GB"}

CASES = [
    # public
    Case("GET", "/healthz", public(200)),
    Case("GET", "/readyz", public(200)),
    Case("GET", "/v1/meta/timezones", public(200)),
    Case("GET", "/v1/meta/timezones/suggest", public(200)),
    Case("GET", "/v1/meta/countries", public(200)),
    # me
    Case("GET", "/v1/me", signed_in(200)),
    Case("PATCH", "/v1/me", signed_in(200), body={"language": "en"}),
    # families
    Case("POST", "/v1/families", onboarded(201), body={"name": "New"}),
    Case("GET", "/v1/families", onboarded(200)),
    Case("GET", "/v1/families/{family_id}", family_a(member=200, organizer=200)),
    Case(
        "PATCH",
        "/v1/families/{family_id}",
        family_a(member=403, organizer=200),
        body={"name": "A2"},
    ),
    Case(
        "POST",
        "/v1/families/{family_id}/organizer",
        family_a(member=403, organizer=200),
        prepare=transfer_target,
    ),
    Case(
        "DELETE",
        "/v1/families/{family_id}/members/{user_id}",
        family_a(member=403, organizer=204),
        prepare=fresh_victim,
    ),
    Case("POST", "/v1/families/{family_id}/leave", family_a(member=204, organizer=409)),
    # invites
    Case("POST", "/v1/families/{family_id}/invites", family_a(member=201, organizer=201)),
    Case("GET", "/v1/families/{family_id}/invites", family_a(member=200, organizer=200)),
    Case(
        "DELETE",
        "/v1/families/{family_id}/invites/{invite_id}",
        family_a(member=403, organizer=204),  # a member who didn't create it can't
        prepare=fresh_invite,
    ),
    Case("POST", "/v1/invites/preview", signed_in(200), prepare=fresh_invite),
    Case(
        "POST",
        "/v1/invites/accept",
        {**onboarded(0), "outsider": 200, "member": 409, "organizer": 409},
        prepare=fresh_invite,
    ),
    # elders
    Case(
        "POST",
        "/v1/families/{family_id}/elders",
        family_a(member=201, organizer=201),
        body=ELDER_BODY,
    ),
    Case("GET", "/v1/elders/{elder_id}", family_a(member=200, organizer=200)),
    Case(
        "PATCH",
        "/v1/elders/{elder_id}",
        family_a(member=200, organizer=200),
        body={"relation_label": "Mom"},
    ),
    Case("POST", "/v1/elders/{elder_id}/pause", family_a(member=200, organizer=200), body={}),
    Case("POST", "/v1/elders/{elder_id}/resume", family_a(member=200, organizer=200)),
    Case("POST", "/v1/elders/{elder_id}/primary", family_a(member=403, organizer=200)),
    # pairing & devices
    Case("POST", "/v1/elders/{elder_id}/pairing-codes", family_a(member=201, organizer=201)),
    Case("GET", "/v1/elders/{elder_id}/devices", family_a(member=200, organizer=200)),
    Case(
        "DELETE",
        "/v1/elders/{elder_id}/devices/{device_id}",
        family_a(member=204, organizer=204),
        prepare=fresh_device,
    ),
    Case("POST", "/v1/pairing/claim", public(201), prepare=fresh_pairing_code),  # no login
    Case("GET", "/v1/device/me", device_only()),
    Case("POST", "/v1/device/token/rotate", device_only()),
    Case("POST", "/v1/device/push-token", device_only(204), prepare=fresh_push_token),
    # Family A has a PIN (2468); family B has none, so its device gets 409 no_family_pin.
    Case("POST", "/v1/device/leave", device_only(204, other_device=409), prepare=pin_2468),
    # push tokens & family PIN (Phase 3)
    Case("POST", "/v1/me/push-tokens", signed_in(204), prepare=fresh_push_token),
    Case(
        "DELETE",
        "/v1/me/push-tokens",
        signed_in(204),
        prepare=lambda world: _query({"token": "ExponentPushToken[gone]"}),
    ),
    Case(
        "PUT",
        "/v1/families/{family_id}/pin",
        family_a(member=403, organizer=204),
        body={"pin": "2468"},
    ),
    Case("DELETE", "/v1/families/{family_id}/pin", family_a(member=403, organizer=204)),
]


def test_cases_name_every_role() -> None:
    for case in CASES:
        assert set(case.expect) == set(ROLES), case.id
        assert all(status for status in case.expect.values()), case.id


def test_every_route_is_in_the_matrix(settings: Settings) -> None:
    # The OpenAPI document lists every operation (FastAPI nests included routers in
    # app.routes, so walking that is fragile). ENV=test: /dev routes aren't mounted.
    paths = create_app(settings).openapi()["paths"]
    routes = {(method.upper(), path) for path, operations in paths.items() for method in operations}
    assert routes == {(case.method, case.path) for case in CASES}


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
async def test_authorization(
    case: Case, client: httpx.AsyncClient, session: AsyncSession, fake_supabase: FakeSupabase
) -> None:
    world = await build_world(session, fake_supabase)
    # Callers expected to fail go first, so a successful destructive call can't affect them.
    for role in sorted(ROLES, key=lambda r: 200 <= case.expect[r] < 300):
        values: dict[str, Any] = {"family_id": world.family_a, "elder_id": world.elder_a}
        if case.prepare:
            values |= await case.prepare(world)
        body = values.pop("__body__", case.body)
        query = values.pop("__query__", None)
        response = await client.request(
            case.method,
            case.path.format(**values),
            headers=world.headers(role),
            json=body,
            params=query,
        )
        assert response.status_code == case.expect[role], (
            f"{case.id} as {role}: {response.status_code} {response.text}"
        )


# ---------------------------------------------------------------- cross-family references


async def test_ids_from_another_family_are_not_found(
    client: httpx.AsyncClient, session: AsyncSession, fake_supabase: FakeSupabase
) -> None:
    """Mixing family A's path with family B's ids never reaches B's data."""
    world = await build_world(session, fake_supabase)
    organizer = world.headers("organizer")
    b_invite = await world.code(
        CodeKind.invite, family_id=world.family_b, kind=InviteKind.member, created_by_user_id=None
    )
    b_invite_id = b_invite.invite_id
    b_device_id, _ = await world.device(world.elder_b)
    await session.commit()

    attempts = [
        ("DELETE", f"/v1/families/{world.family_a}/invites/{b_invite_id}"),
        ("DELETE", f"/v1/elders/{world.elder_a}/devices/{b_device_id}"),
        ("GET", f"/v1/elders/{world.elder_b}"),
        ("POST", f"/v1/elders/{world.elder_b}/pairing-codes"),
        ("GET", f"/v1/elders/{world.elder_b}/devices"),
        ("DELETE", f"/v1/families/{world.family_b}/members/{world.organizer_a.id}"),
    ]
    for method, path in attempts:
        response = await client.request(method, path, headers=organizer)
        assert response.status_code == 404, f"{method} {path}: {response.text}"


async def test_devices_only_ever_see_their_own_elder(
    client: httpx.AsyncClient, session: AsyncSession, fake_supabase: FakeSupabase
) -> None:
    world = await build_world(session, fake_supabase)
    mine = (await client.get("/v1/device/me", headers=world.headers("device"))).json()
    theirs = (await client.get("/v1/device/me", headers=world.headers("other_device"))).json()
    assert (mine["elder"]["id"], mine["family"]["id"]) == (str(world.elder_a), str(world.family_a))
    assert (theirs["elder"]["id"], theirs["family"]["id"]) == (
        str(world.elder_b),
        str(world.family_b),
    )


async def test_unknown_ids_look_the_same_as_other_families(
    client: httpx.AsyncClient, session: AsyncSession, fake_supabase: FakeSupabase
) -> None:
    world = await build_world(session, fake_supabase)
    headers = world.headers("organizer")
    unknown = await client.get(f"/v1/families/{uuid.uuid4()}", headers=headers)
    foreign = await client.get(f"/v1/families/{world.family_b}", headers=headers)
    assert unknown.status_code == foreign.status_code == 404
    assert unknown.json()["detail"] == foreign.json()["detail"]
