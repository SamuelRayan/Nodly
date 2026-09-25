"""A signed-in family member's push tokens (one per phone the app is installed on)."""

from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete

from nodly.api.common import USER_AUTH_ERRORS, problems
from nodly.auth.users import CurrentUser
from nodly.db import SessionDep
from nodly.models import DevicePlatform, PushProvider, PushToken
from nodly.push import register_push_token

router = APIRouter(prefix="/v1/me/push-tokens", tags=["me"])


class PushTokenIn(BaseModel):
    provider: PushProvider = PushProvider.expo
    token: str = Field(min_length=1, max_length=512, examples=["ExponentPushToken[xxxxxxxx]"])
    platform: DevicePlatform


@router.post("", status_code=status.HTTP_204_NO_CONTENT, responses=problems(*USER_AUTH_ERRORS, 422))
async def register_my_push_token(
    body: PushTokenIn, user: CurrentUser, session: SessionDep
) -> Response:
    """Call after sign-in and whenever the token changes. Works before onboarding."""
    await register_push_token(
        session, provider=body.provider, token=body.token, platform=body.platform, user_id=user.id
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, responses=problems(*USER_AUTH_ERRORS))
async def remove_my_push_token(
    token: Annotated[str, Query(min_length=1, max_length=512)],
    user: CurrentUser,
    session: SessionDep,
    provider: PushProvider = PushProvider.expo,
) -> Response:
    """Call on sign-out so this phone stops getting your notifications."""
    await session.execute(
        delete(PushToken).where(
            PushToken.provider == provider,
            PushToken.token == token,
            PushToken.user_id == user.id,
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
