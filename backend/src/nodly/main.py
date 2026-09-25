"""FastAPI app factory. Run with: uvicorn nodly.main:create_app --factory"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from nodly import __version__
from nodly.api import health, meta
from nodly.config import Settings, get_settings
from nodly.constants import APP_NAME
from nodly.db import create_engine, create_sessionmaker
from nodly.errors import install_error_handlers
from nodly.log import configure_logging
from nodly.middleware import RequestContextMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    # Created here rather than in the lifespan so test clients (which skip lifespan) work too.
    engine = create_engine(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    show_docs = settings.env != "prod"
    app = FastAPI(
        title=APP_NAME,
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if show_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if show_docs else None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)

    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health.router)
    app.include_router(meta.router)
    return app
