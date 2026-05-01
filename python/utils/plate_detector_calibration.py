from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLATE_DETECTION_CALIBRATION_PATH = (
    os.environ.get('GROM_OCR_PLATE_DETECTION_CALIBRATION_PATH')
    or str(PROJECT_ROOT / 'data' / 'plate_detector_calibration.json')
)


def _default_plate_detector_calibration():
    return {
        'version': '2026-04-03',
        'source': 'builtin_default',
        'thresholds': {
            'aspect_target': 4.2,
            'aspect_min': 1.7,
            'aspect_max': 9.2,
            'area_min_ratio': 0.0018,
            'area_max_ratio': 0.42,
            'min_image_width': 64,
            'min_image_height': 32,
            'min_box_width': 34,
            'min_box_height': 14,
        },
        'crop': {
            'pad_ratio': 0.08,
            'pad_ratio_small': 0.05,
            'pad_ratio_large': -0.02,
            'min_width': 58,
            'min_height': 18,
        },
        'quality': {
            'aspect_target': 4.2,
            'aspect_tolerance': 1.8,
            'aspect_min': 1.5,
            'aspect_max': 8.5,
            'min_area': 4500,
        },
    }


def _merge_dict(base, overlay):
    merged = dict(base or {})
    if not isinstance(overlay, dict):
        return merged

    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(value, dict):
            nested = dict(existing) if isinstance(existing, dict) else {}
            nested.update(value)
            merged[key] = nested
        elif isinstance(value, list):
            merged[key] = list(value)
        else:
            merged[key] = value
    return merged


@lru_cache(maxsize=1)
def load_plate_detector_calibration():
    calibration = _default_plate_detector_calibration()
    calibration['loaded_from'] = 'builtin_default'
    calibration['calibration_path'] = PLATE_DETECTION_CALIBRATION_PATH

    if not PLATE_DETECTION_CALIBRATION_PATH:
        return calibration

    if not os.path.exists(PLATE_DETECTION_CALIBRATION_PATH):
        calibration['load_error'] = 'calibration_file_not_found'
        return calibration

    try:
        with open(PLATE_DETECTION_CALIBRATION_PATH, 'r', encoding='utf-8') as handle:
            loaded = json.load(handle)
    except Exception as exc:  # pragma: no cover - best effort loader
        calibration['load_error'] = str(exc) or 'calibration_file_load_failed'
        return calibration

    if not isinstance(loaded, dict):
        calibration['load_error'] = 'calibration_file_invalid_format'
        return calibration

    merged = _merge_dict(calibration, loaded)
    merged['loaded_from'] = 'file'
    merged['load_error'] = ''
    return merged
