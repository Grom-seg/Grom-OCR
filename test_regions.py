import json
import os
import time
from pathlib import Path

import requests

API_BASE = os.environ.get("GROM_OCR_TEST_API_BASE", "http://127.0.0.1:8000").rstrip("/")
API_URL = f"{API_BASE}/process"
IMG_PATH = r"C:\Grom_OCR\data\uploads\20171119_154214_ch6-1024x576.jpg"


def test_process_regions_returns_json():
    start = time.time()
    with open(IMG_PATH, "rb") as f:
        resp = requests.post(
            API_URL,
            files={"image": ("img.jpg", f, "image/jpeg")},
            timeout=300,
        )

    elapsed = time.time() - start

    content_type = (resp.headers.get("content-type") or "").lower()
    if resp.status_code != 200:
        raise AssertionError(
            f"HTTP {resp.status_code} after {elapsed:.1f}s. content-type={content_type} body[:500]={resp.text[:500]}"
        )

    is_json_ct = "application/json" in content_type or content_type.endswith("+json")
    looks_like_json = resp.text.strip().startswith("{") or resp.text.strip().startswith("[")
    if not (is_json_ct or looks_like_json):
        raise AssertionError(
            f"Resposta não parece JSON. content-type={content_type} body[:500]={resp.text[:500]}"
        )

    data = resp.json()

    assert isinstance(data, dict), "payload JSON deve ser um objeto"
    assert "regions_tested" in data, "payload deve conter 'regions_tested'"
    assert "detections" in data, "payload deve conter 'detections'"
    assert isinstance(data.get("detections", []), list), "detections deve ser uma lista"
