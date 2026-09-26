"""FastAPI app factory. Run with: uvicorn nodly.main:create_app --factory"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from nodly import __version__
from nodly.api import (
    checkins,
    dev,
    device,
    elders,
    families,
    health,
    help,
    invites,
    me,
    meta,
    pairing,
    push_tokens,
)
from nodly.api.openapi import install_openapi, operation_id
from nodly.auth.supabase import SupabaseTokenVerifier
from nodly.config import Settings, get_settings
from nodly.constants import APP_NAME
from nodly.db import create_engine, create_sessionmaker
from nodly.errors import install_error_handlers
from nodly.log import configure_logging
from nodly.middleware import RequestContextMiddleware


def create_app(
    settings: Settings | None = None, *, http_client: httpx.AsyncClient | None = None
) -> FastAPI:
    """`http_client` is for outbound calls (Supabase JWKS); tests pass a mocked one."""
    settings = settings or get_settings()
    configure_logging(settings)

    # Created here rather than in the lifespan so test clients (which skip lifespan) work too.
    engine = create_engine(settings)
    http = http_client or httpx.AsyncClient()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()
        if http_client is None:
            await http.aclose()

    show_docs = settings.env != "prod"
    app = FastAPI(
        title=APP_NAME,
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if show_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if show_docs else None,
        generate_unique_id_function=operation_id,
        swagger_ui_parameters={"persistAuthorization": True},
    )
    install_openapi(app)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.http = http
    app.state.token_verifier = (
        SupabaseTokenVerifier(settings, http) if settings.supabase_url else None
    )

    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(push_tokens.router)
    app.include_router(families.router)
    app.include_router(invites.router)
    app.include_router(elders.router)
    app.include_router(checkins.router)
    app.include_router(help.router)
    app.include_router(pairing.router)
    app.include_router(device.router)
    app.include_router(meta.router)
    if settings.env == "dev":
        app.include_router(dev.router)
    return app
