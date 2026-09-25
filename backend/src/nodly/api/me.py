"""The signed-in family member's own profile and onboarding."""

import uuid
from datetime import datetime
from typing import Literal, Self

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator
from pydantic_core import PydanticCustomError

from nodly.api.common import USER_AUTH_ERRORS, problems
from nodly.api.types import CountryCode, DisplayName, LanguageTag, PhoneInput, TimezoneName
from nodly.audit import record_audit
from nodly.auth.users import CurrentUser
from nodly.clock import utcnow
from nodly.db import SessionDep
from nodly.models import ActorType, User
from nodly.services.phones import normalize_e164

router = APIRouter(prefix="/v1/me", tags=["me"])

OnboardingField = Literal["display_name", "timezone", "country_code", "age_confirmation"]


class Onboarding(BaseModel):
    complete: bool
    missing: list[OnboardingField] = Field(
        description="What PATCH /v1/me still needs before family features unlock"
    )


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    timezone: str | None
    country_code: str | None
    phone_e164: str | None
    language: str | None
    age_confirmed: bool
    onboarding: Onboarding
    created_at: datetime


class MeUpdate(BaseModel):
    """Fields left out stay as they are. Name, timezone and country can't be cleared."""

    display_name: DisplayName | None = None
    timezone: TimezoneName | None = None
    country_code: CountryCode | None = None
    phone: PhoneInput | None = Field(default=None, description="Any format; null clears it")
    language: LanguageTag | None = None
    confirm_age_16_plus: Literal[True] | None = Field(
        default=None, description="Send true to confirm you are 16 or older (required once)"
    )

    @model_validator(mode="after")
    def _required_fields_stay_set(self) -> Self:
        for name in ("display_name", "timezone", "country_code"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise PydanticCustomError("cannot_clear", f"{name} can't be cleared")
        return self


def _missing(user: User) -> list[OnboardingField]:
    missing: list[OnboardingField] = []
    if user.display_name is None:
        missing.append("display_name")
    if user.timezone is None:
        missing.append("timezone")
    if user.country_code is None:
        missing.append("country_code")
    if user.age_confirmed_at is None:
        missing.append("age_confirmation")
    return missing


def _me(user: User) -> MeOut:
    return MeOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        timezone=user.timezone,
        country_code=user.country_code,
        phone_e164=user.phone_e164,
        language=user.language,
        age_confirmed=user.age_confirmed_at is not None,
        onboarding=Onboarding(complete=user.is_onboarded, missing=_missing(user)),
        created_at=user.created_at,
    )


@router.get("", responses=problems(*USER_AUTH_ERRORS, 409))
async def get_me(user: CurrentUser) -> MeOut:
    """Your profile. The first call after signing up creates your Nodly account."""
    return _me(user)


@router.patch("", responses=problems(*USER_AUTH_ERRORS, 422))
async def update_me(body: MeUpdate, user: CurrentUser, session: SessionDep) -> MeOut:
    """Fill in or change your profile. Onboarding completes once your name, timezone and
    country are set and you've confirmed you're 16 or older."""
    now = utcnow()
    changes = body.model_dump(exclude_unset=True)
    for name in ("display_name", "timezone", "country_code", "language"):
        if name in changes:
            setattr(user, name, changes[name])
    if "phone" in changes:
        # A number without + is read in the user's country (the new one if it's changing).
        phone = changes["phone"]
        user.phone_e164 = normalize_e164(phone, user.country_code) if phone else None
    if body.confirm_age_16_plus and user.age_confirmed_at is None:
        user.age_confirmed_at = now
    if not user.is_onboarded and not _missing(user):
        user.onboarded_at = now
        record_audit(
            session,
            actor_type=ActorType.user,
            actor_id=user.id,
            action="user.onboarded",
            entity_type="user",
            entity_id=user.id,
        )
    await session.commit()
    return _me(user)
