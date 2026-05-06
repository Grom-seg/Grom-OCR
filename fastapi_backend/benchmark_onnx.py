"""
Benchmark ONNX vs YOLO - Phase 4
Compara latência, throughput e detecções entre os dois backends.

Uso:
    python -m fastapi_backend.benchmark_onnx --image caminho/imagem.jpg
    python -m fastapi_backend.benchmark_onnx --image caminho/imagem.jpg --runs 50
"""
import argparse
import json
import logging
import os
import time
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)


def _benchmark_yolo(image_path: str, runs: int = 20) -> dict:
    """Mede latência do detector YOLO (ultralytics)."""
    try:
        from ultralytics import YOLO
        import os as _os
        model_path = _os.getenv('GROM_YOLO_MODEL', 'yolov8n.pt')
        model = YOLO(model_path)

        # Warm-up
        for _ in range(3):
            model(image_path, verbose=False)

        times = []
        detections_count = 0
        for _ in range(runs):
            t0 = time.perf_counter()
            results = model(image_path, verbose=False)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            times.append(elapsed_ms)

            for r in results:
                detections_count += len(r.boxes)

        return {
            'backend': 'yolo_pt',
            'runs': runs,
            'avg_ms': round(float(np.mean(times)), 2),
            'min_ms': round(float(np.min(times)), 2),
            'max_ms': round(float(np.max(times)), 2),
            'std_ms': round(float(np.std(times)), 2),
            'avg_detections': round(detections_count / runs, 2),
            'error': None,
        }
    except Exception as exc:
        return {'backend': 'yolo_pt', 'error': str(exc)}


def _benchmark_onnx(image_path: str, runs: int = 20) -> dict:
    """Mede latência do OnnxDetector."""
    try:
        from fastapi_backend.onnx_detector import OnnxDetector
        detector = OnnxDetector()

        if not detector.is_ready:
            return {
                'backend': 'onnx',
                'error': (
                    'Modelo ONNX não encontrado. '
                    'Execute: python -m fastapi_backend.onnx_exporter'
                ),
            }

        bench = detector.benchmark(image_path, runs=runs)
        detections = detector.detect(image_path)

        return {
            'backend': 'onnx',
            'runs': bench['runs'],
            'avg_ms': bench['avg_ms'],
            'min_ms': bench['min_ms'],
            'max_ms': bench['max_ms'],
            'std_ms': bench['std_ms'],
            'avg_detections': len(detections),
            'error': None,
        }
    except Exception as exc:
        return {'backend': 'onnx', 'error': str(exc)}


def run_benchmark(
    image_path: str,
    runs: int = 20,
    include_yolo: bool = True,
    include_onnx: bool = True,
) -> dict:
    """
    Executa benchmark completo e retorna relatório comparativo.

    Returns:
        {
            'image': str,
            'runs': int,
            'yolo': {...},
            'onnx': {...},
            'speedup': float | None,  # onnx_avg / yolo_avg (< 1 = onnx mais rápido)
            'winner': 'yolo' | 'onnx' | 'tie' | 'error',
        }
    """
    if not os.path.exists(image_path):
        return {'error': f'Imagem não encontrada: {image_path}'}

    logger.info('Benchmark iniciado: %s (%d runs cada)', image_path, runs)

    result: dict = {
        'image': os.path.abspath(image_path),
        'runs': runs,
        'yolo': None,
        'onnx': None,
        'speedup': None,
        'winner': 'error',
    }

    if include_yolo:
        logger.info('Benchmarkando YOLO...')
        result['yolo'] = _benchmark_yolo(image_path, runs)

    if include_onnx:
        logger.info('Benchmarkando ONNX...')
        result['onnx'] = _benchmark_onnx(image_path, runs)

    # Calcula speedup
    yolo_ok = result['yolo'] and not result['yolo'].get('error')
    onnx_ok = result['onnx'] and not result['onnx'].get('error')

    if yolo_ok and onnx_ok:
        yolo_avg = result['yolo']['avg_ms']
        onnx_avg = result['onnx']['avg_ms']
        if yolo_avg > 0:
            speedup = onnx_avg / yolo_avg
            result['speedup'] = round(speedup, 3)
            if abs(speedup - 1.0) < 0.05:
                result['winner'] = 'tie'
            elif speedup < 1.0:
                result['winner'] = 'onnx'
            else:
                result['winner'] = 'yolo'
    elif yolo_ok:
        result['winner'] = 'yolo'
    elif onnx_ok:
        result['winner'] = 'onnx'

    return result


def format_report(result: dict) -> str:
    """Formata relatório de benchmark para exibição no terminal."""
    lines = [
        '=' * 60,
        'BENCHMARK: YOLO vs ONNX',
        f'Imagem : {result.get("image", "N/A")}',
        f'Runs   : {result.get("runs", 0)}',
        '=' * 60,
    ]

    for backend in ('yolo', 'onnx'):
        data = result.get(backend)
        if data is None:
            continue
        lines.append(f'\n[{backend.upper()}]')
        if data.get('error'):
            lines.append(f'  ERRO: {data["error"]}')
        else:
            lines.append(f'  avg : {data["avg_ms"]:.1f} ms')
            lines.append(f'  min : {data["min_ms"]:.1f} ms')
            lines.append(f'  max : {data["max_ms"]:.1f} ms')
            lines.append(f'  std : {data["std_ms"]:.1f} ms')
            lines.append(f'  dets: {data.get("avg_detections", "N/A")}')

    lines.append('')
    speedup = result.get('speedup')
    winner = result.get('winner', 'error')

    if speedup is not None:
        if winner == 'onnx':
            lines.append(f'ONNX é {1/speedup:.2f}x mais rápido que YOLO')
        elif winner == 'yolo':
            lines.append(f'YOLO é {speedup:.2f}x mais rápido que ONNX')
        else:
            lines.append('Desempenho equivalente (< 5% diferença)')

    lines.append('=' * 60)
    return '\n'.join(lines)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(description='Benchmark ONNX vs YOLO')
    parser.add_argument('--image', required=True, help='Caminho para imagem de teste')
    parser.add_argument('--runs', type=int, default=20, help='Número de iterações')
    parser.add_argument('--no-yolo', action='store_true', help='Pular benchmark YOLO')
    parser.add_argument('--no-onnx', action='store_true', help='Pular benchmark ONNX')
    parser.add_argument('--json', action='store_true', help='Saída em JSON')
    args = parser.parse_args()

    result = run_benchmark(
        image_path=args.image,
        runs=args.runs,
        include_yolo=not args.no_yolo,
        include_onnx=not args.no_onnx,
    )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_report(result))
