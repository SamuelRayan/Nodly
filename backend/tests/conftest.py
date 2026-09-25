from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from nodly.config import Settings, get_settings
from nodly.main import create_app
from nodly.models import Base
from tests.fake_supabase import TEST_SUPABASE_URL, FakeSupabase
from tests.support import migrate


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


async def _reset_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture(scope="session")
async def engine(test_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The test database, built once per run with the real migrations (not create_all)."""
    engine = create_async_engine(test_database_url)
    await _reset_schema(engine)
    async with engine.begin() as conn:
        await conn.run_sync(migrate, "upgrade", "head")
    yield engine
    await _reset_schema(engine)
    await engine.dispose()


@pytest.fixture
async def clean_db(engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    """Empties every table after the test. Deleting (rather than rolling back one outer
    transaction) lets code under test commit and use several connections, like the worker.
    DELETE is used over TRUNCATE because it is much faster on near-empty tables."""
    yield engine
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest.fixture
async def session(clean_db: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(clean_db, expire_on_commit=False) as session:
        yield session


TEST_CODE_SECRET = "test-code-hash-secret-0123456789abcdef"


def make_settings(database_url: str, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "env": "test",
        "database_url": database_url,
        "code_hash_secret": TEST_CODE_SECRET,
        "supabase_url": TEST_SUPABASE_URL,
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[call-arg, arg-type]


@pytest.fixture
def settings(test_database_url: str) -> Settings:
    return make_settings(test_database_url)


@pytest.fixture
def fake_supabase() -> FakeSupabase:
    return FakeSupabase()


@asynccontextmanager
async def app_client(
    settings: Settings, supabase: FakeSupabase | None = None
) -> AsyncIterator[httpx.AsyncClient]:
    """A client for an app whose outbound HTTP (Supabase JWKS) goes to the fake."""
    async with httpx.AsyncClient(transport=(supabase or FakeSupabase()).transport()) as outbound:
        app = create_app(settings, http_client=outbound)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
        await app.state.engine.dispose()


@pytest.fixture
async def client(
    settings: Settings, clean_db: AsyncEngine, fake_supabase: FakeSupabase
) -> AsyncIterator[httpx.AsyncClient]:
    async with app_client(settings, fake_supabase) as c:
        yield c
