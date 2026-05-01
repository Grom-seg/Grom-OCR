#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = PROJECT_ROOT / 'data' / 'benchmark_catalog.json'
SUMMARY_PATH = PROJECT_ROOT / 'data' / 'benchmark_catalog_summary.json'

OUTPUTS = {
    'scene_preprocess': PROJECT_ROOT / 'data' / 'scene_preprocess_benchmark_manifest.json',
    'scene_preprocess_hard': PROJECT_ROOT / 'data' / 'scene_preprocess_benchmark_manifest_hard.json',
    'plate_detector': PROJECT_ROOT / 'data' / 'plate_detector_benchmark_manifest.json',
    'plate_detector_hard': PROJECT_ROOT / 'data' / 'plate_detector_benchmark_manifest_hard.json',
    'ocr_reranking': PROJECT_ROOT / 'data' / 'ocr_reranking_benchmark_manifest.json',
    'ocr_reranking_hard': PROJECT_ROOT / 'data' / 'ocr_reranking_benchmark_manifest_hard.json',
    'ocr_reranking_real': PROJECT_ROOT / 'data' / 'ocr_reranking_benchmark_manifest_real.json',
    'ocr_reranking_real_hard': PROJECT_ROOT / 'data' / 'ocr_reranking_benchmark_manifest_real_hard.json',
    'ocr_reranking_core_real': PROJECT_ROOT / 'data' / 'ocr_reranking_benchmark_manifest_core_real.json',
    'ocr_reranking_core_real_hard': PROJECT_ROOT / 'data' / 'ocr_reranking_benchmark_manifest_core_real_hard.json',
    'ocr_reranking_crops_real': PROJECT_ROOT / 'data' / 'ocr_reranking_benchmark_manifest_crops_real.json',
    'ocr_reranking_crops_real_hard': PROJECT_ROOT / 'data' / 'ocr_reranking_benchmark_manifest_crops_real_hard.json',
}

HARD_DIFFICULTIES = {'hard', 'critical'}
ALLOWED_TARGETS = {'scene_preprocess', 'plate_detector', 'ocr_reranking'}
CORE_REAL_IMAGES = {
    'data/uploads/20171119_154214_ch6-1024x576.jpg',
    'data/uploads/10458347_x216.jpg',
    'data/uploads/sddefault.jpg',
    'data/uploads/placa_20171119_154214_ch6-1024x576.jpg',
    'data/uploads/placa_10458347_x216.jpg',
    'data/uploads/placa_sddefault.jpg',
}


def normalize_targets(value):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    targets = []
    for item in value:
        text = str(item or '').strip()
        if text in ALLOWED_TARGETS:
            targets.append(text)
    return targets


def load_catalog(path: Path):
    catalog = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(catalog, list):
        raise ValueError('O catalogo precisa ser uma lista de entradas.')

    normalized = []
    for index, item in enumerate(catalog, start=1):
        if not isinstance(item, dict):
            raise ValueError(f'Entrada invalida no catalogo em #{index}.')
        image = str(item.get('image') or '').strip()
        kind = str(item.get('kind') or '').strip().lower()
        if not image:
            raise ValueError(f'Entrada #{index} sem image.')
        if kind not in {'scene', 'crop', 'pdf'}:
            raise ValueError(f'Entrada #{index} com kind invalido: {kind!r}')
        normalized.append({
            'image': image,
            'kind': kind,
            'expected_text': str(item.get('expected_text') or '').strip(),
            'difficulty': str(item.get('difficulty') or 'medium').strip().lower() or 'medium',
            'targets': normalize_targets(item.get('targets')),
            'notes': str(item.get('notes') or '').strip(),
        })
    return normalized


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def build_manifest(catalog, target, hard_only=False):
    entries = []
    seen = set()
    for item in catalog:
        if target not in item['targets']:
            continue
        if hard_only and item['difficulty'] not in HARD_DIFFICULTIES:
            continue
        if target in {'scene_preprocess', 'ocr_reranking'} and not item['expected_text']:
            continue
        if target == 'plate_detector' and item['kind'] == 'pdf':
            continue

        manifest_item = {
            'image': item['image'],
            'kind': item['kind'],
            'notes': item['notes'],
            'difficulty': item['difficulty'],
        }
        if item['expected_text']:
            manifest_item['expected_text'] = item['expected_text']

        key = (manifest_item['image'], manifest_item['kind'])
        if key in seen:
            continue
        seen.add(key)
        entries.append(manifest_item)
    return entries


def build_real_plate_manifest(catalog, hard_only=False):
    entries = []
    seen = set()
    for item in catalog:
        if 'ocr_reranking' not in item['targets']:
            continue
        if item['kind'] == 'pdf':
            continue
        if hard_only and item['difficulty'] not in HARD_DIFFICULTIES:
            continue
        if not item['expected_text']:
            continue
        manifest_item = {
            'image': item['image'],
            'kind': item['kind'],
            'notes': item['notes'],
            'difficulty': item['difficulty'],
            'expected_text': item['expected_text'],
        }
        key = (manifest_item['image'], manifest_item['kind'])
        if key in seen:
            continue
        seen.add(key)
        entries.append(manifest_item)
    return entries


def build_core_real_plate_manifest(catalog, hard_only=False):
    entries = []
    seen = set()
    for item in catalog:
        if item['image'] not in CORE_REAL_IMAGES:
            continue
        if 'ocr_reranking' not in item['targets']:
            continue
        if item['kind'] == 'pdf':
            continue
        if hard_only and item['difficulty'] not in HARD_DIFFICULTIES:
            continue
        if not item['expected_text']:
            continue
        manifest_item = {
            'image': item['image'],
            'kind': item['kind'],
            'notes': item['notes'],
            'difficulty': item['difficulty'],
            'expected_text': item['expected_text'],
        }
        key = (manifest_item['image'], manifest_item['kind'])
        if key in seen:
            continue
        seen.add(key)
        entries.append(manifest_item)
    return entries


def build_crop_real_plate_manifest(catalog, hard_only=False):
    entries = []
    seen = set()
    for item in catalog:
        if item['kind'] != 'crop':
            continue
        if 'ocr_reranking' not in item['targets']:
            continue
        if hard_only and item['difficulty'] not in HARD_DIFFICULTIES:
            continue
        if not item['expected_text']:
            continue
        manifest_item = {
            'image': item['image'],
            'kind': item['kind'],
            'notes': item['notes'],
            'difficulty': item['difficulty'],
            'expected_text': item['expected_text'],
        }
        key = (manifest_item['image'], manifest_item['kind'])
        if key in seen:
            continue
        seen.add(key)
        entries.append(manifest_item)
    return entries


def summarize(catalog, manifests):
    summary = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'catalog_path': str(CATALOG_PATH.resolve()),
        'total_catalog_items': len(catalog),
        'difficulty_counts': dict(sorted(Counter(item['difficulty'] for item in catalog).items())),
        'targets': {},
    }
    for name, entries in manifests.items():
        summary['targets'][name] = {
            'count': len(entries),
            'with_expected_text': sum(1 for item in entries if item.get('expected_text')),
            'pdf_count': sum(1 for item in entries if str(item.get('kind')) == 'pdf'),
            'difficulty_counts': dict(sorted(Counter(item.get('difficulty', 'medium') for item in entries).items())),
        }
    return summary


def main():
    parser = argparse.ArgumentParser(description='Gera manifests de benchmark a partir do catalogo mestre.')
    parser.add_argument('--catalog', default=str(CATALOG_PATH), help='Caminho do catalogo mestre JSON.')
    parser.add_argument('--summary', default=str(SUMMARY_PATH), help='Caminho do resumo gerado.')
    args = parser.parse_args()

    catalog_path = Path(args.catalog).resolve()
    catalog = load_catalog(catalog_path)

    manifests = {
        'scene_preprocess': build_manifest(catalog, 'scene_preprocess', hard_only=False),
        'scene_preprocess_hard': build_manifest(catalog, 'scene_preprocess', hard_only=True),
        'plate_detector': build_manifest(catalog, 'plate_detector', hard_only=False),
        'plate_detector_hard': build_manifest(catalog, 'plate_detector', hard_only=True),
        'ocr_reranking': build_manifest(catalog, 'ocr_reranking', hard_only=False),
        'ocr_reranking_hard': build_manifest(catalog, 'ocr_reranking', hard_only=True),
        'ocr_reranking_real': build_real_plate_manifest(catalog, hard_only=False),
        'ocr_reranking_real_hard': build_real_plate_manifest(catalog, hard_only=True),
        'ocr_reranking_core_real': build_core_real_plate_manifest(catalog, hard_only=False),
        'ocr_reranking_core_real_hard': build_core_real_plate_manifest(catalog, hard_only=True),
        'ocr_reranking_crops_real': build_crop_real_plate_manifest(catalog, hard_only=False),
        'ocr_reranking_crops_real_hard': build_crop_real_plate_manifest(catalog, hard_only=True),
    }

    for name, entries in manifests.items():
        write_json(OUTPUTS[name], entries)

    write_json(Path(args.summary).resolve(), summarize(catalog, manifests))
    print(f'Catalogo carregado: {catalog_path}')
    for name, entries in manifests.items():
        print(f'{name}: {len(entries)} entradas')
    print(f'Resumo salvo em: {Path(args.summary).resolve()}')


if __name__ == '__main__':
    main()
