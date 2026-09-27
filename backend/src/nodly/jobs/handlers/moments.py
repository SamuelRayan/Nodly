"""Checking uploaded moments, and telling the family about new ones (CLAUDE.md §9)."""

import uuid
from typing import Any

from sqlalchemy import select

from nodly.clock import utcnow
from nodly.jobs.registry import JobContext, PermanentJobError, job_handler
from nodly.models import Elder, ElderDevice, Moment, MomentStatus, PushProvider, PushToken, User
from nodly.moments.service import VERIFY_JOB, verify
from nodly.push import Push, deliver, family_tokens, push_sender

KIND_WORDS = {"photo": "a photo", "video": "a video", "voice": "a voice note"}


@job_handler(VERIFY_JOB)
async def verify_moment(ctx: JobContext, payload: dict[str, Any]) -> None:
    try:
        moment_id = uuid.UUID(payload["moment_id"])
    except (KeyError, ValueError) as error:
        raise PermanentJobError(f"Bad payload: {error}") from error

    async with ctx.sessionmaker() as session:
        moment = await session.get(Moment, moment_id)
        if moment is None:
            return
        await verify(session, moment, utcnow(), ctx.settings)
        if moment.status != MomentStatus.published or moment.deleted_at is not None:
            return

        # "Priya sent a photo": to the elders' phones and everyone else in the family.
        author = "Your family"
        if moment.author_user_id:
            user = await session.get(User, moment.author_user_id)
            if user and user.display_name:
                author = user.display_name.split(" ")[0]
        elif moment.author_device_id:
            elder = await session.scalar(
                select(Elder)
                .join(ElderDevice, ElderDevice.elder_id == Elder.id)
                .where(ElderDevice.id == moment.author_device_id)
            )
            if elder:
                author = elder.relation_label or elder.display_name
        tokens = await family_tokens(session, moment.family_id, exclude_user=moment.author_user_id)
        tokens += list(
            await session.scalars(
                select(PushToken.token)
                .join(ElderDevice, ElderDevice.id == PushToken.elder_device_id)
                .join(Elder, Elder.id == ElderDevice.elder_id)
                .where(
                    Elder.family_id == moment.family_id,
                    ElderDevice.revoked_at.is_(None),
                    ElderDevice.id != moment.author_device_id,
                    PushToken.provider == PushProvider.expo,
                    PushToken.disabled_at.is_(None),
                )
            )
        )
        push = Push(
            tokens=tokens,
            title=f"{author} sent {KIND_WORDS.get(moment.kind, 'a moment')}",
            body="Open Nodly to see it.",
            channel_id="moments",
            data={"type": "moment", "moment_id": str(moment.id)},
            priority="normal",
        )
        await deliver(session, push_sender(ctx.settings), push)
        await session.commit()
