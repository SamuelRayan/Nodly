from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from nodly.config import Settings, get_settings
from nodly.main import create_app


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = get_settings().test_database_url
    if not url:
        pytest.fail("TEST_DATABASE_URL is not set; see backend/.env.example", pytrace=False)
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail(
            "TEST_DATABASE_URL must name a database ending in _test, because the suite wipes it",
            pytrace=False,
        )
    return url


@pytest.fixture(scope="session")
async def engine(test_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(test_database_url)
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
    yield engine
    await engine.dispose()


def make_settings(database_url: str, **overrides: object) -> Settings:
    values: dict[str, object] = {"env": "test", "database_url": database_url, **overrides}
    return Settings(_env_file=None, **values)  # type: ignore[call-arg, arg-type]


@pytest.fixture
def settings(test_database_url: str) -> Settings:
    return make_settings(test_database_url)


@pytest.fixture
async def client(settings: Settings, engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.state.engine.dispose()
