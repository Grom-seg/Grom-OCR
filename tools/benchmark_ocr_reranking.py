#!/usr/bin/env python
from __future__ import annotations

import argparse
import copy
import io
import json
import mimetypes
import os
import time
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

import cv2
import requests
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
from utils import ocr_reranking_calibration  # noqa: E402


DEFAULT_MANIFEST = PROJECT_ROOT / 'data' / 'ocr_reranking_benchmark_manifest.json'
DEFAULT_OUTPUT = PROJECT_ROOT / 'data' / 'ocr_reranking_benchmark_results.json'
DEFAULT_CALIBRATION_OUTPUT = PROJECT_ROOT / 'data' / 'ocr_reranking_calibration.generated.json'
DEFAULT_DIRECT_ENGINES = ('tesseract', 'rapidocr', 'easyocr')


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


def parse_engine_names(value):
    raw = str(value or '').strip()
    if not raw or raw.lower() == 'auto':
        return list(DEFAULT_DIRECT_ENGINES)

    engines = []
    for part in raw.split(','):
        name = normalize_expected_text(part).lower()
        if name:
            engines.append(name)
    return engines or list(DEFAULT_DIRECT_ENGINES)


def load_bgr_image(image_path):
    if image_path.suffix.lower() == '.pdf':
        raise ValueError(
            f'Modo direto suporta somente imagens raster; use um manifesto de crops/imagens, nao PDF: {image_path}'
        )
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f'Falha ao carregar imagem: {image_path}')
    return image


def normalize_expected_text(value):
    return ocr_agent.normalize_plate_text(value) or ''


def extract_payload_best(payload):
    best = payload.get('best', {})
    if not isinstance(best, dict):
        return ''
    return normalize_expected_text(best.get('text', ''))


def extract_best_meta(payload):
    best = payload.get('best', {})
    if not isinstance(best, dict):
        best = {}
    return best


def extract_top_candidates(payload):
    candidates = payload.get('top_candidates', [])
    if isinstance(candidates, list):
        return [item for item in candidates if isinstance(item, dict)]
    return []


def extract_engine_blocks(payload):
    ocr_block = payload.get('ocr', {})
    if isinstance(ocr_block, dict):
        return {str(key): value for key, value in ocr_block.items() if isinstance(value, dict)}
    return {}


def candidate_rank(entries, expected_text):
    for index, candidate in enumerate(entries, start=1):
        if normalize_expected_text(candidate.get('text', '')) == expected_text:
            return index
    return None


def post_local(image_path):
    client = ocr_agent.app.test_client()
    payload = image_path.read_bytes()
    data = {
        'image': (io.BytesIO(payload), image_path.name, mimetypes.guess_type(image_path.name)[0] or 'application/octet-stream'),
    }
    response = client.post('/process', data=data, content_type='multipart/form-data')
    try:
        body = response.get_json(silent=True) or {}
    except Exception:
        body = {}
    return response.status_code, body


def post_remote(api_url, image_path):
    url = api_url.rstrip('/') + '/process'
    with image_path.open('rb') as handle:
        files = {'image': (image_path.name, handle, mimetypes.guess_type(image_path.name)[0] or 'application/octet-stream')}
        response = requests.post(url, files=files, timeout=900)
    try:
        body = response.json()
    except Exception:
        body = {'error': response.text[:500]}
    return response.status_code, body


def call_direct_engine(engine_name, image):
    engine_key = str(engine_name or '').strip().lower()
    if engine_key == 'tesseract':
        return ocr_agent.ocr_tesseract(image)
    if engine_key == 'easyocr':
        return ocr_agent.ocr_easyocr(image)
    if engine_key == 'rapidocr':
        return ocr_agent.ocr_rapidocr(image)
    if engine_key == 'trocr':
        return ocr_agent.ocr_trocr(image)
    if engine_key == 'doctr':
        return ocr_agent.ocr_doctr(image)
    if engine_key == 'paddleocr':
        return ocr_agent.ocr_paddleocr(image)
    return {
        'text': '',
        'avg_conf': 0.0,
        'score': 0.0,
        'pattern': 'Indefinido',
        'chars': [],
        'candidates': [],
        'error': f'engine_not_supported:{engine_key}',
    }


def run_direct_ocr(image_path, engine_names):
    image = load_bgr_image(image_path)
    ocr_results = {}
    engine_status = {}
    warnings = []

    for engine_name in engine_names:
        start = time.perf_counter()
        try:
            result = call_direct_engine(engine_name, image)
            elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        except Exception as exc:
            result = {
                'text': '',
                'avg_conf': 0.0,
                'score': 0.0,
                'pattern': 'Indefinido',
                'chars': [],
                'candidates': [],
                'error': str(exc),
            }
            elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)

        ocr_results[engine_name] = result
        engine_status[engine_name] = {
            'enabled': True,
            'available': True,
            'status': 'executed' if not result.get('error') else 'failed',
            'has_text': bool(normalize_expected_text(result.get('text', ''))),
            'elapsed_ms': elapsed_ms,
            'error': str(result.get('error', '')) if result.get('error') else '',
            'warning': str(result.get('warning', '')) if result.get('warning') else '',
        }
        if result.get('warning'):
            warnings.append(f'{engine_name}:{result["warning"]}')
        if result.get('error'):
            warnings.append(f'{engine_name}:{result["error"]}')

    consensus = ocr_agent.build_consensus_report(ocr_results)
    best_engine, best_payload = ocr_agent.get_best_result(ocr_results)
    top_candidates = ocr_agent.build_top_candidates(ocr_results)
    if isinstance(best_payload, dict):
        best_payload = dict(best_payload)
        best_payload.setdefault('engine', best_engine or '')

    assessment = ocr_agent.build_assessment(best_payload, consensus, warnings, adulterado=False)
    ocr_engine_summary = ocr_agent.build_engine_summary(engine_status)

    payload = {
        'ocr': ocr_results,
        'best': best_payload or {},
        'top_candidates': top_candidates,
        'char_options': [],
        'regions_tested': [],
        'color_info': {},
        'plate_pattern_info': {},
        'adulteracao': False,
        'forensic': {},
        'consensus': consensus,
        'assessment': assessment,
        'pericial': {'evidence_level': assessment.get('evidence_level', '')},
        'visual_profile': {},
        'external_systems_comparison': {},
        'ocr_engine_status': engine_status,
        'ocr_engine_summary': ocr_engine_summary,
        'ocr_reranking_calibration': ocr_reranking_calibration.load_ocr_reranking_calibration(),
        'engine_runtime': {name: {'mode': 'direct', 'elapsed_ms': meta.get('elapsed_ms', 0.0)} for name, meta in engine_status.items()},
        'plate_detection': {'status': 'direct_crop', 'region': 'direct_crop'},
        'capture_integrity': {},
        'operational_protocol': {},
        'vehicle_confrontation_form': {},
        'warnings': warnings,
    }
    return payload


def summarize_sample(entry, status_code, payload):
    expected_text = normalize_expected_text(entry.get('expected_text', ''))
    best_text = extract_payload_best(payload)
    matched = bool(expected_text) and expected_text == best_text
    best_meta = extract_best_meta(payload)
    top_candidates = extract_top_candidates(payload)
    engine_blocks = extract_engine_blocks(payload)
    consensus = payload.get('consensus', {})
    if not isinstance(consensus, dict):
        consensus = {}

    engine_matches = {}
    for engine_name, block in engine_blocks.items():
        candidates = block.get('candidates', [])
        if not isinstance(candidates, list):
            candidates = []
        normalized_candidates = [item for item in candidates if isinstance(item, dict)]
        engine_matches[engine_name] = {
            'text': normalize_expected_text(block.get('text', '')),
            'top_match': normalize_expected_text(block.get('text', '')) == expected_text if expected_text else False,
            'candidate_rank': candidate_rank(normalized_candidates, expected_text),
            'candidate_found': candidate_rank(normalized_candidates, expected_text) is not None,
            'candidate_count': len(normalized_candidates),
            'best_score': float(best_meta.get('score', 0.0) or 0.0) if engine_name == best_meta.get('engine') else float(block.get('score', 0.0) or 0.0),
            'avg_conf': float(block.get('avg_conf', 0.0) or 0.0),
        }

    expected_in_top_candidates = candidate_rank(top_candidates, expected_text)
    top_candidate = top_candidates[0] if top_candidates else {}
    top_candidate_text = normalize_expected_text(top_candidate.get('text', '')) if isinstance(top_candidate, dict) else ''

    return {
        'image': str(entry.get('image', '')),
        'kind': str(entry.get('kind', 'scene')),
        'notes': str(entry.get('notes', '')),
        'status_code': int(status_code),
        'expected_text': expected_text,
        'observed_best_text': best_text,
        'observed_best_engine': str(best_meta.get('engine', '')),
        'observed_best_score': float(best_meta.get('score', 0.0) or 0.0),
        'observed_best_confidence': float(best_meta.get('avg_conf', 0.0) or 0.0),
        'observed_best_weighted_support': float(best_meta.get('weighted_support', 0.0) or 0.0),
        'observed_best_support_count': int(best_meta.get('support_count', 0) or 0),
        'observed_best_selection_reason': str(best_meta.get('selection_reason', '')),
        'observed_best_acceptance_reason': str(best_meta.get('acceptance_reason', '')),
        'matched': matched,
        'top_candidate_text': top_candidate_text,
        'expected_in_top_candidates_rank': expected_in_top_candidates,
        'top_candidate_count': len(top_candidates),
        'consensus_ratio': float(consensus.get('agreement_ratio', 0.0) or 0.0),
        'consensus_count': int(consensus.get('agreement_count', 0) or 0),
        'engines_considered': int(consensus.get('engines_considered', 0) or 0),
        'engine_matches': engine_matches,
        'top_candidates': top_candidates[:8],
        'engine_blocks': {
            name: {
                'text': block.get('text', ''),
                'score': float(block.get('score', 0.0) or 0.0),
                'avg_conf': float(block.get('avg_conf', 0.0) or 0.0),
                'pattern': block.get('pattern', 'Indefinido'),
                'candidate_count': len(block.get('candidates', []) if isinstance(block.get('candidates', []), list) else []),
            }
            for name, block in engine_blocks.items()
        },
        'warnings': payload.get('warnings', []),
        'ocr_engine_summary': payload.get('ocr_engine_summary', {}),
        'ocr_engine_status': payload.get('ocr_engine_status', {}),
        'assessment': payload.get('assessment', {}),
        'pericial_status': (payload.get('assessment') or {}).get('evidence_level', ''),
    }


def run_benchmark(manifest_path, api_url=None, direct=False, engine_names=None):
    entries = load_manifest(manifest_path)
    if not entries:
        raise ValueError('O manifesto nao possui entradas.')

    engine_names = list(engine_names or DEFAULT_DIRECT_ENGINES)
    results = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        image_path = resolve_image_path(entry)
        if not image_path.exists():
            raise FileNotFoundError(f'Imagem nao encontrada: {image_path}')

        if direct:
            payload = run_direct_ocr(image_path, engine_names)
            status_code = 200 if not any((meta or {}).get('error') for meta in (payload.get('ocr_engine_status') or {}).values()) else 206
        elif api_url:
            status_code, payload = post_remote(api_url, image_path)
        else:
            status_code, payload = post_local(image_path)

        sample = summarize_sample(entry, status_code, payload)
        sample['index'] = index
        results.append(sample)

    total = len(results)
    matched_count = sum(1 for item in results if item.get('matched'))
    best_engine_counts = defaultdict(int)
    top_candidate_match_count = 0
    expected_in_top_candidates_count = 0
    expected_rank_values = []
    best_weighted_support_correct = []
    best_weighted_support_wrong = []

    engine_stats = defaultdict(lambda: {
        'total': 0,
        'top_match': 0,
        'candidate_found': 0,
        'candidate_rank_values': [],
        'top_score_values': [],
        'top_conf_values': [],
    })

    for item in results:
        best_engine = str(item.get('observed_best_engine', '') or '')
        if best_engine:
            best_engine_counts[best_engine] += 1
        if item.get('top_candidate_text') == item.get('expected_text') and item.get('expected_text'):
            top_candidate_match_count += 1
        if item.get('expected_in_top_candidates_rank') is not None:
            expected_in_top_candidates_count += 1
            expected_rank_values.append(int(item.get('expected_in_top_candidates_rank') or 0))

        if item.get('matched'):
            best_weighted_support_correct.append(float(item.get('observed_best_weighted_support', 0.0) or 0.0))
        else:
            best_weighted_support_wrong.append(float(item.get('observed_best_weighted_support', 0.0) or 0.0))

        for engine_name, meta in (item.get('engine_matches') or {}).items():
            if not isinstance(meta, dict):
                continue
            stats = engine_stats[str(engine_name)]
            stats['total'] += 1
            stats['top_match'] += int(bool(meta.get('top_match')))
            stats['candidate_found'] += int(bool(meta.get('candidate_found')))
            rank = meta.get('candidate_rank')
            if rank is not None:
                stats['candidate_rank_values'].append(int(rank))
            stats['top_score_values'].append(float(meta.get('best_score', 0.0) or 0.0))
            stats['top_conf_values'].append(float(meta.get('avg_conf', 0.0) or 0.0))

    def mean_or_zero(values):
        return float(mean(values)) if values else 0.0

    def median_or_zero(values):
        return float(median(values)) if values else 0.0

    per_engine_summary = {}
    for engine_name, stats in engine_stats.items():
        total_engine = max(1, int(stats['total']))
        per_engine_summary[engine_name] = {
            'total': int(stats['total']),
            'top_match': int(stats['top_match']),
            'candidate_found': int(stats['candidate_found']),
            'top_match_rate_percent': round((float(stats['top_match']) / float(total_engine)) * 100.0, 2),
            'candidate_recall_rate_percent': round((float(stats['candidate_found']) / float(total_engine)) * 100.0, 2),
            'mean_candidate_rank': round(mean_or_zero(stats['candidate_rank_values']), 3),
            'median_candidate_rank': round(median_or_zero(stats['candidate_rank_values']), 3),
            'mean_top_score': round(mean_or_zero(stats['top_score_values']), 2),
            'mean_top_confidence': round(mean_or_zero(stats['top_conf_values']), 2),
        }

    summary = {
        'total': total,
        'matched': matched_count,
        'accuracy_percent': round((float(matched_count) / float(max(1, total))) * 100.0, 2),
        'top_candidate_match_count': top_candidate_match_count,
        'top_candidate_match_rate_percent': round((float(top_candidate_match_count) / float(max(1, total))) * 100.0, 2),
        'expected_in_top_candidates_count': expected_in_top_candidates_count,
        'expected_in_top_candidates_rate_percent': round((float(expected_in_top_candidates_count) / float(max(1, total))) * 100.0, 2),
        'avg_expected_rank': round(mean_or_zero(expected_rank_values), 3),
        'median_expected_rank': round(median_or_zero(expected_rank_values), 3),
        'avg_best_weighted_support_matched': round(mean_or_zero(best_weighted_support_correct), 3),
        'avg_best_weighted_support_mismatched': round(mean_or_zero(best_weighted_support_wrong), 3),
        'best_engine_counts': dict(sorted(best_engine_counts.items(), key=lambda item: (-item[1], item[0]))),
        'per_engine_summary': dict(sorted(per_engine_summary.items(), key=lambda item: item[0])),
    }

    return {
        'generated_at_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'manifest': str(manifest_path.resolve()),
        'summary': summary,
        'results': results,
    }


def build_calibration_from_results(base_calibration, results):
    calibration = copy.deepcopy(base_calibration)
    ensemble_weights = calibration.setdefault('ensemble_weights', {})
    ensemble = calibration.setdefault('ensemble', {})
    engine_profiles = calibration.setdefault('engine_profiles', {})
    base_defaults = ocr_reranking_calibration._default_ocr_reranking_calibration()
    base_weights = copy.deepcopy(base_calibration.get('ensemble_weights', base_defaults.get('ensemble_weights', {})))
    base_ensemble = base_calibration.get('ensemble', base_defaults.get('ensemble', {}))

    engine_stats = defaultdict(lambda: {
        'total': 0,
        'top_match': 0,
        'candidate_found': 0,
        'candidate_rank_values': [],
        'correct_weighted_support': [],
        'wrong_weighted_support': [],
    })
    expected_rank_values = []
    correct_supports = []
    wrong_supports = []
    pdf_supports = []
    pdf_correct_supports = []

    for item in results:
        expected = normalize_expected_text(item.get('expected_text', ''))
        matched = bool(item.get('matched'))
        if item.get('expected_in_top_candidates_rank') is not None:
            expected_rank_values.append(int(item.get('expected_in_top_candidates_rank') or 0))

        support_value = float(item.get('observed_best_weighted_support', 0.0) or 0.0)
        if matched:
            correct_supports.append(support_value)
        else:
            wrong_supports.append(support_value)
        if str(item.get('kind', '')).lower() == 'pdf':
            pdf_supports.append(support_value)
            if matched:
                pdf_correct_supports.append(support_value)

        for engine_name, meta in (item.get('engine_matches') or {}).items():
            if not isinstance(meta, dict):
                continue
            stats = engine_stats[str(engine_name)]
            stats['total'] += 1
            stats['top_match'] += int(bool(meta.get('top_match')))
            stats['candidate_found'] += int(bool(meta.get('candidate_found')))
            rank = meta.get('candidate_rank')
            if rank is not None:
                stats['candidate_rank_values'].append(int(rank))
            if bool(meta.get('top_match')):
                stats['correct_weighted_support'].append(float(item.get('observed_best_weighted_support', 0.0) or 0.0))
            else:
                stats['wrong_weighted_support'].append(float(item.get('observed_best_weighted_support', 0.0) or 0.0))

    def mean_or_zero(values):
        return float(mean(values)) if values else 0.0

    def default_value(value, fallback):
        try:
            return float(value)
        except Exception:
            return float(fallback)

    correct_support_floor = percentile(correct_supports, 20) if correct_supports else 0.0
    wrong_support_ceiling = percentile(wrong_supports, 80) if wrong_supports else 0.0

    for engine_name, stats in engine_stats.items():
        total = max(1, int(stats['total']))
        top_match_rate = float(stats['top_match']) / float(total)
        candidate_recall = float(stats['candidate_found']) / float(total)
        rank_score = 1.0
        if stats['candidate_rank_values']:
            rank_score = clamp(1.2 / max(1.0, mean_or_zero(stats['candidate_rank_values'])), 0.2, 1.0)
        quality = (top_match_rate * 0.60) + (candidate_recall * 0.25) + (rank_score * 0.15)
        delta = clamp((quality - 0.55) * 0.28, -0.10, 0.10)
        base_weight = default_value(base_weights.get(engine_name, 1.0), 1.0)
        ensemble_weights[engine_name] = round(clamp(base_weight + delta, 0.55, 1.35), 3)

        runtime_profile = {
            key: value
            for key, value in copy.deepcopy(ocr_agent.get_engine_weight_profile(engine_name)).items()
            if not callable(value)
        }
        profile = dict(engine_profiles.get(engine_name, {}))
        for key, value in runtime_profile.items():
            profile.setdefault(key, value)

        default_factor_min = default_value(profile.get('factor_min', runtime_profile.get('factor_min', 0.18)), 0.18)
        default_factor_max = default_value(profile.get('factor_max', runtime_profile.get('factor_max', 1.0)), 1.0)
        if top_match_rate >= 0.75:
            profile['factor_min'] = round(clamp(default_factor_min + 0.01, 0.05, 1.0), 3)
            profile['factor_max'] = round(clamp(default_factor_max + 0.03, default_factor_min + 0.02, 1.2), 3)
        elif top_match_rate <= 0.45:
            profile['factor_min'] = round(clamp(default_factor_min - 0.01, 0.05, default_factor_min), 3)
            profile['factor_max'] = round(clamp(default_factor_max - 0.04, default_factor_min + 0.02, 1.2), 3)
        else:
            profile['factor_min'] = round(default_factor_min, 3)
            profile['factor_max'] = round(default_factor_max, 3)

        engine_profiles[engine_name] = profile

    rank_decay_step = default_value(base_ensemble.get('rank_decay_step', 0.22), 0.22)
    if expected_rank_values:
        mean_rank = mean_or_zero(expected_rank_values)
        rank_decay_step = clamp(rank_decay_step + ((1.15 - mean_rank) * 0.015), 0.16, 0.28)

    support_bonus_per_engine = default_value(base_ensemble.get('support_bonus_per_engine', 1.35), 1.35)
    if correct_supports or wrong_supports:
        support_bonus_per_engine = clamp(
            support_bonus_per_engine + ((mean_or_zero(correct_supports) - mean_or_zero(wrong_supports)) * 0.12),
            1.05,
            1.75,
        )

    single_engine_min_weighted_support = default_value(base_ensemble.get('single_engine_min_weighted_support', 6.4), 6.4)
    if correct_supports and wrong_supports:
        single_engine_min_weighted_support = max(
            single_engine_min_weighted_support,
            clamp(wrong_support_ceiling + 0.25, 5.8, 8.5),
            clamp(correct_support_floor - 0.15, 5.8, 8.5),
        )
    elif wrong_supports:
        single_engine_min_weighted_support = max(
            single_engine_min_weighted_support,
            clamp(percentile(wrong_supports, 80) + 0.25, 5.8, 8.5),
        )
    elif correct_supports:
        single_engine_min_weighted_support = max(
            single_engine_min_weighted_support,
            clamp(correct_support_floor - 0.15, 5.8, 8.5),
        )

    pdf_probable_min_weighted_support = default_value(base_ensemble.get('pdf_probable_min_weighted_support', 6.6), 6.6)
    if pdf_supports:
        pdf_probable_min_weighted_support = max(
            pdf_probable_min_weighted_support,
            clamp(percentile(pdf_supports, 75) + 0.15, 5.8, 8.5),
        )

    ensemble.update({
        'rank_decay_step': round(rank_decay_step, 3),
        'min_rank_decay': round(default_value(base_ensemble.get('min_rank_decay', 0.25), 0.25), 3),
        'pattern_bonus': round(default_value(base_ensemble.get('pattern_bonus', 0.90), 0.90), 3),
        'pattern_penalty': round(default_value(base_ensemble.get('pattern_penalty', -0.60), -0.60), 3),
        'length_bonus': round(default_value(base_ensemble.get('length_bonus', 0.95), 0.95), 3),
        'length_penalty': round(default_value(base_ensemble.get('length_penalty', -0.25), -0.25), 3),
        'score_divisor': round(default_value(base_ensemble.get('score_divisor', 85.0), 85.0), 3),
        'score_component_cap': round(default_value(base_ensemble.get('score_component_cap', 2.0), 2.0), 3),
        'conf_divisor': round(default_value(base_ensemble.get('conf_divisor', 100.0), 100.0), 3),
        'conf_component_cap': round(default_value(base_ensemble.get('conf_component_cap', 1.2), 1.2), 3),
        'support_bonus_per_engine': round(support_bonus_per_engine, 3),
        'support_bonus_cap': round(default_value(base_ensemble.get('support_bonus_cap', 4.05), 4.05), 3),
        'consensus_min_support': int(default_value(base_ensemble.get('consensus_min_support', 2), 2)),
        'required_length': int(default_value(base_ensemble.get('required_length', 7), 7)),
        'single_engine_min_weighted_support': round(single_engine_min_weighted_support, 3),
        'single_engine_min_confidence': round(default_value(base_ensemble.get('single_engine_min_confidence', 75.0), 75.0), 3),
        'single_engine_fallback_divisor': round(default_value(base_ensemble.get('single_engine_fallback_divisor', 18.0), 18.0), 3),
        'pdf_probable_min_score': round(default_value(base_ensemble.get('pdf_probable_min_score', 96.0), 96.0), 3),
        'pdf_probable_min_confidence': round(default_value(base_ensemble.get('pdf_probable_min_confidence', 62.0), 62.0), 3),
        'pdf_probable_min_weighted_support': round(pdf_probable_min_weighted_support, 3),
        'pdf_probable_min_support_count': int(default_value(base_ensemble.get('pdf_probable_min_support_count', 2), 2)),
        'pdf_probable_required_length': int(default_value(base_ensemble.get('pdf_probable_required_length', 7), 7)),
    })

    calibration['ensemble_weights'] = dict(sorted(ensemble_weights.items(), key=lambda item: item[0]))
    calibration['ensemble'] = ensemble
    calibration['engine_profiles'] = dict(sorted(engine_profiles.items(), key=lambda item: item[0]))
    calibration['generated_from_benchmark'] = True
    calibration['benchmark_summary'] = {
        'total': int(len(results)),
        'matched': int(sum(1 for item in results if item.get('matched'))),
        'accuracy_percent': round((float(sum(1 for item in results if item.get('matched'))) / float(max(1, len(results)))) * 100.0, 2),
        'avg_expected_rank': round(mean_or_zero(expected_rank_values), 3),
        'avg_best_weighted_support_matched': round(mean_or_zero(correct_supports), 3),
        'avg_best_weighted_support_mismatched': round(mean_or_zero(wrong_supports), 3),
        'per_engine_summary': {
            engine_name: {
                'total': int(stats['total']),
                'top_match': int(stats['top_match']),
                'candidate_found': int(stats['candidate_found']),
                'top_match_rate_percent': round((float(stats['top_match']) / float(max(1, int(stats['total'])))) * 100.0, 2),
                'candidate_recall_rate_percent': round((float(stats['candidate_found']) / float(max(1, int(stats['total'])))) * 100.0, 2),
                'mean_candidate_rank': round(mean_or_zero(stats['candidate_rank_values']), 3),
            }
            for engine_name, stats in sorted(engine_stats.items(), key=lambda item: item[0])
        },
    }
    return calibration


def main():
    parser = argparse.ArgumentParser(description='Benchmark do re-ranking OCR do Grom OCR.')
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST, help='Caminho do manifesto JSON/JSONL.')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT, help='Arquivo JSON com o resultado consolidado.')
    parser.add_argument('--api-url', type=str, default='', help='URL base de uma API em execucao, ex.: http://127.0.0.1:5000')
    parser.add_argument('--direct', action='store_true', help='Executa OCR direto no processo atual, sem chamar /process.')
    parser.add_argument('--engines', type=str, default='auto', help='Lista de motores para o modo direto, separada por virgula.')
    parser.add_argument('--export-calibration', type=Path, default=DEFAULT_CALIBRATION_OUTPUT, help='Gera um arquivo de calibracao sugerida.')
    parser.add_argument('--apply-calibration', action='store_true', help='Copia a calibracao gerada para o arquivo ativo.')
    args = parser.parse_args()

    api_url = args.api_url.strip() or None
    engine_names = parse_engine_names(args.engines)
    report = run_benchmark(args.manifest, api_url=api_url, direct=bool(args.direct), engine_names=engine_names)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)

    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))
    print(f'Resultado salvo em: {args.output}')

    if args.export_calibration:
        base_calibration = ocr_reranking_calibration.load_ocr_reranking_calibration()
        suggested = build_calibration_from_results(base_calibration, report['results'])
        args.export_calibration.parent.mkdir(parents=True, exist_ok=True)
        with args.export_calibration.open('w', encoding='utf-8') as handle:
            json.dump(suggested, handle, ensure_ascii=False, indent=2)
        print(f'Calibracao sugerida salva em: {args.export_calibration}')

        if args.apply_calibration:
            active_path = Path(ocr_reranking_calibration.OCR_RERANKING_CALIBRATION_PATH)
            active_path.parent.mkdir(parents=True, exist_ok=True)
            with active_path.open('w', encoding='utf-8') as handle:
                json.dump(suggested, handle, ensure_ascii=False, indent=2)
            print(f'Calibracao aplicada em: {active_path}')


if __name__ == '__main__':
    main()
