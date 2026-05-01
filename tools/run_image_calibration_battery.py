import argparse
import io
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'python'))

import ocr_agent  # noqa: E402


DEFAULT_CASES_PATH = os.path.join(PROJECT_ROOT, 'data', 'calibration', 'image_canonical_cases.json')
DEFAULT_OUTPUT_PATH = os.path.join(PROJECT_ROOT, 'data', 'test_results', 'image_calibration_battery_current.json')


def load_cases(path):
    with open(path, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError('image battery cases must be a list')
    return data


def load_json_payload(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def load_policy(path):
    if not path:
        return {}
    loaded = load_json_payload(path)
    return loaded if isinstance(loaded, dict) else {}


def normalize_text(value):
    return ''.join(ch for ch in str(value or '').upper() if ch.isalnum())


def run_case(client, case):
    path = str(case.get('path', '') or '').strip()
    if not path or not os.path.exists(path):
        return {
            'file': str(case.get('file', '') or os.path.basename(path) or 'indefinido'),
            'path': path,
            'error': 'arquivo_nao_encontrado',
            'matched': False,
        }

    started = time.perf_counter()
    with open(path, 'rb') as fh:
        response = client.post(
            '/process_simple',
            data={
                'analysis_mode': 'video_frame',
                'image': (io.BytesIO(fh.read()), os.path.basename(path)),
            },
            content_type='multipart/form-data',
        )
    elapsed = round(time.perf_counter() - started, 2)
    payload = response.get_json() or {}
    operational = payload.get('operational_protocol') or {}
    conclusion = operational.get('conclusion') or {}

    expected_text = normalize_text(case.get('expected_text', ''))
    actual_text = normalize_text(payload.get('ocr', ''))
    expected_pattern = str(case.get('expected_pattern', 'Indefinido') or 'Indefinido')
    actual_pattern = str(payload.get('pattern', 'Indefinido') or 'Indefinido')
    expected_status = str(case.get('expected_status', 'INCONCLUSIVO') or 'INCONCLUSIVO')
    actual_status = str(payload.get('status', 'INCONCLUSIVO') or 'INCONCLUSIVO')

    return {
        'file': str(case.get('file', '') or os.path.basename(path)),
        'path': path,
        'case_kind': str(case.get('case_kind', '') or ''),
        'notes': str(case.get('notes', '') or ''),
        'http_status': int(response.status_code),
        'elapsed_seconds': elapsed,
        'expected_text': expected_text,
        'actual_text': actual_text,
        'expected_pattern': expected_pattern,
        'actual_pattern': actual_pattern,
        'expected_status': expected_status,
        'actual_status': actual_status,
        'confidence': float(payload.get('confidence', 0.0) or 0.0),
        'score': float(payload.get('score', 0.0) or 0.0),
        'support_count': int(payload.get('support_count', 0) or 0),
        'support_rank': float(payload.get('support_rank', 0.0) or 0.0),
        'acceptance_reason': str(payload.get('acceptance_reason', '') or ''),
        'selection_reason': str(payload.get('selection_reason', '') or ''),
        'conclusion_decision': str(conclusion.get('decision', '') or ''),
        'conclusion_level': str(conclusion.get('level', '') or ''),
        'protocol_status': str(operational.get('status', '') or ''),
        'matched': (
            actual_text == expected_text
            and actual_pattern == expected_pattern
            and actual_status == expected_status
        ),
    }


def build_summary(results):
    total = len(results)
    valid = [item for item in results if not item.get('error')]
    matched = [item for item in valid if item.get('matched')]
    avg_time = round(sum(float(item.get('elapsed_seconds', 0.0) or 0.0) for item in valid) / max(1, len(valid)), 2)
    return {
        'generated_at': datetime.now().isoformat(),
        'total_cases': total,
        'valid_cases': len(valid),
        'matched_cases': len(matched),
        'accuracy_percent': round((len(matched) / max(1, len(valid))) * 100.0, 1),
        'average_elapsed_seconds': avg_time,
        'failures': [
            {
                'file': item.get('file'),
                'expected_text': item.get('expected_text'),
                'actual_text': item.get('actual_text'),
                'expected_status': item.get('expected_status'),
                'actual_status': item.get('actual_status'),
                'expected_pattern': item.get('expected_pattern'),
                'actual_pattern': item.get('actual_pattern'),
            }
            for item in valid
            if not item.get('matched')
        ],
    }


def coerce_summary_from_payload(payload):
    if isinstance(payload, dict):
        nested = payload.get('summary')
        if isinstance(nested, dict):
            return nested
        return payload
    return {}


def evaluate_gate(summary, *, baseline_summary=None, min_accuracy=None, min_matched=None, max_average_seconds=None, max_accuracy_drop=None, max_matched_drop=None):
    checks = []

    def add_check(name, passed, actual=None, expected=None, detail=''):
        checks.append({
            'name': str(name),
            'passed': bool(passed),
            'actual': actual,
            'expected': expected,
            'detail': str(detail or ''),
        })

    accuracy = float(summary.get('accuracy_percent', 0.0) or 0.0)
    matched = int(summary.get('matched_cases', 0) or 0)
    average_seconds = float(summary.get('average_elapsed_seconds', 0.0) or 0.0)

    if min_accuracy is not None:
        add_check(
            'min_accuracy_percent',
            accuracy >= float(min_accuracy),
            actual=round(accuracy, 2),
            expected=float(min_accuracy),
            detail='Acuracia percentual da bateria canônica.',
        )

    if min_matched is not None:
        add_check(
            'min_matched_cases',
            matched >= int(min_matched),
            actual=matched,
            expected=int(min_matched),
            detail='Quantidade minima de casos batidos integralmente.',
        )

    if max_average_seconds is not None:
        add_check(
            'max_average_elapsed_seconds',
            average_seconds <= float(max_average_seconds),
            actual=round(average_seconds, 2),
            expected=float(max_average_seconds),
            detail='Tempo medio maximo por caso valido.',
        )

    if baseline_summary:
        baseline_accuracy = float(baseline_summary.get('accuracy_percent', 0.0) or 0.0)
        baseline_matched = int(baseline_summary.get('matched_cases', 0) or 0)

        if max_accuracy_drop is not None:
            accuracy_drop = round(baseline_accuracy - accuracy, 2)
            add_check(
                'max_accuracy_drop_percent',
                accuracy_drop <= float(max_accuracy_drop),
                actual=accuracy_drop,
                expected=float(max_accuracy_drop),
                detail='Queda maxima permitida contra o baseline de acuracia.',
            )

        if max_matched_drop is not None:
            matched_drop = baseline_matched - matched
            add_check(
                'max_matched_drop_cases',
                matched_drop <= int(max_matched_drop),
                actual=matched_drop,
                expected=int(max_matched_drop),
                detail='Queda maxima permitida contra o baseline de casos batidos.',
            )

    return {
        'passed': all(item.get('passed') for item in checks) if checks else True,
        'checks': checks,
    }


def main():
    parser = argparse.ArgumentParser(description='Run the canonical image calibration battery.')
    parser.add_argument('--cases', default=DEFAULT_CASES_PATH)
    parser.add_argument('--output', default=DEFAULT_OUTPUT_PATH)
    parser.add_argument('--policy-file', type=Path, default=None, help='Politica JSON compartilhada da Fase 1.')
    parser.add_argument('--baseline', default='', help='JSON anterior para comparacao de regressao.')
    parser.add_argument('--min-accuracy', type=float, default=None, help='Acuracia minima percentual exigida.')
    parser.add_argument('--min-matched', type=int, default=None, help='Quantidade minima de casos batidos.')
    parser.add_argument('--max-average-seconds', type=float, default=None, help='Tempo medio maximo por caso valido.')
    parser.add_argument('--max-accuracy-drop', type=float, default=None, help='Queda maxima permitida de acuracia contra baseline.')
    parser.add_argument('--max-matched-drop', type=int, default=None, help='Queda maxima permitida de matched_cases contra baseline.')
    args = parser.parse_args()

    policy = load_policy(args.policy_file.resolve()) if args.policy_file else {}
    battery_policy = policy.get('image_calibration_battery', {}) if isinstance(policy, dict) else {}
    if not isinstance(battery_policy, dict):
        battery_policy = {}

    baseline_path = str(args.baseline or battery_policy.get('baseline_path', '') or '')
    min_accuracy = args.min_accuracy if args.min_accuracy is not None else battery_policy.get('min_accuracy')
    min_matched = args.min_matched if args.min_matched is not None else battery_policy.get('min_matched')
    max_average_seconds = args.max_average_seconds if args.max_average_seconds is not None else battery_policy.get('max_average_seconds')
    max_accuracy_drop = args.max_accuracy_drop if args.max_accuracy_drop is not None else battery_policy.get('max_accuracy_drop')
    max_matched_drop = args.max_matched_drop if args.max_matched_drop is not None else battery_policy.get('max_matched_drop')

    cases = load_cases(args.cases)
    client = ocr_agent.app.test_client()
    results = [run_case(client, case) for case in cases]
    summary = build_summary(results)
    baseline_payload = load_json_payload(baseline_path) if baseline_path else {}
    baseline_summary = coerce_summary_from_payload(baseline_payload)
    gate = evaluate_gate(
        summary,
        baseline_summary=baseline_summary,
        min_accuracy=min_accuracy,
        min_matched=min_matched,
        max_average_seconds=max_average_seconds,
        max_accuracy_drop=max_accuracy_drop,
        max_matched_drop=max_matched_drop,
    )
    payload = {
        'summary': summary,
        'gate': {
            'policy_file': str(args.policy_file.resolve()) if args.policy_file else '',
            'baseline_path': baseline_path,
            'baseline_summary': baseline_summary if baseline_summary else {},
            **gate,
        },
        'results': results,
    }

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if not gate.get('passed', True):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
