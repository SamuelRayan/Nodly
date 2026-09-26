"""The OpenAPI document: clean operation ids, tag docs, and errors described as they really
are (application/problem+json with the Problem schema). scripts/export_openapi.py writes it
to backend/openapi.json for the mobile app's type generator (openapi-typescript)."""

import json
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

from nodly.config import Settings

DESCRIPTION = """\
The Nodly API.

**Auth.** Family members send their Supabase access token:
`Authorization: Bearer <jwt>` (scheme *SupabaseJWT*). The first `GET /v1/me` creates the
account; family features need onboarding (`PATCH /v1/me`). A paired elder phone sends its
device token instead: `Authorization: Bearer ndt_...` (scheme *DeviceToken*), only on
`/v1/device/*`.

**Errors** are RFC 9457 problem details (`application/problem+json`). Switch on `code`;
`detail` is English for developers.

**Access.** Families you don't belong to don't exist for you (404). Organizer-only actions
return 403 `organizer_required` to other members.
"""

TAGS: list[dict[str, Any]] = [
    {"name": "me", "description": "Your account and onboarding."},
    {"name": "families", "description": "Families and their members."},
    {"name": "invites", "description": "Single-use member invites (code, link, QR; 48 hours)."},
    {"name": "elders", "description": "Elder profiles, check-in settings, pause, primary elder."},
    {
        "name": "pairing",
        "description": "Pairing an elder's phone (15-minute codes, no login on the phone) and "
        "managing paired devices.",
    },
    {
        "name": "checkins",
        "description": "An elder's daily check-in, for the family: today's status, the last "
        '7 days, "mark okay" and "I\'m on it".',
    },
    {"name": "device", "description": "Called by a paired elder phone with its device token."},
    {"name": "meta", "description": "Reference data: timezones and countries. No auth."},
    {"name": "health", "description": "Liveness and readiness probes."},
    {"name": "dev (ENV=dev only)", "description": "Test-data helpers; never mounted outside dev."},
]

PROBLEM_MEDIA_TYPE = "application/problem+json"
_PROBLEM_REF = {"$ref": "#/components/schemas/Problem"}


def operation_id(route: APIRoute) -> str:
    """The handler's name, e.g. create_family; dev-only routes get a dev_ prefix."""
    return f"dev_{route.name}" if route.path.startswith("/dev") else route.name


def _describe_errors_as_problems(document: dict[str, Any]) -> None:
    for path_item in document.get("paths", {}).values():
        for operation in path_item.values():
            for status, response in operation.get("responses", {}).items():
                if status.isdigit() and int(status) >= 400:
                    response["content"] = {PROBLEM_MEDIA_TYPE: {"schema": _PROBLEM_REF}}
                    if response.get("description") == "Validation Error":
                        response["description"] = "Invalid input (`validation_error`, ...)"
    schemas = document.get("components", {}).get("schemas", {})
    # FastAPI's default 422 shapes; our 422s are problems (see nodly.errors).
    schemas.pop("HTTPValidationError", None)
    schemas.pop("ValidationError", None)


def install_openapi(app: FastAPI) -> None:
    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            document = get_openapi(
                title=app.title,
                version=app.version,
                description=DESCRIPTION,
                routes=app.routes,
            )
            used = {
                tag
                for item in document.get("paths", {}).values()
                for operation in item.values()
                for tag in operation.get("tags", [])
            }
            document["tags"] = [tag for tag in TAGS if tag["name"] in used]
            _describe_errors_as_problems(document)
            app.openapi_schema = document
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]


def export_settings() -> Settings:
    """Settings for rendering the public document: not dev (no /dev routes), no DB needed."""
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        env="test",
        database_url="postgresql+asyncpg://unused@localhost/unused",
        code_hash_secret="openapi-export-only-not-a-real-secret",
        supabase_url="https://your-project-ref.supabase.co",
    )


def render_openapi() -> str:
    """The public document as committed in backend/openapi.json."""
    from nodly.main import create_app  # local import: main imports this module

    document = create_app(export_settings()).openapi()
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
