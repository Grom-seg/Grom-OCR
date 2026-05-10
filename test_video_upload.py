#!/usr/bin/env python3
"""
Script de teste para endpoint /process_video com rastreamento temporal de veículos
"""
import requests
import json
import sys
from pathlib import Path

video_path = r"C:\Users\Família Grom\OneDrive\Desktop\Josuel\Placas\VID-20260412-WA0017.mp4"
api_base = "http://127.0.0.1:8000"

if not Path(video_path).exists():
    print(f"✗ Arquivo não encontrado: {video_path}")
    sys.exit(1)

print("[VIDEO] Testando rastreamento temporal de veiculos")
print(f"   Arquivo: {video_path}")
print(f"   Tamanho: {Path(video_path).stat().st_size / (1024*1024):.1f} MB")
print(f"   API: {api_base}/process_video")

try:
    with open(video_path, "rb") as f:
        files = {"video": f}
        data = {
            "analysis_stage": "final",
            "max_frames_to_analyze": "12",
            "sample_every_n_frames": "5",
        }
        print("\n[INFO] Enviando video para processamento...")
        resp = requests.post(
            f"{api_base}/process_video",
            files=files,
            data=data,
            timeout=180
        )

    print(f"[OK] Resposta HTTP: {resp.status_code}")

    if resp.status_code == 200:
        result = resp.json()

        # Extrai informações de rastreamento temporal
        video_context = result.get("video_context", {})
        vehicle_tracks = video_context.get("vehicle_tracks", [])
        total_vehicles = video_context.get("total_vehicles_detected", 0)

        print("\n[RESULT] Resultado do rastreamento temporal:")
        print(f"   Veículos detectados: {total_vehicles}")
        print(f"   FPS: {video_context.get('fps')}")
        print(f"   Total de frames: {video_context.get('total_frames')}")
        print(f"   Frames analisados: {video_context.get('frames_analyzed')}")

        for track in vehicle_tracks:
            track_id = track.get("track_id")
            plate = track.get("consolidated_plate", "?")
            timespan = track.get("timespan_sec", (0, 0))
            det_count = track.get("detections_count", 0)
            avg_conf = track.get("avg_confidence", 0)
            candidates = track.get("plate_candidates", {})

            print(f"\n   [VEICULO] #{track_id}:")
            print(f"      Placa consolidada: {plate}")
            print(f"      Período: {timespan[0]:.2f}s - {timespan[1]:.2f}s")
            print(f"      Detecções: {det_count}")
            print(f"      Confiança média: {avg_conf:.2%}")
            print(f"      Candidatos de placa: {candidates}")

            frames = track.get("frames", [])
            if frames:
                print(f"      Frames:")
                for fr in frames[:3]:  # Primeiros 3
                    print(f"        - Frame {fr.get('frame_index')}: {fr.get('plate_text', '?')} @ {fr.get('timestamp_sec', 0):.2f}s (conf: {fr.get('confidence', 0):.2%})")
                if len(frames) > 3:
                    print(f"        ... ({len(frames) - 3} mais)")

        # Salva resultado completo
        output_file = Path("resultado_video_temporal.json")
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\n[ARQUIVO] Resultado completo salvo em: {output_file}")

    else:
        print(f"[ERRO] HTTP {resp.status_code}")
        print(f"   Resposta: {resp.text[:500]}")

except requests.exceptions.ConnectionError:
    print(f"[ERRO] Conexao: servidor nao respondeu em {api_base}")
    print("   Verifique se o FastAPI esta rodando")
except Exception as e:
    print(f"[ERRO] {e}")
    import traceback
    traceback.print_exc()
