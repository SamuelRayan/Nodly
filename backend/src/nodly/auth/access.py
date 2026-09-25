"""Who may touch which family, as FastAPI dependencies.

Rules (docs/DECISIONS.md, Phase 2):
- Only members see a family or anything in it. To everyone else it doesn't exist (404), so
  ids can't be probed across families.
- Organizer-only actions answer 403 organizer_required to other members.
"""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select

from nodly.auth.users import OnboardedUser
from nodly.db import SessionDep
from nodly.errors import ForbiddenError, NotFoundError
from nodly.models import Elder, Family, FamilyMember, FamilyRole, User


class OrganizerRequiredError(ForbiddenError):
    code = "organizer_required"
    title = "Only the family organizer can do this"


@dataclass(frozen=True)
class FamilyAccess:
    family: Family
    member: FamilyMember
    user: User

    @property
    def is_organizer(self) -> bool:
        return self.member.role == FamilyRole.organizer


@dataclass(frozen=True)
class ElderAccess(FamilyAccess):
    elder: Elder


async def _family_access(session: SessionDep, family_id: uuid.UUID, user: User) -> FamilyAccess:
    row = (
        await session.execute(
            select(Family, FamilyMember)
            .join(FamilyMember, FamilyMember.family_id == Family.id)
            .where(Family.id == family_id, FamilyMember.user_id == user.id)
        )
    ).first()
    if row is None:
        raise NotFoundError("Family not found.")
    return FamilyAccess(family=row[0], member=row[1], user=user)


async def family_member(
    family_id: uuid.UUID, user: OnboardedUser, session: SessionDep
) -> FamilyAccess:
    return await _family_access(session, family_id, user)


async def family_organizer(
    access: Annotated[FamilyAccess, Depends(family_member)],
) -> FamilyAccess:
    if not access.is_organizer:
        raise OrganizerRequiredError()
    return access


async def elder_member(
    elder_id: uuid.UUID, user: OnboardedUser, session: SessionDep
) -> ElderAccess:
    elder = await session.get(Elder, elder_id)
    if elder is None:
        raise NotFoundError("Elder not found.")
    try:
        access = await _family_access(session, elder.family_id, user)
    except NotFoundError:
        raise NotFoundError("Elder not found.") from None
    return ElderAccess(family=access.family, member=access.member, user=user, elder=elder)


async def elder_organizer(access: Annotated[ElderAccess, Depends(elder_member)]) -> ElderAccess:
    if not access.is_organizer:
        raise OrganizerRequiredError()
    return access


MemberAccess = Annotated[FamilyAccess, Depends(family_member)]
OrganizerAccess = Annotated[FamilyAccess, Depends(family_organizer)]
ElderMemberAccess = Annotated[ElderAccess, Depends(elder_member)]
ElderOrganizerAccess = Annotated[ElderAccess, Depends(elder_organizer)]
