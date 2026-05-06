#!/usr/bin/env python3
"""
Teste E2E final: validar fluxo completo OCR + Telemetria após integração.
"""
import requests
import json
import time
import sys
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"
TEST_IMAGE = "data/datasets/Imagens/fiat.jpg"

def test_health():
    print("[E2E] 1. Health check...", end=" ")
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        assert r.status_code == 200
        print("✓")
        return True
    except Exception as e:
        print(f"✗ {e}")
        return False

def test_ocr_runtime():
    print("[E2E] 2. OCR runtime diagnostics...", end=" ")
    try:
        r = requests.get(f"{BASE_URL}/ocr/runtime", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "ocr_runtime" in data
        print("✓")
        print(f"   Engine: {data['ocr_runtime']['selected_engine']}")
        return True
    except Exception as e:
        print(f"✗ {e}")
        return False

def test_process_endpoint():
    print("[E2E] 3. Process endpoint with OCR...", end=" ")
    try:
        if not Path(TEST_IMAGE).exists():
            print(f"✗ Image not found")
            return False
        with open(TEST_IMAGE, "rb") as f:
            r = requests.post(f"{BASE_URL}/process", files={"image": f}, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "ocr_engine_status" in data
        assert "ocr_engine_summary" in data
        print("✓")
        return True
    except Exception as e:
        print(f"✗ {e}")
        return False

def test_full_pipeline():
    print("[E2E] 4. Full pipeline endpoint...", end=" ")
    try:
        if not Path(TEST_IMAGE).exists():
            print(f"✗ Image not found")
            return False
        with open(TEST_IMAGE, "rb") as f:
            r = requests.post(f"{BASE_URL}/full-pipeline", files={"file": f}, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "detections" in data
        assert "ocr_results" in data
        print("✓")
        return True
    except Exception as e:
        print(f"✗ {e}")
        return False

def main():
    print("=" * 60)
    print("TESTE E2E FINAL - OCR + TELEMETRIA")
    print("=" * 60)

    # Aguardar servidor pronto
    for i in range(10):
        try:
            requests.get(f"{BASE_URL}/health", timeout=2)
            break
        except:
            if i == 9:
                print("\n✗ Backend indisponível")
                return False
            time.sleep(1)

    results = [
        test_health(),
        test_ocr_runtime(),
        test_process_endpoint(),
        test_full_pipeline(),
    ]

    print("\n" + "=" * 60)
    passed = sum(results)
    print(f"RESULTADO: {passed}/4 testes passaram")
    print("=" * 60)
    return all(results)

if __name__ == "__main__":
    sys.exit(0 if main() else 1)
