#!/usr/bin/env python
from __future__ import annotations

import argparse
import io
import json
import os
import re
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Tuple

import cv2
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi_backend import main as backend_main

app = backend_main.app

DEFAULT_OUTPUT = PROJECT_ROOT / 'data' / 'upscale_calibration_report.json'
DEFAULT_MANIFESTS = [
    PROJECT_ROOT / 'data' / 'ocr_reranking_benchmark_manifest_crops_real.json',
    PROJECT_ROOT / 'data' / 'ocr_reranking_benchmark_manifest_core_real.json',
    PROJECT_ROOT / 'data' / 'ocr_reranking_benchmark_manifest_core_real_hard.json',
]

PLATE_OLD = re.compile(r'^[A-Z]{3}[0-9]{4}$')
PLATE_MERCOSUL = re.compile(r'^[A-Z]{3}[0-9][A-Z][0-9]{2}$')


@dataclass(frozen=True)
class UpscaleConfig:
    name: str
    min_width: int
    factor: float
    max_width: int


def normalize_plate(text: str) -> str:
    return ''.join(ch for ch in str(text or '').upper() if ch.isalnum())


def plate_pattern_score(text: str) -> float:
    txt = normalize_plate(text)
    if PLATE_OLD.fullmatch(txt) or PLATE_MERCOSUL.fullmatch(txt):
        return 1.0
    if len(txt) == 7:
        letters = sum(1 for c in txt if c.isalpha())
        digits = sum(1 for c in txt if c.isdigit())
        if letters >= 2 and digits >= 2:
            return 0.6
    return 0.0


def parse_confidence(payload: dict) -> float:
    cs = payload.get('confidence_score', {})
    if isinstance(cs, dict):
        val = float(cs.get('overall_confidence', 0.0) or 0.0)
    else:
        val = float(cs or 0.0)
    if val > 1.0:
        val /= 100.0
    return max(0.0, min(1.0, val))


def extract_best_text_from_full_pipeline(payload: dict) -> Tuple[str, float]:
    ocr_results = payload.get('ocr_results', [])
    if not isinstance(ocr_results, list):
        return '', 0.0

    best_text = ''
    best_conf = 0.0
    for block in ocr_results:
        if not isinstance(block, dict):
            continue
        rows = block.get('ocr', [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            txt = normalize_plate(row.get('text', ''))
            conf = float(row.get('confidence', row.get('avg_conf', 0.0)) or 0.0)
            if conf > 1.0:
                conf /= 100.0
            if txt and conf >= best_conf:
                best_conf = conf
                best_text = txt
    return best_text, max(0.0, min(1.0, best_conf))


def load_cases(manifests: List[Path]) -> List[dict]:
    seen = set()
    merged: List[dict] = []
    for manifest in manifests:
        if not manifest.exists():
            continue
        data = json.loads(manifest.read_text(encoding='utf-8'))
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, dict):
                continue
            rel_path = str(item.get('image', '')).strip()
            if not rel_path:
                continue
            if rel_path in seen:
                continue
            seen.add(rel_path)
            merged.append(item)
    return merged


def resolve_path(image_ref: str) -> Path:
    p = Path(image_ref)
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
    return p


def classify_environment(image_path: Path, difficulty: str) -> str:
    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if img is None:
        return 'desconhecido'
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mean_luma = float(gray.mean())
    contrast = float(gray.std())

    diff = (difficulty or '').lower()
    if diff in {'critical', 'hard'} and mean_luma < 125:
        return 'fechado'
    if mean_luma >= 120 and contrast >= 40:
        return 'aberto'
    return 'fechado'


def score_case(expected: str, observed: str, confidence: float) -> Dict[str, float]:
    exp = normalize_plate(expected)
    obs = normalize_plate(observed)
    exact = 1.0 if (exp and obs == exp) else 0.0
    similarity = SequenceMatcher(None, exp, obs).ratio() if exp else 0.0
    pattern = plate_pattern_score(obs)

    # Score inspirado em boas práticas ALPR robustas (similar ao uso de KPIs em CCPD):
    # prioriza acerto exato e mantém peso de similaridade/confiança para cenários degradados.
    final = (0.65 * exact) + (0.20 * similarity) + (0.10 * confidence) + (0.05 * pattern)
    return {
        'exact': exact,
        'similarity': similarity,
        'pattern': pattern,
        'final': final,
    }


def make_configs() -> List[UpscaleConfig]:
    return [
        UpscaleConfig('baseline_sem_upscale', 0, 1.0, 900),
        UpscaleConfig('light_240_1.8_900', 240, 1.8, 900),
        UpscaleConfig('balanced_320_2.5_1400', 320, 2.5, 1400),
        UpscaleConfig('balanced_360_2.4_1400', 360, 2.4, 1400),
        UpscaleConfig('balanced_360_2.8_1500', 360, 2.8, 1500),
        UpscaleConfig('aggressive_420_3.4_1800', 420, 3.4, 1800),
    ]


def run_config(client: TestClient, cfg: UpscaleConfig, cases: List[dict]) -> dict:
    os.environ['GROM_OCR_CROP_UPSCALE_MIN_WIDTH'] = str(cfg.min_width)
    os.environ['GROM_OCR_CROP_UPSCALE_FACTOR'] = str(cfg.factor)
    os.environ['GROM_OCR_CROP_UPSCALE_MAX_WIDTH'] = str(cfg.max_width)

    rows = []
    for case in cases:
        image_ref = str(case.get('image', '')).strip()
        expected = str(case.get('expected_text', '')).strip()
        difficulty = str(case.get('difficulty', '')).strip().lower()
        img_path = resolve_path(image_ref)
        if not img_path.exists():
            continue

        env = classify_environment(img_path, difficulty)
        with img_path.open('rb') as fh:
            response = client.post(
                '/full-pipeline/',
                files={'file': (img_path.name, fh, 'application/octet-stream')},
            )

        payload = {}
        try:
            payload = response.json()
        except Exception:
            payload = {}

        observed, conf = extract_best_text_from_full_pipeline(payload)
        if conf <= 0.0:
            conf = parse_confidence(payload)
        score = score_case(expected, observed, conf)

        rows.append({
            'image': image_ref,
            'difficulty': difficulty,
            'environment': env,
            'expected': normalize_plate(expected),
            'observed': normalize_plate(observed),
            'http_status': int(response.status_code),
            'confidence': conf,
            'score': score,
        })

    def aggregate(items: List[dict]) -> dict:
        if not items:
            return {
                'count': 0,
                'exact_rate': 0.0,
                'avg_similarity': 0.0,
                'avg_confidence': 0.0,
                'avg_score': 0.0,
            }
        exacts = [float(i['score']['exact']) for i in items]
        sims = [float(i['score']['similarity']) for i in items]
        confs = [float(i['confidence']) for i in items]
        finals = [float(i['score']['final']) for i in items]
        return {
            'count': len(items),
            'exact_rate': round(sum(exacts) / len(exacts), 4),
            'avg_similarity': round(sum(sims) / len(sims), 4),
            'avg_confidence': round(sum(confs) / len(confs), 4),
            'avg_score': round(sum(finals) / len(finals), 4),
            'median_score': round(statistics.median(finals), 4),
        }

    all_agg = aggregate(rows)
    open_agg = aggregate([r for r in rows if r.get('environment') == 'aberto'])
    closed_agg = aggregate([r for r in rows if r.get('environment') == 'fechado'])

    return {
        'config': {
            'name': cfg.name,
            'min_width': cfg.min_width,
            'factor': cfg.factor,
            'max_width': cfg.max_width,
        },
        'summary': {
            'all': all_agg,
            'aberto': open_agg,
            'fechado': closed_agg,
        },
        'rows': rows,
    }


def pick_best(results: List[dict], segment: str) -> dict:
    ordered = sorted(
        results,
        key=lambda r: (
            float(r['summary'][segment]['avg_score']),
            float(r['summary'][segment]['exact_rate']),
            float(r['summary'][segment]['avg_similarity']),
        ),
        reverse=True,
    )
    return ordered[0] if ordered else {}


def main() -> None:
    parser = argparse.ArgumentParser(description='Calibracao de upscaling de crops para OCR no /process (FastAPI).')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    cases = load_cases(DEFAULT_MANIFESTS)
    # Evita ruído e throttling na calibração de upscaling local.
    backend_main._PLATE_RECOGNIZER_AVAILABLE = False
    backend_main._EASYOCR_AVAILABLE = False
    client = TestClient(app)

    results = []
    for cfg in make_configs():
        print(f'[CAL] Testando {cfg.name}...')
        results.append(run_config(client, cfg, cases))

    best_all = pick_best(results, 'all')
    best_open = pick_best(results, 'aberto')
    best_closed = pick_best(results, 'fechado')

    report = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'methodology': {
            'reference': [
                'ALPR benchmark practices (exact match + edit similarity + confidence)',
                'CCPD-inspired robustness criteria for blur/low-light stress testing',
            ],
            'note': 'CCPD foi usado como referencia tecnica de robustez, nao como corpus principal BR/Mercosul.',
        },
        'cases_total': len(cases),
        'results': results,
        'best': {
            'all': best_all.get('config', {}),
            'aberto': best_open.get('config', {}),
            'fechado': best_closed.get('config', {}),
        },
        'best_summary': {
            'all': best_all.get('summary', {}).get('all', {}),
            'aberto': best_open.get('summary', {}).get('aberto', {}),
            'fechado': best_closed.get('summary', {}).get('fechado', {}),
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    print('=== CALIBRACAO DE UPSCALING (CROP OCR) ===')
    print(f"Casos avaliados: {len(cases)}")
    print(f"Melhor geral   : {report['best']['all']}")
    print(f"Melhor aberto  : {report['best']['aberto']}")
    print(f"Melhor fechado : {report['best']['fechado']}")
    print(f"Relatorio salvo: {args.output}")


if __name__ == '__main__':
    main()
