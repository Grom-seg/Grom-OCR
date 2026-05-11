#!/usr/bin/env python3
"""Testes do endpoint /osint/search."""

from fastapi.testclient import TestClient

from fastapi_backend.main import app


client = TestClient(app)


def test_osint_search_endpoint_shape() -> None:
    response = client.get("/osint/search", params={"make": "honda", "model": "civic", "limit": 3})
    assert response.status_code == 200

    payload = response.json()
    assert payload.get("status") == "ok"
    assert isinstance(payload.get("candidates"), list)
    assert isinstance(payload.get("db_status"), dict)


def test_osint_search_has_candidates_for_known_make_model() -> None:
    response = client.get("/osint/search", params={"make": "honda", "model": "civic", "limit": 3})
    assert response.status_code == 200

    payload = response.json()
    candidates = payload.get("candidates", [])
    assert len(candidates) >= 1

    first = candidates[0]
    assert "make" in first
    assert "model" in first
    assert "score" in first
    assert "source" in first


def test_osint_search_respects_limit() -> None:
    response = client.get("/osint/search", params={"make": "toyota", "limit": 2})
    assert response.status_code == 200

    payload = response.json()
    candidates = payload.get("candidates", [])
    assert len(candidates) <= 2
