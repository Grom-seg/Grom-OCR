#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / 'tools'
DATA_DIR = PROJECT_ROOT / 'data'
PYTHON_EXE = Path(os.environ.get('GROM_OCR_PYTHON_EXE') or sys.executable)
LATEST_SUMMARY_PATH = DATA_DIR / 'benchmark_suite_latest.json'
LATEST_INDEX_PATH = DATA_DIR / 'benchmark_suite_latest_index.json'

JOB_DEFINITIONS = [
    {
        'benchmark': 'scene_preprocess',
        'group': 'standard',
        'name': 'scene_preprocess_full',
        'script': 'benchmark_scene_preprocess.py',
        'manifest': 'scene_preprocess_benchmark_manifest.json',
        'output_name': 'scene_preprocess_full.json',
        'calibration_name': 'scene_preprocess_full.calibration.json',
        'extra_args': [],
    },
    {
        'benchmark': 'scene_preprocess',
        'group': 'hard',
        'name': 'scene_preprocess_hard',
        'script': 'benchmark_scene_preprocess.py',
        'manifest': 'scene_preprocess_benchmark_manifest_hard.json',
        'output_name': 'scene_preprocess_hard.json',
        'calibration_name': 'scene_preprocess_hard.calibration.json',
        'extra_args': [],
    },
    {
        'benchmark': 'plate_detector',
        'group': 'standard',
        'name': 'plate_detector_full',
        'script': 'benchmark_plate_detector.py',
        'manifest': 'plate_detector_benchmark_manifest.json',
        'output_name': 'plate_detector_full.json',
        'calibration_name': 'plate_detector_full.calibration.json',
        'extra_args': [],
    },
    {
        'benchmark': 'plate_detector',
        'group': 'hard',
        'name': 'plate_detector_hard',
        'script': 'benchmark_plate_detector.py',
        'manifest': 'plate_detector_benchmark_manifest_hard.json',
        'output_name': 'plate_detector_hard.json',
        'calibration_name': 'plate_detector_hard.calibration.json',
        'extra_args': [],
    },
    {
        'benchmark': 'ocr_reranking',
        'group': 'standard',
        'name': 'ocr_reranking_full',
        'script': 'benchmark_ocr_reranking.py',
        'manifest': 'ocr_reranking_benchmark_manifest.json',
        'output_name': 'ocr_reranking_full.json',
        'calibration_name': 'ocr_reranking_full.calibration.json',
        'extra_args': [],
    },
    {
        'benchmark': 'ocr_reranking',
        'group': 'hard',
        'name': 'ocr_reranking_hard',
        'script': 'benchmark_ocr_reranking.py',
        'manifest': 'ocr_reranking_benchmark_manifest_hard.json',
        'output_name': 'ocr_reranking_hard.json',
        'calibration_name': 'ocr_reranking_hard.calibration.json',
        'extra_args': [],
    },
    {
        'benchmark': 'ocr_reranking',
        'group': 'real',
        'name': 'ocr_reranking_real_direct',
        'script': 'benchmark_ocr_reranking.py',
        'manifest': 'ocr_reranking_benchmark_manifest_real.json',
        'output_name': 'ocr_reranking_real_direct.json',
        'calibration_name': 'ocr_reranking_real_direct.calibration.json',
        'extra_args': ['--direct', '--engines', 'auto'],
    },
    {
        'benchmark': 'ocr_reranking',
        'group': 'real',
        'name': 'ocr_reranking_real_hard_direct',
        'script': 'benchmark_ocr_reranking.py',
        'manifest': 'ocr_reranking_benchmark_manifest_real_hard.json',
        'output_name': 'ocr_reranking_real_hard_direct.json',
        'calibration_name': 'ocr_reranking_real_hard_direct.calibration.json',
        'extra_args': ['--direct', '--engines', 'auto'],
    },
    {
        'benchmark': 'ocr_reranking',
        'group': 'real',
        'name': 'ocr_reranking_core_real_direct',
        'script': 'benchmark_ocr_reranking.py',
        'manifest': 'ocr_reranking_benchmark_manifest_core_real.json',
        'output_name': 'ocr_reranking_core_real_direct.json',
        'calibration_name': 'ocr_reranking_core_real_direct.calibration.json',
        'extra_args': ['--direct', '--engines', 'auto'],
    },
    {
        'benchmark': 'ocr_reranking',
        'group': 'real',
        'name': 'ocr_reranking_core_real_hard_direct',
        'script': 'benchmark_ocr_reranking.py',
        'manifest': 'ocr_reranking_benchmark_manifest_core_real_hard.json',
        'output_name': 'ocr_reranking_core_real_hard_direct.json',
        'calibration_name': 'ocr_reranking_core_real_hard_direct.calibration.json',
        'extra_args': ['--direct', '--engines', 'auto'],
    },
    {
        'benchmark': 'ocr_reranking',
        'group': 'real',
        'name': 'ocr_reranking_crops_real_direct',
        'script': 'benchmark_ocr_reranking.py',
        'manifest': 'ocr_reranking_benchmark_manifest_crops_real.json',
        'output_name': 'ocr_reranking_crops_real_direct.json',
        'calibration_name': 'ocr_reranking_crops_real_direct.calibration.json',
        'extra_args': ['--direct', '--engines', 'auto'],
    },
    {
        'benchmark': 'ocr_reranking',
        'group': 'real',
        'name': 'ocr_reranking_crops_real_hard_direct',
        'script': 'benchmark_ocr_reranking.py',
        'manifest': 'ocr_reranking_benchmark_manifest_crops_real_hard.json',
        'output_name': 'ocr_reranking_crops_real_hard_direct.json',
        'calibration_name': 'ocr_reranking_crops_real_hard_direct.calibration.json',
        'extra_args': ['--direct', '--engines', 'auto'],
    },
]


def slug_timestamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def read_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def get_nested_value(payload, path, default=None):
    current = payload
    for token in str(path or '').split('.'):
        token = token.strip()
        if not token:
            continue
        if not isinstance(current, dict):
            return default
        current = current.get(token)
    if current is None:
        return default
    return current


def load_policy(path: Path | None):
    if path is None:
        return {}
    loaded = read_json(path.resolve())
    return loaded if isinstance(loaded, dict) else {}


def coerce_job_reports_by_name(payload):
    if not isinstance(payload, dict):
        return {}
    reports = payload.get('job_reports', [])
    if not isinstance(reports, list):
        return {}
    result = {}
    for item in reports:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name', '') or '').strip()
        if name:
            result[name] = item
    return result


def evaluate_suite_gate(suite_report, policy, baseline_report=None, baseline_path=''):
    checks = []
    baseline_jobs = coerce_job_reports_by_name(baseline_report)
    policy_jobs = policy.get('jobs', {}) if isinstance(policy, dict) else {}
    require_all_jobs_ok = bool(policy.get('require_all_jobs_ok', True)) if isinstance(policy, dict) else True

    def add_check(scope, name, passed, actual=None, expected=None, detail=''):
        checks.append({
            'scope': str(scope),
            'name': str(name),
            'passed': bool(passed),
            'actual': actual,
            'expected': expected,
            'detail': str(detail or ''),
        })

    if require_all_jobs_ok:
        for report in suite_report.get('job_reports', []):
            name = str(report.get('name', '') or '').strip() or 'unknown_job'
            add_check(
                name,
                'job_status_ok',
                str(report.get('status', '')) == 'ok',
                actual=str(report.get('status', '')),
                expected='ok',
                detail='Cada benchmark selecionado deve concluir com status ok.',
            )

    for report in suite_report.get('job_reports', []):
        name = str(report.get('name', '') or '').strip()
        if not name:
            continue
        job_policy = policy_jobs.get(name)
        if not isinstance(job_policy, dict):
            continue
        baseline_job = baseline_jobs.get(name, {})
        metrics = job_policy.get('metrics', [])
        if not isinstance(metrics, list):
            continue
        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            metric_path = str(metric.get('path', '') or '').strip()
            if not metric_path:
                continue
            actual = get_nested_value(report, metric_path)
            if actual is None:
                add_check(name, metric_path, False, actual=None, expected='metric_present', detail='Metrica nao encontrada no job report.')
                continue
            if 'min' in metric:
                expected = float(metric.get('min'))
                passed = float(actual) >= expected
                add_check(name, f'{metric_path}:min', passed, actual=float(actual), expected=expected, detail='Valor minimo absoluto exigido pela politica.')
            if 'max' in metric:
                expected = float(metric.get('max'))
                passed = float(actual) <= expected
                add_check(name, f'{metric_path}:max', passed, actual=float(actual), expected=expected, detail='Valor maximo absoluto exigido pela politica.')
            if 'max_drop_vs_baseline' in metric:
                if not baseline_job:
                    add_check(name, f'{metric_path}:baseline_present', False, actual=None, expected='baseline_job_present', detail='Job ausente no baseline para comparacao.')
                    continue
                baseline_value = get_nested_value(baseline_job, metric_path)
                if baseline_value is None:
                    add_check(name, f'{metric_path}:baseline_metric_present', False, actual=None, expected='baseline_metric_present', detail='Metrica ausente no baseline do job.')
                    continue
                allowed_drop = float(metric.get('max_drop_vs_baseline'))
                drop = float(baseline_value) - float(actual)
                passed = drop <= allowed_drop
                add_check(
                    name,
                    f'{metric_path}:max_drop_vs_baseline',
                    passed,
                    actual=round(drop, 4),
                    expected=allowed_drop,
                    detail='Queda maxima permitida contra o baseline do mesmo job.',
                )

    return {
        'policy_applied': bool(policy),
        'baseline_path': str(baseline_path or ''),
        'passed': all(item.get('passed') for item in checks) if checks else True,
        'checks': checks,
    }


def build_selected_jobs(mode: str, include_real: bool):
    selected = []
    for job in JOB_DEFINITIONS:
        if job['group'] in {'standard', 'hard'}:
            if mode == 'standard' and job['group'] != 'standard':
                continue
            if mode == 'hard' and job['group'] != 'hard':
                continue
            selected.append(job)
        elif include_real:
            selected.append(job)
    return selected


def resolve_script_path(script_name: str) -> Path:
    path = (TOOLS_DIR / script_name).resolve()
    if not path.exists():
        raise FileNotFoundError(f'Script nao encontrado: {path}')
    return path


def refresh_manifests():
    script_path = resolve_script_path('generate_benchmark_manifests.py')
    proc = subprocess.run(
        [str(PYTHON_EXE), str(script_path)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            'Falha ao regenerar manifests de benchmark.\n'
            f'stdout:\n{proc.stdout}\n'
            f'stderr:\n{proc.stderr}'
        )


def run_job(job: dict, run_root: Path, api_url: str, stop_on_error: bool):
    job_dir = run_root / job['group'] / job['name']
    job_dir.mkdir(parents=True, exist_ok=True)
    output_path = job_dir / job['output_name']
    calibration_path = job_dir / job['calibration_name']
    stdout_path = job_dir / 'stdout.log'
    stderr_path = job_dir / 'stderr.log'

    script_path = resolve_script_path(job['script'])
    manifest_path = (PROJECT_ROOT / 'data' / job['manifest']).resolve()
    if not manifest_path.exists():
        raise FileNotFoundError(f'Manifesto nao encontrado: {manifest_path}')

    cmd = [
        str(PYTHON_EXE),
        str(script_path),
        '--manifest', str(manifest_path),
        '--output', str(output_path),
        '--export-calibration', str(calibration_path),
    ]
    if api_url:
        cmd.extend(['--api-url', api_url])
    if job.get('extra_args'):
        cmd.extend([str(item) for item in job['extra_args']])

    started = datetime.now(timezone.utc)
    print(f"[{job['group']}] {job['name']} -> starting")
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    finished = datetime.now(timezone.utc)
    stdout_path.write_text(proc.stdout or '', encoding='utf-8')
    stderr_path.write_text(proc.stderr or '', encoding='utf-8')

    report = read_json(output_path)
    summary = report.get('summary') if isinstance(report, dict) else {}
    if not isinstance(summary, dict):
        summary = {}

    status = 'ok' if proc.returncode == 0 and report else 'failed'
    print(f"[{job['group']}] {job['name']} -> {status} ({(finished - started).total_seconds():.2f}s)")
    if proc.returncode != 0 and stop_on_error:
        raise RuntimeError(
            f"Falha no benchmark {job['name']} (code={proc.returncode}).\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )

    return {
        'benchmark': job['benchmark'],
        'group': job['group'],
        'name': job['name'],
        'script': job['script'],
        'manifest': str(manifest_path),
        'output': str(output_path),
        'calibration_output': str(calibration_path),
        'stdout_log': str(stdout_path),
        'stderr_log': str(stderr_path),
        'started_at_utc': started.isoformat().replace('+00:00', 'Z'),
        'finished_at_utc': finished.isoformat().replace('+00:00', 'Z'),
        'duration_sec': round((finished - started).total_seconds(), 3),
        'returncode': int(proc.returncode),
        'status': status,
        'summary': summary,
    }


def aggregate_group_summaries(job_reports):
    groups = {}
    for report in job_reports:
        group = str(report.get('group', 'unknown'))
        bucket = groups.setdefault(group, {
            'jobs': 0,
            'ok': 0,
            'failed': 0,
            'duration_sec': 0.0,
        })
        bucket['jobs'] += 1
        bucket['ok'] += int(report.get('status') == 'ok')
        bucket['failed'] += int(report.get('status') != 'ok')
        bucket['duration_sec'] += float(report.get('duration_sec', 0.0) or 0.0)
    for value in groups.values():
        value['duration_sec'] = round(value['duration_sec'], 3)
    return dict(sorted(groups.items(), key=lambda item: item[0]))


def aggregate_benchmark_summaries(job_reports):
    benchmarks = {}
    for report in job_reports:
        benchmark = str(report.get('benchmark', 'unknown'))
        bucket = benchmarks.setdefault(benchmark, {
            'jobs': 0,
            'ok': 0,
            'failed': 0,
            'duration_sec': 0.0,
        })
        bucket['jobs'] += 1
        bucket['ok'] += int(report.get('status') == 'ok')
        bucket['failed'] += int(report.get('status') != 'ok')
        bucket['duration_sec'] += float(report.get('duration_sec', 0.0) or 0.0)
    for value in benchmarks.values():
        value['duration_sec'] = round(value['duration_sec'], 3)
    return dict(sorted(benchmarks.items(), key=lambda item: item[0]))


def main():
    parser = argparse.ArgumentParser(description='Executa a suite permanente de benchmark do Grom OCR.')
    parser.add_argument(
        '--mode',
        choices=['standard', 'hard', 'all'],
        default='all',
        help='Selecao dos subconjuntos fixos principais.',
    )
    parser.add_argument(
        '--include-real',
        action='store_true',
        help='Inclui os subconjuntos OCR reais em modo direto para calibracao mais fina.',
    )
    parser.add_argument(
        '--api-url',
        type=str,
        default='',
        help='URL base da API em execucao para os benchmarks em modo roteado, ex.: http://127.0.0.1:5000',
    )
    parser.add_argument(
        '--skip-refresh-manifests',
        action='store_true',
        help='Nao regenera os manifests a partir do catalogo mestre antes de executar a suite.',
    )
    parser.add_argument(
        '--stop-on-error',
        action='store_true',
        help='Interrompe a suite ao primeiro benchmark que falhar.',
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=DATA_DIR / 'benchmark_runs',
        help='Diretorio raiz para gravar os resultados desta execucao.',
    )
    parser.add_argument(
        '--baseline-summary',
        type=Path,
        default=None,
        help='Resumo JSON anterior da suite para comparacao de regressao por job.',
    )
    parser.add_argument(
        '--policy-file',
        type=Path,
        default=None,
        help='Politica JSON declarativa com checks absolutos e de regressao por job.',
    )
    args = parser.parse_args()

    if not args.skip_refresh_manifests:
        print('Regenerando manifests a partir do catalogo mestre...')
        refresh_manifests()

    run_id = slug_timestamp()
    run_root = (args.output_dir.resolve() / run_id)
    run_root.mkdir(parents=True, exist_ok=True)

    selected_jobs = build_selected_jobs(args.mode, bool(args.include_real))
    if not selected_jobs:
        raise ValueError('Nenhum benchmark foi selecionado.')

    job_reports = []
    for job in selected_jobs:
        report = run_job(job, run_root, args.api_url.strip(), bool(args.stop_on_error))
        job_reports.append(report)

    catalog_summary = read_json(DATA_DIR / 'benchmark_catalog_summary.json') or {}
    raw_policy = load_policy(args.policy_file)
    policy = raw_policy.get('benchmark_suite', {}) if isinstance(raw_policy, dict) else {}
    if not isinstance(policy, dict):
        policy = {}
    baseline_summary_path = args.baseline_summary
    if baseline_summary_path is None and isinstance(policy, dict):
        candidate = str(policy.get('baseline_summary_path', '') or '').strip()
        if candidate:
            baseline_summary_path = Path(candidate)
    baseline_report = read_json(baseline_summary_path.resolve()) if baseline_summary_path else None
    suite_report = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'run_id': run_id,
        'project_root': str(PROJECT_ROOT),
        'python_executable': str(PYTHON_EXE),
        'mode': args.mode,
        'include_real': bool(args.include_real),
        'api_url': args.api_url.strip() or '',
        'refresh_manifests': not bool(args.skip_refresh_manifests),
        'output_root': str(run_root),
        'catalog_summary_path': str((DATA_DIR / 'benchmark_catalog_summary.json').resolve()),
        'catalog_summary': catalog_summary,
        'job_count': len(job_reports),
        'job_reports': job_reports,
        'benchmark_summary': aggregate_benchmark_summaries(job_reports),
        'group_summary': aggregate_group_summaries(job_reports),
        'overall_status': 'ok' if all(report.get('status') == 'ok' for report in job_reports) else 'review',
    }
    suite_report['gate'] = evaluate_suite_gate(
        suite_report,
        policy,
        baseline_report=baseline_report,
        baseline_path=str(baseline_summary_path.resolve()) if baseline_summary_path else '',
    )
    if not suite_report['gate'].get('passed', True):
        suite_report['overall_status'] = 'failed_gate'

    suite_summary_path = run_root / 'benchmark_suite_summary.json'
    write_json(suite_summary_path, suite_report)
    write_json(LATEST_SUMMARY_PATH, suite_report)
    write_json(LATEST_INDEX_PATH, {
        'generated_at_utc': suite_report['generated_at_utc'],
        'run_id': run_id,
        'latest_summary': str(suite_summary_path),
        'output_root': str(run_root),
        'overall_status': suite_report['overall_status'],
    })

    print(json.dumps({
        'run_id': run_id,
        'overall_status': suite_report['overall_status'],
        'job_count': suite_report['job_count'],
        'gate': suite_report['gate'],
        'benchmark_summary': suite_report['benchmark_summary'],
        'group_summary': suite_report['group_summary'],
        'output_root': suite_report['output_root'],
        'latest_summary': str(LATEST_SUMMARY_PATH.resolve()),
    }, ensure_ascii=False, indent=2))

    if not suite_report['gate'].get('passed', True):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
