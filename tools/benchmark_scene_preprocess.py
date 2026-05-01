#!/usr/bin/env python
from __future__ import annotations

import argparse
import copy
import io
import json
import mimetypes
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = PROJECT_ROOT / 'python'
TESSERACT_CMD = PROJECT_ROOT / 'tools' / 'tesseract-portable' / 'tesseract.exe'
TESSDATA_DIR = PROJECT_ROOT / 'tools' / 'tesseract-portable' / 'tessdata'
os.environ.setdefault('GROM_OCR_TESSERACT_CMD', str(TESSERACT_CMD))
os.environ.setdefault('TESSDATA_PREFIX', str(TESSDATA_DIR))
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

import ocr_agent  # noqa: E402
from utils import scene_preprocess  # noqa: E402


DEFAULT_MANIFEST = PROJECT_ROOT / 'data' / 'scene_preprocess_benchmark_manifest.json'
DEFAULT_OUTPUT = PROJECT_ROOT / 'data' / 'scene_preprocess_benchmark_results.json'
DEFAULT_CALIBRATION_OUTPUT = PROJECT_ROOT / 'data' / 'scene_preprocess_calibration.generated.json'


def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


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


def normalize_expected_text(value):
    text = ocr_agent.normalize_plate_text(value)
    return text or ''


def extract_scene_preprocess(payload):
    scene = payload.get('scene_preprocess')
    if not isinstance(scene, dict):
        input_meta = payload.get('input_meta', {})
        if isinstance(input_meta, dict):
            scene = input_meta.get('scene_preprocess', {})
    if not isinstance(scene, dict):
        scene = {}
    return scene


def extract_best_text(payload, route):
    if route == '/process_simple':
        candidate = payload.get('ocr', '')
        if candidate:
            return normalize_expected_text(candidate)
        return ''

    best = payload.get('best', {})
    if isinstance(best, dict):
        candidate = best.get('text', '')
        if candidate:
            return normalize_expected_text(candidate)

    ocr_block = payload.get('ocr', {})
    if isinstance(ocr_block, dict):
        tesseract_text = ((ocr_block.get('tesseract') or {}).get('text', '') if isinstance(ocr_block.get('tesseract'), dict) else '')
        if tesseract_text:
            return normalize_expected_text(tesseract_text)

    return ''


def extract_confidence(payload, route):
    if route == '/process_simple':
        return float(payload.get('conf_avg', 0.0) or 0.0)
    best = payload.get('best', {})
    if isinstance(best, dict):
        return float(best.get('avg_conf', 0.0) or 0.0)
    return float(payload.get('conf_avg', 0.0) or 0.0)


def post_local(route, image_path):
    client = ocr_agent.app.test_client()
    payload = image_path.read_bytes()
    data = {
        'image': (io.BytesIO(payload), image_path.name, mimetypes.guess_type(image_path.name)[0] or 'application/octet-stream'),
    }
    response = client.post(route, data=data, content_type='multipart/form-data')
    try:
        body = response.get_json(silent=True) or {}
    except Exception:
        body = {}
    return response.status_code, body


def post_remote(api_url, route, image_path):
    url = api_url.rstrip('/') + route
    with image_path.open('rb') as handle:
        files = {'image': (image_path.name, handle, mimetypes.guess_type(image_path.name)[0] or 'application/octet-stream')}
        response = requests.post(url, files=files, timeout=600)
    try:
        body = response.json()
    except Exception:
        body = {'error': response.text[:500]}
    return response.status_code, body


def prefix_candidates_from_calibration(calibration):
    prefixes = set()
    profiles = calibration.get('profiles', {})
    if not isinstance(profiles, dict):
        return prefixes
    for profile in profiles.values():
        if not isinstance(profile, dict):
            continue
        variant_prefix_bonus = profile.get('variant_prefix_bonus', {})
        if not isinstance(variant_prefix_bonus, dict):
            continue
        for prefix in variant_prefix_bonus.keys():
            prefix_text = str(prefix or '').strip().lower()
            if prefix_text:
                prefixes.add(prefix_text)
    return sorted(prefixes, key=len, reverse=True)


def matched_prefix(variant_name, prefix_pool):
    name = str(variant_name or '').strip().lower()
    for prefix in prefix_pool:
        if name.startswith(prefix):
            return prefix
    if '_' in name:
        return name.split('_', 1)[0]
    return name


def build_calibration_from_results(base_calibration, results):
    calibration = copy.deepcopy(base_calibration)
    profiles = calibration.setdefault('profiles', {})
    prefix_pool = prefix_candidates_from_calibration(calibration)

    scenario_stats = defaultdict(lambda: {
        'total': 0,
        'correct': 0,
        'families': defaultdict(lambda: {'total': 0, 'correct': 0}),
        'prefixes': defaultdict(lambda: {'total': 0, 'correct': 0}),
    })

    for item in results:
        scenario = str(item.get('scenario_primary') or item.get('scenario_label') or 'balanced')
        expected = str(item.get('expected_text') or '')
        observed = str(item.get('observed_text') or '')
        correct = bool(expected) and expected == observed
        family = str(item.get('selected_family') or 'opencv').lower()
        prefix = matched_prefix(item.get('selected_variant'), prefix_pool)

        stats = scenario_stats[scenario]
        stats['total'] += 1
        stats['correct'] += int(correct)
        stats['families'][family]['total'] += 1
        stats['families'][family]['correct'] += int(correct)
        stats['prefixes'][prefix]['total'] += 1
        stats['prefixes'][prefix]['correct'] += int(correct)

    for scenario, stats in scenario_stats.items():
        profile = profiles.get(scenario, {})
        if not isinstance(profile, dict):
            profile = {}

        original_margin = float(profile.get('original_margin', 0.75))
        total = max(1, int(stats['total']))
        correct_rate = float(stats['correct']) / float(total)
        if correct_rate < 0.8:
            original_margin = clamp(original_margin - ((0.8 - correct_rate) * 0.45), 0.2, 1.0)
        elif correct_rate > 0.92:
            original_margin = clamp(original_margin + ((correct_rate - 0.92) * 0.15), 0.25, 1.0)
        profile['original_margin'] = round(original_margin, 3)

        variant_prefix_bonus = profile.get('variant_prefix_bonus', {})
        if not isinstance(variant_prefix_bonus, dict):
            variant_prefix_bonus = {}
        for prefix, prefix_stats in stats['prefixes'].items():
            prefix_total = max(1, int(prefix_stats['total']))
            prefix_correct_rate = float(prefix_stats['correct']) / float(prefix_total)
            delta = (prefix_correct_rate - 0.5) * 1.8
            current = float(variant_prefix_bonus.get(prefix, 0.0))
            variant_prefix_bonus[prefix] = round(clamp(current + delta, -2.0, 5.0), 3)
        profile['variant_prefix_bonus'] = variant_prefix_bonus

        family_bonus = profile.get('family_bonus', {})
        if not isinstance(family_bonus, dict):
            family_bonus = {}
        for family, family_stats in stats['families'].items():
            family_total = max(1, int(family_stats['total']))
            family_correct_rate = float(family_stats['correct']) / float(family_total)
            delta = (family_correct_rate - correct_rate) * 1.1
            current = float(family_bonus.get(family, family_bonus.get('default', 0.0)) or 0.0)
            family_bonus[family] = round(clamp(current + delta, -1.5, 2.5), 3)
        profile['family_bonus'] = family_bonus

        profiles[scenario] = profile

    calibration['profiles'] = profiles
    calibration['generated_from_benchmark'] = True
    calibration['benchmark_summary'] = {
        'scenarios': {
            scenario: {
                'total': int(stats['total']),
                'correct': int(stats['correct']),
                'accuracy_percent': round((float(stats['correct']) / float(max(1, stats['total']))) * 100.0, 2),
            }
            for scenario, stats in scenario_stats.items()
        }
    }
    return calibration


def run_benchmark(manifest_path, route, api_url=None):
    entries = load_manifest(manifest_path)
    if not entries:
        raise ValueError('O manifesto nao possui entradas.')

    results = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        image_path = resolve_image_path(entry)
        if not image_path.exists():
            raise FileNotFoundError(f'Imagem nao encontrada: {image_path}')

        if api_url:
            status_code, payload = post_remote(api_url, route, image_path)
        else:
            status_code, payload = post_local(route, image_path)

        scene_preprocess = extract_scene_preprocess(payload)
        scene_profile = scene_preprocess.get('scene_profile', {}) if isinstance(scene_preprocess, dict) else {}
        if not isinstance(scene_profile, dict):
            scene_profile = {}

        expected_text = normalize_expected_text(entry.get('expected_text', ''))
        observed_text = extract_best_text(payload, route)
        matched = bool(expected_text) and expected_text == observed_text

        results.append({
            'index': index,
            'image': str(image_path),
            'expected_text': expected_text,
            'observed_text': observed_text,
            'matched': matched,
            'status_code': status_code,
            'confidence': round(extract_confidence(payload, route), 2),
            'scene_label': str(scene_preprocess.get('scenario_label') or scene_profile.get('label') or 'balanced'),
            'scenario_primary': str(scene_preprocess.get('scenario_primary') or scene_profile.get('primary') or 'balanced'),
            'scenario_tags': scene_preprocess.get('scenario_tags', scene_profile.get('tags', [])),
            'scenario_reasons': scene_preprocess.get('scenario_reasons', scene_profile.get('reasons', [])),
            'selected_variant': str(scene_preprocess.get('selected_variant', 'original')),
            'selected_family': str(scene_preprocess.get('selected_family', 'opencv')),
            'selection_reason': str(scene_preprocess.get('selection_reason', 'n/a')),
            'original_margin': float(scene_preprocess.get('original_margin', 0.0) or 0.0),
            'quality_before': scene_preprocess.get('quality_before', {}),
            'quality_after': scene_preprocess.get('quality_after', {}),
            'improvement': float(scene_preprocess.get('improvement', 0.0) or 0.0),
            'candidate_count': int(scene_preprocess.get('candidate_count', 0) or 0),
            'route': route,
            'notes': entry.get('notes', ''),
        })

    total = len(results)
    matched_count = sum(1 for item in results if item['matched'])
    avg_confidence = sum(float(item.get('confidence', 0.0)) for item in results) / float(max(1, total))
    avg_improvement = sum(float(item.get('improvement', 0.0)) for item in results) / float(max(1, total))

    scenario_summary = defaultdict(lambda: {'total': 0, 'correct': 0, 'avg_confidence': 0.0, 'selected_variants': defaultdict(int)})
    for item in results:
        scenario = str(item.get('scenario_primary') or item.get('scene_label') or 'balanced')
        bucket = scenario_summary[scenario]
        bucket['total'] += 1
        bucket['correct'] += int(bool(item.get('matched')))
        bucket['avg_confidence'] += float(item.get('confidence', 0.0))
        bucket['selected_variants'][str(item.get('selected_variant') or 'original')] += 1

    summary = {
        'total': total,
        'matched': matched_count,
        'accuracy_percent': round((float(matched_count) / float(max(1, total))) * 100.0, 2),
        'avg_confidence': round(avg_confidence, 2),
        'avg_improvement': round(avg_improvement, 2),
        'route': route,
        'scenario_summary': {
            scenario: {
                'total': int(bucket['total']),
                'correct': int(bucket['correct']),
                'accuracy_percent': round((float(bucket['correct']) / float(max(1, bucket['total']))) * 100.0, 2),
                'avg_confidence': round(float(bucket['avg_confidence']) / float(max(1, bucket['total'])), 2),
                'selected_variants': dict(sorted(bucket['selected_variants'].items(), key=lambda item: (-item[1], item[0]))),
            }
            for scenario, bucket in scenario_summary.items()
        },
    }

    return {
        'generated_at_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'manifest': str(manifest_path.resolve()),
        'summary': summary,
        'results': results,
    }


def main():
    parser = argparse.ArgumentParser(description='Benchmark do pre-processamento de cenas para o Grom OCR.')
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST, help='Caminho do manifesto JSON/JSONL.')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT, help='Arquivo JSON com o resultado consolidado.')
    parser.add_argument('--route', choices=['/process', '/process_simple'], default='/process', help='Endpoint a ser benchmarkado.')
    parser.add_argument('--api-url', type=str, default='', help='URL base de uma API em execucao, ex.: http://127.0.0.1:5000')
    parser.add_argument('--export-calibration', type=Path, default=DEFAULT_CALIBRATION_OUTPUT, help='Gera um arquivo de calibracao sugerida.')
    args = parser.parse_args()

    api_url = args.api_url.strip() or None
    report = run_benchmark(args.manifest, args.route, api_url=api_url)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)

    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))
    print(f'Resultado salvo em: {args.output}')

    if args.export_calibration:
        base_calibration = scene_preprocess.load_scene_preprocess_calibration()
        suggested = build_calibration_from_results(base_calibration, report['results'])
        args.export_calibration.parent.mkdir(parents=True, exist_ok=True)
        with args.export_calibration.open('w', encoding='utf-8') as handle:
            json.dump(suggested, handle, ensure_ascii=False, indent=2)
        print(f'Calibracao sugerida salva em: {args.export_calibration}')


if __name__ == '__main__':
    main()
