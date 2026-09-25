"""Schemas and helpers shared by the /v1 routers."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    422: "Invalid input (`validation_error`, `invalid_code`, ...)",
    429: "Too many failed attempts; see the Retry-After header",
    503: "Sign-in unavailable (`auth_unavailable`, `auth_not_configured`)",
}


def problems(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """`responses=` entries documenting problem+json errors for a route."""
    return {status: {"model": Problem, "description": _DESCRIPTIONS[status]} for status in statuses}


USER_AUTH_ERRORS = (401, 403, 503)
