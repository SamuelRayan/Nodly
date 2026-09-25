"""Dev-only helpers for creating test data and poking the job queue from /docs.

Mounted only when ENV=dev (see nodly.main). There is no auth here on purpose: these routes
must never exist in staging or prod. Every write is recorded in the audit log as actor "dev".
"""

import uuid
from datetime import datetime, time
from typing import Annotated, Any, Self

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic_core import PydanticCustomError
from sqlalchemy import select

from nodly.api.types import (
    CountryCode,
    DisplayName,
    LanguageTag,
    PhoneInput,
    TimezoneName,
    normalize_phone_field,
)
from nodly.audit import record_audit
from nodly.clock import utcnow
from nodly.db import SessionDep
from nodly.errors import NotFoundError
from nodly.jobs import queue
from nodly.models import ActorType, Elder, Family, FamilyMember, FamilyRole, Job, JobStatus, User

router = APIRouter(prefix="/dev", tags=["dev (ENV=dev only)"])

Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_lower=True, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    ),
]


# ---------------------------------------------------------------- schemas


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class FamilyIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class FamilyOut(ORMModel):
    id: uuid.UUID
    name: str
    created_at: datetime


class UserIn(BaseModel):
    """A test user with a finished profile (no Supabase account: it can't sign in)."""

    email: Email = Field(examples=["priya@example.com"])
    display_name: DisplayName = Field(examples=["Priya"])
    timezone: TimezoneName
    country_code: CountryCode
    phone: PhoneInput | None = None
    language: LanguageTag | None = None

    @model_validator(mode="after")
    def _phone_to_e164(self) -> Self:
        self.phone = normalize_phone_field(self.phone, self.country_code)
        return self


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    timezone: str | None
    country_code: str | None
    phone_e164: str | None
    language: str | None
    onboarded_at: datetime | None
    created_at: datetime


class MemberIn(BaseModel):
    user_id: uuid.UUID
    role: FamilyRole = FamilyRole.member


class MemberOut(BaseModel):
    user_id: uuid.UUID
    display_name: str | None
    email: str
    role: FamilyRole
    joined_at: datetime


class ElderIn(BaseModel):
    display_name: DisplayName = Field(examples=["Mom"])
    timezone: TimezoneName
    country_code: CountryCode = Field(description="Picks the emergency number on Help screens")
    phone: PhoneInput | None = None
    language: LanguageTag | None = None
    is_primary: bool = Field(
        default=False, description="The primary elder's timezone is the family clock"
    )
    checkin_remind_at: time = time(9, 0)
    checkin_due_by: time = time(12, 0)
    checkin_grace_minutes: int = Field(default=60, ge=0, le=720)
    checkin_activity_counts_as_ok: bool = True

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.checkin_remind_at > self.checkin_due_by:
            raise PydanticCustomError(
                "reminder_after_due", "checkin_remind_at must not be after checkin_due_by"
            )
        self.phone = normalize_phone_field(self.phone, self.country_code)
        return self


class ElderOut(ORMModel):
    id: uuid.UUID
    family_id: uuid.UUID
    display_name: str
    timezone: str
    country_code: str
    phone_e164: str | None
    language: str | None
    is_primary: bool
    checkin_remind_at: time
    checkin_due_by: time
    checkin_grace_minutes: int
    checkin_activity_counts_as_ok: bool
    created_at: datetime


class FamilyDetailOut(FamilyOut):
    members: list[MemberOut]
    elders: list[ElderOut]


class JobIn(BaseModel):
    type: Annotated[str, StringConstraints(min_length=1, max_length=100)] = Field(
        examples=["debug.echo", "debug.fail"]
    )
    payload: dict[str, Any] = Field(default_factory=dict)
    run_at: datetime | None = Field(default=None, description="Default: now")
    idempotency_key: str | None = Field(default=None, max_length=200)
    max_attempts: int | None = Field(default=None, ge=1, le=100)


class JobOut(ORMModel):
    id: int
    type: str
    payload: dict[str, Any]
    status: JobStatus
    run_at: datetime
    attempts: int
    max_attempts: int
    idempotency_key: str | None
    last_error: str | None
    locked_by: str | None
    finished_at: datetime | None
    created_at: datetime


class EnqueueOut(BaseModel):
    created: bool
    job: JobOut


# ---------------------------------------------------------------- families & people


async def _get_family(session: SessionDep, family_id: uuid.UUID) -> Family:
    family = await session.get(Family, family_id)
    if family is None:
        raise NotFoundError(f"Family {family_id} doesn't exist.")
    return family


@router.post("/families", status_code=status.HTTP_201_CREATED)
async def create_family(body: FamilyIn, session: SessionDep) -> FamilyOut:
    family = Family(name=body.name)
    session.add(family)
    await session.flush()
    record_audit(
        session,
        actor_type=ActorType.dev,
        action="family.created",
        family_id=family.id,
        entity_type="family",
        entity_id=family.id,
    )
    await session.commit()
    return FamilyOut.model_validate(family)


@router.get("/families")
async def list_families(session: SessionDep) -> list[FamilyOut]:
    families = await session.scalars(select(Family).order_by(Family.created_at.desc()).limit(100))
    return [FamilyOut.model_validate(f) for f in families]


@router.get("/families/{family_id}")
async def get_family(family_id: uuid.UUID, session: SessionDep) -> FamilyDetailOut:
    family = await _get_family(session, family_id)
    members = (
        await session.execute(
            select(FamilyMember, User)
            .join(User, User.id == FamilyMember.user_id)
            .where(FamilyMember.family_id == family_id)
            .order_by(FamilyMember.created_at)
        )
    ).all()
    elders = await session.scalars(
        select(Elder).where(Elder.family_id == family_id).order_by(Elder.created_at)
    )
    return FamilyDetailOut(
        id=family.id,
        name=family.name,
        created_at=family.created_at,
        members=[
            MemberOut(
                user_id=user.id,
                display_name=user.display_name,
                email=user.email,
                role=FamilyRole(member.role),
                joined_at=member.created_at,
            )
            for member, user in members
        ],
        elders=[ElderOut.model_validate(e) for e in elders],
    )


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(body: UserIn, session: SessionDep) -> UserOut:
    now = utcnow()
    user = User(
        email=body.email,
        display_name=body.display_name,
        timezone=body.timezone,
        country_code=body.country_code,
        phone_e164=body.phone,
        language=body.language,
        age_confirmed_at=now,
        onboarded_at=now,
    )
    session.add(user)
    await session.flush()
    record_audit(
        session,
        actor_type=ActorType.dev,
        action="user.created",
        entity_type="user",
        entity_id=user.id,
    )
    await session.commit()
    return UserOut.model_validate(user)


@router.get("/users")
async def list_users(session: SessionDep) -> list[UserOut]:
    users = await session.scalars(select(User).order_by(User.created_at.desc()).limit(100))
    return [UserOut.model_validate(u) for u in users]


@router.post("/families/{family_id}/members", status_code=status.HTTP_201_CREATED)
async def add_member(family_id: uuid.UUID, body: MemberIn, session: SessionDep) -> MemberOut:
    await _get_family(session, family_id)
    user = await session.get(User, body.user_id)
    if user is None:
        raise NotFoundError(f"User {body.user_id} doesn't exist.")
    member = FamilyMember(family_id=family_id, user_id=user.id, role=body.role)
    session.add(member)
    await session.flush()  # a duplicate or second organizer is a 409 with the constraint name
    record_audit(
        session,
        actor_type=ActorType.dev,
        action="family.member_added",
        family_id=family_id,
        entity_type="user",
        entity_id=user.id,
        data={"role": body.role},
    )
    await session.commit()
    return MemberOut(
        user_id=user.id,
        display_name=user.display_name,
        email=user.email,
        role=body.role,
        joined_at=member.created_at,
    )


@router.post("/families/{family_id}/elders", status_code=status.HTTP_201_CREATED)
async def create_elder(family_id: uuid.UUID, body: ElderIn, session: SessionDep) -> ElderOut:
    await _get_family(session, family_id)
    elder = Elder(
        family_id=family_id,
        display_name=body.display_name,
        timezone=body.timezone,
        country_code=body.country_code,
        phone_e164=body.phone,
        language=body.language,
        is_primary=body.is_primary,
        checkin_remind_at=body.checkin_remind_at,
        checkin_due_by=body.checkin_due_by,
        checkin_grace_minutes=body.checkin_grace_minutes,
        checkin_activity_counts_as_ok=body.checkin_activity_counts_as_ok,
    )
    session.add(elder)
    await session.flush()  # a second primary elder is a 409 with the constraint name
    record_audit(
        session,
        actor_type=ActorType.dev,
        action="elder.created",
        family_id=family_id,
        entity_type="elder",
        entity_id=elder.id,
    )
    await session.commit()
    return ElderOut.model_validate(elder)


# ---------------------------------------------------------------- jobs


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
async def enqueue_job(body: JobIn, session: SessionDep) -> EnqueueOut:
    """Try `debug.echo` (succeeds) or `debug.fail` (retries with backoff, then goes dead)."""
    result = await queue.enqueue(
        session,
        body.type,
        body.payload,
        run_at=body.run_at,
        idempotency_key=body.idempotency_key,
        max_attempts=body.max_attempts,
    )
    await session.commit()
    return EnqueueOut(created=result.created, job=JobOut.model_validate(result.job))


@router.get("/jobs")
async def list_jobs(
    session: SessionDep,
    job_status: Annotated[JobStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[JobOut]:
    query = select(Job).order_by(Job.id.desc()).limit(limit)
    if job_status is not None:
        query = query.where(Job.status == job_status)
    return [JobOut.model_validate(j) for j in await session.scalars(query)]


@router.post("/jobs/{job_id}/requeue")
async def requeue_job(job_id: int, session: SessionDep) -> JobOut:
    """Move a dead job back to the queue with a fresh set of attempts."""
    job = await queue.requeue_dead(session, job_id, now=utcnow())
    return JobOut.model_validate(job)
