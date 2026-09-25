"""FastAPI dependencies for signed-in family members (Supabase access tokens)."""

from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from nodly.audit import record_audit
from nodly.auth.supabase import (
    AuthNotConfiguredError,
    InvalidTokenError,
    SupabaseClaims,
    SupabaseTokenVerifier,
)
from nodly.db import SessionDep
from nodly.errors import ConflictError, ForbiddenError, UnauthorizedError
from nodly.models import ActorType, User
from nodly.security.credentials import is_device_token

supabase_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="SupabaseJWT",
    description="A family member's Supabase access token (Authorization: Bearer <jwt>).",
)


class NotAuthenticatedError(UnauthorizedError):
    code = "not_authenticated"
    title = "Sign in required"


class EmailRequiredError(ForbiddenError):
    code = "email_required"
    title = "An email address is required"


class OnboardingRequiredError(ForbiddenError):
    code = "onboarding_required"
    title = "Finish setting up your profile first"


class EmailInUseError(ConflictError):
    code = "email_in_use"
    title = "Email already in use"


async def current_claims(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(supabase_bearer)],
) -> SupabaseClaims:
    verifier: SupabaseTokenVerifier | None = request.app.state.token_verifier
    if verifier is None:
        raise AuthNotConfiguredError("SUPABASE_URL isn't set on this server.")
    if credentials is None:
        raise NotAuthenticatedError("Send Authorization: Bearer <Supabase access token>.")
    if is_device_token(credentials.credentials):
        raise InvalidTokenError("Elder device tokens can't call family endpoints.")
    return await verifier.verify(credentials.credentials)


async def current_user(
    claims: Annotated[SupabaseClaims, Depends(current_claims)], session: SessionDep
) -> User:
    """The caller's user row, created on first sight (GET /v1/me starts onboarding)."""
    user = await session.scalar(select(User).where(User.auth_user_id == claims.user_id))
    email = claims.email.lower() if claims.email else None
    if user is not None:
        if email and user.email != email:  # changed in Supabase Auth
            user.email = email
            await _commit_or_email_conflict(session)
        return user

    if email is None:
        raise EmailRequiredError("Nodly accounts sign in with an email address.")
    try:
        created_id = await session.scalar(
            insert(User)
            .values(auth_user_id=claims.user_id, email=email)
            .on_conflict_do_nothing(index_elements=[User.auth_user_id])
            .returning(User.id)
        )
        if created_id is not None:
            record_audit(
                session,
                actor_type=ActorType.user,
                actor_id=created_id,
                action="user.created",
                entity_type="user",
                entity_id=created_id,
            )
        await session.commit()
    except IntegrityError as exc:  # the email belongs to another row (e.g. a /dev user)
        await session.rollback()
        raise EmailInUseError("Another Nodly account already uses this email.") from exc
    # Also covers a parallel first request that inserted the row just before us.
    return await session.scalar(select(User).where(User.auth_user_id == claims.user_id))  # type: ignore[return-value]


async def _commit_or_email_conflict(session: SessionDep) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise EmailInUseError("Another Nodly account already uses this email.") from exc


async def onboarded_user(user: Annotated[User, Depends(current_user)]) -> User:
    if not user.is_onboarded:
        raise OnboardingRequiredError(
            "Set your name, country and timezone and confirm you're 16 or older (PATCH /v1/me)."
        )
    return user


CurrentUser = Annotated[User, Depends(current_user)]
OnboardedUser = Annotated[User, Depends(onboarded_user)]
