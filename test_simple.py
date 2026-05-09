import json
import os
import time
from pathlib import Path

import requests

API_BASE = os.environ.get("GROM_OCR_TEST_API_BASE", "http://127.0.0.1:8000").rstrip("/")
API_URL = f"{API_BASE}/process"
IMG_PATH = r"C:\Grom_OCR\data\uploads\20171119_154214_ch6-1024x576.jpg"
OUT_PATH = r"C:\Grom_OCR\data\test_results\last_simple_test.json"


def test_process_returns_json_and_has_expected_shape():
    start = time.time()
    with open(IMG_PATH, "rb") as f:
        resp = requests.post(
            API_URL,
            files={"image": (Path(IMG_PATH).name, f, "image/jpeg")},
            timeout=300,
        )

    elapsed = time.time() - start

    content_type = (resp.headers.get("content-type") or "").lower()
    if resp.status_code != 200:
        raise AssertionError(
            f"HTTP {resp.status_code} after {elapsed:.1f}s. content-type={content_type} body[:500]={resp.text[:500]}"
        )

    # Garantir que é JSON antes de chamar resp.json()
    is_json_ct = "application/json" in content_type or content_type.endswith("+json")
    looks_like_json = resp.text.strip().startswith("{") or resp.text.strip().startswith("[")

    if not (is_json_ct or looks_like_json):
        raise AssertionError(
            f"Resposta não parece JSON. content-type={content_type} body[:500]={resp.text[:500]}"
        )

    data = resp.json()

    # Checks mínimos de forma
    assert isinstance(data, dict), "payload JSON deve ser um objeto"
    assert "ocr" in data, "payload deve conter 'ocr'"
    assert "best" in data, "payload deve conter 'best'"
    assert "consensus" in data, "payload deve conter 'consensus'"
    assert "confidence_score" in data, "payload deve conter 'confidence_score'"

    # opcional: salvar para inspeção local
    try:
        Path(OUT_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    except Exception:
        # não falhar o teste por causa do artefato
        pass
