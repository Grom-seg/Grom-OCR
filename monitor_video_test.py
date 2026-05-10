#!/usr/bin/env python3
"""
Monitor de progresso do teste de rastreamento de veículos
"""
import time
import json
from pathlib import Path
import requests

result_file = Path("resultado_video_temporal.json")
api_base = "http://127.0.0.1:8000"
start_time = time.time()
max_wait = 600  # 10 minutos

print("⏳ Monitorando processamento de vídeo...")
print(f"   Resultado esperado em: {result_file}")

while time.time() - start_time < max_wait:
    if result_file.exists():
        try:
            with open(result_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            print(f"\n✓ Processamento concluído em {(time.time()-start_time):.0f}s")

            # Extrai informações
            video_ctx = data.get("video_context", {})
            vehicles = video_ctx.get("vehicle_tracks", [])

            print(f"\n📊 RESULTADO:")
            print(f"   Veículos detectados: {len(vehicles)}")
            print(f"   Frames analisados: {video_ctx.get('frames_analyzed')}")
            print(f"   FPS: {video_ctx.get('fps'):.1f}")
            print(f"   SHA256 do vídeo: {video_ctx.get('source_video_sha256', 'N/A')[:16]}...")

            for v in vehicles:
                print(f"\n   🚗 Veículo #{v.get('track_id')}:")
                print(f"      Placa: {v.get('consolidated_plate', '?')}")
                print(f"      Período: {v.get('timespan_sec', (0, 0))[0]:.2f}s - {v.get('timespan_sec', (0, 0))[1]:.2f}s")
                print(f"      Detecções: {v.get('detections_count')}")
                print(f"      Confiança média: {v.get('avg_confidence', 0):.1%}")

            break
        except Exception as e:
            print(f"   ⚠ Erro ao ler resultado: {e}")
            break
    else:
        elapsed = time.time() - start_time
        print(f"   {int(elapsed):3d}s - Aguardando...", end="\r")
        time.sleep(2)

else:
    print(f"\n✗ Timeout após {max_wait}s de espera")
    print(f"   Verifique se o servidor está respondendo: {api_base}")
