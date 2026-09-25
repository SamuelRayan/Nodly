"""Schemas and helpers shared by the /v1 routers."""

from typing import Annotated, Any

from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from nodly.config import Settings


def app_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


SettingsDep = Annotated[Settings, Depends(app_settings)]


def client_ip(request: Request) -> str | None:
    """The caller's IP. Behind a proxy, uvicorn's --proxy-headers must be on for this to be
    the real client rather than the proxy."""
    return request.client.host if request.client else None


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Problem(BaseModel):
    """An error, as RFC 9457 problem details. Switch on `code`; `detail` is English for
    developers. Some problems add fields (e.g. `errors`, `constraint`, `retry_after`)."""

    model_config = ConfigDict(extra="allow")

    type: str = Field(examples=["urn:nodly:problem:not_found"])
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    code: str = Field(examples=["not_found"])
    request_id: str | None = None


_DESCRIPTIONS = {
    401: "Missing, invalid or expired credentials (`not_authenticated`, `invalid_token`, "
    "`token_expired`, `device_revoked`)",
    403: "Signed in but not allowed (`onboarding_required`, `organizer_required`, ...)",
    404: "Not found, or not visible to you",
    409: "Conflicts with the current state",
    410: "The code has expired or was already used (`code_expired`, `code_used`)",
    422: "Invalid input (`validation_error`, `invalid_code`, ...)",
    429: "Too many failed attempts; see the Retry-After header",
    503: "Sign-in unavailable (`auth_unavailable`, `auth_not_configured`)",
}


def problems(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """`responses=` entries documenting problem+json errors for a route."""
    return {status: {"model": Problem, "description": _DESCRIPTIONS[status]} for status in statuses}


USER_AUTH_ERRORS = (401, 403, 503)
