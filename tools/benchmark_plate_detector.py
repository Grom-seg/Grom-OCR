#!/usr/bin/env python
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = PROJECT_ROOT / 'python'
TESSERACT_CMD = PROJECT_ROOT / 'tools' / 'tesseract-portable' / 'tesseract.exe'
TESSDATA_DIR = PROJECT_ROOT / 'tools' / 'tesseract-portable' / 'tessdata'
os.environ.setdefault('GROM_OCR_TESSERACT_CMD', str(TESSERACT_CMD))
os.environ.setdefault('TESSDATA_PREFIX', str(TESSDATA_DIR))
os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

import ocr_agent  # noqa: E402
from utils import plate_detector_calibration  # noqa: E402


DEFAULT_MANIFEST = PROJECT_ROOT / 'data' / 'plate_detector_benchmark_manifest.json'
DEFAULT_OUTPUT = PROJECT_ROOT / 'data' / 'plate_detector_benchmark_results.json'
DEFAULT_CALIBRATION_OUTPUT = PROJECT_ROOT / 'data' / 'plate_detector_calibration.generated.json'


def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def percentile(values, pct):
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=float), pct))


def load_manifest(path: Path):
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(f'Manifesto nao encontrado: {path}')

    if path.suffix.lower() == '.jsonl':
        entries = []
        with path.open('r', encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                entries.append(json.loads(line))
        return entries

    with path.open('r', encoding='utf-8') as handle:
        loaded = json.load(handle)

    if isinstance(loaded, dict):
        entries = loaded.get('items', [])
        if not isinstance(entries, list):
            raise ValueError('O manifesto deve conter uma lista em items.')
        return entries

    if not isinstance(loaded, list):
        raise ValueError('O manifesto precisa ser uma lista ou um objeto com items.')

    return loaded


def resolve_image_path(entry):
    image_value = str(entry.get('image') or '').strip()
    if not image_value:
        raise ValueError('Entrada sem caminho de imagem.')

    candidate = Path(image_value)
    if not candidate.is_absolute():
        candidate = (PROJECT_ROOT / candidate).resolve()
    return candidate


def summarize_detection(image_path, kind='scene', notes=''):
    img = cv2.imread(str(image_path))
    if img is None or getattr(img, 'size', 0) == 0:
        return {
            'image': str(image_path),
            'kind': kind,
            'notes': notes,
            'status_code': 0,
            'error': 'image_load_failed',
        }

    image_height, image_width = img.shape[:2]
    regions = ocr_agent.build_plate_regions(img, None)
    summary = ocr_agent.build_plate_detection_summary(regions)
    selected_region_name = str(summary.get('selected_region', ''))
    selected_region_img = None
    for region_name, region_img in regions:
        if str(region_name) == selected_region_name:
            selected_region_img = region_img
            break
    if selected_region_img is None and regions:
        selected_region_img = regions[0][1]

    selected_height = int(selected_region_img.shape[0]) if selected_region_img is not None else 0
    selected_width = int(selected_region_img.shape[1]) if selected_region_img is not None else 0
    selected_area = int(selected_height * selected_width)
    image_area = int(image_height * image_width)
    selected_area_ratio = float(selected_area) / float(image_area) if image_area > 0 else 0.0

    return {
        'image': str(image_path),
        'kind': kind,
        'notes': notes,
        'status_code': 200,
        'image_width': int(image_width),
        'image_height': int(image_height),
        'image_area': int(image_area),
        'candidate_count': int(summary.get('candidate_count', 0) or 0),
        'selected_region': selected_region_name,
        'selected_source': str(summary.get('selected_source', 'none') or 'none'),
        'selected_quality_score': float(summary.get('selected_quality_score', 0.0) or 0.0),
        'selected_score': float(summary.get('selected_score', 0.0) or 0.0),
        'selected_aspect_ratio': float(summary.get('selected_aspect_ratio', 0.0) or 0.0),
        'selected_quality_label': str(summary.get('selected_quality_label', 'indefinida') or 'indefinida'),
        'selected_plausibility_bonus': float(summary.get('selected_plausibility_bonus', 0.0) or 0.0),
        'selected_shape_hint': str(summary.get('selected_shape_hint', 'indefinida') or 'indefinida'),
        'selected_width': int(selected_width),
        'selected_height': int(selected_height),
        'selected_area': int(selected_area),
        'selected_area_ratio': round(float(selected_area_ratio), 6),
        'used_full_image': bool(summary.get('used_full_image', False)),
        'roi_detected': bool(summary.get('status') == 'roi_detectado' and not summary.get('used_full_image', False)),
        'candidate_regions': [str(item[0]) for item in regions[:8]],
        'summary': summary,
    }


def build_calibration_from_results(base_calibration, results):
    calibration = copy.deepcopy(base_calibration)
    thresholds = calibration.setdefault('thresholds', {})
    crop = calibration.setdefault('crop', {})
    quality = calibration.setdefault('quality', {})

    usable = [
        item for item in results
        if item.get('status_code') == 200
        and float(item.get('selected_aspect_ratio', 0.0) or 0.0) > 0.0
        and not (item.get('kind') == 'scene' and item.get('used_full_image'))
    ]
    detector_samples = [item for item in usable if item.get('kind') == 'scene' and item.get('roi_detected')]
    if not detector_samples:
        detector_samples = [item for item in usable if item.get('kind') == 'scene']
    if not detector_samples:
        detector_samples = list(usable)

    aspect_values = [float(item.get('selected_aspect_ratio', 0.0) or 0.0) for item in usable if float(item.get('selected_aspect_ratio', 0.0) or 0.0) > 0.0]
    quality_pool = [item for item in usable if float(item.get('selected_quality_score', 0.0) or 0.0) > 0.0]
    quality_aspects = [float(item.get('selected_aspect_ratio', 0.0) or 0.0) for item in quality_pool if float(item.get('selected_aspect_ratio', 0.0) or 0.0) > 0.0]
    quality_areas = [int(item.get('selected_area', 0) or 0) for item in quality_pool if int(item.get('selected_area', 0) or 0) > 0]

    if aspect_values:
        thresholds['aspect_target'] = round(float(np.median(np.asarray(aspect_values, dtype=float))), 3)

    if quality_aspects:
        quality['aspect_target'] = round(float(np.median(np.asarray(quality_aspects, dtype=float))), 3)
        quality['aspect_tolerance'] = round(float(clamp((percentile(quality_aspects, 90) - percentile(quality_aspects, 10)) / 2.2, 1.0, 2.6)), 3)
    if quality_areas:
        quality['min_area'] = int(round(clamp(min(quality.get('min_area', 4500), percentile(quality_areas, 15) * 0.90), 3000, 30000)))

    calibration['loaded_from'] = 'benchmark_suggestion'
    calibration['benchmark_summary'] = {
        'total': int(len(results)),
        'usable': int(len(usable)),
        'scene_samples': int(len(detector_samples)),
        'scene_roi_detected': int(sum(1 for item in detector_samples if item.get('roi_detected'))),
        'scene_roi_rate_percent': round((float(sum(1 for item in detector_samples if item.get('roi_detected'))) / float(max(1, len(detector_samples)))) * 100.0, 2),
        'full_image_selected': int(sum(1 for item in results if item.get('used_full_image'))),
        'source_family_counts': dict(sorted(
            (
                (source, sum(1 for item in results if str(item.get('selected_source', 'none')) == source))
                for source in sorted({str(item.get('selected_source', 'none')) for item in results})
            ),
            key=lambda item: (-item[1], item[0]),
        )),
        'suggested_aspect_target': round(float(np.median(np.asarray(aspect_values, dtype=float))), 3) if aspect_values else None,
        'suggested_quality_aspect_target': round(float(np.median(np.asarray(quality_aspects, dtype=float))), 3) if quality_aspects else None,
    }
    return calibration


def run_benchmark(manifest_path):
    entries = load_manifest(manifest_path)
    if not entries:
        raise ValueError('O manifesto nao possui entradas.')

    results = []
    source_family_counts = defaultdict(int)
    kind_counts = defaultdict(int)
    roi_detected_count = 0
    full_image_count = 0
    quality_label_counts = defaultdict(int)

    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        image_path = resolve_image_path(entry)
        if not image_path.exists():
            raise FileNotFoundError(f'Imagem nao encontrada: {image_path}')

        kind = str(entry.get('kind') or 'scene').strip().lower() or 'scene'
        notes = str(entry.get('notes') or '').strip()
        item = summarize_detection(image_path, kind=kind, notes=notes)
        item['index'] = index
        item['expected_kind'] = kind
        item['notes'] = notes
        results.append(item)

        source_family_counts[str(item.get('selected_source', 'none'))] += 1
        kind_counts[kind] += 1
        quality_label_counts[str(item.get('selected_quality_label', 'indefinida'))] += 1
        if item.get('roi_detected'):
            roi_detected_count += 1
        if item.get('used_full_image'):
            full_image_count += 1

    total = len(results)
    scene_total = sum(1 for item in results if item.get('kind') == 'scene')
    crop_total = sum(1 for item in results if item.get('kind') != 'scene')
    scene_roi_rate = (sum(1 for item in results if item.get('kind') == 'scene' and item.get('roi_detected')) / float(max(1, scene_total))) * 100.0
    scene_fallback_rate = (sum(1 for item in results if item.get('kind') == 'scene' and item.get('used_full_image')) / float(max(1, scene_total))) * 100.0
    avg_selected_score = sum(float(item.get('selected_score', 0.0) or 0.0) for item in results) / float(max(1, total))
    avg_selected_quality = sum(float(item.get('selected_quality_score', 0.0) or 0.0) for item in results) / float(max(1, total))

    summary = {
        'total': total,
        'scene_total': scene_total,
        'crop_total': crop_total,
        'roi_detected_total': roi_detected_count,
        'full_image_total': full_image_count,
        'scene_roi_rate_percent': round(float(scene_roi_rate), 2),
        'scene_fallback_rate_percent': round(float(scene_fallback_rate), 2),
        'avg_selected_score': round(float(avg_selected_score), 2),
        'avg_selected_quality_score': round(float(avg_selected_quality), 2),
        'selected_source_counts': dict(sorted(source_family_counts.items(), key=lambda item: (-item[1], item[0]))),
        'quality_label_counts': dict(sorted(quality_label_counts.items(), key=lambda item: (-item[1], item[0]))),
        'kind_counts': dict(sorted(kind_counts.items(), key=lambda item: (-item[1], item[0]))),
    }

    return {
        'generated_at_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'manifest': str(manifest_path.resolve()),
        'summary': summary,
        'results': results,
    }


def main():
    parser = argparse.ArgumentParser(description='Benchmark do detector/recorte de placas para o Grom OCR.')
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST, help='Caminho do manifesto JSON/JSONL.')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT, help='Arquivo JSON com o resultado consolidado.')
    parser.add_argument('--export-calibration', type=Path, default=DEFAULT_CALIBRATION_OUTPUT, help='Gera um arquivo de calibracao sugerida.')
    args = parser.parse_args()

    report = run_benchmark(args.manifest)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)

    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))
    print(f'Resultado salvo em: {args.output}')

    if args.export_calibration:
        base_calibration = plate_detector_calibration.load_plate_detector_calibration()
        suggested = build_calibration_from_results(base_calibration, report['results'])
        args.export_calibration.parent.mkdir(parents=True, exist_ok=True)
        with args.export_calibration.open('w', encoding='utf-8') as handle:
            json.dump(suggested, handle, ensure_ascii=False, indent=2)
        print(f'Calibracao sugerida salva em: {args.export_calibration}')


if __name__ == '__main__':
    main()
