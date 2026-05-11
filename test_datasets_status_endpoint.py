#!/usr/bin/env python3
"""Teste rápido do endpoint /datasets/status."""

from fastapi.testclient import TestClient

from fastapi_backend.main import app


client = TestClient(app)


def test_datasets_status_endpoint_shape() -> None:
    response = client.get("/datasets/status")
    assert response.status_code == 200

    payload = response.json()
    assert payload.get("status") == "ok"
    assert isinstance(payload.get("datasets"), dict)
    assert isinstance(payload.get("missing_requirements"), list)
    assert isinstance(payload.get("ready_for_brcars_osint"), bool)


def test_datasets_status_has_brazilian_reference() -> None:
    response = client.get("/datasets/status")
    payload = response.json()
    assert payload.get("datasets", {}).get("brazilian_cars_ref", {}).get("available") is True
