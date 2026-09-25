"""The identity migration: constraints, defaults, cascades, and that models match migrations."""

import uuid
from datetime import UTC, datetime, time, timedelta

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from nodly.errors import constraint_name
from nodly.models import (
    ActorType,
    AuditLog,
    Base,
    Elder,
    ElderDevice,
    FamilyMember,
    FamilyRole,
    Invite,
    InviteKind,
    PushToken,
    User,
)
from tests.support import make_elder, make_family, make_member, make_user, migrate

NOT_NULL_VIOLATION = "23502"
HASH = "a" * 64
NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


async def assert_violates(session: AsyncSession, constraint: str) -> None:
    with pytest.raises(IntegrityError) as excinfo:
        await session.flush()
    assert constraint_name(excinfo.value) == constraint
    await session.rollback()


async def assert_not_null(session: AsyncSession, column: str) -> None:
    with pytest.raises(IntegrityError) as excinfo:
        await session.flush()
    assert getattr(excinfo.value.orig, "sqlstate", None) == NOT_NULL_VIOLATION
    assert column in str(excinfo.value.orig)
    await session.rollback()


# ---------------------------------------------------------------- migrations


async def test_models_match_migrations(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        diff = await conn.run_sync(
            lambda sync_conn: compare_metadata(MigrationContext.configure(sync_conn), Base.metadata)
        )
    assert diff == []


async def test_migrations_downgrade_to_base_and_back(engine: AsyncEngine) -> None:
    # Postgres DDL is transactional: the round trip is rolled back, other tests are unaffected.
    async with engine.connect() as conn:
        transaction = await conn.begin()
        await conn.run_sync(migrate, "downgrade", "base")
        await conn.run_sync(migrate, "upgrade", "head")
        await transaction.rollback()


# ---------------------------------------------------------------- timezones are required


async def test_new_user_may_have_an_empty_profile(session: AsyncSession) -> None:
    # Rows are created on the first GET /v1/me, before onboarding.
    session.add(User(email="new@example.com"))
    await session.flush()


@pytest.mark.parametrize("missing", ["display_name", "timezone", "country_code", "age_confirmed"])
async def test_onboarded_user_needs_a_complete_profile(session: AsyncSession, missing: str) -> None:
    fields: dict[str, object] = {
        "display_name": "Arjun",
        "timezone": "Asia/Kolkata",
        "country_code": "IN",
        "age_confirmed_at": NOW,
    }
    fields.pop("age_confirmed_at" if missing == "age_confirmed" else missing)
    session.add(User(email="arjun@example.com", onboarded_at=NOW, **fields))
    await assert_violates(session, "ck_users_onboarded_profile_complete")


async def test_elder_timezone_is_required(session: AsyncSession) -> None:
    family = await make_family(session)
    session.add(Elder(family_id=family.id, display_name="Dad", country_code="GB"))
    await assert_not_null(session, "timezone")


async def test_elder_country_is_required(session: AsyncSession) -> None:
    family = await make_family(session)
    session.add(Elder(family_id=family.id, display_name="Dad", timezone="Europe/London"))
    await assert_not_null(session, "country_code")


async def test_empty_timezone_is_rejected(session: AsyncSession) -> None:
    family = await make_family(session)
    session.add(Elder(family_id=family.id, display_name="Dad", timezone="", country_code="GB"))
    await assert_violates(session, "ck_elders_timezone_not_empty")


# ---------------------------------------------------------------- elders


async def test_elder_checkin_defaults(session: AsyncSession) -> None:
    elder = await make_elder(session, await make_family(session))
    await session.refresh(elder)
    assert elder.checkin_remind_at == time(9, 0)
    assert elder.checkin_due_by == time(12, 0)
    assert elder.checkin_grace_minutes == 60
    assert elder.checkin_activity_counts_as_ok is True
    assert elder.is_primary is False


async def test_one_primary_elder_per_family(session: AsyncSession) -> None:
    family, other = await make_family(session), await make_family(session)
    await make_elder(session, family, is_primary=True)
    await make_elder(session, family)  # a second, non-primary elder is fine
    await make_elder(session, other, is_primary=True)  # another family's primary is fine
    session.add(
        Elder(
            family_id=family.id,
            display_name="Dad",
            timezone="Asia/Kolkata",
            country_code="IN",
            is_primary=True,
        )
    )
    await assert_violates(session, "uq_elders_one_primary_per_family")


async def test_reminder_must_not_be_after_due_time(session: AsyncSession) -> None:
    family = await make_family(session)
    session.add(
        Elder(
            family_id=family.id,
            display_name="Dad",
            timezone="Asia/Kolkata",
            country_code="IN",
            checkin_remind_at=time(13, 0),
            checkin_due_by=time(12, 0),
        )
    )
    await assert_violates(session, "ck_elders_checkin_remind_before_due")


async def test_grace_minutes_range(session: AsyncSession) -> None:
    family = await make_family(session)
    session.add(
        Elder(
            family_id=family.id,
            display_name="Dad",
            timezone="Asia/Kolkata",
            country_code="IN",
            checkin_grace_minutes=721,
        )
    )
    await assert_violates(session, "ck_elders_checkin_grace_minutes")


@pytest.mark.parametrize("code", ["in", "IND", "I1"])
async def test_country_code_format(session: AsyncSession, code: str) -> None:
    family = await make_family(session)
    session.add(
        Elder(family_id=family.id, display_name="Dad", timezone="Asia/Kolkata", country_code=code)
    )
    # "IND" fails the varchar(2) length (a DataError); the others fail the CHECK.
    with pytest.raises(DBAPIError):
        await session.flush()
    await session.rollback()


# ---------------------------------------------------------------- users & members


async def test_email_is_unique_ignoring_case(session: AsyncSession) -> None:
    await make_user(session, email="priya@example.com")
    session.add(User(email="Priya@Example.com", display_name="P", timezone="Europe/London"))
    await assert_violates(session, "uq_users_email_lower")


@pytest.mark.parametrize("phone", ["919876543210", "+0123456789", "+91 98765 43210", "+12345"])
async def test_phone_must_be_e164(session: AsyncSession, phone: str) -> None:
    session.add(User(email="p@example.com", display_name="P", timezone="UTC", phone_e164=phone))
    await assert_violates(session, "ck_users_phone_e164")


async def test_one_organizer_per_family(session: AsyncSession) -> None:
    family = await make_family(session)
    await make_member(session, family, await make_user(session), FamilyRole.organizer)
    await make_member(session, family, await make_user(session), FamilyRole.member)
    second = await make_user(session)
    session.add(FamilyMember(family_id=family.id, user_id=second.id, role=FamilyRole.organizer))
    await assert_violates(session, "uq_family_members_one_organizer")


async def test_user_joins_a_family_once(session: AsyncSession) -> None:
    family, user = await make_family(session), await make_user(session)
    await make_member(session, family, user)
    session.add(FamilyMember(family_id=family.id, user_id=user.id, role=FamilyRole.member))
    await assert_violates(session, "uq_family_members_family_id_user_id")


async def test_role_must_be_known(session: AsyncSession) -> None:
    family, user = await make_family(session), await make_user(session)
    session.add(FamilyMember(family_id=family.id, user_id=user.id, role="admin"))
    await assert_violates(session, "ck_family_members_role")


async def test_a_user_can_belong_to_several_families(session: AsyncSession) -> None:
    user = await make_user(session)
    await make_member(session, await make_family(session), user, FamilyRole.organizer)
    await make_member(session, await make_family(session), user, FamilyRole.organizer)


# ---------------------------------------------------------------- devices, invites, push tokens


async def test_device_token_hash_is_unique_hex(session: AsyncSession) -> None:
    elder = await make_elder(session, await make_family(session))
    session.add(ElderDevice(elder_id=elder.id, token_hash="not-a-hash", platform="android"))
    await assert_violates(session, "ck_elder_devices_token_hash")

    elder = await make_elder(session, await make_family(session))
    session.add(ElderDevice(elder_id=elder.id, token_hash=HASH, platform="android"))
    await session.flush()
    session.add(ElderDevice(elder_id=elder.id, token_hash=HASH, platform="ios"))
    await assert_violates(session, "uq_elder_devices_token_hash")


async def test_pairing_invite_needs_an_elder(session: AsyncSession) -> None:
    family = await make_family(session)
    session.add(
        Invite(
            family_id=family.id,
            kind=InviteKind.elder_pairing,
            code_hash=HASH,
            expires_at=NOW + timedelta(minutes=15),
        )
    )
    await assert_violates(session, "ck_invites_pairing_has_elder")


async def test_member_invite_must_not_name_an_elder(session: AsyncSession) -> None:
    family = await make_family(session)
    elder = await make_elder(session, family)
    session.add(
        Invite(
            family_id=family.id,
            kind=InviteKind.member,
            elder_id=elder.id,
            code_hash=HASH,
            expires_at=NOW + timedelta(hours=48),
        )
    )
    await assert_violates(session, "ck_invites_pairing_has_elder")


async def test_invite_must_expire_after_creation(session: AsyncSession) -> None:
    family = await make_family(session)
    session.add(
        Invite(
            family_id=family.id,
            kind=InviteKind.member,
            code_hash=HASH,
            created_at=NOW,
            expires_at=NOW,
        )
    )
    await assert_violates(session, "ck_invites_expires_after_created")


@pytest.mark.parametrize("owners", ["none", "both"])
async def test_push_token_has_exactly_one_owner(session: AsyncSession, owners: str) -> None:
    family = await make_family(session)
    user = await make_user(session)
    elder = await make_elder(session, family)
    device = ElderDevice(elder_id=elder.id, token_hash=HASH, platform="android")
    session.add(device)
    await session.flush()
    session.add(
        PushToken(
            user_id=user.id if owners == "both" else None,
            elder_device_id=device.id if owners == "both" else None,
            provider="expo",
            token="ExponentPushToken[x]",
            platform="android",
        )
    )
    await assert_violates(session, "ck_push_tokens_exactly_one_owner")


# ---------------------------------------------------------------- cascades & audit log


async def test_deleting_a_family_removes_its_elders_members_and_devices(
    session: AsyncSession,
) -> None:
    family = await make_family(session)
    user = await make_user(session)
    await make_member(session, family, user, FamilyRole.organizer)
    elder = await make_elder(session, family)
    session.add(ElderDevice(elder_id=elder.id, token_hash=HASH, platform="android"))
    await session.commit()

    await session.delete(family)
    await session.commit()

    for model in (Elder, FamilyMember, ElderDevice):
        assert await session.scalar(select(func.count()).select_from(model)) == 0
    # The user account is not part of the family and stays.
    assert await session.get(type(user), user.id) is not None


async def test_audit_log_defaults(session: AsyncSession) -> None:
    entry = AuditLog(actor_type=ActorType.system, action="test.happened", family_id=uuid.uuid4())
    session.add(entry)
    await session.flush()
    await session.refresh(entry)
    assert entry.id > 0
    assert entry.data == {}
    assert entry.occurred_at is not None
