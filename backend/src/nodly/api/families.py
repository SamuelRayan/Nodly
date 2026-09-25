"""Families and their members."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select, update

from nodly.api.common import USER_AUTH_ERRORS, problems
from nodly.api.schemas import FamilyDetail, FamilySummary, family_detail
from nodly.audit import record_audit
from nodly.auth.access import MemberAccess, OrganizerAccess
from nodly.auth.users import OnboardedUser
from nodly.clock import utcnow
from nodly.db import SessionDep
from nodly.errors import ConflictError, NotFoundError
from nodly.models import ActorType, Family, FamilyMember, FamilyRole, Invite, InviteKind

router = APIRouter(prefix="/v1/families", tags=["families"])

FamilyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class FamilyCreate(BaseModel):
    name: FamilyName = Field(examples=["The Sharmas"])


class FamilyUpdate(BaseModel):
    name: FamilyName


class OrganizerTransfer(BaseModel):
    user_id: uuid.UUID = Field(description="A current member who becomes the organizer")


class OrganizerMustTransferError(ConflictError):
    code = "organizer_must_transfer"
    title = "Hand the organizer role to someone else first"


class AlreadyOrganizerError(ConflictError):
    code = "already_organizer"
    title = "Already the organizer"


def _audit(
    actor_id: uuid.UUID, family_id: uuid.UUID, action: str, session: SessionDep, **data: object
) -> None:
    record_audit(
        session,
        actor_type=ActorType.user,
        actor_id=actor_id,
        family_id=family_id,
        action=action,
        entity_type="family",
        entity_id=family_id,
        data=dict(data),
    )


async def _revoke_invites_created_by(
    session: SessionDep, family_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Someone who leaves or is removed can't keep bringing people in."""
    await session.execute(
        update(Invite)
        .where(
            Invite.family_id == family_id,
            Invite.created_by_user_id == user_id,
            Invite.kind == InviteKind.member,
            Invite.consumed_at.is_(None),
            Invite.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses=problems(*USER_AUTH_ERRORS, 422),
)
async def create_family(
    body: FamilyCreate, user: OnboardedUser, session: SessionDep
) -> FamilyDetail:
    """Start a family. You become its organizer."""
    family = Family(name=body.name)
    session.add(family)
    await session.flush()
    session.add(FamilyMember(family_id=family.id, user_id=user.id, role=FamilyRole.organizer))
    _audit(user.id, family.id, "family.created", session, name=family.name)
    await session.commit()
    return await family_detail(session, family, FamilyRole.organizer)


@router.get("", responses=problems(*USER_AUTH_ERRORS))
async def list_my_families(user: OnboardedUser, session: SessionDep) -> list[FamilySummary]:
    """Families you belong to, with your role in each."""
    rows = await session.execute(
        select(Family, FamilyMember.role)
        .join(FamilyMember, FamilyMember.family_id == Family.id)
        .where(FamilyMember.user_id == user.id)
        .order_by(Family.created_at, Family.id)
    )
    return [
        FamilySummary(id=f.id, name=f.name, my_role=FamilyRole(role), created_at=f.created_at)
        for f, role in rows
    ]


@router.get("/{family_id}", responses=problems(*USER_AUTH_ERRORS, 404))
async def get_family(access: MemberAccess, session: SessionDep) -> FamilyDetail:
    """Members, elders and the family clock."""
    return await family_detail(session, access.family, access.member.role)


@router.patch("/{family_id}", responses=problems(*USER_AUTH_ERRORS, 404, 422))
async def rename_family(
    body: FamilyUpdate, access: OrganizerAccess, session: SessionDep
) -> FamilyDetail:
    """Organizer only."""
    old_name = access.family.name
    access.family.name = body.name
    _audit(access.user.id, access.family.id, "family.renamed", session, old=old_name, new=body.name)
    await session.commit()
    return await family_detail(session, access.family, access.member.role)


@router.post("/{family_id}/organizer", responses=problems(*USER_AUTH_ERRORS, 404, 409))
async def transfer_organizer(
    body: OrganizerTransfer, access: OrganizerAccess, session: SessionDep
) -> FamilyDetail:
    """Organizer only: make another member the organizer; you become a member."""
    if body.user_id == access.user.id:
        raise AlreadyOrganizerError("You're already the organizer.")
    target = await session.scalar(
        select(FamilyMember).where(
            FamilyMember.family_id == access.family.id, FamilyMember.user_id == body.user_id
        )
    )
    if target is None:
        raise NotFoundError("That person isn't a member of this family.")
    # Demote first: the "one organizer per family" index is checked per statement.
    access.member.role = FamilyRole.member
    await session.flush()
    target.role = FamilyRole.organizer
    _audit(
        access.user.id,
        access.family.id,
        "family.organizer_transferred",
        session,
        from_user_id=str(access.user.id),
        to_user_id=str(body.user_id),
    )
    await session.commit()
    return await family_detail(session, access.family, FamilyRole.member)


@router.delete(
    "/{family_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problems(*USER_AUTH_ERRORS, 404, 409),
)
async def remove_member(
    user_id: uuid.UUID, access: OrganizerAccess, session: SessionDep
) -> Response:
    """Organizer only. Their open invites are revoked too."""
    if user_id == access.user.id:
        raise OrganizerMustTransferError("You can't remove yourself; transfer the organizer role.")
    target = await session.scalar(
        select(FamilyMember).where(
            FamilyMember.family_id == access.family.id, FamilyMember.user_id == user_id
        )
    )
    if target is None:
        raise NotFoundError("That person isn't a member of this family.")
    await session.delete(target)
    await _revoke_invites_created_by(session, access.family.id, user_id)
    _audit(access.user.id, access.family.id, "member.removed", session, user_id=str(user_id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{family_id}/leave",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problems(*USER_AUTH_ERRORS, 404, 409),
)
async def leave_family(access: MemberAccess, session: SessionDep) -> Response:
    """Leave a family. The organizer must hand the role to someone else first."""
    if access.is_organizer:
        raise OrganizerMustTransferError("Make another member the organizer before leaving.")
    await session.delete(access.member)
    await _revoke_invites_created_by(session, access.family.id, access.user.id)
    _audit(access.user.id, access.family.id, "member.left", session)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
