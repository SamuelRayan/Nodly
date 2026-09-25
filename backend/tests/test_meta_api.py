import httpx

from nodly.errors import PROBLEM_MEDIA_TYPE


async def test_timezone_list(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/meta/timezones")
    assert response.status_code == 200
    zones = {zone["id"]: zone for zone in response.json()["timezones"]}
    assert zones["Asia/Kolkata"]["utc_offset"] == "+05:30"
    assert zones["Asia/Kolkata"]["label"] == "Kolkata, India"


async def test_timezone_suggestions(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/v1/meta/timezones/suggest",
        params={"device_timezone": "Asia/Calcutta", "phone": "+61 2 9374 4000"},
    )
    assert response.status_code == 200
    suggestions = response.json()["suggestions"]
    assert [(s["id"], s["reason"]) for s in suggestions[:2]] == [
        ("Asia/Kolkata", "device"),
        ("Australia/Sydney", "phone_number"),
    ]


async def test_suggestions_without_inputs_are_empty(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/meta/timezones/suggest")
    assert response.json() == {"suggestions": []}


async def test_invalid_phone_is_a_problem(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/meta/timezones/suggest", params={"phone": "+44 12"})
    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.json()["code"] == "invalid_phone"


async def test_invalid_country_hint_is_a_validation_error(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/v1/meta/timezones/suggest", params={"phone": "2125550123", "phone_country": "ZZ"}
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["errors"][0]["type"] == "invalid_country"
    assert body["errors"][0]["loc"] == ["query", "phone_country"]


async def test_countries(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/meta/countries")
    countries = {c["code"]: c for c in response.json()["countries"]}
    assert countries["IN"] == {"code": "IN", "name": "India", "flag": "🇮🇳"}
