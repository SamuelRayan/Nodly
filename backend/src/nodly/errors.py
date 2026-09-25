"""Errors as RFC 9457 problem details (application/problem+json).

Every error body has: type, title, status, detail (optional), instance, code, request_id.
Clients switch on `code` (stable, snake_case) and show their own translated text; `detail` is
English for developers. https://www.rfc-editor.org/rfc/rfc9457
"""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"
UNIQUE_VIOLATION = "23505"

_CODES_BY_STATUS = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}


def problem_type(code: str) -> str:
    return f"urn:nodly:problem:{code}"


class AppError(Exception):
    """Base for errors we raise on purpose. Subclasses set status/code/title."""

    status: int = 400
    code: str = "bad_request"
    title: str = "Bad request"
    headers: dict[str, str] | None = None

    def __init__(
        self, detail: str | None = None, *, headers: dict[str, str] | None = None, **extra: Any
    ) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        self.extra = extra
        if headers is not None:
            self.headers = headers


class UnauthorizedError(AppError):
    status = 401
    code = "unauthorized"
    title = "Unauthorized"
    headers = {"WWW-Authenticate": "Bearer"}  # noqa: RUF012  # read-only class default


class ForbiddenError(AppError):
    status = 403
    code = "forbidden"
    title = "Forbidden"


class TooManyRequestsError(AppError):
    status = 429
    code = "rate_limited"
    title = "Too many attempts"


class ServiceUnavailableError(AppError):
    status = 503
    code = "service_unavailable"
    title = "Service unavailable"


class NotFoundError(AppError):
    status = 404
    code = "not_found"
    title = "Not found"


class ConflictError(AppError):
    status = 409
    code = "conflict"
    title = "Conflict"


class InvalidInputError(AppError):
    """Input that passed schema validation but failed a domain rule (bad timezone, phone...)."""

    status = 422
    code = "invalid_input"
    title = "Invalid input"


def problem_response(
    *,
    status: int,
    code: str,
    title: str | None = None,
    detail: str | None = None,
    instance: str | None = None,
    request_id: str | None = None,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": problem_type(code),
        "title": title or HTTPStatus(status).phrase,
        "status": status,
    }
    if detail:
        body["detail"] = detail
    if instance:
        body["instance"] = instance
    body["code"] = code
    body["request_id"] = request_id
    body.update(extra)
    return JSONResponse(body, status_code=status, headers=headers, media_type=PROBLEM_MEDIA_TYPE)


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


async def _app_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return problem_response(
        status=exc.status,
        code=exc.code,
        title=exc.title,
        detail=exc.detail,
        instance=request.url.path,
        request_id=_request_id(request),
        headers=exc.headers,
        **exc.extra,
    )


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    phrase = HTTPStatus(exc.status_code).phrase
    detail = exc.detail if isinstance(exc.detail, str) and exc.detail != phrase else None
    return problem_response(
        status=exc.status_code,
        code=_CODES_BY_STATUS.get(exc.status_code, f"http_{exc.status_code}"),
        detail=detail,
        instance=request.url.path,
        request_id=_request_id(request),
        headers=dict(exc.headers) if exc.headers else None,
    )


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Leave out the rejected input: it can contain secrets (tokens, codes).
    errors = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]
    return problem_response(
        status=422,
        code="validation_error",
        title="Validation error",
        detail="The request is invalid; see errors.",
        instance=request.url.path,
        request_id=_request_id(request),
        errors=errors,
    )


def constraint_name(exc: IntegrityError) -> str | None:
    """The violated constraint, from asyncpg's exception under SQLAlchemy's wrapper."""
    cause = getattr(exc.orig, "__cause__", None)
    return getattr(cause, "constraint_name", None)


async def _integrity_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, IntegrityError)
    if getattr(exc.orig, "sqlstate", None) != UNIQUE_VIOLATION:
        # Anything else (FK, NOT NULL, CHECK) is a bug in our validation: let it be a 500.
        raise exc
    return problem_response(
        status=409,
        code="conflict",
        title="Conflict",
        detail="This already exists.",
        instance=request.url.path,
        request_id=_request_id(request),
        constraint=constraint_name(exc),
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(IntegrityError, _integrity_error)
    # Unhandled exceptions become a 500 problem in RequestContextMiddleware (nodly.middleware),
    # which still knows the request ID and adds the X-Request-ID header.
