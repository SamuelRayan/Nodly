import httpx

from nodly.errors import PROBLEM_MEDIA_TYPE
from nodly.main import create_app
from tests.conftest import make_settings


async def test_healthz(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_with_database(client: httpx.AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}


async def test_readyz_without_database_is_503_problem() -> None:
    # Nothing listens on port 1; the short timeout keeps the test fast on Windows, where
    # refused localhost connections are retried for ~2s.
    settings = make_settings(
        "postgresql+asyncpg://nodly:nodly@127.0.0.1:1/nodly_test",
        readiness_db_timeout_seconds=0.5,
    )
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/readyz")
    await app.state.engine.dispose()

    assert response.status_code == 503
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    body = response.json()
    assert body["code"] == "not_ready"
    assert body["checks"] == {"database": "unavailable"}
    assert body["request_id"] == response.headers["x-request-id"]
