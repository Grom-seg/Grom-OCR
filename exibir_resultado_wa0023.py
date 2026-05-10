import json

d = json.load(open(r'C:\Grom_OCR\resultado_video_WA0023.json', encoding='utf-8'))
vc = d.get('video_context', {}) or {}

print('=== VIDEO CONTEXT ===')
print('FPS:', vc.get('fps'))
print('Duracao:', vc.get('duration_sec'), 's')
print('Frames analisados:', vc.get('frames_analyzed'))
print('Frame melhor: #', vc.get('best_frame_index'), '@', vc.get('best_frame_timestamp_sec'), 's')
print('Total veiculos:', vc.get('total_vehicles_detected'))

vts = vc.get('vehicle_tracks', [])
print('\n--- Rastreamento de Veiculos ---')
for i, vt in enumerate(vts, 1):
    print(f'\nVeiculo #{i} | track_id={vt.get("track_id")}')
    print(f'  Placa consolidada : {vt.get("consolidated_plate") or "(nao lida)"}')
    print(f'  Candidatos OCR    : {vt.get("plate_candidates")}')
    print(f'  Frames detectados : {vt.get("detections_count")}')
    ts = vt.get('timespan_sec') or {}
    if isinstance(ts, dict):
        print(f'  Intervalo         : {ts.get("start")} -> {ts.get("end")} s')
    else:
        print(f'  Intervalo         : {ts}')
    print(f'  Confianca media   : {vt.get("avg_confidence", 0):.0%}')

print('\n--- Melhor Placa (frame principal) ---')
best = d.get('best') or {}
print('Placa:', best.get('text') or '(nao detectada)')
print('Confianca:', d.get('confidence_score', {}).get('overall_confidence', 0))
print('Valida:', best.get('valid'))

fs = vc.get('frame_summary', [])
print('\n--- Frame Summary ---')
print(f"{'Frame':>6}  {'T(s)':>7}  {'Nitidez':>8}  {'Placa':^12}  {'Conf':>5}")
for fr in fs:
    p = fr.get('plate_read') or '-'
    c = fr.get('confidence', 0.0)
    print(f"{fr.get('frame_index', '?'):>6}  {str(fr.get('timestamp_sec', '?')):>7}  {fr.get('sharpness', 0.0):>8.1f}  {p:^12}  {c:.0%}")
