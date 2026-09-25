"""Looking up a typed/scanned invite or pairing code, with brute-force protection."""

import uuid

from fastapi import Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.api.common import client_ip
from nodly.clock import utcnow
from nodly.config import Settings
from nodly.errors import AppError, InvalidInputError
from nodly.models import Invite, InviteKind
from nodly.security.credentials import CodeKind, hash_code, normalize_code
from nodly.security.throttle import CodeAttemptThrottle


class CodeIn(BaseModel):
    code: str = Field(
        min_length=1,
        max_length=40,
        examples=["7KQ4M-2XD9P"],
        description="As shown or scanned; case, spaces and dashes don't matter",
    )


class InvalidCodeError(InvalidInputError):
    code = "invalid_code"
    title = "That code doesn't work"


class CodeExpiredError(AppError):
    status = 410
    code = "code_expired"
    title = "That code has expired"


class CodeUsedError(AppError):
    status = 410
    code = "code_used"
    title = "That code was already used or cancelled"


_KINDS = {CodeKind.invite: InviteKind.member, CodeKind.pairing: InviteKind.elder_pairing}


async def redeem_code(
    request: Request,
    session: AsyncSession,
    settings: Settings,
    raw_code: str,
    kind: CodeKind,
    *,
    user_id: uuid.UUID | None = None,
) -> Invite:
    """The open invite/pairing row for `raw_code`, locked FOR UPDATE for the caller to use up.

    Every failure (unknown, expired, used) counts towards the throttle and is committed before
    the error is raised; too many failures -> 429 before the code is even looked at.
    """
    throttle = CodeAttemptThrottle(settings)
    now = utcnow()
    limits = throttle.limits(ip=client_ip(request), user_id=user_id)
    await throttle.check(session, limits, now)

    code = normalize_code(raw_code, kind)
    invite = None
    if code is not None:
        code_hash = hash_code(code, kind, settings.code_hash_secret.get_secret_value())
        invite = await session.scalar(
            select(Invite)
            .where(Invite.code_hash == code_hash, Invite.kind == _KINDS[kind])
            .with_for_update()
        )

    error: AppError | None = None
    if invite is None:
        error = InvalidCodeError("Check the code and try again.")
    elif invite.consumed_at is not None or invite.revoked_at is not None:
        error = CodeUsedError("Ask your family for a new code.")
    elif invite.expires_at <= now:
        error = CodeExpiredError("Ask your family for a new code.")
    if error is not None:
        await throttle.record_failure(session, limits, now)
        raise error
    assert invite is not None
    return invite
