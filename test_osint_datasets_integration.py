#!/usr/bin/env python3
"""Valida integração OSINT com referência local de modelos brasileiros."""

from fastapi_backend.datasets_loader import datasets_status, match_brazilian_model
from fastapi_backend.vehicle_osint import build_vehicle_osint_report


def test_datasets_status_reports_local_reference() -> None:
    status = datasets_status()
    assert isinstance(status, dict)
    assert status.get("brazilian_cars_ref", {}).get("available") is True
    assert int(status.get("brazilian_cars_ref", {}).get("total_makes", 0)) > 0
    assert int(status.get("brazilian_cars_ref", {}).get("total_models", 0)) > 0


def test_match_brazilian_model_finds_known_candidate() -> None:
    match = match_brazilian_model(make="ACURA", model_candidate="Integra")
    assert isinstance(match, dict)
    assert match.get("matched") is True
    assert match.get("match_type") in {"exact", "partial"}


def test_vehicle_osint_report_embeds_dataset_trace() -> None:
    report = build_vehicle_osint_report(
        vehicle_analysis={
            "vehicle_detections": [{"class_name": "car", "confidence": 0.88}],
            "make_model_clip": [{"label": "ACURA Integra", "score": 0.91}],
            "light_regions": {"reliable": True},
            "headlight_templates": [{"template": "sedan_front", "make": "ACURA", "score": 0.70}],
        },
        top_candidates=[{"text": "ABC1D23", "engine": "ocr", "score": 0.81}],
        vehicle_info={"fabricante": "ACURA", "modelo": "Integra"},
        analysis_id="test-osint-001",
        source_filename="frame_test.jpg",
    )

    assert isinstance(report, dict)
    assert report.get("status") == "ok"
    assert isinstance(report.get("query_trace"), dict)
    assert isinstance(report.get("top_model_candidates"), list)
    assert report.get("query_trace", {}).get("datasets_loader_available") is True

    ds = report.get("query_trace", {}).get("datasets_status", {})
    assert ds.get("brazilian_cars_ref", {}).get("available") is True

    if report.get("top_model_candidates"):
        evidence = report["top_model_candidates"][0].get("evidence", {})
        assert isinstance(evidence.get("brazilian_model_match", {}), dict)
