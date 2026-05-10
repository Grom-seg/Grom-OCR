"""
Análise pericial do vídeo VID-20260412-WA0023.mp4
Pipeline em 2 fases: frames leves → melhor frame completo
"""
import requests
import json
import sys
import time

VIDEO_PATH = r"C:\Users\Família Grom\Downloads\VID-20260412-WA0023.mp4"
OUTPUT_PATH = r"C:\Grom_OCR\resultado_video_WA0023.json"
API_URL = "http://127.0.0.1:8000/process_video"

print(f"[INFO] Enviando vídeo: {VIDEO_PATH}")
print(f"[INFO] Timeout: 300s — aguarde...")

start = time.time()

try:
    with open(VIDEO_PATH, "rb") as f:
        resp = requests.post(
            API_URL,
            files={"video": (f.name.split("\\")[-1], f, "video/mp4")},
            data={
                "analysis_stage": "final",
                "max_frames_to_analyze": "10",
                "sample_every_n_frames": "8",
            },
            timeout=300,
        )
    elapsed = round(time.time() - start, 1)
    print(f"[OK] Resposta em {elapsed}s — HTTP {resp.status_code}")

    if resp.status_code != 200:
        print(f"[ERRO] {resp.text[:500]}")
        sys.exit(1)

    data = resp.json()

    with open(OUTPUT_PATH, "w", encoding="utf-8") as out:
        json.dump(data, out, ensure_ascii=False, indent=2)
    print(f"[OK] Resultado salvo em: {OUTPUT_PATH}")

    # ──────────────── Resumo ────────────────
    best = data.get("best", {}) or {}
    conf = data.get("confidence_score", {}) or {}
    vc = data.get("video_context", {}) or {}

    print("\n" + "═"*55)
    print("           RESULTADO PERICIAL — VÍDEO")
    print("═"*55)
    print(f"Vídeo       : {vc.get('source_video', '?')}")
    print(f"FPS         : {vc.get('fps', '?')}")
    dur = vc.get('duration_sec')
    print(f"Duração     : {dur}s" if dur else "Duração     : ?")
    print(f"Frames anal.: {vc.get('frames_analyzed', '?')}")
    print(f"Frame melhor: #{vc.get('best_frame_index','?')} @ {vc.get('best_frame_timestamp_sec','?')}s")
    print()
    print(f"PLACA LIDA  : {best.get('text', '(não detectada)')}")
    print(f"Confiança   : {conf.get('overall_confidence', 0.0):.0%}")
    print(f"Placa válida: {'SIM' if best.get('valid') else 'NÃO'}")

    vehicle_tracks = vc.get("vehicle_tracks", [])
    print(f"\nVeículos rastreados: {vc.get('total_vehicles_detected', 0)}")
    for i, vt in enumerate(vehicle_tracks, 1):
        print(f"\n  Veículo #{i} | track_id={vt.get('track_id', '?')}")
        print(f"    Placa consolidada : {vt.get('consolidated_plate') or '(não lida)'}")
        print(f"    Candidatos OCR    : {vt.get('plate_candidates', [])}")
        print(f"    Frames detectado  : {vt.get('detections_count', 0)}")
        ts = vt.get('timespan_sec', {}) or {}
        print(f"    Intervalo (s)     : {ts.get('start','?')} → {ts.get('end','?')}")
        print(f"    Confiança média   : {vt.get('avg_confidence', 0):.0%}")

    fs = vc.get("frame_summary", [])
    if fs:
        print(f"\nSumário de frames ({len(fs)} processados):")
        print(f"  {'Frame':>6}  {'Tempo(s)':>8}  {'Nitidez':>8}  {'Placa':^12}  {'Conf':>6}")
        print(f"  {'─'*6}  {'─'*8}  {'─'*8}  {'─'*12}  {'─'*6}")
        for fr in fs:
            plate = fr.get('plate_read') or '—'
            conf_v = fr.get('confidence', 0.0)
            print(f"  {fr.get('frame_index','?'):>6}  {str(fr.get('timestamp_sec','?')):>8}  {fr.get('sharpness',0.0):>8.1f}  {plate:^12}  {conf_v:.0%}")

    print("\n" + "═"*55)

except requests.exceptions.Timeout:
    print(f"[TIMEOUT] Não respondeu em 300s — servidor ainda processando?")
    sys.exit(2)
except Exception as ex:
    print(f"[ERRO] {ex}")
    sys.exit(3)
