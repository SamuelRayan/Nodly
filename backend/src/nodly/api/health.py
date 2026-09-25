"""Liveness and readiness probes."""

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from nodly.config import Settings
from nodly.errors import problem_response

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthOut(BaseModel):
    status: Literal["ok"] = "ok"


class ReadyOut(BaseModel):
    status: Literal["ready"] = "ready"
    checks: dict[str, str]


@router.get("/healthz", response_model=HealthOut)
async def healthz() -> HealthOut:
    """Liveness: the process is up. Never touches the database."""
    return HealthOut()


@router.get(
    "/readyz",
    response_model=ReadyOut,
    responses={503: {"description": "A dependency (the database) is unavailable"}},
)
async def readyz(request: Request) -> ReadyOut | JSONResponse:
    """Readiness: the database answers `SELECT 1` within the configured timeout."""
    settings: Settings = request.app.state.settings
    try:
        async with asyncio.timeout(settings.readiness_db_timeout_seconds):
            async with request.app.state.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("readiness check failed", extra={"error": repr(exc)})
        return problem_response(
            status=503,
            code="not_ready",
            title="Not ready",
            detail="The database is unavailable.",
            instance=request.url.path,
            request_id=getattr(request.state, "request_id", None),
            checks={"database": "unavailable"},
        )
    return ReadyOut(checks={"database": "ok"})
