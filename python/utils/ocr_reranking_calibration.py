from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OCR_RERANKING_CALIBRATION_PATH = (
    os.environ.get('GROM_OCR_OCR_RERANKING_CALIBRATION_PATH')
    or str(PROJECT_ROOT / 'data' / 'ocr_reranking_calibration.json')
)


def _default_ocr_reranking_calibration():
    return {
        'version': '2026-04-12-r1',
        'source': 'builtin_default',
        'ensemble_weights': {
            'plate_recognizer': 1.18,
            'easyocr': 0.66,
            'rapidocr': 1.18,
            'tesseract': 0.48,
            'pdf_probe': 0.66,
            'paddleocr': 0.80,
            'trocr': 0.76,
            'doctr': 0.74,
        },
        'ensemble': {
            'rank_decay_step': 0.20,
            'min_rank_decay': 0.25,
            'pattern_bonus': 0.95,
            'pattern_penalty': -0.70,
            'length_bonus': 1.00,
            'length_penalty': -0.30,
            'score_divisor': 85.0,
            'score_component_cap': 2.0,
            'conf_divisor': 100.0,
            'conf_component_cap': 1.2,
            'support_bonus_per_engine': 1.85,
            'support_bonus_cap': 4.5,
            'consensus_min_support': 2,
            'required_length': 7,
            'single_engine_min_weighted_support': 8.8,
            'single_engine_min_confidence': 74.0,
            'single_engine_fallback_divisor': 20.0,
            'pdf_probable_min_score': 98.0,
            'pdf_probable_min_confidence': 68.0,
            'pdf_probable_min_weighted_support': 7.0,
            'pdf_probable_min_support_count': 2,
            'pdf_probable_required_length': 7,
            'style_bias': {
                'enabled': True,
                'strong_style_min_confidence': 65.0,
                'style_match_rank_credit': 0.55,
                'style_match_rank_scale': 0.22,
                'style_mismatch_rank_penalty': 0.60,
                'style_mismatch_rank_scale': 0.20,
                'leading_d_bonus': 7.9,
                'leading_d_bonus_scale': 0.80,
                'leading_d_rank_credit': 1.0,
                'leading_d_rank_scale': 0.18,
                'close_conf_margin': 5.0,
                'close_score_margin': 15.0,
            },
        },
        'engine_profiles': {
            'easyocr': {
                'name': 'easyocr',
                'factor_min': 0.18,
                'factor_max': 1.04,
                'accept_conf': 30.0,
                'accept_score': 50.0,
                'pattern_score': 62.0,
                'min_hits': 2,
                'min_variant_hits': 2,
                'gap_scale': 14.0,
                'warning_penalty': 0.85,
                'error_penalty': 0.71,
                'low_reliability_penalty': 0.57,
                'no_text_penalty': 0.84,
                'weak_pattern_penalty': 0.67,
                'reliability_boost': 0.07,
            },
            'rapidocr': {
                'name': 'rapidocr',
                'factor_min': 0.20,
                'factor_max': 1.06,
                'accept_conf': 28.0,
                'accept_score': 48.0,
                'pattern_score': 62.0,
                'min_hits': 2,
                'min_variant_hits': 2,
                'gap_scale': 13.0,
                'warning_penalty': 0.84,
                'error_penalty': 0.70,
                'low_reliability_penalty': 0.55,
                'no_text_penalty': 0.82,
                'weak_pattern_penalty': 0.66,
                'reliability_boost': 0.08,
            },
            'tesseract': {
                'name': 'tesseract',
                'factor_min': 0.12,
                'factor_max': 0.90,
                'accept_conf': 78.0,
                'accept_score': 68.0,
                'pattern_score': 100.0,
                'min_hits': 2,
                'min_variant_hits': 2,
                'gap_scale': 18.0,
                'warning_penalty': 0.84,
                'error_penalty': 0.70,
                'low_reliability_penalty': 0.52,
                'no_text_penalty': 0.80,
                'weak_pattern_penalty': 0.64,
                'reliability_boost': 0.04,
            },
            'trocr': {
                'name': 'trocr',
                'factor_min': 0.14,
                'factor_max': 0.86,
                'accept_conf': 36.0,
                'accept_score': 56.0,
                'pattern_score': 66.0,
                'min_hits': 2,
                'min_variant_hits': 2,
                'gap_scale': 15.0,
                'warning_penalty': 0.85,
                'error_penalty': 0.71,
                'low_reliability_penalty': 0.56,
                'no_text_penalty': 0.83,
                'weak_pattern_penalty': 0.67,
                'reliability_boost': 0.04,
            },
            'doctr': {
                'name': 'doctr',
                'factor_min': 0.14,
                'factor_max': 0.84,
                'accept_conf': 34.0,
                'accept_score': 54.0,
                'pattern_score': 64.0,
                'min_hits': 2,
                'min_variant_hits': 2,
                'gap_scale': 15.0,
                'warning_penalty': 0.85,
                'error_penalty': 0.71,
                'low_reliability_penalty': 0.56,
                'no_text_penalty': 0.83,
                'weak_pattern_penalty': 0.67,
                'reliability_boost': 0.04,
            },
            'paddleocr': {
                'name': 'paddleocr',
                'factor_min': 0.15,
                'factor_max': 0.92,
                'accept_conf': 32.0,
                'accept_score': 50.0,
                'pattern_score': 62.0,
                'min_hits': 2,
                'min_variant_hits': 2,
                'gap_scale': 14.0,
                'warning_penalty': 0.85,
                'error_penalty': 0.71,
                'low_reliability_penalty': 0.56,
                'no_text_penalty': 0.83,
                'weak_pattern_penalty': 0.67,
                'reliability_boost': 0.05,
            },
            'plate_recognizer': {
                'name': 'plate_recognizer',
                'factor_min': 0.22,
                'factor_max': 1.10,
                'accept_conf': 60.0,
                'accept_score': 68.0,
                'pattern_score': 74.0,
                'min_hits': 2,
                'min_variant_hits': 1,
                'gap_scale': 12.0,
                'warning_penalty': 0.84,
                'error_penalty': 0.70,
                'low_reliability_penalty': 0.55,
                'no_text_penalty': 0.82,
                'weak_pattern_penalty': 0.65,
                'reliability_boost': 0.09,
            },
            'pdf_probe': {
                'name': 'pdf_probe',
                'factor_min': 0.12,
                'factor_max': 0.82,
                'accept_conf': 48.0,
                'accept_score': 56.0,
                'pattern_score': 64.0,
                'min_hits': 1,
                'min_variant_hits': 1,
                'gap_scale': 18.0,
                'warning_penalty': 0.85,
                'error_penalty': 0.71,
                'low_reliability_penalty': 0.57,
                'no_text_penalty': 0.88,
                'weak_pattern_penalty': 0.74,
                'reliability_boost': 0.03,
            },
        },
        'benchmark_summary': {},
        'runtime_policy': {
            'disabled_by_default_engines': ['trocr', 'doctr', 'paddleocr'],
            'weight_caps': {
                'trocr': 0.35,
                'doctr': 0.35,
                'paddleocr': 0.35,
            },
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


def _apply_runtime_policy(calibration):
    if not isinstance(calibration, dict):
        return calibration

    policy = calibration.get('runtime_policy', {})
    if not isinstance(policy, dict):
        return calibration

    disabled_engines = policy.get('disabled_by_default_engines', [])
    if not isinstance(disabled_engines, (list, tuple, set)):
        disabled_engines = []

    weight_caps = policy.get('weight_caps', {})
    if not isinstance(weight_caps, dict):
        weight_caps = {}

    ensemble_weights = calibration.get('ensemble_weights', {})
    if not isinstance(ensemble_weights, dict):
        ensemble_weights = {}
        calibration['ensemble_weights'] = ensemble_weights

    applied = False
    for engine in disabled_engines:
        key = str(engine or '').strip().lower()
        if not key:
            continue
        try:
            cap = float(weight_caps.get(key, 0.35))
        except (TypeError, ValueError):
            cap = 0.35
        cap = max(0.1, min(cap, 1.0))
        try:
            current = float(ensemble_weights.get(key, cap))
        except (TypeError, ValueError):
            current = cap
        capped = min(current, cap)
        if capped != current:
            ensemble_weights[key] = round(capped, 4)
            applied = True

    if applied:
        calibration['runtime_policy_applied'] = True
    return calibration


@lru_cache(maxsize=1)
def load_ocr_reranking_calibration():
    calibration = _default_ocr_reranking_calibration()
    calibration['loaded_from'] = 'builtin_default'
    calibration['calibration_path'] = OCR_RERANKING_CALIBRATION_PATH

    if not OCR_RERANKING_CALIBRATION_PATH:
        return calibration

    if not os.path.exists(OCR_RERANKING_CALIBRATION_PATH):
        calibration['load_error'] = 'calibration_file_not_found'
        return calibration

    try:
        with open(OCR_RERANKING_CALIBRATION_PATH, 'r', encoding='utf-8') as handle:
            loaded = json.load(handle)
    except Exception as exc:  # pragma: no cover - best effort loader
        calibration['load_error'] = str(exc) or 'calibration_file_load_failed'
        return calibration

    if not isinstance(loaded, dict):
        calibration['load_error'] = 'calibration_file_invalid_format'
        return calibration

    merged = _merge_dict(calibration, loaded)
    merged = _apply_runtime_policy(merged)
    merged['loaded_from'] = 'file'
    merged['load_error'] = ''
    return merged
