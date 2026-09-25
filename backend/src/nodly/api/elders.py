"""Elder profiles: create, update, pause/resume check-ins, choose the primary elder."""

from datetime import time
from typing import Annotated, Self

from fastapi import APIRouter, status
from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, model_validator
from pydantic_core import PydanticCustomError
from sqlalchemy import select, update

from nodly.api.common import USER_AUTH_ERRORS, problems
from nodly.api.schemas import ElderOut, FamilyDetail, elder_out, family_detail
from nodly.api.types import (
    CountryCode,
    DisplayName,
    LanguageTag,
    PhoneInput,
    TimezoneName,
    normalize_phone_field,
)
from nodly.audit import record_audit
from nodly.auth.access import (
    ElderMemberAccess,
    ElderOrganizerAccess,
    FamilyAccess,
    MemberAccess,
)
from nodly.clock import utcnow
from nodly.db import SessionDep
from nodly.errors import InvalidInputError
from nodly.models import ActorType, Elder
from nodly.services.phones import normalize_e164

router = APIRouter(tags=["elders"])

RelationLabel = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=40),
    Field(examples=["Mom"], description="How the family refers to them"),
]
FullName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
    Field(examples=["Asha Sharma"], description="For recipe bylines later"),
]

DEFAULT_REMIND_AT = time(9, 0)
DEFAULT_DUE_BY = time(12, 0)


class CheckinSettingsIn(BaseModel):
    """Any subset; missing values keep the current (or default) setting."""

    remind_at: time | None = Field(default=None, examples=["09:00"])
    due_by: time | None = Field(default=None, examples=["12:00"])
    grace_minutes: int | None = Field(default=None, ge=0, le=720)
    activity_counts_as_ok: bool | None = None


class ElderCreate(BaseModel):
    display_name: DisplayName = Field(examples=["Asha"])
    relation_label: RelationLabel | None = None
    full_name: FullName | None = None
    timezone: TimezoneName
    country_code: CountryCode = Field(description="Picks the emergency number on Help screens")
    language: LanguageTag | None = None
    phone: PhoneInput | None = None
    checkin: CheckinSettingsIn = Field(default_factory=CheckinSettingsIn)

    @model_validator(mode="after")
    def _check(self) -> Self:
        remind = self.checkin.remind_at or DEFAULT_REMIND_AT
        due = self.checkin.due_by or DEFAULT_DUE_BY
        if remind > due:
            raise PydanticCustomError("reminder_after_due", "remind_at must not be after due_by")
        self.phone = normalize_phone_field(self.phone, self.country_code)
        return self


class ElderUpdate(BaseModel):
    """Fields left out stay as they are. Optional fields can be cleared with null."""

    display_name: DisplayName | None = None
    relation_label: RelationLabel | None = None
    full_name: FullName | None = None
    timezone: TimezoneName | None = None
    country_code: CountryCode | None = None
    language: LanguageTag | None = None
    phone: PhoneInput | None = None
    checkin: CheckinSettingsIn | None = None

    @model_validator(mode="after")
    def _required_fields_stay_set(self) -> Self:
        for name in ("display_name", "timezone", "country_code"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise PydanticCustomError("cannot_clear", f"{name} can't be cleared")
        return self


class PauseIn(BaseModel):
    until: AwareDatetime | None = Field(
        default=None, description="Resume automatically at this time; null = until resumed"
    )


class ReminderAfterDueError(InvalidInputError):
    code = "reminder_after_due"
    title = "The reminder must come before the due time"


def _audit(
    session: SessionDep, access: FamilyAccess, elder: Elder, action: str, **data: object
) -> None:
    record_audit(
        session,
        actor_type=ActorType.user,
        actor_id=access.user.id,
        family_id=access.family.id,
        action=action,
        entity_type="elder",
        entity_id=elder.id,
        data=dict(data),
    )


@router.post(
    "/v1/families/{family_id}/elders",
    status_code=status.HTTP_201_CREATED,
    responses=problems(*USER_AUTH_ERRORS, 404, 422),
)
async def create_elder(body: ElderCreate, access: MemberAccess, session: SessionDep) -> ElderOut:
    """Any member can add an elder. The family's first elder becomes the primary elder, whose
    timezone is the family clock."""
    has_primary = await session.scalar(
        select(Elder.id).where(Elder.family_id == access.family.id, Elder.is_primary)
    )
    checkin = body.checkin
    elder = Elder(
        family_id=access.family.id,
        display_name=body.display_name,
        relation_label=body.relation_label,
        full_name=body.full_name,
        timezone=body.timezone,
        country_code=body.country_code,
        language=body.language,
        phone_e164=body.phone,
        is_primary=has_primary is None,
        checkin_remind_at=checkin.remind_at or DEFAULT_REMIND_AT,
        checkin_due_by=checkin.due_by or DEFAULT_DUE_BY,
        checkin_grace_minutes=60 if checkin.grace_minutes is None else checkin.grace_minutes,
        checkin_activity_counts_as_ok=(
            True if checkin.activity_counts_as_ok is None else checkin.activity_counts_as_ok
        ),
    )
    session.add(elder)
    await session.flush()
    _audit(session, access, elder, "elder.created", is_primary=elder.is_primary)
    await session.commit()
    return elder_out(elder)


@router.get("/v1/elders/{elder_id}", responses=problems(*USER_AUTH_ERRORS, 404))
async def get_elder(access: ElderMemberAccess) -> ElderOut:
    return elder_out(access.elder)


@router.patch("/v1/elders/{elder_id}", responses=problems(*USER_AUTH_ERRORS, 404, 422))
async def update_elder(
    body: ElderUpdate, access: ElderMemberAccess, session: SessionDep
) -> ElderOut:
    """Any member can update the profile and check-in settings."""
    elder = access.elder
    changes = body.model_dump(exclude_unset=True, exclude={"checkin", "phone"})
    for name, value in changes.items():
        setattr(elder, name, value)
    changed = sorted(changes)
    if "phone" in body.model_fields_set:
        elder.phone_e164 = normalize_e164(body.phone, elder.country_code) if body.phone else None
        changed.append("phone")
    if body.checkin is not None:
        for name, value in body.checkin.model_dump(exclude_unset=True).items():
            if value is None:
                continue
            column = (
                "checkin_activity_counts_as_ok"
                if name == "activity_counts_as_ok"
                else f"checkin_{name}"
            )
            setattr(elder, column, value)
            changed.append(f"checkin.{name}")
    if elder.checkin_remind_at > elder.checkin_due_by:
        raise ReminderAfterDueError("remind_at must not be after due_by.")
    if changed:
        _audit(session, access, elder, "elder.updated", fields=changed)
        await session.commit()
    return elder_out(elder)


@router.post("/v1/elders/{elder_id}/pause", responses=problems(*USER_AUTH_ERRORS, 404, 422))
async def pause_elder(body: PauseIn, access: ElderMemberAccess, session: SessionDep) -> ElderOut:
    """Stop check-in reminders and missed-check-in alerts (e.g. a hospital stay or a trip).
    Help is never paused."""
    now = utcnow()
    if body.until is not None and body.until <= now:
        raise InvalidInputError("`until` must be in the future.")
    elder = access.elder
    elder.paused_at = now
    elder.paused_until = body.until
    _audit(
        session, access, elder, "elder.paused", until=body.until.isoformat() if body.until else None
    )
    await session.commit()
    return elder_out(elder, now)


@router.post("/v1/elders/{elder_id}/resume", responses=problems(*USER_AUTH_ERRORS, 404))
async def resume_elder(access: ElderMemberAccess, session: SessionDep) -> ElderOut:
    elder = access.elder
    if elder.paused_at is not None:
        elder.paused_at = None
        elder.paused_until = None
        _audit(session, access, elder, "elder.resumed")
        await session.commit()
    return elder_out(elder)


@router.post("/v1/elders/{elder_id}/primary", responses=problems(*USER_AUTH_ERRORS, 404))
async def make_primary_elder(access: ElderOrganizerAccess, session: SessionDep) -> FamilyDetail:
    """Organizer only: this elder's timezone becomes the family clock (which decides 'today'
    for check-ins and billing)."""
    elder = access.elder
    if not elder.is_primary:
        # Clear the old primary first: "one primary per family" is checked per statement.
        await session.execute(
            update(Elder)
            .where(Elder.family_id == elder.family_id, Elder.is_primary)
            .values(is_primary=False, updated_at=utcnow())
        )
        elder.is_primary = True
        _audit(session, access, elder, "elder.primary_changed", timezone=elder.timezone)
        await session.commit()
    return await family_detail(session, access.family, access.member.role)
