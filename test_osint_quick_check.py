#!/usr/bin/env python3
"""Validação rápida de OSINT em /process (imagem) apenas."""
import json
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests not available")
    exit(1)

results = []

# Test /process only
print("Testando /process (imagem)...", flush=True)
try:
    img_path = Path("test-assets/plate_test.png")
    start = time.time()
    r = requests.post("http://127.0.0.1:8001/process", files={"image": img_path.open("rb")}, timeout=60)
    elapsed = time.time() - start
    data = r.json()

    has_osint = isinstance(data.get("vehicle_osint"), dict) and len(data["vehicle_osint"]) > 0

    print(f"Status HTTP: {r.status_code}")
    print(f"OSINT presente: {has_osint}")
    print(f"Tempo: {elapsed:.1f}s")

    if has_osint:
        print(f"OSINT.status: {data['vehicle_osint'].get('status')}")
        print(f"Chaves no payload: {list(data.keys())[:5]}")
        results.append({"endpoint": "/process", "status": "OK", "has_osint": True})

except Exception as e:
    print(f"ERRO: {e}")
    results.append({"endpoint": "/process", "status": "ERRO", "error": str(e)})

# Save
with open("resultado_validacao_osint_runtime.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"\nSalvo: resultado_validacao_osint_runtime.json")
print(f"Status geral: {'✓ OK' if results and results[0]['status']=='OK' else '✗ ERRO'}")
