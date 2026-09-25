"""Request context: request IDs, one access-log line per request, and the last-resort 500.

A pure ASGI middleware (not BaseHTTPMiddleware) so context variables set here are visible to
the endpoint and its dependencies.
"""

import logging
import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from nodly.errors import problem_response
from nodly.log import bind_log_context

logger = logging.getLogger("nodly.request")

REQUEST_ID_HEADER = "X-Request-ID"
# Accept a caller's request ID only if it's short and harmless to log.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._\-]{8,128}$")


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", ()):
        if name == b"x-request-id":
            candidate = value.decode("latin-1")
            return candidate if _SAFE_REQUEST_ID.match(candidate) else None
    return None


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        status = 500
        response_started = False
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status = message["status"]
                response_started = True
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        with bind_log_context(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_request_id)
            except Exception:
                logger.exception("unhandled error")
                if response_started:
                    raise
                response = problem_response(
                    status=500,
                    code="internal_error",
                    detail="Something went wrong on our side.",
                    instance=scope.get("path"),
                    request_id=request_id,
                )
                await response(scope, receive, send_with_request_id)
            finally:
                logger.info(
                    "request",
                    extra={
                        "method": scope.get("method"),
                        "path": scope.get("path"),
                        "status": status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    },
                )
