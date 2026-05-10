#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

try:
    import requests
except Exception:  # pragma: no cover
    requests = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / 'data'
DEFAULT_MANIFEST = DATA_DIR / 'video_forensic_benchmark_manifest.json'
DEFAULT_OUTPUT_JSON = DATA_DIR / 'test_results' / 'video_forensic_benchmark_latest.json'
DEFAULT_OUTPUT_MD = DATA_DIR / 'test_results' / 'video_forensic_benchmark_latest.md'
DEFAULT_POLICY = DATA_DIR / 'judicial_threshold_policy.json'


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _normalize_plate(value: str) -> str:
    txt = ''.join(ch for ch in str(value or '').upper() if ch.isalnum())
    return txt.strip()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _write_markdown(path: Path, report: Dict[str, Any]) -> None:
    lines: List[str] = []
    lines.append('# Benchmark Formal de Video Pericial')
    lines.append('')
    lines.append(f"- Gerado em UTC: {report.get('generated_at_utc', '-')}")
    lines.append(f"- Casos executados: {report.get('summary', {}).get('executed_cases', 0)}")
    lines.append(f"- Casos aprovados: {report.get('summary', {}).get('passed_cases', 0)}")
    lines.append(f"- Precisao global: {report.get('summary', {}).get('global_precision', 0.0):.4f}")
    lines.append('')

    lines.append('## Precisao por classe de qualidade')
    lines.append('')
    for key, item in sorted((report.get('quality_metrics', {}) or {}).items()):
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- {key}: precision={item.get('precision', 0.0):.4f} "
            f"(meta={item.get('target_precision', 0.0):.4f}, n={item.get('total', 0)})"
        )
    lines.append('')

    lines.append('## Precisao por cenário')
    lines.append('')
    for key, item in sorted((report.get('scenario_metrics', {}) or {}).items()):
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- {key}: precision={item.get('precision', 0.0):.4f} "
            f"(meta={item.get('target_precision', 0.0):.4f}, n={item.get('total', 0)})"
        )
    lines.append('')

    lines.append('## Thresholds jurídicos recomendados')
    lines.append('')
    tr = report.get('recommended_judicial_thresholds', {})
    lines.append(f"- confidence_min: {tr.get('confidence_min', 0.75):.4f}")
    lines.append(f"- consensus_ratio_min: {tr.get('consensus_ratio_min', 50.0):.2f}")
    lines.append(f"- image_quality_min: {tr.get('image_quality_min', 0.60):.4f}")
    lines.append('')

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def _calc_precision(items: List[Dict[str, Any]]) -> float:
    if not items:
        return 0.0
    ok = sum(1 for x in items if bool(x.get('matched', False)))
    return ok / float(len(items))


def _percentile(values: List[float], q: float, fallback: float) -> float:
    if not values:
        return fallback
    ordered = sorted(values)
    idx = int(max(0, min(len(ordered) - 1, round((q / 100.0) * (len(ordered) - 1)))))
    return float(ordered[idx])


def _run_case(api_base: str, case: Dict[str, Any]) -> Dict[str, Any]:
    result = {
        'id': str(case.get('id', 'case')),
        'quality_class': str(case.get('quality_class', 'indefinida')),
        'scenarios': case.get('scenarios', []),
        'video_path': str(case.get('video_path', '')),
        'expected_plate': _normalize_plate(case.get('expected_plate', '')),
        'ok': False,
        'matched': False,
        'error': '',
    }

    video_path = (PROJECT_ROOT / result['video_path']).resolve()
    if not video_path.exists():
        result['error'] = 'video_not_found'
        return result

    if requests is None:
        result['error'] = 'requests_not_available'
        return result

    max_frames = int(case.get('max_frames_to_analyze', 12) or 12)
    sample_n = int(case.get('sample_every_n_frames', 5) or 5)

    url = f"{api_base.rstrip('/')}/process_video"
    try:
        with video_path.open('rb') as stream:
            files = {'video': (video_path.name, stream, 'video/mp4')}
            data = {
                'analysis_stage': str(case.get('analysis_stage', 'final')),
                'max_frames_to_analyze': str(max_frames),
                'sample_every_n_frames': str(sample_n),
            }
            resp = requests.post(url, files=files, data=data, timeout=180)
    except Exception as exc:
        result['error'] = f'request_failed:{exc}'
        return result

    if resp.status_code >= 400:
        result['error'] = f'http_{resp.status_code}'
        return result

    try:
        payload = resp.json()
    except Exception:
        result['error'] = 'invalid_json_response'
        return result

    if not isinstance(payload, dict):
        result['error'] = 'response_not_dict'
        return result

    best = payload.get('best', {}) if isinstance(payload.get('best'), dict) else {}
    confidence = payload.get('confidence_score', {}) if isinstance(payload.get('confidence_score'), dict) else {}
    consensus = payload.get('consensus', {}) if isinstance(payload.get('consensus'), dict) else {}
    image_quality = payload.get('image_quality', {}) if isinstance(payload.get('image_quality'), dict) else {}
    judicial = payload.get('judicial_readiness', {}) if isinstance(payload.get('judicial_readiness'), dict) else {}

    predicted = _normalize_plate(best.get('text', ''))
    expected = result['expected_plate']
    matched = bool(predicted and expected and predicted == expected)
    if expected == '':
        matched = (predicted == '')

    result.update({
        'ok': True,
        'matched': matched,
        'predicted_plate': predicted,
        'overall_confidence': _safe_float(confidence.get('overall_confidence', 0.0)),
        'consensus_ratio': _safe_float(consensus.get('agreement_ratio', 0.0)),
        'image_quality_score': _safe_float(image_quality.get('overall_quality_score', 0.0)),
        'judicial_status': str(judicial.get('status', 'indefinido') or 'indefinido'),
        'analysis_id': str((payload.get('forensic', {}) if isinstance(payload.get('forensic'), dict) else {}).get('analysis_id', '') or ''),
        'pdf_report': str(payload.get('pdf_report', '') or ''),
    })
    return result


def _build_group_metrics(case_results: List[Dict[str, Any]], targets: Dict[str, Any], key_name: str) -> Dict[str, Any]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in case_results:
        if not bool(row.get('ok')):
            continue
        keys = row.get(key_name, []) if key_name == 'scenarios' else [row.get(key_name, 'indefinida')]
        if not isinstance(keys, list):
            keys = [keys]
        for key in keys:
            k = str(key or 'indefinida')
            grouped.setdefault(k, []).append(row)

    metrics: Dict[str, Any] = {}
    for key, items in grouped.items():
        precision = _calc_precision(items)
        target = float((targets.get(key, {}) if isinstance(targets.get(key, {}), dict) else {}).get('min_precision', 0.0))
        metrics[key] = {
            'total': len(items),
            'matched': sum(1 for x in items if bool(x.get('matched'))),
            'precision': round(precision, 6),
            'target_precision': target,
            'passed': precision >= target,
        }

    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description='Benchmark formal de video pericial e calibracao da matriz juridica.')
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--api-base', default='')
    parser.add_argument('--output-json', type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument('--output-md', type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument('--policy-out', type=Path, default=DEFAULT_POLICY)
    parser.add_argument('--calibrate-write', action='store_true')
    args = parser.parse_args()

    manifest = _load_json(args.manifest.resolve())
    if not manifest:
        print(json.dumps({'error': 'manifest_not_found_or_invalid', 'manifest': str(args.manifest)}, ensure_ascii=False))
        return 2

    api_base = str(args.api_base or manifest.get('api_base') or 'http://127.0.0.1:8000')
    cases = manifest.get('cases', []) if isinstance(manifest.get('cases'), list) else []

    case_results = [_run_case(api_base, case if isinstance(case, dict) else {}) for case in cases]
    executed = [c for c in case_results if c.get('ok')]
    passed_cases = [c for c in executed if c.get('matched')]

    quality_targets = manifest.get('quality_targets', {}) if isinstance(manifest.get('quality_targets'), dict) else {}
    scenario_targets = manifest.get('scenario_targets', {}) if isinstance(manifest.get('scenario_targets'), dict) else {}

    quality_metrics = _build_group_metrics(case_results, quality_targets, 'quality_class')
    scenario_metrics = _build_group_metrics(case_results, scenario_targets, 'scenarios')

    confidence_tp = [float(c.get('overall_confidence', 0.0) or 0.0) for c in passed_cases]
    consensus_tp = [float(c.get('consensus_ratio', 0.0) or 0.0) for c in passed_cases]
    quality_tp = [float(c.get('image_quality_score', 0.0) or 0.0) for c in passed_cases]

    recommended_thresholds = {
        'confidence_min': round(max(0.55, _percentile(confidence_tp, 10.0, 0.75)), 4),
        'consensus_ratio_min': round(max(35.0, _percentile(consensus_tp, 10.0, 50.0)), 2),
        'image_quality_min': round(max(0.45, _percentile(quality_tp, 10.0, 0.60)), 4),
    }

    global_precision = _calc_precision(executed)
    all_quality_passed = all(bool(v.get('passed')) for v in quality_metrics.values()) if quality_metrics else False
    all_scenario_passed = all(bool(v.get('passed')) for v in scenario_metrics.values()) if scenario_metrics else False

    report = {
        'generated_at_utc': _utc_now(),
        'manifest': str(args.manifest.resolve()),
        'api_base': api_base,
        'summary': {
            'total_cases': len(case_results),
            'executed_cases': len(executed),
            'passed_cases': len(passed_cases),
            'skipped_cases': len([c for c in case_results if not c.get('ok')]),
            'global_precision': round(global_precision, 6),
            'all_quality_targets_passed': all_quality_passed,
            'all_scenario_targets_passed': all_scenario_passed,
        },
        'quality_metrics': quality_metrics,
        'scenario_metrics': scenario_metrics,
        'recommended_judicial_thresholds': recommended_thresholds,
        'cases': case_results,
    }

    _write_json(args.output_json.resolve(), report)
    _write_markdown(args.output_md.resolve(), report)

    if args.calibrate_write:
        policy_payload = {
            'updated_at_utc': _utc_now(),
            'source': 'video_forensic_benchmark_calibration',
            'manifest': str(args.manifest.resolve()),
            'thresholds': recommended_thresholds,
            'notes': [
                'Gerado automaticamente por benchmark formal de vídeo por cenários.',
                'Revisar periodicamente após entrada de novos casos reais.',
            ],
        }
        _write_json(args.policy_out.resolve(), policy_payload)

    print(json.dumps({
        'summary': report['summary'],
        'output_json': str(args.output_json.resolve()),
        'output_md': str(args.output_md.resolve()),
        'policy_out': str(args.policy_out.resolve()) if args.calibrate_write else '',
    }, ensure_ascii=False))

    return 0 if (all_quality_passed and all_scenario_passed and len(executed) > 0) else 1


if __name__ == '__main__':
    raise SystemExit(main())
