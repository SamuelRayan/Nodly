"""Moments (CLAUDE.md §9): start, upload, complete, the feeds, "new" counts, hearts, delete, and
short-lived signed links to the files. Family members and elders' phones share the same shapes.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.api.common import USER_AUTH_ERRORS, SettingsDep, problems
from nodly.auth.access import FamilyAccess, MemberAccess, _family_access
from nodly.auth.devices import CurrentDevice
from nodly.auth.users import OnboardedUser
from nodly.clock import utcnow
from nodly.config import Settings
from nodly.db import SessionDep
from nodly.errors import ConflictError, ForbiddenError, InvalidInputError, NotFoundError
from nodly.media import check_signature, path_for, signed_path
from nodly.models import (
    Elder,
    ElderDevice,
    Moment,
    MomentKind,
    MomentReaction,
    MomentStatus,
    MomentView,
    User,
)
from nodly.moments.service import complete, create_intent, store_upload

router = APIRouter(tags=["moments"])

PHOTO_CONTENT_TYPES = ("image/jpeg", "image/png", "image/webp")


@dataclass(frozen=True)
class Viewer:
    """Who is looking: a family member or an elder's phone."""

    family_id: uuid.UUID
    user_id: uuid.UUID | None = None
    device_id: uuid.UUID | None = None


class MomentIn(BaseModel):
    kind: Literal["photo"] = Field(description="Photos for now; voice notes and videos next")
    content_type: Literal["image/jpeg", "image/png", "image/webp"]


class MomentOut(BaseModel):
    id: uuid.UUID
    kind: MomentKind
    status: MomentStatus
    author_name: str | None
    by_elder: bool
    is_mine: bool
    intent_at: datetime = Field(description="When it was started (the server's clock)")
    published_at: datetime | None
    width: int | None
    height: int | None
    duration_ms: int | None
    url: str | None = Field(description="Signed link to the file, valid for a few minutes")
    thumbnail_url: str | None
    upload_path: str | None = Field(description="PUT the file's bytes here (while awaiting)")
    hearts: int
    hearted_by_me: bool
    viewed_by_me: bool
    reject_reason: str | None = Field(
        description="upload_missing | not_a_photo | too_large (rejected only)"
    )
    qualifies: bool = Field(description="Counts for the family's free day of Plus (§10)")
    qualifying_local_date: date | None = Field(description="That day, on the family clock")
    not_qualifying_reason: str | None = Field(
        description="near_duplicate | late | posted_by_elder | no_family_clock"
    )


class MomentPage(BaseModel):
    items: list[MomentOut]
    next_before: datetime | None = Field(description="Pass as ?before= for the next page")
    new_count: int = Field(description="Published moments by others that you haven't seen")


class ReactionsDisabledError(ConflictError):
    code = "reactions_disabled"
    title = "Hearts are turned off"


class NotYourMomentError(ForbiddenError):
    code = "not_your_moment"
    title = "Only whoever shared it can do this"


class UploadNotExpectedError(ConflictError):
    code = "upload_not_expected"
    title = "This moment isn't waiting for a file"


class TooLargeError(InvalidInputError):
    code = "too_large"
    title = "That file is too large"


# ---------------------------------------------------------------- shared pieces


def _visible(viewer: Viewer):  # type: ignore[no-untyped-def]
    """Published and not deleted, or your own (any state) so you can follow its progress."""
    mine = (
        Moment.author_user_id == viewer.user_id
        if viewer.user_id
        else Moment.author_device_id == viewer.device_id
    )
    return and_(
        Moment.family_id == viewer.family_id,
        Moment.deleted_at.is_(None),
        (Moment.status == MomentStatus.published) | mine,
    )


def _seen_by(viewer: Viewer):  # type: ignore[no-untyped-def]
    condition = MomentView.moment_id == Moment.id
    if viewer.user_id:
        return exists().where(condition, MomentView.user_id == viewer.user_id)
    return exists().where(condition, MomentView.device_id == viewer.device_id)


async def new_count(session: AsyncSession, viewer: Viewer) -> int:
    """Published moments from others that this viewer hasn't opened yet."""
    not_mine = (
        Moment.author_user_id.is_distinct_from(viewer.user_id)
        if viewer.user_id
        else Moment.author_device_id.is_distinct_from(viewer.device_id)
    )
    count = await session.scalar(
        select(func.count())
        .select_from(Moment)
        .where(
            Moment.family_id == viewer.family_id,
            Moment.status == MomentStatus.published,
            Moment.deleted_at.is_(None),
            not_mine,
            ~_seen_by(viewer),
        )
    )
    return count or 0


async def moment_out(
    session: AsyncSession, settings: Settings, moment: Moment, viewer: Viewer
) -> MomentOut:
    return (await moments_out(session, settings, [moment], viewer))[0]


async def moments_out(
    session: AsyncSession, settings: Settings, moments: list[Moment], viewer: Viewer
) -> list[MomentOut]:
    ids = [moment.id for moment in moments]
    hearts = dict(
        (
            await session.execute(
                select(MomentReaction.moment_id, func.count())
                .where(MomentReaction.moment_id.in_(ids))
                .group_by(MomentReaction.moment_id)
            )
        ).all()
    )
    mine_filter = (
        MomentReaction.user_id == viewer.user_id
        if viewer.user_id
        else MomentReaction.device_id == viewer.device_id
    )
    hearted = set(
        await session.scalars(
            select(MomentReaction.moment_id).where(MomentReaction.moment_id.in_(ids), mine_filter)
        )
    )
    view_filter = (
        MomentView.user_id == viewer.user_id
        if viewer.user_id
        else MomentView.device_id == viewer.device_id
    )
    viewed = set(
        await session.scalars(
            select(MomentView.moment_id).where(MomentView.moment_id.in_(ids), view_filter)
        )
    )
    user_ids = {moment.author_user_id for moment in moments if moment.author_user_id}
    names: dict[uuid.UUID, str | None] = {}
    if user_ids:
        rows = await session.execute(
            select(User.id, User.display_name).where(User.id.in_(user_ids))
        )
        names.update({user_id: name for user_id, name in rows})
    device_ids = {moment.author_device_id for moment in moments if moment.author_device_id}
    if device_ids:
        rows = await session.execute(
            select(ElderDevice.id, Elder.relation_label, Elder.display_name)
            .join(Elder, Elder.id == ElderDevice.elder_id)
            .where(ElderDevice.id.in_(device_ids))
        )
        names.update({device: label or name for device, label, name in rows})

    out = []
    for moment in moments:
        published = moment.status == MomentStatus.published
        author = moment.author_user_id or moment.author_device_id
        is_mine = (viewer.user_id is not None and moment.author_user_id == viewer.user_id) or (
            viewer.device_id is not None and moment.author_device_id == viewer.device_id
        )
        out.append(
            MomentOut(
                id=moment.id,
                kind=MomentKind(moment.kind),
                status=MomentStatus(moment.status),
                author_name=names.get(author) if author else None,
                by_elder=moment.by_elder,
                is_mine=is_mine,
                intent_at=moment.intent_at,
                published_at=moment.published_at,
                width=moment.width,
                height=moment.height,
                duration_ms=moment.duration_ms,
                url=signed_path(settings, moment.storage_key) if published else None,
                thumbnail_url=signed_path(settings, moment.thumbnail_key)
                if published and moment.thumbnail_key
                else None,
                upload_path=(
                    f"/v1/device/moments/{moment.id}/file"
                    if viewer.device_id
                    else f"/v1/moments/{moment.id}/file"
                )
                if moment.status == MomentStatus.awaiting_upload and is_mine
                else None,
                hearts=hearts.get(moment.id, 0),
                hearted_by_me=moment.id in hearted,
                viewed_by_me=moment.id in viewed,
                reject_reason=moment.reject_reason,
                qualifies=moment.qualifies,
                qualifying_local_date=moment.qualifying_local_date,
                not_qualifying_reason=moment.not_qualifying_reason,
            )
        )
    return out


async def _page(
    session: AsyncSession, settings: Settings, viewer: Viewer, before: datetime | None, limit: int
) -> MomentPage:
    order_key = func.coalesce(Moment.published_at, Moment.intent_at)
    query = select(Moment).where(_visible(viewer))
    if before is not None:
        query = query.where(order_key < before)
    moments = list(await session.scalars(query.order_by(order_key.desc()).limit(limit + 1)))
    more = len(moments) > limit
    moments = moments[:limit]
    last = moments[-1] if moments else None
    return MomentPage(
        items=await moments_out(session, settings, moments, viewer),
        next_before=(last.published_at or last.intent_at) if more and last else None,
        new_count=await new_count(session, viewer),
    )


async def _moment_for(session: AsyncSession, moment_id: uuid.UUID, viewer: Viewer) -> Moment:
    moment = await session.scalar(select(Moment).where(Moment.id == moment_id, _visible(viewer)))
    if moment is None:
        raise NotFoundError("Moment not found.")
    return moment


def _require_mine(moment: Moment, viewer: Viewer) -> None:
    mine = (viewer.user_id and moment.author_user_id == viewer.user_id) or (
        viewer.device_id and moment.author_device_id == viewer.device_id
    )
    if not mine:
        raise NotYourMomentError("Only whoever shared this moment can do that.")


async def _upload(
    request: Request, session: AsyncSession, settings: Settings, moment: Moment, viewer: Viewer
) -> MomentOut:
    _require_mine(moment, viewer)
    if moment.status != MomentStatus.awaiting_upload:
        raise UploadNotExpectedError("This moment already has its file.")
    size = await store_upload(settings, moment, request.stream(), settings.moment_photo_max_bytes)
    if size < 0:
        raise TooLargeError(
            f"Photos can be up to {settings.moment_photo_max_bytes // (1024 * 1024)} MB."
        )
    moment.size_bytes = size
    await session.commit()
    return await moment_out(session, settings, moment, viewer)


async def _mark_viewed(session: AsyncSession, moment: Moment, viewer: Viewer) -> None:
    values = {"moment_id": moment.id, "viewed_at": utcnow()}
    if viewer.user_id:
        statement = insert(MomentView).values(**values, user_id=viewer.user_id)
        statement = statement.on_conflict_do_nothing(
            index_elements=[MomentView.moment_id, MomentView.user_id],
            index_where=MomentView.user_id.is_not(None),
        )
    else:
        statement = insert(MomentView).values(**values, device_id=viewer.device_id)
        statement = statement.on_conflict_do_nothing(
            index_elements=[MomentView.moment_id, MomentView.device_id],
            index_where=MomentView.device_id.is_not(None),
        )
    await session.execute(statement)
    await session.commit()


async def _set_heart(
    session: AsyncSession, settings: Settings, moment: Moment, viewer: Viewer, on: bool
) -> None:
    if not settings.reactions_enabled:
        raise ReactionsDisabledError("Hearts are turned off for now.")
    if moment.status != MomentStatus.published:
        raise NotFoundError("Moment not found.")
    who = (
        MomentReaction.user_id == viewer.user_id
        if viewer.user_id
        else MomentReaction.device_id == viewer.device_id
    )
    existing = await session.scalar(
        select(MomentReaction).where(MomentReaction.moment_id == moment.id, who)
    )
    if on and existing is None:
        session.add(
            MomentReaction(moment_id=moment.id, user_id=viewer.user_id, device_id=viewer.device_id)
        )
    elif not on and existing is not None:
        await session.delete(existing)
    await session.commit()


# ---------------------------------------------------------------- family members


async def _user_viewer(
    moment_id: uuid.UUID, session: SessionDep, user: OnboardedUser
) -> tuple[Moment, Viewer]:
    moment = await session.get(Moment, moment_id)
    if moment is None:
        raise NotFoundError("Moment not found.")
    access: FamilyAccess = await _family_access(session, moment.family_id, user)
    viewer = Viewer(family_id=access.family.id, user_id=user.id)
    return await _moment_for(session, moment_id, viewer), viewer


UserMoment = Annotated[tuple[Moment, Viewer], Depends(_user_viewer)]
AUTH = problems(*USER_AUTH_ERRORS, 404)


@router.post(
    "/v1/families/{family_id}/moments",
    status_code=status.HTTP_201_CREATED,
    responses=problems(*USER_AUTH_ERRORS, 404, 422),
)
async def start_moment(
    body: MomentIn, access: MemberAccess, session: SessionDep, settings: SettingsDep
) -> MomentOut:
    """Start sharing a moment: its time (for "counts for today") is now, on the server.
    Then PUT the file to upload_path and POST .../complete."""
    moment = await create_intent(
        session,
        family_id=access.family.id,
        kind=MomentKind(body.kind),
        content_type=body.content_type,
        now=utcnow(),
        author_user_id=access.user.id,
    )
    viewer = Viewer(family_id=access.family.id, user_id=access.user.id)
    return await moment_out(session, settings, moment, viewer)


@router.get("/v1/families/{family_id}/moments", responses=AUTH)
async def family_moments(
    access: MemberAccess,
    session: SessionDep,
    settings: SettingsDep,
    before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> MomentPage:
    """The family's moments, newest first (plus your own still on their way)."""
    viewer = Viewer(family_id=access.family.id, user_id=access.user.id)
    return await _page(session, settings, viewer, before, limit)


@router.get("/v1/moments/{moment_id}", responses=AUTH)
async def get_moment(target: UserMoment, session: SessionDep, settings: SettingsDep) -> MomentOut:
    moment, viewer = target
    return await moment_out(session, settings, moment, viewer)


@router.put("/v1/moments/{moment_id}/file", responses=problems(*USER_AUTH_ERRORS, 404, 409, 422))
async def upload_moment_file(
    request: Request, target: UserMoment, session: SessionDep, settings: SettingsDep
) -> MomentOut:
    """The file's raw bytes (Content-Type as announced). Sending it again replaces it."""
    moment, viewer = target
    return await _upload(request, session, settings, moment, viewer)


@router.post("/v1/moments/{moment_id}/complete", responses=AUTH)
async def complete_moment(
    target: UserMoment, session: SessionDep, settings: SettingsDep
) -> MomentOut:
    """Upload finished: check it. Calling again is harmless."""
    moment, viewer = target
    _require_mine(moment, viewer)
    await complete(session, moment, utcnow())
    return await moment_out(session, settings, moment, viewer)


@router.post("/v1/moments/{moment_id}/view", status_code=204, responses=AUTH)
async def view_moment(target: UserMoment, session: SessionDep) -> Response:
    moment, viewer = target
    await _mark_viewed(session, moment, viewer)
    return Response(status_code=204)


@router.put("/v1/moments/{moment_id}/heart", responses=problems(*USER_AUTH_ERRORS, 404, 409))
async def heart_moment(target: UserMoment, session: SessionDep, settings: SettingsDep) -> MomentOut:
    moment, viewer = target
    await _set_heart(session, settings, moment, viewer, on=True)
    return await moment_out(session, settings, moment, viewer)


@router.delete("/v1/moments/{moment_id}/heart", responses=problems(*USER_AUTH_ERRORS, 404, 409))
async def unheart_moment(
    target: UserMoment, session: SessionDep, settings: SettingsDep
) -> MomentOut:
    moment, viewer = target
    await _set_heart(session, settings, moment, viewer, on=False)
    return await moment_out(session, settings, moment, viewer)


@router.delete("/v1/moments/{moment_id}", status_code=204, responses=AUTH)
async def delete_moment(target: UserMoment, session: SessionDep) -> Response:
    """Delete your own moment (it disappears for everyone)."""
    moment, viewer = target
    _require_mine(moment, viewer)
    moment.deleted_at = utcnow()
    await session.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- elders' phones


async def _device_viewer(
    moment_id: uuid.UUID, session: SessionDep, access: CurrentDevice
) -> tuple[Moment, Viewer]:
    viewer = Viewer(family_id=access.family.id, device_id=access.device.id)
    return await _moment_for(session, moment_id, viewer), viewer


DeviceMoment = Annotated[tuple[Moment, Viewer], Depends(_device_viewer)]
DEVICE = problems(401, 404)


@router.get("/v1/device/moments", tags=["device"], responses=problems(401))
async def device_moments(
    access: CurrentDevice,
    session: SessionDep,
    settings: SettingsDep,
    before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> MomentPage:
    """The family's moments for the elder, newest first, with how many are new."""
    viewer = Viewer(family_id=access.family.id, device_id=access.device.id)
    return await _page(session, settings, viewer, before, limit)


@router.post("/v1/device/moments", status_code=201, tags=["device"], responses=problems(401, 422))
async def device_start_moment(
    body: MomentIn, access: CurrentDevice, session: SessionDep, settings: SettingsDep
) -> MomentOut:
    """An elder shares a photo too (the big camera button). Elder posts never earn Plus."""
    moment = await create_intent(
        session,
        family_id=access.family.id,
        kind=MomentKind(body.kind),
        content_type=body.content_type,
        now=utcnow(),
        author_device_id=access.device.id,
    )
    viewer = Viewer(family_id=access.family.id, device_id=access.device.id)
    return await moment_out(session, settings, moment, viewer)


@router.put(
    "/v1/device/moments/{moment_id}/file", tags=["device"], responses=problems(401, 404, 409, 422)
)
async def device_upload_moment_file(
    request: Request, target: DeviceMoment, session: SessionDep, settings: SettingsDep
) -> MomentOut:
    moment, viewer = target
    return await _upload(request, session, settings, moment, viewer)


@router.post("/v1/device/moments/{moment_id}/complete", tags=["device"], responses=DEVICE)
async def device_complete_moment(
    target: DeviceMoment, session: SessionDep, settings: SettingsDep
) -> MomentOut:
    moment, viewer = target
    _require_mine(moment, viewer)
    await complete(session, moment, utcnow())
    return await moment_out(session, settings, moment, viewer)


@router.post(
    "/v1/device/moments/{moment_id}/view", status_code=204, tags=["device"], responses=DEVICE
)
async def device_view_moment(target: DeviceMoment, session: SessionDep) -> Response:
    moment, viewer = target
    await _mark_viewed(session, moment, viewer)
    return Response(status_code=204)


@router.put(
    "/v1/device/moments/{moment_id}/heart", tags=["device"], responses=problems(401, 404, 409)
)
async def device_heart_moment(
    target: DeviceMoment, session: SessionDep, settings: SettingsDep
) -> MomentOut:
    """ "Send love"."""
    moment, viewer = target
    await _set_heart(session, settings, moment, viewer, on=True)
    return await moment_out(session, settings, moment, viewer)


@router.delete(
    "/v1/device/moments/{moment_id}/heart", tags=["device"], responses=problems(401, 404, 409)
)
async def device_unheart_moment(
    target: DeviceMoment, session: SessionDep, settings: SettingsDep
) -> MomentOut:
    moment, viewer = target
    await _set_heart(session, settings, moment, viewer, on=False)
    return await moment_out(session, settings, moment, viewer)


# ---------------------------------------------------------------- the files


@router.get("/v1/media/{key:path}", tags=["moments"], responses=problems(403, 404))
async def media(key: str, settings: SettingsDep, exp: int = 0, sig: str = "") -> FileResponse:
    """A moment's file or thumbnail, through a signed link from the API (no login: the
    signature is the permission, and it expires within minutes)."""
    if not check_signature(settings, key, exp, sig):
        raise ForbiddenError("This link has expired or isn't valid.")
    try:
        path = path_for(settings, key)
    except ValueError as error:
        raise NotFoundError("Not found.") from error
    if not path.is_file():
        raise NotFoundError("Not found.")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=300"})
