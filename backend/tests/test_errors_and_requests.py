"""problem+json bodies, request IDs and the access log."""

import json
import logging
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from nodly.config import Settings
from nodly.errors import PROBLEM_MEDIA_TYPE, ConflictError
from nodly.log import JsonFormatter, bind_log_context
from nodly.main import create_app


@pytest.fixture
async def app_with_test_routes(settings: Settings) -> AsyncIterator[FastAPI]:
    app = create_app(settings)

    @app.get("/_test/boom")
    async def boom() -> None:
        raise RuntimeError("secret internals")

    @app.get("/_test/conflict")
    async def conflict() -> None:
        raise ConflictError("Already paired.", constraint="uq_example")

    @app.get("/_test/items/{item_id}")
    async def item(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    yield app
    await app.state.engine.dispose()


@pytest.fixture
async def test_client(app_with_test_routes: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app_with_test_routes)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def assert_problem(response: httpx.Response, status: int, code: str) -> dict:
    assert response.status_code == status
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    body = response.json()
    assert body["status"] == status
    assert body["code"] == code
    assert body["type"] == f"urn:nodly:problem:{code}"
    assert body["title"]
    assert body["request_id"] == response.headers["x-request-id"]
    return body


async def test_unknown_route_is_404_problem(client: httpx.AsyncClient) -> None:
    body = assert_problem(await client.get("/nope"), 404, "not_found")
    assert body["instance"] == "/nope"


async def test_wrong_method_is_405_problem_with_allow_header(client: httpx.AsyncClient) -> None:
    response = await client.post("/healthz")
    assert_problem(response, 405, "method_not_allowed")
    assert "GET" in response.headers["allow"]


async def test_validation_error_lists_errors_without_echoing_input(
    test_client: httpx.AsyncClient,
) -> None:
    body = assert_problem(await test_client.get("/_test/items/abc"), 422, "validation_error")
    assert body["errors"][0]["loc"] == ["path", "item_id"]
    assert "input" not in body["errors"][0]


async def test_app_error_carries_code_and_extras(test_client: httpx.AsyncClient) -> None:
    body = assert_problem(await test_client.get("/_test/conflict"), 409, "conflict")
    assert body["detail"] == "Already paired."
    assert body["constraint"] == "uq_example"


async def test_unhandled_error_is_generic_500(
    test_client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="nodly.request"):
        response = await test_client.get("/_test/boom")
    body = assert_problem(response, 500, "internal_error")
    assert "secret internals" not in response.text
    assert body["instance"] == "/_test/boom"
    assert any(r.message == "unhandled error" and r.exc_info for r in caplog.records)


async def test_request_id_is_generated(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert len(response.headers["x-request-id"]) == 32


async def test_safe_incoming_request_id_is_kept(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz", headers={"X-Request-ID": "mobile-1234-abcd"})
    assert response.headers["x-request-id"] == "mobile-1234-abcd"


@pytest.mark.parametrize("bad", ["short", "has spaces in it", "x" * 129, "semi;colon;id"])
async def test_unsafe_incoming_request_id_is_replaced(client: httpx.AsyncClient, bad: str) -> None:
    response = await client.get("/healthz", headers={"X-Request-ID": bad})
    assert response.headers["x-request-id"] != bad


async def test_access_log_line_per_request(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="nodly.request"):
        await client.get("/healthz")
    [record] = [r for r in caplog.records if r.name == "nodly.request"]
    assert (record.method, record.path, record.status) == ("GET", "/healthz", 200)  # type: ignore[attr-defined]
    assert record.duration_ms >= 0  # type: ignore[attr-defined]


def test_json_formatter_includes_context_and_extras() -> None:
    record = logging.makeLogRecord(
        {"name": "nodly.x", "levelname": "INFO", "msg": "hello %s", "args": ("world",)}
    )
    record.job_type = "debug.echo"
    with bind_log_context(request_id="abc123"):
        line = JsonFormatter().format(record)
    payload = json.loads(line)
    assert payload["msg"] == "hello world"
    assert payload["request_id"] == "abc123"
    assert payload["job_type"] == "debug.echo"
    assert payload["ts"].endswith("Z")
