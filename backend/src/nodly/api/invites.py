"""Member invites: a single-use code (also as a link and QR payload), valid 48 hours."""

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from nodly.api.codes import CodeIn, redeem_code
from nodly.api.common import USER_AUTH_ERRORS, SettingsDep, problems
from nodly.api.schemas import FamilyDetail, family_detail
from nodly.audit import record_audit
from nodly.auth.access import MemberAccess, OrganizerRequiredError
from nodly.auth.users import CurrentUser, OnboardedUser
from nodly.clock import utcnow
from nodly.config import Settings
from nodly.db import SessionDep
from nodly.errors import ConflictError, NotFoundError
from nodly.models import ActorType, Family, FamilyMember, FamilyRole, Invite, InviteKind, User
from nodly.security.credentials import CodeKind, format_code, generate_code, hash_code

router = APIRouter(tags=["invites"])

_CODE_ATTEMPTS = 3  # a collision of 50-bit random codes is astronomically unlikely


class InviteCreated(BaseModel):
    id: uuid.UUID
    code: str = Field(description="Shown only now; the server keeps just a hash")
    link: str = Field(description="Share this; the app opens it and accepts the invite")
    qr_payload: str = Field(description="Encode this in a QR code (same as the link)")
    expires_at: datetime


class InviteOut(BaseModel):
    id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    created_by_name: str | None
    created_at: datetime
    expires_at: datetime


class InvitePreview(BaseModel):
    family_id: uuid.UUID
    family_name: str
    invited_by: str | None
    expires_at: datetime
    already_member: bool


class AlreadyMemberError(ConflictError):
    code = "already_member"
    title = "You're already in this family"


async def create_code_row(
    session: SessionDep,
    settings: Settings,
    code_kind: CodeKind,
    **fields: object,
) -> tuple[Invite, str]:
    """Insert an invite/pairing row with a fresh random code; returns it and the raw code."""
    secret = settings.code_hash_secret.get_secret_value()
    for attempt in range(1, _CODE_ATTEMPTS + 1):
        code = generate_code(code_kind)
        invite = Invite(code_hash=hash_code(code, code_kind, secret), **fields)
        try:
            async with session.begin_nested():
                session.add(invite)
                await session.flush()
        except IntegrityError:
            if attempt == _CODE_ATTEMPTS:
                raise
            continue
        return invite, code
    raise AssertionError("unreachable")


@router.post(
    "/v1/families/{family_id}/invites",
    status_code=status.HTTP_201_CREATED,
    responses=problems(*USER_AUTH_ERRORS, 404),
)
async def create_invite(
    access: MemberAccess, session: SessionDep, settings: SettingsDep
) -> InviteCreated:
    """Any member can invite. The code works once, for INVITE_TTL_HOURS (48h)."""
    now = utcnow()
    invite, code = await create_code_row(
        session,
        settings,
        CodeKind.invite,
        family_id=access.family.id,
        kind=InviteKind.member,
        created_by_user_id=access.user.id,
        created_at=now,
        expires_at=now + timedelta(hours=settings.invite_ttl_hours),
    )
    record_audit(
        session,
        actor_type=ActorType.user,
        actor_id=access.user.id,
        family_id=access.family.id,
        action="invite.created",
        entity_type="invite",
        entity_id=invite.id,
        data={"expires_at": invite.expires_at.isoformat()},
    )
    await session.commit()
    link = f"{settings.invite_link_base_url}{code}"
    return InviteCreated(
        id=invite.id,
        code=format_code(code),
        link=link,
        qr_payload=link,
        expires_at=invite.expires_at,
    )


@router.get("/v1/families/{family_id}/invites", responses=problems(*USER_AUTH_ERRORS, 404))
async def list_open_invites(access: MemberAccess, session: SessionDep) -> list[InviteOut]:
    """Invites that can still be used (codes aren't shown again)."""
    rows = await session.execute(
        select(Invite, User.display_name)
        .outerjoin(User, User.id == Invite.created_by_user_id)
        .where(
            Invite.family_id == access.family.id,
            Invite.kind == InviteKind.member,
            Invite.consumed_at.is_(None),
            Invite.revoked_at.is_(None),
            Invite.expires_at > utcnow(),
        )
        .order_by(Invite.created_at, Invite.id)
    )
    return [
        InviteOut(
            id=invite.id,
            created_by_user_id=invite.created_by_user_id,
            created_by_name=name,
            created_at=invite.created_at,
            expires_at=invite.expires_at,
        )
        for invite, name in rows
    ]


@router.delete(
    "/v1/families/{family_id}/invites/{invite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problems(*USER_AUTH_ERRORS, 404, 409),
)
async def revoke_invite(
    invite_id: uuid.UUID, access: MemberAccess, session: SessionDep
) -> Response:
    """The person who created the invite, or the organizer, can cancel it."""
    invite = await session.get(Invite, invite_id)
    if invite is None or invite.family_id != access.family.id or invite.kind != InviteKind.member:
        raise NotFoundError("Invite not found.")
    if invite.created_by_user_id != access.user.id and not access.is_organizer:
        raise OrganizerRequiredError("Only its creator or the organizer can cancel an invite.")
    if invite.consumed_at is not None:
        raise ConflictError("This invite was already used.")
    if invite.revoked_at is None:
        invite.revoked_at = utcnow()
        record_audit(
            session,
            actor_type=ActorType.user,
            actor_id=access.user.id,
            family_id=access.family.id,
            action="invite.revoked",
            entity_type="invite",
            entity_id=invite.id,
        )
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _is_member(session: SessionDep, family_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    found = await session.scalar(
        select(FamilyMember.id).where(
            FamilyMember.family_id == family_id, FamilyMember.user_id == user_id
        )
    )
    return found is not None


@router.post("/v1/invites/preview", responses=problems(*USER_AUTH_ERRORS, 410, 422, 429))
async def preview_invite(
    body: CodeIn, request: Request, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> InvitePreview:
    """Who invited you to which family, before joining. Works before onboarding is done;
    doesn't use the code up. Wrong codes count towards the brute-force limit."""
    invite = await redeem_code(
        request, session, settings, body.code, CodeKind.invite, user_id=user.id
    )
    family = await session.get_one(Family, invite.family_id)
    inviter = (
        await session.get(User, invite.created_by_user_id) if invite.created_by_user_id else None
    )
    preview = InvitePreview(
        family_id=family.id,
        family_name=family.name,
        invited_by=inviter.display_name if inviter else None,
        expires_at=invite.expires_at,
        already_member=await _is_member(session, family.id, user.id),
    )
    await session.rollback()  # release the row lock; nothing was changed
    return preview


@router.post("/v1/invites/accept", responses=problems(*USER_AUTH_ERRORS, 409, 410, 422, 429))
async def accept_invite(
    body: CodeIn, request: Request, user: OnboardedUser, session: SessionDep, settings: SettingsDep
) -> FamilyDetail:
    """Join the family. The code is used up; if you're already a member it isn't."""
    invite = await redeem_code(
        request, session, settings, body.code, CodeKind.invite, user_id=user.id
    )
    if await _is_member(session, invite.family_id, user.id):
        raise AlreadyMemberError("You're already a member of this family.")
    now = utcnow()
    session.add(FamilyMember(family_id=invite.family_id, user_id=user.id, role=FamilyRole.member))
    invite.consumed_at = now
    invite.consumed_by_user_id = user.id
    record_audit(
        session,
        actor_type=ActorType.user,
        actor_id=user.id,
        family_id=invite.family_id,
        action="member.joined",
        entity_type="invite",
        entity_id=invite.id,
        data={"invited_by": str(invite.created_by_user_id) if invite.created_by_user_id else None},
    )
    await session.commit()
    family = await session.get_one(Family, invite.family_id)
    return await family_detail(session, family, FamilyRole.member)
