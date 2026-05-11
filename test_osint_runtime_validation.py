#!/usr/bin/env python3
"""Valida presença de OSINT em runtime nos endpoints de imagem e vídeo."""
import json
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests not available", file=sys.stderr)
    sys.exit(1)

BASE_URL = "http://127.0.0.1:8001"
RESULTS = []

# Test 1: /process endpoint (image)
print("[1/2] Testando /process (imagem)...", flush=True)
try:
    img_path = Path("test-assets/plate_test.png")
    if not img_path.exists():
        print(f"  ERROR: {img_path} not found", file=sys.stderr)
        RESULTS.append({"endpoint": "/process", "status": "ERRO", "reason": "imagem não encontrada"})
    else:
        start = time.time()
        r = requests.post(f"{BASE_URL}/process", files={"image": img_path.open("rb")}, timeout=60)
        elapsed = time.time() - start
        data = r.json() if r.status_code == 200 else {}

        has_osint = isinstance(data.get("vehicle_osint"), dict) and len(data["vehicle_osint"]) > 0
        status = "✓ OSINT OK" if has_osint else "✗ OSINT AUSENTE"

        print(f"  Status HTTP: {r.status_code}")
        print(f"  Tempo: {elapsed:.1f}s")
        print(f"  Resultado: {status}")

        if has_osint:
            osint_status = data["vehicle_osint"].get("status", "?")
            print(f"  OSINT status interno: {osint_status}")
            RESULTS.append({"endpoint": "/process", "status": "OK", "osint_status": osint_status, "time_sec": round(elapsed, 1)})
        else:
            RESULTS.append({"endpoint": "/process", "status": "ERRO", "reason": "vehicle_osint não no payload"})
except Exception as e:
    print(f"  EXCEPTION: {e}", file=sys.stderr)
    RESULTS.append({"endpoint": "/process", "status": "ERRO", "reason": str(e)})

# Test 2: /process_video endpoint (video)
print("\n[2/2] Testando /process_video (vídeo)...", flush=True)
try:
    vid_path = Path("data/test_results/video_real_test.mp4")
    if not vid_path.exists():
        print(f"  ERROR: {vid_path} not found", file=sys.stderr)
        RESULTS.append({"endpoint": "/process_video", "status": "ERRO", "reason": "vídeo não encontrado"})
    else:
        print(f"  Arquivo: {vid_path.name} ({vid_path.stat().st_size} bytes)")
        start = time.time()
        r = requests.post(f"{BASE_URL}/process_video", files={"video": vid_path.open("rb")}, timeout=300)
        elapsed = time.time() - start
        data = r.json() if r.status_code == 200 else {}

        has_osint = isinstance(data.get("vehicle_osint"), dict) and len(data["vehicle_osint"]) > 0
        has_video_ctx = isinstance(data.get("video_context"), dict) and len(data["video_context"]) > 0
        status = "✓ OSINT OK" if has_osint else "✗ OSINT AUSENTE"

        print(f"  Status HTTP: {r.status_code}")
        print(f"  Tempo: {elapsed:.1f}s")
        print(f"  Resultado: {status}")
        print(f"  video_context presente: {has_video_ctx}")

        if has_osint:
            osint_status = data["vehicle_osint"].get("status", "?")
            print(f"  OSINT status interno: {osint_status}")
            RESULTS.append({"endpoint": "/process_video", "status": "OK", "osint_status": osint_status, "time_sec": round(elapsed, 1), "video_context": has_video_ctx})
        else:
            RESULTS.append({"endpoint": "/process_video", "status": "ERRO", "reason": "vehicle_osint não no payload"})
except Exception as e:
    print(f"  EXCEPTION: {e}", file=sys.stderr)
    RESULTS.append({"endpoint": "/process_video", "status": "ERRO", "reason": str(e)})

# Consolidate results
print("\n" + "="*60)
print("RESUMO DE VALIDAÇÃO DE RUNTIME")
print("="*60)

for r in RESULTS:
    endpoint = r["endpoint"]
    status = r["status"]
    indicator = "✓" if status == "OK" else "✗"
    print(f"{indicator} {endpoint}: {status}")
    if "reason" in r:
        print(f"  Motivo: {r['reason']}")
    if "osint_status" in r:
        print(f"  OSINT interno: {r['osint_status']}")
    if "time_sec" in r:
        print(f"  Tempo: {r['time_sec']}s")

all_ok = all(r["status"] == "OK" for r in RESULTS)
exit_code = 0 if all_ok else 1

print("="*60)
print(f"CONCLUSÃO: {'✓ OSINT VALIDADO EM AMBOS ENDPOINTS' if all_ok else '✗ FALHAS DETECTADAS'}")
print("="*60)

# Save report to file
report_path = Path("resultado_validacao_osint_runtime.json")
with open(report_path, "w") as f:
    json.dump({"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "results": RESULTS, "all_ok": all_ok}, f, indent=2)
print(f"\nRelatório salvo: {report_path}")

sys.exit(exit_code)
