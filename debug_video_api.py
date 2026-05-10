#!/usr/bin/env python3
"""
Debug - verifica o que a API retorna
"""
import requests
import json
from pathlib import Path

video_path = r"C:\Users\Família Grom\OneDrive\Desktop\Josuel\Placas\VID-20260412-WA0017.mp4"

print(f"Arquivo: {Path(video_path).stat().st_size / 1e6:.1f} MB")
print(f"Enviando para http://127.0.0.1:8000/process_video...\n")

try:
    with open(video_path, "rb") as f:
        files = {"video": f}
        data = {
            "analysis_stage": "final",
            "max_frames_to_analyze": "12",
            "sample_every_n_frames": "5",
        }
        resp = requests.post(
            "http://127.0.0.1:8000/process_video",
            files=files,
            data=data,
            timeout=180
        )

    print(f"Status HTTP: {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('content-type')}")
    print(f"Content-Length: {len(resp.content)} bytes\n")

    if resp.status_code == 200:
        try:
            result = resp.json()
            print(f"✓ JSON válido")
            print(f"  Keys principais: {list(result.keys())}")

            if "video_context" in result:
                vc = result["video_context"]
                print(f"  video_context keys: {list(vc.keys())}")
                print(f"  total_vehicles_detected: {vc.get('total_vehicles_detected')}")
                print(f"  vehicle_tracks: {len(vc.get('vehicle_tracks', []))} rastreados")

                # Salva resultado
                with open("resultado_debug_video.json", "w", encoding="utf-8") as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)
                print(f"\n✓ Resultado salvo em resultado_debug_video.json")

        except json.JSONDecodeError as e:
            print(f"✗ Erro ao decodificar JSON: {e}")
            print(f"  Primeiros 500 chars: {resp.text[:500]}")
    else:
        print(f"✗ Erro HTTP {resp.status_code}")
        print(f"  Resposta: {resp.text[:300]}")

except requests.exceptions.Timeout:
    print("✗ Timeout na requisição (180s)")
except requests.exceptions.ConnectionError as e:
    print(f"✗ Erro de conexão: {e}")
except Exception as e:
    print(f"✗ Erro: {e}")
    import traceback
    traceback.print_exc()
