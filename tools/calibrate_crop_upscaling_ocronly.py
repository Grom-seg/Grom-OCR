#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi_backend.main import _upscale_crop_for_ocr  # noqa: E402
from fastapi_backend.ocr_module import run_ocr  # noqa: E402

DEFAULT_OUTPUT = PROJECT_ROOT / 'data' / 'upscale_calibration_report.json'
DEFAULT_MANIFEST = PROJECT_ROOT / 'data' / 'ocr_reranking_benchmark_manifest_crops_real.json'

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


def classify_environment(image_path: Path, difficulty: str) -> str:
    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if img is None:
        return 'desconhecido'
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mean_luma = float(gray.mean())
    contrast = float(gray.std())
    if (difficulty or '').lower() in {'hard', 'critical'} and mean_luma < 130:
        return 'fechado'
    if mean_luma >= 120 and contrast >= 40:
        return 'aberto'
    return 'fechado'


def score_case(expected: str, observed: str, confidence: float) -> Dict[str, float]:
    exp = normalize_plate(expected)
    obs = normalize_plate(observed)
    exact = 1.0 if (exp and exp == obs) else 0.0
    similarity = SequenceMatcher(None, exp, obs).ratio() if exp else 0.0
    pattern = plate_pattern_score(obs)
    final = (0.65 * exact) + (0.2 * similarity) + (0.1 * confidence) + (0.05 * pattern)
    return {
        'exact': exact,
        'similarity': similarity,
        'pattern': pattern,
        'final': final,
    }


def resolve_image(path_text: str) -> Path:
    p = Path(path_text)
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
    return p


def make_configs() -> List[UpscaleConfig]:
    return [
        UpscaleConfig('baseline_sem_upscale', 0, 1.0, 900),
        UpscaleConfig('light_240_1.8_900', 240, 1.8, 900),
        UpscaleConfig('balanced_320_2.5_1400', 320, 2.5, 1400),
        UpscaleConfig('balanced_360_2.8_1500', 360, 2.8, 1500),
        UpscaleConfig('aggressive_420_3.4_1800', 420, 3.4, 1800),
    ]


def pick_best_ocr_row(rows: List[dict]) -> tuple[str, float]:
    best_text = ''
    best_conf = 0.0
    for row in rows or []:
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


def aggregate(rows: List[dict]) -> dict:
    if not rows:
        return {
            'count': 0,
            'exact_rate': 0.0,
            'avg_similarity': 0.0,
            'avg_confidence': 0.0,
            'avg_score': 0.0,
        }
    exacts = [float(r['score']['exact']) for r in rows]
    sims = [float(r['score']['similarity']) for r in rows]
    confs = [float(r['confidence']) for r in rows]
    finals = [float(r['score']['final']) for r in rows]
    return {
        'count': len(rows),
        'exact_rate': round(sum(exacts) / len(exacts), 4),
        'avg_similarity': round(sum(sims) / len(sims), 4),
        'avg_confidence': round(sum(confs) / len(confs), 4),
        'avg_score': round(sum(finals) / len(finals), 4),
        'median_score': round(statistics.median(finals), 4),
    }


def run_config(cfg: UpscaleConfig, cases: List[dict]) -> dict:
    os.environ['GROM_OCR_CROP_UPSCALE_MIN_WIDTH'] = str(cfg.min_width)
    os.environ['GROM_OCR_CROP_UPSCALE_FACTOR'] = str(cfg.factor)
    os.environ['GROM_OCR_CROP_UPSCALE_MAX_WIDTH'] = str(cfg.max_width)

    rows = []
    for case in cases:
        image_ref = str(case.get('image', '')).strip()
        expected = normalize_plate(case.get('expected_text', ''))
        difficulty = str(case.get('difficulty', '')).strip().lower()
        img_path = resolve_image(image_ref)
        if not img_path.exists():
            continue

        environment = classify_environment(img_path, difficulty)

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=img_path.suffix) as tf:
                temp_path = tf.name
            shutil.copy2(img_path, temp_path)
            _upscale_crop_for_ocr(temp_path)
            ocr_rows = run_ocr(temp_path)
            observed, conf = pick_best_ocr_row(ocr_rows)
        except Exception:
            observed, conf = '', 0.0
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

        score = score_case(expected, observed, conf)
        rows.append({
            'image': image_ref,
            'difficulty': difficulty,
            'environment': environment,
            'expected': expected,
            'observed': observed,
            'confidence': conf,
            'score': score,
        })

    return {
        'config': {
            'name': cfg.name,
            'min_width': cfg.min_width,
            'factor': cfg.factor,
            'max_width': cfg.max_width,
        },
        'summary': {
            'all': aggregate(rows),
            'aberto': aggregate([r for r in rows if r.get('environment') == 'aberto']),
            'fechado': aggregate([r for r in rows if r.get('environment') == 'fechado']),
        },
        'rows': rows,
    }


def pick_best(results: List[dict], segment: str) -> dict:
    ranked = sorted(
        results,
        key=lambda r: (
            float(r['summary'][segment]['avg_score']),
            float(r['summary'][segment]['exact_rate']),
            float(r['summary'][segment]['avg_similarity']),
        ),
        reverse=True,
    )
    return ranked[0] if ranked else {}


def main() -> None:
    parser = argparse.ArgumentParser(description='Calibracao de upscaling de crop antes do OCR (modo OCR-only).')
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    cases = json.loads(args.manifest.read_text(encoding='utf-8'))
    if not isinstance(cases, list):
        raise ValueError('Manifesto deve ser lista JSON.')

    results = []
    for cfg in make_configs():
        print(f'[CAL] {cfg.name}')
        results.append(run_config(cfg, cases))

    best_all = pick_best(results, 'all')
    best_open = pick_best(results, 'aberto')
    best_closed = pick_best(results, 'fechado')

    report = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'methodology': {
            'reference': [
                'ALPR benchmark criteria: exact match + edit similarity + confidence',
                'CCPD-inspired robustness checks under degraded conditions',
            ],
            'note': 'CCPD usado como referencia de robustez, nao como base principal BR/Mercosul.',
        },
        'manifest': str(args.manifest),
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

    print('=== CALIBRACAO UPSCALING OCR-ONLY ===')
    print(f"Casos: {len(cases)}")
    print(f"Melhor geral   : {report['best']['all']}")
    print(f"Melhor aberto  : {report['best']['aberto']}")
    print(f"Melhor fechado : {report['best']['fechado']}")
    print(f"Saida          : {args.output}")


if __name__ == '__main__':
    main()
