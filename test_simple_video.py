#!/usr/bin/env python3
"""
Teste direto do endpoint /process_video sem save para debug
"""
import requests
import json
from pathlib import Path

video_path = r"C:\Users\Família Grom\OneDrive\Desktop\Josuel\Placas\VID-20260412-WA0017.mp4"
api_base = "http://127.0.0.1:8000"

print(f"Arquivo: {Path(video_path).stat().st_size / 1e6:.1f} MB")

try:
    with open(video_path, "rb") as f:
        files = {"video": f}
        data = {
            "analysis_stage": "final",
            "max_frames_to_analyze": "12",
            "sample_every_n_frames": "5",
        }
        print(f"POST {api_base}/process_video")
        resp = requests.post(f"{api_base}/process_video", files=files, data=data, timeout=180)

    print(f"Status: {resp.status_code}")

    if resp.status_code == 200:
        result = resp.json()

        # Salva resultado
        output = Path("resultado_video_temporal.json")
        with open(output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        print(f"✓ Resultado salvo em {output}")

        # Mostra summary
        vc = result.get("video_context", {})
        print(f"\nVeículos: {len(vc.get('vehicle_tracks', []))}")
        print(f"Frames analisados: {vc.get('frames_analyzed')}")

    else:
        print(f"✗ Erro: {resp.text[:200]}")

except Exception as e:
    print(f"✗ Exceção: {e}")
    import traceback
    traceback.print_exc()
