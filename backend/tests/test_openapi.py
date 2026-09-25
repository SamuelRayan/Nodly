"""The committed OpenAPI document is current, and it describes the API honestly."""

import json

from nodly.api.openapi import render_openapi
from nodly.config import BACKEND_DIR


def document() -> dict:
    return json.loads(render_openapi())


def test_committed_openapi_json_is_up_to_date() -> None:
    committed = (BACKEND_DIR / "openapi.json").read_text(encoding="utf-8")
    assert committed == render_openapi(), "run: python scripts/export_openapi.py"


def test_operation_ids_are_handler_names_and_unique() -> None:
    ids = [op["operationId"] for item in document()["paths"].values() for op in item.values()]
    assert len(ids) == len(set(ids))
    assert "create_family" in ids and "claim_pairing_code" in ids
    assert not [i for i in ids if i.startswith("dev_")]  # /dev is never exported


def test_errors_are_problem_json() -> None:
    doc = document()
    for item in doc["paths"].values():
        for op in item.values():
            for status, response in op["responses"].items():
                if int(status) >= 400:
                    assert list(response["content"]) == ["application/problem+json"]
    assert "HTTPValidationError" not in doc["components"]["schemas"]
    assert "Problem" in doc["components"]["schemas"]


def test_security_schemes() -> None:
    doc = document()
    assert set(doc["components"]["securitySchemes"]) == {"SupabaseJWT", "DeviceToken"}
    me = doc["paths"]["/v1/me"]["get"]
    device = doc["paths"]["/v1/device/me"]["get"]
    claim = doc["paths"]["/v1/pairing/claim"]["post"]
    assert me["security"] == [{"SupabaseJWT": []}]
    assert device["security"] == [{"DeviceToken": []}]
    assert "security" not in claim  # the elder's phone has no login
