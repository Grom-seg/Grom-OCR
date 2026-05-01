from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MICROCALIBRATION_PATH = (
    os.environ.get('GROM_OCR_MICROCALIBRATION_PATH')
    or str(PROJECT_ROOT / 'data' / 'ocr_microcalibration.json')
).strip()


def _normalize_key(value) -> str:
    text = '' if value is None else str(value).strip().lower()
    return text.replace(' ', '').replace('-', '').replace('_', '')


def _default_microcalibration():
    return {
        'version': '2026-04-05-r1',
        'source': 'builtin_default',
        'overrides': {},
    }


@lru_cache(maxsize=1)
def load_microcalibration():
    calibration = _default_microcalibration()
    calibration['calibration_path'] = MICROCALIBRATION_PATH

    if not MICROCALIBRATION_PATH:
        calibration['load_error'] = 'microcalibration_path_empty'
        return calibration

    if not os.path.exists(MICROCALIBRATION_PATH):
        calibration['load_error'] = 'microcalibration_file_not_found'
        return calibration

    try:
        with open(MICROCALIBRATION_PATH, 'r', encoding='utf-8') as handle:
            loaded = json.load(handle)
    except Exception as exc:  # pragma: no cover - best effort loader
        calibration['load_error'] = str(exc) or 'microcalibration_file_load_failed'
        return calibration

    if not isinstance(loaded, dict):
        calibration['load_error'] = 'microcalibration_file_invalid_format'
        return calibration

    overrides = loaded.get('overrides', {})
    if not isinstance(overrides, dict):
        overrides = {}

    normalized_overrides = {}
    for key, value in overrides.items():
        normalized_key = _normalize_key(key)
        if not normalized_key or not isinstance(value, dict):
            continue
        normalized_overrides[normalized_key] = dict(value)

    calibration.update({k: v for k, v in loaded.items() if k != 'overrides'})
    calibration['overrides'] = normalized_overrides
    calibration['loaded_from'] = 'file'
    calibration['load_error'] = ''
    return calibration


def lookup_microcalibration_override(*, source_sha256=None, photo_filename=None, plate_filename=None):
    calibration = load_microcalibration()
    overrides = calibration.get('overrides', {})
    if not isinstance(overrides, dict) or not overrides:
        return {}

    def _filename_variants(value):
        text = '' if value is None else str(value).strip()
        if not text:
            return []
        variants = [text]
        try:
            path = Path(text)
            stem = path.stem
            if stem and stem not in variants:
                variants.append(stem)
        except Exception:
            pass
        return variants

    candidates = [
        source_sha256,
        photo_filename,
        os.path.basename(str(photo_filename or '')),
        *_filename_variants(photo_filename),
        plate_filename,
        os.path.basename(str(plate_filename or '')),
        *_filename_variants(plate_filename),
    ]
    for candidate in candidates:
        key = _normalize_key(candidate)
        if key and key in overrides:
            result = dict(overrides[key])
            result['match_key'] = key
            result.setdefault('calibration_version', str(calibration.get('version', 'builtin_default')))
            result.setdefault('calibration_path', str(calibration.get('calibration_path', MICROCALIBRATION_PATH)))
            return result
    return {}
